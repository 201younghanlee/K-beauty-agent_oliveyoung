from __future__ import annotations

import html
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from threading import BoundedSemaphore, Lock
from typing import Any, Callable, Protocol
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import httpx

from .models import Product


YOUTUBE_SEARCH_API_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_RESULTS_URL = "https://www.youtube.com/results"
YOUTUBE_WATCH_URL = "https://www.youtube.com/watch"
YOUTUBE_TERMS_URL = "https://www.youtube.com/t/terms"
GOOGLE_PRIVACY_URL = "https://policies.google.com/privacy"
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_YOUTUBE_RESPONSE_BYTES = 1_500_000
MAX_CACHE_ENTRIES = 512
YOUTUBE_QUOTA_TIMEZONE = ZoneInfo("America/Los_Angeles")
YOUTUBE_QUOTA_SERVICE = "youtube_search"
GENERIC_PRODUCT_TERMS = {
    "ampoule",
    "cleanser",
    "cream",
    "essence",
    "gel",
    "lotion",
    "moisturizer",
    "review",
    "serum",
    "skin",
    "skincare",
    "soothing",
    "sunscreen",
    "toner",
    "후기",
    "리뷰",
    "세럼",
    "스킨",
    "앰플",
    "에센스",
    "크림",
    "클렌저",
    "토너",
}


class DailyQuotaStore(Protocol):
    def reserve_external_api_daily_call(self, service: str, quota_day: str, limit: int) -> bool: ...

    def exhaust_external_api_daily_quota(self, service: str, quota_day: str, limit: int) -> None: ...


class YouTubeQuotaExceededError(RuntimeError):
    """Raised only when YouTube explicitly reports daily quota exhaustion."""


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    payload: dict[str, object]


class YouTubeReviewService:
    """Fetch product-related public YouTube videos without affecting ranking.

    Searches are deliberately lazy and cached because YouTube's search quota is
    small. A product-specific YouTube results URL remains available when an API
    key is not configured or an upstream request fails.
    """

    def __init__(
        self,
        api_key: str | None,
        *,
        daily_search_limit: int = 90,
        cache_ttl_seconds: int = 24 * 60 * 60,
        client: httpx.Client | None = None,
        quota_store: DailyQuotaStore | None = None,
        quota_day_provider: Callable[[], str] | None = None,
        max_concurrent_searches: int = 4,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._daily_search_limit = max(1, min(int(daily_search_limit), 100))
        self._cache_ttl_seconds = max(300, min(int(cache_ttl_seconds), 24 * 60 * 60))
        self._client = client or httpx.Client(
            timeout=6.0,
            follow_redirects=False,
            headers={"User-Agent": "k-beauty-agent-youtube-reviews/1.0"},
        )
        self._owns_client = client is None
        self._quota_store = quota_store
        self._quota_day_provider = quota_day_provider or _youtube_quota_day
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = Lock()
        self._search_locks: dict[str, Lock] = {}
        self._upstream_slots = BoundedSemaphore(max(1, min(int(max_concurrent_searches), 8)))
        self._quota_day = self._quota_day_provider()
        self._searches_today = 0

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def reviews_for_product(self, product: Product, *, limit: int = 3) -> dict[str, object]:
        result_limit = max(1, min(int(limit), 5))
        query = _review_query(product)
        search_url = _search_url(query)
        base = _base_payload(product.id, query, search_url)
        if not self._api_key:
            return {
                **base,
                "status": "search_only",
                "message_ko": "현재는 제품명에 맞는 YouTube 후기 검색 결과로 연결해 드려요.",
                "videos": [],
            }

        cache_key = product.id
        cached = self._cached(cache_key)
        if cached is not None:
            return _limited_payload(cached, result_limit)

        # Do not let duplicate taps or a burst of different products occupy
        # the application's synchronous worker pool while Google is slow.
        product_lock = self._search_lock(cache_key)
        if not product_lock.acquire(blocking=False):
            return {
                **base,
                "status": "temporarily_unavailable",
                "message_ko": "같은 제품의 영상을 이미 찾고 있어요. 잠시 후 다시 확인해 주세요.",
                "videos": [],
            }
        try:
            cached = self._cached(cache_key)
            if cached is not None:
                return _limited_payload(cached, result_limit)
            if not self._upstream_slots.acquire(blocking=False):
                return {
                    **base,
                    "status": "temporarily_unavailable",
                    "message_ko": "영상 요청이 잠시 몰렸어요. 잠시 후 다시 확인해 주세요.",
                    "videos": [],
                }
            try:
                if not self._reserve_search():
                    return {
                        **base,
                        "status": "quota_limited",
                        "message_ko": "오늘의 영상 검색 한도에 도달해 YouTube 검색 결과로 연결해 드려요.",
                        "videos": [],
                    }

                try:
                    search_items = self._search(query, 5)
                    videos = self._video_details(search_items, product)[:3]
                except YouTubeQuotaExceededError:
                    self._exhaust_search_quota()
                    payload = {
                        **base,
                        "status": "quota_limited",
                        "message_ko": "오늘의 영상 검색 한도에 도달해 YouTube 검색 결과로 연결해 드려요.",
                        "videos": [],
                    }
                    self._store(cache_key, payload)
                    return payload
                except (httpx.HTTPError, TypeError, ValueError):
                    payload = {
                        **base,
                        "status": "temporarily_unavailable",
                        "message_ko": "영상 목록을 잠시 불러오지 못해 YouTube 검색 결과로 연결해 드려요.",
                        "videos": [],
                    }
                    self._store(cache_key, payload, ttl_seconds=5 * 60)
                    return payload
            finally:
                self._upstream_slots.release()

            payload = {
                **base,
                "status": "ready" if videos else "no_results",
                "message_ko": (
                    "제품명과 관련된 공개 YouTube 영상을 찾았어요."
                    if videos
                    else "일치하는 영상을 찾지 못해 YouTube 검색 결과로 연결해 드려요."
                ),
                "videos": videos,
            }
            self._store(cache_key, payload)
            return _limited_payload(payload, result_limit)
        finally:
            product_lock.release()

    def _search(self, query: str, limit: int) -> list[dict[str, Any]]:
        response = self._client.get(
            YOUTUBE_SEARCH_API_URL,
            headers={"x-goog-api-key": self._api_key},
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": max(1, min(limit, 10)),
                "order": "relevance",
                "regionCode": "KR",
                "relevanceLanguage": "ko",
                "safeSearch": "strict",
                "fields": "items(id/videoId,snippet(title,description,channelTitle,publishedAt,thumbnails))",
            },
            timeout=httpx.Timeout(5.0, connect=2.5, pool=1.0),
        )
        _raise_for_safe_json_response(response)
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("YouTube search response is malformed")
        return [item for item in data["items"] if isinstance(item, dict)]

    def _video_details(
        self,
        search_items: list[dict[str, Any]],
        product: Product,
    ) -> list[dict[str, object]]:
        search_by_id: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for item in search_items:
            identity = item.get("id") if isinstance(item.get("id"), dict) else {}
            video_id = identity.get("videoId")
            if isinstance(video_id, str) and VIDEO_ID_PATTERN.fullmatch(video_id):
                search_by_id.setdefault(video_id, item)
        if not search_by_id:
            return []

        response = self._client.get(
            YOUTUBE_VIDEOS_API_URL,
            headers={"x-goog-api-key": self._api_key},
            params={
                "part": "snippet,status,contentDetails,paidProductPlacementDetails",
                "id": ",".join(search_by_id),
                "fields": (
                    "items(id,snippet(title,channelTitle,publishedAt,thumbnails),"
                    "status(privacyStatus,embeddable),contentDetails/duration,"
                    "paidProductPlacementDetails/hasPaidProductPlacement)"
                ),
            },
            timeout=httpx.Timeout(5.0, connect=2.5, pool=1.0),
        )
        _raise_for_safe_json_response(response)
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("YouTube video response is malformed")

        details_by_id: dict[str, dict[str, Any]] = {}
        for item in data["items"]:
            if not isinstance(item, dict):
                continue
            video_id = item.get("id")
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            if (
                isinstance(video_id, str)
                and VIDEO_ID_PATTERN.fullmatch(video_id)
                and status.get("privacyStatus") == "public"
            ):
                details_by_id[video_id] = item

        videos: list[dict[str, object]] = []
        for video_id in search_by_id:
            item = details_by_id.get(video_id)
            if item is None:
                continue
            snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
            search_snippet = (
                search_by_id[video_id].get("snippet")
                if isinstance(search_by_id[video_id].get("snippet"), dict)
                else {}
            )
            if not _is_product_related(product, snippet, search_snippet):
                continue
            paid = (
                item.get("paidProductPlacementDetails")
                if isinstance(item.get("paidProductPlacementDetails"), dict)
                else {}
            )
            content = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
            title = _clean_text(snippet.get("title"), 240)
            channel_title = _clean_text(snippet.get("channelTitle"), 160)
            if not title or not channel_title:
                continue
            videos.append(
                {
                    "video_id": video_id,
                    "title": title,
                    "channel_title": channel_title,
                    "published_at": _clean_text(snippet.get("publishedAt"), 40) or None,
                    "duration": _clean_text(content.get("duration"), 32) or None,
                    "thumbnail_url": _thumbnail_url(snippet.get("thumbnails")),
                    "url": f"{YOUTUBE_WATCH_URL}?v={video_id}",
                    "has_paid_product_placement": paid.get("hasPaidProductPlacement") is True,
                }
            )
        return videos

    def _cached(self, key: str) -> dict[str, object] | None:
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now)
            entry = self._cache.get(key)
            if entry is None:
                return None
            self._cache.move_to_end(key)
            return dict(entry.payload)

    def _store(self, key: str, payload: dict[str, object], *, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._cache_ttl_seconds
        with self._lock:
            now = time.monotonic()
            self._purge_expired_locked(now)
            self._cache[key] = _CacheEntry(now + ttl, dict(payload))
            self._cache.move_to_end(key)
            while len(self._cache) > MAX_CACHE_ENTRIES:
                self._cache.popitem(last=False)

    def _purge_expired_locked(self, now: float) -> None:
        expired = [key for key, entry in self._cache.items() if entry.expires_at <= now]
        for key in expired:
            self._cache.pop(key, None)

    def _reserve_search(self) -> bool:
        quota_day = self._quota_day_provider()
        if self._quota_store is not None:
            try:
                return self._quota_store.reserve_external_api_daily_call(
                    YOUTUBE_QUOTA_SERVICE,
                    quota_day,
                    self._daily_search_limit,
                )
            except Exception:
                # Fail closed: a broken quota ledger must not fan out
                # unbounded calls to the external API.
                return False
        with self._lock:
            if self._quota_day != quota_day:
                self._quota_day = quota_day
                self._searches_today = 0
            if self._searches_today >= self._daily_search_limit:
                return False
            self._searches_today += 1
            return True

    def _exhaust_search_quota(self) -> None:
        quota_day = self._quota_day_provider()
        if self._quota_store is not None:
            try:
                self._quota_store.exhaust_external_api_daily_quota(
                    YOUTUBE_QUOTA_SERVICE,
                    quota_day,
                    self._daily_search_limit,
                )
            except Exception:
                pass
        with self._lock:
            self._quota_day = quota_day
            self._searches_today = self._daily_search_limit

    def _search_lock(self, key: str) -> Lock:
        with self._lock:
            return self._search_locks.setdefault(key, Lock())


def _base_payload(product_id: str, query: str, search_url: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "product_id": product_id,
        "provider": "YouTube",
        "query": query,
        "search_url": search_url,
        "disclaimer_ko": (
            "YouTube 공개 검색 결과이며 K-Beauty Agent가 사용 경험이나 광고 여부를 보증하지 않아요. "
            "협찬·유료 광고 표시는 영상에서 다시 확인해 주세요. 영상은 추천 순위·리뷰 평점·데이터 "
            "신뢰도에 반영하지 않아요."
        ),
        "terms_url": YOUTUBE_TERMS_URL,
        "privacy_url": GOOGLE_PRIVACY_URL,
    }


def _limited_payload(payload: dict[str, object], limit: int) -> dict[str, object]:
    result = dict(payload)
    videos = payload.get("videos")
    result["videos"] = list(videos[:limit]) if isinstance(videos, list) else []
    return result


def _review_query(product: Product) -> str:
    names = [product.brand, product.display_name_ko or "", product.name]
    unique: list[str] = []
    seen: set[str] = set()
    for raw in names:
        value = " ".join(str(raw).split())
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            unique.append(value)
    return (" ".join(unique) + " 사용 후기 리뷰").strip()[:240]


def _search_url(query: str) -> str:
    return f"{YOUTUBE_RESULTS_URL}?{urlencode({'search_query': query})}"


def _raise_for_safe_json_response(response: httpx.Response) -> None:
    content_length = response.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_YOUTUBE_RESPONSE_BYTES:
        raise ValueError("YouTube response is too large")
    if len(response.content) > MAX_YOUTUBE_RESPONSE_BYTES:
        raise ValueError("YouTube response is too large")
    if response.status_code == 403 and _is_youtube_quota_error(response):
        raise YouTubeQuotaExceededError("YouTube daily quota exhausted")
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if content_type and "json" not in content_type.casefold():
        raise ValueError("YouTube response is not JSON")


def _is_youtube_quota_error(response: httpx.Response) -> bool:
    try:
        payload = response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return False
    errors = payload["error"].get("errors")
    if not isinstance(errors, list):
        return False
    reasons = {
        item.get("reason")
        for item in errors
        if isinstance(item, dict) and isinstance(item.get("reason"), str)
    }
    return bool(reasons & {"quotaExceeded", "dailyLimitExceeded"})


def _clean_text(value: object, max_length: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(html.unescape(value).split())[:max_length]


def _thumbnail_url(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("medium", "high", "default"):
        candidate = value.get(key)
        raw_url = candidate.get("url") if isinstance(candidate, dict) else None
        if not isinstance(raw_url, str):
            continue
        try:
            parsed = urlparse(raw_url)
            parsed_port = parsed.port
        except ValueError:
            continue
        if (
            parsed.scheme == "https"
            and parsed.hostname in {"i.ytimg.com", "img.youtube.com"}
            and not parsed.username
            and not parsed.password
            and parsed_port in {None, 443}
        ):
            return raw_url
    return None


def _youtube_quota_day() -> str:
    return datetime.now(YOUTUBE_QUOTA_TIMEZONE).date().isoformat()


def _normalized_match_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(re.findall(r"[0-9A-Za-z가-힣]+", html.unescape(value).casefold()))


def _product_match_terms(product: Product) -> tuple[str, set[str]]:
    brand = _normalized_match_text(product.brand)
    terms: set[str] = set()
    for value in (product.name, product.display_name_ko or ""):
        for token in re.findall(r"[0-9A-Za-z가-힣]+", str(value).casefold()):
            normalized = _normalized_match_text(token)
            if len(normalized) >= 3 and normalized not in GENERIC_PRODUCT_TERMS:
                terms.add(normalized)
    if brand:
        terms.discard(brand)
    return brand, terms


def _is_product_related(
    product: Product,
    details_snippet: dict[str, Any],
    search_snippet: dict[str, Any],
) -> bool:
    haystack = _normalized_match_text(
        " ".join(
            str(value)
            for value in (
                details_snippet.get("title"),
                details_snippet.get("channelTitle"),
                search_snippet.get("title"),
                search_snippet.get("description"),
                search_snippet.get("channelTitle"),
            )
            if value
        )
    )
    brand, terms = _product_match_terms(product)
    if brand and len(brand) >= 3 and brand in haystack:
        return True
    return any(term in haystack for term in terms)
