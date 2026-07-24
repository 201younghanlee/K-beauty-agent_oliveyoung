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
YOUTUBE_CHANNELS_API_URL = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_RESULTS_URL = "https://www.youtube.com/results"
YOUTUBE_WATCH_URL = "https://www.youtube.com/watch"
YOUTUBE_CHANNEL_URL = "https://www.youtube.com/channel"
YOUTUBE_TERMS_URL = "https://www.youtube.com/t/terms"
GOOGLE_PRIVACY_URL = "https://policies.google.com/privacy"
VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_PATTERN = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_YOUTUBE_RESPONSE_BYTES = 1_500_000
MAX_CACHE_ENTRIES = 512
YOUTUBE_QUOTA_TIMEZONE = ZoneInfo("America/Los_Angeles")
YOUTUBE_QUOTA_SERVICE = "youtube_search"
GENERIC_PRODUCT_TERMS = {
    "acid",
    "advanced",
    "ampoule",
    "barrier",
    "body",
    "care",
    "clean",
    "cleanser",
    "cleansing",
    "clear",
    "concentrate",
    "concentrated",
    "correcting",
    "cream",
    "dark",
    "essence",
    "fit",
    "foundation",
    "foam",
    "gel",
    "good",
    "green",
    "high",
    "intensive",
    "lotion",
    "low",
    "mild",
    "moisture",
    "moisturizing",
    "moisturizer",
    "makeup",
    "mask",
    "original",
    "power",
    "pure",
    "red",
    "review",
    "serum",
    "shampoo",
    "skin",
    "skincare",
    "soothing",
    "sun",
    "sunscreen",
    "toner",
    "water",
    "watery",
    "사용",
    "후기",
    "리뷰",
    "립밤",
    "마스크",
    "메이크업",
    "바디",
    "로션",
    "보습",
    "세럼",
    "선스크린",
    "선크림",
    "스킨",
    "앰플",
    "에센스",
    "젤",
    "크림",
    "클렌징",
    "클렌저",
    "토너",
    "헤어",
    "폼",
}
REVIEW_INTENT_TERMS = {
    "comparison",
    "empties",
    "empty",
    "experience",
    "favorite",
    "favorites",
    "honest",
    "impression",
    "impressions",
    "recommend",
    "review",
    "reviewed",
    "reviewing",
    "reviews",
    "routine",
    "test",
    "tested",
    "testing",
    "thoughts",
    "tried",
    "try",
    "used",
    "versus",
    "vs",
    "공병",
    "리뷰",
    "발라봄",
    "발라본",
    "비교",
    "사용기",
    "사용후기",
    "솔직",
    "써봄",
    "써본",
    "써봤",
    "일주일",
    "첫인상",
    "추천",
    "테스트",
    "한달",
    "후기",
}
CATEGORY_MATCH_TERMS = {
    "cleanser": {
        "cleanser",
        "cleansing",
        "facewash",
        "foam",
        "wash",
        "세안",
        "클렌저",
        "클렌징",
        "폼",
    },
    "moisturizer": {
        "cream",
        "lotion",
        "moisturizer",
        "moisturizing",
        "로션",
        "보습",
        "수분크림",
        "크림",
    },
    "serum": {
        "ampoule",
        "essence",
        "serum",
        "세럼",
        "앰플",
        "에센스",
    },
    "sunscreen": {
        "spf",
        "sun",
        "suncream",
        "sunscreen",
        "자외선",
        "선스크린",
        "선크림",
    },
    "toner": {
        "toner",
        "토너",
    },
    "face_mask": {
        "claymask",
        "facemask",
        "facialmask",
        "gelmask",
        "mask",
        "sheetmask",
        "sleepingmask",
        "마스크",
        "마스크팩",
        "시트팩",
    },
    "eye_care": {
        "eyecare",
        "eyecream",
        "eyemask",
        "eyepatch",
        "eyeserum",
        "eyetreatment",
        "undereyecream",
        "아이케어",
        "아이크림",
        "아이패치",
        "아이세럼",
        "눈가",
        "눈가케어",
        "눈가크림",
    },
    "lip_care": {
        "lipbalm",
        "lipcare",
        "lipmask",
        "lipmoisturizer",
        "liptreatment",
        "립밤",
        "립케어",
        "립마스크",
    },
    "exfoliator": {
        "exfoliator",
        "exfoliatingtoner",
        "facescrub",
        "peel",
        "scrub",
        "각질",
        "스크럽",
        "필링",
    },
    "body_cleanser": {
        "bathwash",
        "bodywash",
        "showergel",
        "바디워시",
        "샤워젤",
    },
    "body_moisturizer": {
        "bodycream",
        "bodylotion",
        "bodymoisturizer",
        "bodyoil",
        "footcream",
        "handcream",
        "바디로션",
        "바디크림",
        "핸드크림",
        "풋크림",
    },
    "body_exfoliator": {
        "bodyexfoliator",
        "bodyscrub",
        "바디스크럽",
        "바디각질",
    },
    "shampoo": {
        "shampoo",
        "샴푸",
    },
    "conditioner": {
        "conditioner",
        "컨디셔너",
        "린스",
    },
    "hair_treatment": {
        "hairmask",
        "hairoil",
        "hairserum",
        "hairtreatment",
        "scalpcare",
        "트리트먼트",
        "헤어",
    },
    "base_makeup": {
        "basemakeup",
        "bbcream",
        "blush",
        "bronzer",
        "cccream",
        "concealer",
        "facemakeup",
        "facepowder",
        "foundation",
        "tintedmoisturizer",
        "베이스메이크업",
        "블러셔",
        "컨실러",
        "쿠션",
        "파운데이션",
    },
    "eye_makeup": {
        "eyeliner",
        "eyemakeup",
        "eyeshadow",
        "mascara",
        "아이메이크업",
        "마스카라",
        "아이라이너",
        "아이섀도",
    },
    "lip_makeup": {
        "lipgloss",
        "lipmakeup",
        "lipstick",
        "립글로스",
        "립메이크업",
        "립스틱",
    },
}
SCOPED_CATEGORY_MATCH_TERMS = frozenset(
    {
        "basemakeup",
        "bathwash",
        "bbcream",
        "bodycream",
        "bodyexfoliator",
        "bodylotion",
        "bodymoisturizer",
        "bodyoil",
        "bodyscrub",
        "bodywash",
        "cccream",
        "claymask",
        "eyecare",
        "eyecream",
        "eyeliner",
        "eyemakeup",
        "eyemask",
        "eyepatch",
        "eyeserum",
        "eyeshadow",
        "eyetreatment",
        "facemakeup",
        "facemask",
        "facepowder",
        "facescrub",
        "facewash",
        "facialmask",
        "footcream",
        "gelmask",
        "hairmask",
        "hairoil",
        "hairserum",
        "hairtreatment",
        "handcream",
        "lipbalm",
        "lipcare",
        "lipgloss",
        "lipmakeup",
        "lipmask",
        "lipmoisturizer",
        "lipstick",
        "liptreatment",
        "scalpcare",
        "sheetmask",
        "showergel",
        "sleepingmask",
        "suncream",
        "tintedmoisturizer",
        "undereyecream",
        "바디각질",
        "바디로션",
        "바디스크럽",
        "바디워시",
        "바디크림",
        "베이스메이크업",
        "샤워젤",
        "시트팩",
        "아이메이크업",
        "아이세럼",
        "아이케어",
        "아이크림",
        "아이패치",
        "아이라이너",
        "아이섀도",
        "립글로스",
        "립마스크",
        "립메이크업",
        "립스틱",
        "립케어",
        "마스크팩",
        "풋크림",
        "핸드크림",
    }
)
SCOPED_CATEGORY_TOKEN_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "cleanser": (("face", "wash"), ("facial", "wash")),
    "sunscreen": (("sun", "cream"),),
    "face_mask": (
        ("face", "mask"),
        ("facial", "mask"),
        ("sheet", "mask"),
        ("sleeping", "mask"),
        ("clay", "mask"),
        ("gel", "mask"),
    ),
    "eye_care": (
        ("eye", "care"),
        ("eye", "cream"),
        ("eye", "mask"),
        ("eye", "patch"),
        ("eye", "serum"),
        ("eye", "treatment"),
        ("under", "eye"),
    ),
    "lip_care": (
        ("lip", "balm"),
        ("lip", "care"),
        ("lip", "mask"),
        ("lip", "moisturizer"),
        ("lip", "treatment"),
    ),
    "exfoliator": (
        ("face", "scrub"),
        ("facial", "scrub"),
        ("exfoliating", "toner"),
    ),
    "body_cleanser": (
        ("bath", "wash"),
        ("body", "wash"),
        ("shower", "gel"),
    ),
    "body_moisturizer": (
        ("body", "cream"),
        ("body", "lotion"),
        ("body", "moisturizer"),
        ("body", "oil"),
        ("foot", "cream"),
        ("hand", "cream"),
    ),
    "body_exfoliator": (
        ("body", "exfoliator"),
        ("body", "scrub"),
    ),
    "hair_treatment": (
        ("hair", "mask"),
        ("hair", "oil"),
        ("hair", "serum"),
        ("hair", "treatment"),
        ("scalp", "care"),
    ),
    "base_makeup": (
        ("base", "makeup"),
        ("bb", "cream"),
        ("cc", "cream"),
        ("face", "makeup"),
        ("face", "powder"),
        ("tinted", "moisturizer"),
    ),
    "eye_makeup": (
        ("eye", "liner"),
        ("eye", "makeup"),
        ("eye", "shadow"),
    ),
    "lip_makeup": (
        ("lip", "gloss"),
        ("lip", "makeup"),
        ("lip", "stick"),
    ),
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


@dataclass(frozen=True)
class _ProductMatchProfile:
    brand_groups: tuple[tuple[str, ...], ...]
    product_terms: frozenset[str]
    full_name_phrases: tuple[str, ...]
    product_name_phrases: tuple[str, ...]
    category_terms: frozenset[str]


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
                    # A wider first page does not consume another search.list
                    # call. It offsets the stricter local relevance filter while
                    # keeping the daily search quota usage unchanged.
                    search_items = self._search(query, 10)
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
                "videoEmbeddable": "true",
                "videoSyndicated": "true",
                "maxResults": max(1, min(limit, 10)),
                "order": "relevance",
                "regionCode": "KR",
                "relevanceLanguage": "ko",
                "safeSearch": "strict",
                "fields": (
                    "items(id/videoId,"
                    "snippet(title,description,channelId,channelTitle,publishedAt,thumbnails))"
                ),
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
                "part": "snippet,status,contentDetails,paidProductPlacementDetails,statistics",
                "id": ",".join(search_by_id),
                "fields": (
                    "items(id,snippet(title,channelId,channelTitle,publishedAt,thumbnails),"
                    "status(privacyStatus,embeddable,madeForKids),contentDetails/duration,"
                    "paidProductPlacementDetails/hasPaidProductPlacement,"
                    "statistics(viewCount,likeCount))"
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
                and status.get("embeddable") is True
                # The YouTube policies require the MFK status to be checked for
                # every embed. This client does not implement child-directed
                # player tracking controls, so fail closed for MFK or unknown
                # status rather than embedding it.
                and status.get("madeForKids") is False
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
            statistics = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
            title = _clean_text(snippet.get("title"), 240)
            channel_title = _clean_text(snippet.get("channelTitle"), 160)
            if not title or not channel_title:
                continue
            video: dict[str, object] = {
                "video_id": video_id,
                "title": title,
                "channel_title": channel_title,
                "published_at": _clean_text(snippet.get("publishedAt"), 40) or None,
                "duration": _clean_text(content.get("duration"), 32) or None,
                "thumbnail_url": _thumbnail_url(snippet.get("thumbnails")),
                "url": f"{YOUTUBE_WATCH_URL}?v={video_id}",
                "has_paid_product_placement": paid.get("hasPaidProductPlacement") is True,
            }
            channel_id = _channel_id(snippet.get("channelId"))
            if channel_id is not None:
                video["channel_id"] = channel_id
                video["channel_url"] = f"{YOUTUBE_CHANNEL_URL}/{channel_id}"
            view_count = _non_negative_int(statistics.get("viewCount"))
            if view_count is not None:
                video["view_count"] = view_count
            like_count = _non_negative_int(statistics.get("likeCount"))
            if like_count is not None:
                video["like_count"] = like_count
            # Preserve the ordering returned by YouTube search. The local
            # eligibility check only removes clear false positives and never
            # creates a score or re-ranks API results.
            videos.append(video)

        channel_ids = [
            channel_id
            for channel_id in (
                video.get("channel_id")
                for video in videos
            )
            if isinstance(channel_id, str)
        ]
        try:
            channel_details = self._channel_details(channel_ids)
        except (YouTubeQuotaExceededError, httpx.HTTPError, TypeError, ValueError):
            # Channel metadata is optional. A valid public video remains useful
            # even when the separate profile lookup is unavailable.
            channel_details = {}
        for video in videos:
            channel_id = video.get("channel_id")
            if isinstance(channel_id, str):
                video.update(channel_details.get(channel_id, {}))
        return videos

    def _channel_details(self, channel_ids: list[str]) -> dict[str, dict[str, object]]:
        unique_ids = list(dict.fromkeys(channel_ids))
        if not unique_ids:
            return {}

        response = self._client.get(
            YOUTUBE_CHANNELS_API_URL,
            headers={"x-goog-api-key": self._api_key},
            params={
                "part": "snippet,statistics",
                "id": ",".join(unique_ids),
                "fields": (
                    "items(id,snippet(thumbnails),"
                    "statistics(subscriberCount,hiddenSubscriberCount))"
                ),
            },
            timeout=httpx.Timeout(5.0, connect=2.5, pool=1.0),
        )
        _raise_for_safe_json_response(response)
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("YouTube channel response is malformed")

        requested_ids = set(unique_ids)
        details: dict[str, dict[str, object]] = {}
        for item in data["items"]:
            if not isinstance(item, dict):
                continue
            channel_id = _channel_id(item.get("id"))
            if channel_id is None or channel_id not in requested_ids:
                continue
            snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
            statistics = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
            channel: dict[str, object] = {}
            thumbnail_url = _channel_thumbnail_url(snippet.get("thumbnails"))
            if thumbnail_url is not None:
                channel["channel_thumbnail_url"] = thumbnail_url
            hidden = statistics.get("hiddenSubscriberCount")
            if isinstance(hidden, bool):
                channel["subscriber_count_hidden"] = hidden
                if not hidden:
                    subscriber_count = _non_negative_int(statistics.get("subscriberCount"))
                    if subscriber_count is not None:
                        channel["subscriber_count"] = subscriber_count
            details[channel_id] = channel
        return details

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
    # YouTube supports the `|` operator for OR queries. Treat the localized and
    # English product names as alternatives instead of requiring one result to
    # match both languages at once.
    alternatives: list[str] = []
    seen: set[str] = set()
    for raw, review_term in (
        (product.display_name_ko or "", "후기"),
        (product.name, "review"),
    ):
        value = " ".join(str(raw).split())
        key = value.casefold()
        if not value or key in seen:
            continue
        candidate = f"{value} {review_term}"
        separator_size = 1 if alternatives else 0
        remaining = 240 - len("|".join(alternatives)) - separator_size
        if remaining <= len(review_term) + 1:
            break
        alternatives.append(candidate[:remaining].rstrip())
        seen.add(key)

    if alternatives:
        return "|".join(alternatives)
    return f"{' '.join(product.brand.split())[:233]} review".strip()


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


def _channel_id(value: object) -> str | None:
    if isinstance(value, str) and CHANNEL_ID_PATTERN.fullmatch(value):
        return value
    return None


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        candidate = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        if len(value) > len(str(MAX_SAFE_INTEGER)):
            return None
        candidate = int(value)
    else:
        return None
    if 0 <= candidate <= MAX_SAFE_INTEGER:
        return candidate
    return None


def _thumbnail_url(value: object) -> str | None:
    return _thumbnail_url_for_hosts(value, {"i.ytimg.com", "img.youtube.com"})


def _channel_thumbnail_url(value: object) -> str | None:
    return _thumbnail_url_for_hosts(value, {"yt3.ggpht.com", "yt3.googleusercontent.com"})


def _thumbnail_url_for_hosts(value: object, allowed_hosts: set[str]) -> str | None:
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
            and parsed.hostname in allowed_hosts
            and not parsed.username
            and not parsed.password
            and parsed_port in {None, 443}
            and parsed.path.startswith("/")
        ):
            return raw_url
    return None


def _youtube_quota_day() -> str:
    return datetime.now(YOUTUBE_QUOTA_TIMEZONE).date().isoformat()


def _normalized_match_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(re.findall(r"[0-9A-Za-z가-힣]+", html.unescape(value).casefold()))


def _match_tokens(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(re.findall(r"[0-9A-Za-z가-힣]+", html.unescape(value).casefold()))


def _starts_with_tokens(tokens: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return bool(prefix) and len(tokens) >= len(prefix) and tokens[: len(prefix)] == prefix


def _meaningful_product_term(token: str) -> bool:
    if token in GENERIC_PRODUCT_TERMS:
        return False
    if token.isascii() and token.isdigit():
        return len(token) >= 2
    if re.search(r"[가-힣]", token):
        return len(token) >= 2
    return len(token) >= 3


def _product_match_profile(product: Product) -> _ProductMatchProfile:
    brand_tokens = _match_tokens(product.brand)
    brand_groups: list[tuple[str, ...]] = [brand_tokens] if brand_tokens else []
    product_terms: set[str] = set()
    full_name_phrases: list[str] = []
    product_name_phrases: list[str] = []

    for value, localized in (
        (product.name, False),
        (product.display_name_ko or "", True),
    ):
        tokens = _match_tokens(value)
        if not tokens:
            continue
        full_phrase = "".join(tokens)
        if len(full_phrase) >= 6 and full_phrase not in full_name_phrases:
            full_name_phrases.append(full_phrase)

        remaining = tokens
        if _starts_with_tokens(tokens, brand_tokens):
            remaining = tokens[len(brand_tokens) :]
        elif (
            localized
            and len(tokens) >= 2
            and re.search(r"[가-힣]", tokens[0])
            and tokens[0] not in GENERIC_PRODUCT_TERMS
        ):
            localized_brand = (tokens[0],)
            if localized_brand not in brand_groups:
                brand_groups.append(localized_brand)
            remaining = tokens[1:]

        product_phrase = "".join(remaining)
        if len(remaining) >= 2 and len(product_phrase) >= 6:
            if product_phrase not in product_name_phrases:
                product_name_phrases.append(product_phrase)
        for token in remaining:
            if _meaningful_product_term(token):
                product_terms.add(token)

    for brand_group in brand_groups:
        product_terms.difference_update(brand_group)
    category_terms = frozenset(CATEGORY_MATCH_TERMS.get(product.category.casefold(), set()))
    return _ProductMatchProfile(
        brand_groups=tuple(brand_groups),
        product_terms=frozenset(product_terms),
        full_name_phrases=tuple(full_name_phrases),
        product_name_phrases=tuple(product_name_phrases),
        category_terms=category_terms,
    )


def _term_present(term: str, tokens: set[str], compact_values: tuple[str, ...]) -> bool:
    if term in tokens:
        return True
    if re.search(r"[가-힣]", term) or (term.isascii() and len(term) >= 6):
        return any(term in compact for compact in compact_values)
    return False


def _group_present(
    group: tuple[str, ...],
    tokens: set[str],
    compact_values: tuple[str, ...],
) -> bool:
    if not group:
        return False
    if len(group) == 1:
        return _term_present(group[0], tokens, compact_values)
    phrase = "".join(group)
    return any(phrase in compact for compact in compact_values)


def _has_review_intent(values: tuple[object, ...]) -> bool:
    tokens = {
        token
        for value in values
        for token in _match_tokens(value)
    }
    compact_values = tuple(
        compact
        for compact in (_normalized_match_text(value) for value in values)
        if compact
    )
    return any(
        _term_present(term, tokens, compact_values)
        for term in REVIEW_INTENT_TERMS
    )


def _has_conflicting_category(
    category_terms: frozenset[str],
    title_tokens: set[str],
    title_compacts: tuple[str, ...],
) -> bool:
    if not category_terms:
        return False
    target_category = next(
        (
            category
            for category, terms in CATEGORY_MATCH_TERMS.items()
            if frozenset(terms) == category_terms
        ),
        None,
    )
    for category, groups in SCOPED_CATEGORY_TOKEN_GROUPS.items():
        if category == target_category:
            continue
        if any(
            all(
                _term_present(term, title_tokens, title_compacts)
                for term in group
            )
            for group in groups
        ):
            return True
    competing_scoped_terms = SCOPED_CATEGORY_MATCH_TERMS.difference(category_terms)
    if any(
        _term_present(term, title_tokens, title_compacts)
        for term in competing_scoped_terms
    ):
        return True
    target_present = any(
        _term_present(term, title_tokens, title_compacts)
        for term in category_terms
    )
    if target_present:
        return False
    competing_terms = {
        term
        for terms in CATEGORY_MATCH_TERMS.values()
        for term in terms
        if term not in category_terms
    }
    return any(
        _term_present(term, title_tokens, title_compacts)
        for term in competing_terms
    )


def _is_product_related(
    product: Product,
    details_snippet: dict[str, Any],
    search_snippet: dict[str, Any],
) -> bool:
    title_values = (
        details_snippet.get("title"),
        search_snippet.get("title"),
    )
    title_tokens = {
        token
        for value in title_values
        for token in _match_tokens(value)
    }
    title_compacts = tuple(
        compact
        for compact in (_normalized_match_text(value) for value in title_values)
        if compact
    )
    if not title_compacts:
        return False

    profile = _product_match_profile(product)
    if not profile.product_terms and not profile.product_name_phrases:
        # A catalog row containing only a brand cannot be distinguished from
        # brand-wide videos, so prefer no card over a misleading match.
        return False
    if _has_conflicting_category(profile.category_terms, title_tokens, title_compacts):
        return False

    # Descriptions can establish that this is a review/use video, but cannot
    # establish product identity by themselves. This avoids SEO tag lists and
    # channel names pulling unrelated videos into the results.
    title_has_review_intent = _has_review_intent(title_values)
    if not title_has_review_intent and not _has_review_intent(
        (search_snippet.get("description"),)
    ):
        return False

    full_name_match = any(
        phrase in compact
        for phrase in profile.full_name_phrases
        for compact in title_compacts
    )
    if full_name_match:
        return True

    product_phrase_match = any(
        phrase in compact
        for phrase in profile.product_name_phrases
        for compact in title_compacts
    )
    if product_phrase_match:
        return True

    brand_match = any(
        _group_present(group, title_tokens, title_compacts)
        for group in profile.brand_groups
    )
    matched_terms = {
        term
        for term in profile.product_terms
        if _term_present(term, title_tokens, title_compacts)
    }
    matched_named_terms = {
        term
        for term in matched_terms
        if not term.isdigit()
    }
    category_match = any(
        _term_present(term, title_tokens, title_compacts)
        for term in profile.category_terms
    )
    if brand_match and matched_named_terms:
        return True
    if len(matched_named_terms) >= 2:
        return True

    # Numeric edition names (for example 1025 or 77) are only meaningful with
    # a matching product category. A number by itself is too collision-prone.
    if brand_match and matched_terms and category_match:
        return True
    return False
