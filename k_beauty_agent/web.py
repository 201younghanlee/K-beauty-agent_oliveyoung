from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import time
import unicodedata
import uuid
from collections import Counter, OrderedDict, deque
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .agent import KBeautyAgent
from .config import (
    DEFAULT_JSON_DB,
    DEFAULT_CATALOG_MANIFEST,
    DEFAULT_GENERATED_CATALOG_CSV,
    DEFAULT_PRODUCTS_CSV,
    DEFAULT_REVIEWS_CSV,
    admin_token,
    active_affiliate_source_ids,
    affiliate_redirect_secret,
    affiliate_webhook_secret,
    cookie_samesite,
    cors_allow_origins,
    external_cache_path,
    is_production,
    product_source,
    product_reason_llm_enabled,
    public_llm_enabled,
    recommend_rate_limit_requests,
    recommend_rate_limit_window_seconds,
    secure_cookies,
    sqlite_path_from_url,
    validate_runtime_secrets,
    youtube_api_key,
    youtube_review_cache_ttl_seconds,
    youtube_search_daily_limit,
)
from .commerce import CommerceService, RedirectTokenError, disclosure_metadata
from .database import ProductDatabase
from .followup_parser import is_safe_cosmetic_ingredient_text, sanitize_profile_patch
from .ingestion import sync_retailer_sources
from .live_products import LiveProductDatabase
from .llm import HybridExplainer, ProductReasonExplainer
from .knowledge_base import canonical_ingredient_key
from .localization import format_recommendation_text
from .openai_client import OpenAIResponsesClient
from .personalization import apply_profile_patch, build_personalization, profile_to_dict
from .serializers import product_to_dict, product_to_v2_dict, recommendation_to_dict
from .storage import SQLiteStore, SessionWriteLimitError, hash_session
from .skin import analyze_skin_query
from .source_adapters import configured_sources, source_status
from .video_reviews import YouTubeReviewService

SESSION_COOKIE = "kbeauty_session_id"
SESSION_HEADER = "X-KBeauty-Session"
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
COOKIE_MAX_AGE = 30 * 86400
RATE_LIMIT_MAX_BUCKETS = 10_000
VIDEO_REVIEW_RATE_LIMIT_REQUESTS = 8
VIDEO_REVIEW_GLOBAL_RATE_LIMIT_REQUESTS = 30
VIDEO_REVIEW_RATE_LIMIT_WINDOW_SECONDS = 5 * 60
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
PRIVACY_POLICY_VERSION = "2026-07-22"
YOUTUBE_POLICY_ACCEPTANCE_VERSION = PRIVACY_POLICY_VERSION

logger = logging.getLogger("k_beauty_agent")
logging.basicConfig(level=logging.INFO, format="%(message)s")
_rate_limit_lock = Lock()
_rate_limit_buckets: OrderedDict[str, deque[float]] = OrderedDict()
_cleanup_lock = Lock()
_last_cleanup_monotonic = 0.0
RETENTION_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60
MAX_CONVERSION_WEBHOOK_BYTES = 64 * 1024
MAX_PUBLIC_REQUEST_BODY_BYTES = 128 * 1024
ProfileText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
SourceQueryText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
SENSITIVE_HEALTH_INPUT_PATTERN = re.compile(
    r"\b(?:allerg(?:y|ies|ic)|pregnan(?:t|cy)|nursing|breast(?:feed|feeding)|"
    r"rosacea|eczema|psoriasis|dermatitis|prescription|medication)\b"
    r"|(?:알레르기|알러지|임신|임산부|수유|모유|아토피|습진|건선|피부염|질환|처방|복용|약물)",
    re.IGNORECASE,
)


def _request_text_values(value: object) -> list[str]:
    """Collect every textual request field for the sensitive-data gate."""

    if isinstance(value, str):
        return [value]
    if isinstance(value, BaseModel):
        return _request_text_values(value.model_dump(exclude_none=True))
    if isinstance(value, dict):
        return [text for item in value.values() for text in _request_text_values(item)]
    if isinstance(value, (list, tuple, set)):
        return [text for item in value for text in _request_text_values(item)]
    return []


def _close_retailer_sources(sources: list[object]) -> None:
    for source in sources:
        close = getattr(getattr(source, "client", None), "close", None)
        if callable(close):
            close()


@asynccontextmanager
async def _app_lifespan(_: FastAPI):
    try:
        yield
    finally:
        _close_retailer_sources(list(globals().get("_source_registry", [])))
        review_service = globals().get("youtube_reviews")
        if isinstance(review_service, YouTubeReviewService):
            review_service.close()


def _build_agent() -> KBeautyAgent:
    if DEFAULT_PRODUCTS_CSV.exists():
        fallback = ProductDatabase.from_csv(DEFAULT_PRODUCTS_CSV, DEFAULT_REVIEWS_CSV)
    else:
        fallback = ProductDatabase.from_json(DEFAULT_JSON_DB)
    source = product_source()
    if source in {"catalog_snapshot", "hybrid_catalog"}:
        try:
            generated = _load_generated_catalog(DEFAULT_GENERATED_CATALOG_CSV, DEFAULT_CATALOG_MANIFEST)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Generated catalog disabled: %s", exc)
        else:
            return KBeautyAgent(ProductDatabase.combine(fallback, generated))
    if source in {"live_keyless", "live_amazon"}:
        return KBeautyAgent(LiveProductDatabase(fallback, cache_path=external_cache_path()))
    return KBeautyAgent(fallback)


def _load_generated_catalog(csv_path: Path, manifest_path: Path) -> ProductDatabase:
    if not csv_path.is_file() or not manifest_path.is_file():
        raise ValueError("generated CSV and manifest must both exist")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("catalog manifest must be a JSON object")
    if manifest.get("schema_version") != 1 or manifest.get("catalog_source") != "open_beauty_facts":
        raise ValueError("catalog manifest schema or source is unsupported")

    digest = hashlib.sha256()
    with csv_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != manifest.get("csv_sha256"):
        raise ValueError("generated catalog SHA-256 does not match its manifest")

    freshness = manifest.get("record_freshness")
    database = ProductDatabase.from_csv(
        csv_path,
        catalog_updated_at=str(manifest.get("generated_at")) if manifest.get("generated_at") else None,
        catalog_freshness=freshness if isinstance(freshness, dict) else None,
    )
    if len(database.products) != manifest.get("product_count"):
        raise ValueError("generated catalog product count does not match its manifest")
    actual_category_counts = dict(sorted(Counter(product.category for product in database.products).items()))
    if actual_category_counts != manifest.get("category_counts"):
        raise ValueError("generated catalog category counts do not match its manifest")
    if not manifest.get("generated_at") or not isinstance(freshness, dict):
        raise ValueError("generated catalog freshness metadata is missing")
    for product in database.products:
        if (
            product.catalog_source != "open_beauty_facts"
            or product.ingredient_status != "reported"
            or product.recommendation_tier != "eligible"
            or not product.source_product_id
            or not product.source_url
            or not product.image_url
            or not product.ingredients
            or "ODbL-1.0" not in (product.data_license or "")
            or not product.data_attribution_url
        ):
            raise ValueError(f"generated catalog row failed metadata validation: {product.id}")
    return database


validate_runtime_secrets()
app = FastAPI(title="K-Beauty Agent", version="0.2.0", lifespan=_app_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins(),
    allow_origin_regex=None if is_production() else r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
store = SQLiteStore(sqlite_path_from_url())
store.apply_public_profile_minimization_migration()
agent = _build_agent()
commerce = CommerceService(store, affiliate_redirect_secret())
youtube_reviews = YouTubeReviewService(
    youtube_api_key(),
    daily_search_limit=youtube_search_daily_limit(),
    cache_ttl_seconds=youtube_review_cache_ttl_seconds(),
    quota_store=store,
)
_close_retailer_sources(list(globals().get("_source_registry", [])))
_source_registry = configured_sources(include_disabled=True)
commerce.reconcile_source_activation(
    configured_source_ids={source.source_id for source in _source_registry if source.enabled},
    approved_affiliate_source_ids=active_affiliate_source_ids(),
)
commerce.sync_legacy_catalog(agent.database.products)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class RecommendationProfileRequest(BaseModel):
    skin_type: Literal["oily", "dry", "combination", "sensitive", "normal", "unknown"]
    sensitivity_level: Literal["frequent", "occasional", "low"] | None = None
    primary_concern: Literal[
        "oil_control",
        "acne",
        "clogged_pores",
        "hydration",
        "barrier_support",
        "redness",
        "hyperpigmentation",
        "dullness",
        "anti_aging",
        "texture",
        "dryness",
    ] | None = None
    concerns: list[
        Literal[
            "oil_control",
            "acne",
            "clogged_pores",
            "hydration",
            "barrier_support",
            "redness",
            "hyperpigmentation",
            "dullness",
            "anti_aging",
            "texture",
            "dryness",
        ]
    ] = Field(default_factory=list, max_length=8)
    desired_categories: list[Literal["cleanser", "toner", "serum", "moisturizer", "sunscreen", "basic"]] = Field(
        ..., min_length=1, max_length=6
    )
    avoid_ingredients: list[ProfileText] = Field(default_factory=list, max_length=12)
    preferred_ingredients: list[ProfileText] = Field(default_factory=list, max_length=12)
    max_price_krw: int | None = Field(default=None, ge=1_000, le=2_000_000)
    texture_preference: Literal["dewy", "lightweight", "rich", "gel", "watery", "lotion", "cream"] | None = None
    finish_preference: Literal["fresh", "low_sticky", "moist", "glow", "matte"] | None = None


class RecommendRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1200)
    limit: int = Field(3, ge=1, le=8)
    use_openai: bool = True
    language: Literal["en", "ko"] = "en"
    profile: RecommendationProfileRequest | None = None
    privacy_consent: bool = False
    privacy_policy_version: Literal["2026-07-20", "2026-07-22"] = PRIVACY_POLICY_VERSION


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_id: int | None = None
    target: Literal["product", "result"]
    product_id: str | None = Field(default=None, min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    feedback: Literal["liked", "disliked"]
    reason_tags: list[
        Literal[
            "too_expensive",
            "irritating",
            "wrong_skin_type",
            "bad_texture",
            "already_tried",
            "not_available",
            "liked_ingredients",
            "other",
        ]
    ] = Field(default_factory=list, max_length=12)


class SelectionRequest(BaseModel):
    product_id: str = Field(..., min_length=1, max_length=160)
    list_type: Literal["saved", "compare"]
    selected: bool = True


class AdminConversionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    affiliate_program_id: str = Field(..., pattern=r"^[A-Za-z0-9_.-]{1,120}$")
    external_conversion_id: str = Field(..., pattern=r"^[A-Za-z0-9_.:-]{1,240}$")
    status: Literal["pending", "approved", "rejected", "reversed"]
    occurred_at: str | int
    click_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{1,160}$")
    order_amount: int | None = Field(default=None, ge=0, le=9_000_000_000_000)
    commission_amount: int | None = Field(default=None, ge=0, le=9_000_000_000_000)
    currency: str = Field(default="KRW", min_length=3, max_length=3)


class AdminSourceSyncRequest(BaseModel):
    query: SourceQueryText | None = None
    queries: list[SourceQueryText] = Field(default_factory=list, max_length=25)
    source_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,120}$")
    limit: int = Field(default=20, ge=1, le=100)


def _session_id(request: Request) -> str:
    header_session = request.headers.get(SESSION_HEADER)
    if header_session and SESSION_ID_PATTERN.fullmatch(header_session) is None:
        raise HTTPException(status_code=400, detail=f"{SESSION_HEADER} must be a 20-128 character URL-safe token")
    cookie_session = request.cookies.get(SESSION_COOKIE)
    valid_cookie = cookie_session if cookie_session and SESSION_ID_PATTERN.fullmatch(cookie_session) else None
    existing = header_session or valid_cookie
    return existing or secrets.token_urlsafe(32)


def _set_cookie(response: Response, session_id: str, request: Request | None = None) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite=cookie_samesite(),
        secure=secure_cookies() or (request is not None and request.url.scheme == "https"),
    )


def _require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not x_admin_token or not hmac.compare_digest(x_admin_token, admin_token()):
        raise HTTPException(status_code=401, detail="Invalid admin token")


def _require_consented_session(session_id: str) -> None:
    if not store.has_privacy_consent(session_id, PRIVACY_POLICY_VERSION):
        raise HTTPException(status_code=403, detail="An active consented session is required")


def _check_recommendation_rate_limit(request: Request, session_id: str) -> None:
    now = time.monotonic()
    window = recommend_rate_limit_window_seconds()
    limit = recommend_rate_limit_requests()
    client_ip = (request.client.host if request.client else "unknown")[:100]
    limits_by_identifier = {
        f"session:{hash_session(session_id)}": limit,
        "global": min(100_000, limit * 100),
    }
    try:
        if ipaddress.ip_address(client_ip).is_global:
            limits_by_identifier[f"ip:{client_ip}"] = limit
    except ValueError:
        pass

    with _rate_limit_lock:
        buckets: list[tuple[deque[float], int]] = []
        for identifier, identifier_limit in limits_by_identifier.items():
            bucket = _rate_limit_buckets.setdefault(identifier, deque())
            while bucket and now - bucket[0] >= window:
                bucket.popleft()
            _rate_limit_buckets.move_to_end(identifier)
            buckets.append((bucket, identifier_limit))

        if any(len(bucket) >= identifier_limit for bucket, identifier_limit in buckets):
            raise HTTPException(
                status_code=429,
                detail="Too many recommendation requests. Please try again shortly.",
                headers={"Retry-After": str(window)},
            )

        for bucket, _ in buckets:
            bucket.append(now)
        while len(_rate_limit_buckets) > RATE_LIMIT_MAX_BUCKETS:
            _rate_limit_buckets.popitem(last=False)


def _check_video_review_rate_limit(request: Request) -> None:
    now = time.monotonic()
    client_label = (request.client.host if request.client else "unknown")[:200]
    limits_by_identifier = {
        "video-review:global": VIDEO_REVIEW_GLOBAL_RATE_LIMIT_REQUESTS,
    }
    try:
        if ipaddress.ip_address(client_label).is_global:
            client_hash = hashlib.sha256(client_label.encode("utf-8")).hexdigest()[:24]
            limits_by_identifier[f"video-review:client:{client_hash}"] = VIDEO_REVIEW_RATE_LIMIT_REQUESTS
    except ValueError:
        pass

    with _rate_limit_lock:
        buckets: list[tuple[deque[float], int]] = []
        for identifier, identifier_limit in limits_by_identifier.items():
            bucket = _rate_limit_buckets.setdefault(identifier, deque())
            while bucket and now - bucket[0] >= VIDEO_REVIEW_RATE_LIMIT_WINDOW_SECONDS:
                bucket.popleft()
            _rate_limit_buckets.move_to_end(identifier)
            buckets.append((bucket, identifier_limit))
        if any(len(bucket) >= identifier_limit for bucket, identifier_limit in buckets):
            raise HTTPException(
                status_code=429,
                detail="영상 요청이 잠시 몰렸어요. 잠시 후 다시 확인해 주세요.",
                headers={"Retry-After": str(VIDEO_REVIEW_RATE_LIMIT_WINDOW_SECONDS)},
            )
        for bucket, _ in buckets:
            bucket.append(now)
        while len(_rate_limit_buckets) > RATE_LIMIT_MAX_BUCKETS:
            _rate_limit_buckets.popitem(last=False)


def _maybe_cleanup_expired() -> None:
    global _last_cleanup_monotonic
    now = time.monotonic()
    if now - _last_cleanup_monotonic < RETENTION_CLEANUP_INTERVAL_SECONDS:
        return
    with _cleanup_lock:
        if now - _last_cleanup_monotonic < RETENTION_CLEANUP_INTERVAL_SECONDS:
            return
        try:
            store.cleanup_expired()
        except Exception as exc:  # pragma: no cover - operational safeguard
            logger.warning("Retention cleanup failed: %s", str(exc)[:500])
        else:
            _last_cleanup_monotonic = now


@app.middleware("http")
async def structured_logging(request: Request, call_next):
    _maybe_cleanup_expired()
    supplied_request_id = request.headers.get("x-request-id", "")
    request_id = supplied_request_id if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", supplied_request_id) else str(uuid.uuid4())
    started = time.perf_counter()
    status_code = 500
    try:
        if request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.headers.get("content-length")
            if content_length and content_length.isdigit() and int(content_length) > MAX_PUBLIC_REQUEST_BODY_BYTES:
                status_code = 413
                return _request_too_large_response()
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_PUBLIC_REQUEST_BODY_BYTES:
                    status_code = 413
                    return _request_too_large_response()
            request._body = bytes(body)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' https://cdn.jsdelivr.net; img-src 'self' data: https:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        status_code = response.status_code
        return response
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        session_id = _existing_session_for_click(request)
        consented_session_hash = None
        if session_id:
            try:
                if store.has_privacy_consent(session_id, PRIVACY_POLICY_VERSION):
                    consented_session_hash = hash_session(session_id)
            except Exception:  # pragma: no cover - logging must never mask an HTTP response
                consented_session_hash = None
        payload = {
            "event": "http_request",
            "request_id": request_id,
            "method": request.method,
            "path": "/r/{token}" if request.url.path.startswith("/r/") else request.url.path[:500],
            "status_code": status_code,
            "latency_ms": latency_ms,
            "session_hash": consented_session_hash,
        }
        logger.info(json.dumps(payload, ensure_ascii=False))


def _request_too_large_response() -> JSONResponse:
    response = JSONResponse(
        status_code=413,
        content={"detail": "Request body is too large"},
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/compare")
def compare_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/profile")
def profile_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/routine")
def routine_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
def admin_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/privacy")
def privacy_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "privacy.html")


@app.get("/terms")
def terms_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "terms.html")


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "products": len(agent.database.products),
        "product_source": product_source(),
        "product_source_status": _product_source_status(),
        "public_llm_enabled": public_llm_enabled(),
        "youtube_reviews": {
            "api_configured": youtube_reviews.configured,
            "fallback": "product_specific_youtube_search",
        },
    }


@app.get("/api/session")
def get_session(request: Request, response: Response, session_id: str = Depends(_session_id)) -> dict[str, object]:
    session = store.get_session(session_id)
    _set_cookie(response, session_id, request)
    return {
        "session_id_hash": hash_session(session_id),
        "profile": session["profile"] if session else {},
        "recent_queries": store.recent_queries(session_id, 5) if session else [],
        "consented": bool(session and store.has_privacy_consent(session_id, PRIVACY_POLICY_VERSION)),
    }


@app.delete("/api/session")
def reset_session(response: Response, session_id: str = Depends(_session_id)) -> dict[str, object]:
    store.delete_session(session_id)
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        samesite=cookie_samesite(),
        secure=secure_cookies(),
    )
    return {"ok": True}


@app.delete("/api/profile")
def reset_profile(request: Request, response: Response, session_id: str = Depends(_session_id)) -> dict[str, object]:
    if store.has_privacy_consent(session_id, PRIVACY_POLICY_VERSION):
        store.save_profile(session_id, {})
        store.log_event("profile_reset", {}, session_id=session_id)
    _set_cookie(response, session_id, request)
    return {"ok": True, "profile": {}}


@app.get("/api/products")
def products(
    q: str = Query(default="", max_length=120),
    category: str | None = Query(default=None, max_length=40),
    source: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: int = Query(default=0, ge=0),
) -> dict[str, object]:
    if hasattr(agent.database, "catalog_page"):
        page, total = agent.database.catalog_page(
            query=q,
            category=category,
            source=source,
            limit=limit,
            offset=cursor,
        )
    else:
        view = ProductDatabase(list(agent.database.products))
        page, total = view.catalog_page(query=q, category=category, source=source, limit=limit, offset=cursor)
    next_cursor = cursor + len(page) if cursor + len(page) < total else None
    return {
        "products": [product_to_dict(product) for product in page],
        "total": total,
        "next_cursor": next_cursor,
    }


@app.get("/api/catalog/status")
def catalog_status() -> dict[str, object]:
    return _product_source_status()


@app.get("/api/v2/products")
def products_v2(
    q: str = Query(default="", max_length=120),
    category: str | None = Query(default=None, max_length=40),
    source: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: int = Query(default=0, ge=0),
) -> dict[str, object]:
    if hasattr(agent.database, "catalog_page"):
        page, total = agent.database.catalog_page(
            query=q,
            category=category,
            source=source,
            limit=limit,
            offset=cursor,
        )
    else:
        view = ProductDatabase(list(agent.database.products))
        page, total = view.catalog_page(query=q, category=category, source=source, limit=limit, offset=cursor)
    summaries = commerce.product_summaries(product.id for product in page)
    next_cursor = cursor + len(page) if cursor + len(page) < total else None
    commerce_status = commerce.catalog_status()
    return {
        "schema_version": 2,
        "products": [product_to_v2_dict(product, summaries.get(product.id)) for product in page],
        "total": total,
        "next_cursor": next_cursor,
        "affiliate_disclosure": commerce_status["affiliate_disclosure"],
    }


@app.get("/api/v2/products/{product_id}/offers")
def product_offers_v2(product_id: str) -> dict[str, object]:
    if agent.database.get(product_id) is None:
        raise HTTPException(status_code=404, detail="Unknown product_id")
    return commerce.offers_for_product(product_id)


@app.get("/api/v2/products/{product_id}/video-reviews")
def product_video_reviews_v2(
    request: Request,
    product_id: str,
    limit: int = Query(default=3, ge=1, le=3),
    x_youtube_policy_accepted: str | None = Header(
        default=None,
        alias="X-YouTube-Policy-Accepted",
    ),
) -> dict[str, object]:
    if x_youtube_policy_accepted != YOUTUBE_POLICY_ACCEPTANCE_VERSION:
        raise HTTPException(
            status_code=428,
            detail="YouTube 관련 영상 기능의 이용조건과 개인정보 처리 안내에 먼저 동의해 주세요.",
        )
    product = agent.database.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Unknown product_id")
    _check_video_review_rate_limit(request)
    return youtube_reviews.reviews_for_product(product, limit=limit)


@app.get("/api/v2/catalog/status")
def catalog_status_v2() -> dict[str, object]:
    return {
        "catalog": _product_source_status(),
        "commerce": commerce.public_catalog_status(),
    }


@app.post("/api/recommend")
def recommend(payload: RecommendRequest, request: Request, response: Response, session_id: str = Depends(_session_id)) -> dict[str, object]:
    return _recommend(payload, request, response, session_id, is_follow_up=False)


@app.post("/api/v2/recommend")
def recommend_v2(
    payload: RecommendRequest,
    request: Request,
    response: Response,
    session_id: str = Depends(_session_id),
) -> dict[str, object]:
    return _recommend_v2(payload, request, response, session_id, is_follow_up=False)


@app.post("/api/v2/follow-up")
def follow_up_v2(
    payload: RecommendRequest,
    request: Request,
    response: Response,
    session_id: str = Depends(_session_id),
) -> dict[str, object]:
    return _recommend_v2(payload, request, response, session_id, is_follow_up=True)


def _recommend_v2(
    payload: RecommendRequest,
    request: Request,
    response: Response,
    session_id: str,
    *,
    is_follow_up: bool,
) -> dict[str, object]:
    result = _recommend(payload, request, response, session_id, is_follow_up=is_follow_up)
    valid_ids: list[str] = []
    for item in result.get("results", []):
        product_id = item.get("product", {}).get("id")
        if isinstance(product_id, str):
            valid_ids.append(product_id)
        for similar in item.get("similar_products", []):
            similar_id = similar.get("id") if isinstance(similar, dict) else None
            if isinstance(similar_id, str):
                valid_ids.append(similar_id)
    summaries = commerce.product_summaries(valid_ids)
    for item in result.get("results", []):
        product_id = item.get("product", {}).get("id")
        product = agent.database.get(product_id) if isinstance(product_id, str) else None
        if product is not None:
            item["product"] = product_to_v2_dict(product, summaries.get(product.id))
        normalized_similar = []
        for similar in item.get("similar_products", []):
            similar_id = similar.get("id") if isinstance(similar, dict) else None
            similar_product = agent.database.get(similar_id) if isinstance(similar_id, str) else None
            if similar_product is not None:
                normalized_similar.append(
                    product_to_v2_dict(similar_product, summaries.get(similar_product.id))
                )
        item["similar_products"] = normalized_similar

    profile_data = result.get("profile") if isinstance(result.get("profile"), dict) else {}
    has_krw_budget = profile_data.get("max_price_krw") is not None or profile_data.get("min_price_krw") is not None
    additional_candidates: list[dict[str, object]] = []
    if has_krw_budget:
        verified_results: list[dict[str, object]] = []
        for item in result.get("results", []):
            product = item.get("product") if isinstance(item, dict) else None
            commerce_data = product.get("commerce") if isinstance(product, dict) else None
            fresh_krw = commerce_data.get("lowest_fresh_price_krw") if isinstance(commerce_data, dict) else None
            if fresh_krw is None:
                additional_candidates.append(item)
            else:
                verified_results.append(item)
        result["results"] = verified_results
    result["additional_candidates"] = additional_candidates
    result["schema_version"] = 2
    result["affiliate_disclosure"] = commerce.public_catalog_status()["affiliate_disclosure"]
    result["ranking_policy"] = disclosure_metadata(False)["ranking_policy_ko"]
    return result


@app.get("/r/{token}", include_in_schema=False)
def outbound_redirect(token: str, request: Request) -> RedirectResponse:
    try:
        target = commerce.resolve_redirect_token(token)
    except RedirectTokenError as exc:
        raise HTTPException(status_code=404, detail="Link is invalid or expired") from exc
    session_id = _existing_session_for_click(request)
    if session_id and not store.has_privacy_consent(session_id, PRIVACY_POLICY_VERSION):
        session_id = None
    commerce.log_click(target, session_id=session_id)
    response = RedirectResponse(target.url, status_code=302)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.post("/api/follow-up")
def follow_up(payload: RecommendRequest, request: Request, response: Response, session_id: str = Depends(_session_id)) -> dict[str, object]:
    return _recommend(payload, request, response, session_id, is_follow_up=True)


@app.post("/api/feedback")
def feedback(payload: FeedbackRequest, request: Request, response: Response, session_id: str = Depends(_session_id)) -> dict[str, object]:
    if payload.target == "product" and not payload.product_id:
        raise HTTPException(status_code=400, detail="product_id is required for product feedback")
    if payload.target == "result" and payload.product_id is not None:
        raise HTTPException(status_code=400, detail="product_id is only allowed for product feedback")
    _require_consented_session(session_id)
    if payload.recommendation_id is None or not store.recommendation_belongs_to_session(
        payload.recommendation_id, session_id
    ):
        raise HTTPException(status_code=400, detail="recommendation_id must belong to the current session")
    if payload.product_id is not None and (
        agent.database.get(payload.product_id) is None
        or not store.recommendation_contains_product(payload.recommendation_id, session_id, payload.product_id)
    ):
        raise HTTPException(status_code=400, detail="product_id must belong to the referenced recommendation")
    try:
        feedback_id = store.add_feedback(
            session_id=session_id,
            target=payload.target,
            feedback=payload.feedback,
            recommendation_id=payload.recommendation_id,
            product_id=payload.product_id,
            reason_tags=list(payload.reason_tags),
        )
    except SessionWriteLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail="Too many feedback submissions. Please try again later.",
            headers={"Retry-After": "60"},
        ) from exc
    store.log_event(
        "feedback",
        {"target": payload.target, "feedback": payload.feedback, "product_id": payload.product_id},
        session_id=session_id,
    )
    _set_cookie(response, session_id, request)
    return {"ok": True, "feedback_id": feedback_id}


@app.get("/api/selections")
def selections(request: Request, response: Response, session_id: str = Depends(_session_id)) -> dict[str, object]:
    result = _selection_payload(session_id)
    _set_cookie(response, session_id, request)
    return result


@app.post("/api/selections")
def update_selection(
    payload: SelectionRequest,
    request: Request,
    response: Response,
    session_id: str = Depends(_session_id),
) -> dict[str, object]:
    _require_consented_session(session_id)
    if agent.database.get(payload.product_id) is None:
        raise HTTPException(status_code=404, detail="Unknown product_id")
    store.set_selection(session_id, payload.product_id, payload.list_type, payload.selected)
    result = _selection_payload(session_id)
    _set_cookie(response, session_id, request)
    return result


@app.get("/api/admin/metrics")
def admin_metrics(_: None = Depends(_require_admin)) -> dict[str, object]:
    return {**store.metrics(), "commerce": commerce.catalog_status()}


@app.post("/api/admin/conversions")
def admin_conversion(
    payload: AdminConversionRequest,
    _: None = Depends(_require_admin),
) -> dict[str, object]:
    try:
        result = commerce.record_admin_conversion(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "conversion_id": result.record_id, "created": result.created}


@app.post("/api/integrations/affiliate/conversions", include_in_schema=False)
async def signed_affiliate_conversion(
    request: Request,
    x_affiliate_signature: str | None = Header(default=None, alias="X-Affiliate-Signature"),
    x_affiliate_timestamp: str | None = Header(default=None, alias="X-Affiliate-Timestamp"),
) -> dict[str, object]:
    webhook_secret = affiliate_webhook_secret()
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Affiliate conversion callback is not configured")
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_CONVERSION_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Conversion payload is too large")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_CONVERSION_WEBHOOK_BYTES:
            raise HTTPException(status_code=413, detail="Conversion payload is too large")
    raw_payload = bytes(body)
    if not x_affiliate_signature or not x_affiliate_timestamp:
        raise HTTPException(status_code=401, detail="Missing conversion signature")
    try:
        result = commerce.record_signed_conversion(
            raw_payload=raw_payload,
            signature=x_affiliate_signature,
            signed_at=int(x_affiliate_timestamp),
            webhook_secret=webhook_secret,
        )
    except (TypeError, ValueError) as exc:
        status_code = 401 if "signature" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"ok": True, "conversion_id": result.record_id, "created": result.created}


@app.get("/api/admin/sources")
def admin_sources(_: None = Depends(_require_admin)) -> dict[str, object]:
    try:
        sources = list(_source_registry)
        enabled_source_ids = {source.source_id for source in sources if source.enabled}
        approved = active_affiliate_source_ids()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reconciliation = commerce.reconcile_source_activation(
        configured_source_ids=enabled_source_ids,
        approved_affiliate_source_ids=approved,
    )
    return {
        "sources": source_status(sources),
        "active_affiliate_source_ids": sorted(approved),
        "activation_policy": "explicit_source_approval",
        "reconciliation": reconciliation,
    }


@app.get("/api/admin/source-candidates")
def admin_source_candidates(
    source_id: str | None = Query(default=None, pattern=r"^[A-Za-z0-9_.-]{1,120}$"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: int = Query(default=0, ge=0),
    _: None = Depends(_require_admin),
) -> dict[str, object]:
    return commerce.source_review_candidates(source_id=source_id, limit=limit, cursor=cursor)


@app.post("/api/admin/sources/sync")
def admin_source_sync(
    payload: AdminSourceSyncRequest,
    _: None = Depends(_require_admin),
) -> dict[str, object]:
    requested_queries = [payload.query] if payload.query else []
    requested_queries.extend(payload.queries)
    queries = list(dict.fromkeys(query.strip() for query in requested_queries if query and query.strip()))
    if not queries:
        raise HTTPException(status_code=400, detail="Provide query or at least one non-empty queries item")
    try:
        sources = [source for source in _source_registry if source.enabled]
        approved = active_affiliate_source_ids()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.source_id:
        sources = [source for source in sources if source.source_id == payload.source_id]
    if not sources:
        raise HTTPException(status_code=400, detail="No enabled source matches this request")
    commerce.reconcile_source_activation(
        configured_source_ids={source.source_id for source in _source_registry if source.enabled},
        approved_affiliate_source_ids=approved,
    )

    reports: list[dict[str, object]] = []
    for query in queries:
        query_reports = sync_retailer_sources(
            commerce,
            agent.database.products,
            query=query,
            sources=sources,
            active_affiliate_source_ids=approved,
            limit=payload.limit,
        )
        reports.extend({"query": query, **asdict(report)} for report in query_reports)
    return {
        "ok": all(report["status"] == "completed" for report in reports),
        "reports": reports,
        "affiliate_activation_requires_approval": True,
    }


@app.post("/api/admin/cleanup")
def admin_cleanup(_: None = Depends(_require_admin)) -> dict[str, object]:
    return {"deleted": store.cleanup_expired()}


@app.post("/api/admin/reload")
def admin_reload(_: None = Depends(_require_admin)) -> dict[str, object]:
    global agent
    agent = _build_agent()
    commerce.sync_legacy_catalog(agent.database.products)
    return {"ok": True, "products": len(agent.database.products)}


def _recommend(payload: RecommendRequest, request: Request, response: Response, session_id: str, *, is_follow_up: bool) -> dict[str, object]:
    _check_recommendation_rate_limit(request, session_id)
    # Check the natural-language query and every structured text field before
    # creating a session. This prevents moving health text from an avoid field
    # into a preferred ingredient (or a future ProfileText field) to bypass the
    # separate-sensitive-consent gate.
    sensitive_input = _request_text_values(payload)
    if SENSITIVE_HEALTH_INPUT_PATTERN.search(
        unicodedata.normalize("NFKC", " ".join(sensitive_input))
    ):
        detail = (
            "별도 민감정보 동의 기능이 준비되기 전에는 알레르기·임신·수유 정보를 입력할 수 없어요. "
            "건강 상태 대신 피하고 싶은 성분명만 입력해 주세요."
            if payload.language == "ko"
            else "Allergy, pregnancy, and nursing information is disabled until separate sensitive-data consent is available. Enter ingredient names to avoid instead."
        )
        raise HTTPException(status_code=422, detail=detail)
    if payload.profile is not None:
        invalid_ingredients = [
            value
            for value in (*payload.profile.avoid_ingredients, *payload.profile.preferred_ingredients)
            if not is_safe_cosmetic_ingredient_text(value)
        ]
        if invalid_ingredients:
            detail = (
                "성분명 형식만 입력해 주세요. 이메일·전화번호·URL·메모 문장은 입력할 수 없어요."
                if payload.language == "ko"
                else "Enter cosmetic ingredient names only. Email addresses, phone numbers, URLs, and note-like sentences are not allowed."
            )
            raise HTTPException(status_code=422, detail=detail)
    if payload.profile is not None:
        # Sanitization intentionally de-duplicates list fields. Check the raw
        # request first so an accidental duplicate is still reported to the
        # user instead of being silently accepted.
        concerns = list(payload.profile.concerns)
        if len(concerns) != len(set(concerns)):
            _raise_profile_validation("duplicate_concerns", payload.language)
    started = time.perf_counter()
    # Keep the immediately previous client version usable during the staged
    # Toss rollout, but never treat consent to an older notice as consent to
    # the current policy. Legacy clients still receive a stateless result and
    # write no session, profile, recommendation, turn, or event rows.
    policy_is_current = payload.privacy_policy_version == PRIVACY_POLICY_VERSION
    consented = payload.privacy_consent and policy_is_current
    if is_follow_up and not consented:
        raise HTTPException(status_code=400, detail="Privacy consent is required for saved-session follow-up")
    if consented:
        try:
            session = store.ensure_session(session_id)
        except SessionWriteLimitError as exc:
            raise HTTPException(
                status_code=429,
                detail="Anonymous session capacity is temporarily unavailable",
                headers={"Retry-After": "60"},
            ) from exc
        store.record_privacy_consent(session_id, payload.privacy_policy_version)
        feedback_rows = store.feedback_for_session(session_id)
    else:
        session = {"profile": {}}
        feedback_rows = []
    personalization = build_personalization(agent.database.products, feedback_rows)
    profile_patch = _public_profile_patch(payload)
    if is_follow_up:
        public_profile = apply_profile_patch(
            _sanitize_public_profile(session.get("profile") or {}),
            profile_patch,
        )
    else:
        public_profile = profile_patch
    # Validate only after the stored profile and follow-up patch have been
    # merged. This catches cross-turn preferred/avoid conflicts as well as
    # conflicts inside a single structured request.
    public_profile = _validate_public_profile(public_profile, payload.language)
    safe_query = _profile_storage_query(public_profile)
    follow_up_parser_status = "controlled_profile_only"
    recommendation = _fresh_price_agent().recommend(
        safe_query,
        limit=payload.limit,
        personalization=personalization,
        structured_profile=public_profile,
    )
    openai_status = "not_used"
    explanation = format_recommendation_text(recommendation, payload.language)
    if consented and payload.use_openai and public_llm_enabled():
        explainer = HybridExplainer(OpenAIResponsesClient(store=store, session_id=session_id))
        try:
            explanation = explainer.explain(recommendation, language=payload.language)
            openai_status = "ok"
        except Exception as exc:
            openai_status = "fallback"
            store.log_event("openai_error", {"error": str(exc)[:500]}, session_id=session_id)

    product_reason_status = "fallback"
    product_reasons: dict[str, str] = {}
    if consented and public_llm_enabled() and product_reason_llm_enabled():
        try:
            product_reasons = ProductReasonExplainer(OpenAIResponsesClient(store=store, session_id=session_id)).explain_reasons(
                recommendation,
                language=payload.language,
            )
            product_reason_status = "ok" if product_reasons else "empty"
        except Exception as exc:
            product_reason_status = "fallback"
            store.log_event("product_reason_error", {"error": str(exc)[:500]}, session_id=session_id)

    result = recommendation_to_dict(
        recommendation,
        grounded_explanation=explanation,
        openai_status=openai_status,
        language=payload.language,
        product_reasons=product_reasons,
    )
    result["product_source_status"] = _product_source_status()
    result["follow_up_parser_status"] = follow_up_parser_status
    result["product_reason_status"] = product_reason_status
    latency_ms = int((time.perf_counter() - started) * 1000)
    if consented:
        recommendation_id = store.add_recommendation(
            session_id, safe_query, recommendation.decision, result, latency_ms
        )
        result["recommendation_id"] = recommendation_id
        store.add_turn(session_id, "user", safe_query, result)
        store.save_profile(
            session_id,
            _sanitize_public_profile(profile_to_dict(recommendation.profile)),
        )
        store.log_event(
            "recommendation",
            {
                "decision": recommendation.decision,
                "recommendation_count": len(recommendation.results),
                "openai_status": openai_status,
            },
            session_id=session_id,
            latency_ms=latency_ms,
        )
        _set_cookie(response, session_id, request)
    else:
        result["recommendation_id"] = None
    result["privacy"] = {
        "stored": consented,
        "policy_version": PRIVACY_POLICY_VERSION if consented else None,
        "required_policy_version": PRIVACY_POLICY_VERSION,
        "consent_refresh_required": payload.privacy_consent and not policy_is_current,
    }
    return result


def _product_source_status() -> dict[str, object]:
    if hasattr(agent.database, "last_source_status"):
        return dict(agent.database.last_source_status)
    if hasattr(agent.database, "source_status"):
        status = dict(agent.database.source_status())
        status["product_source"] = product_source()
        return status
    return {"product_source": product_source(), "source_used": "curated_csv", "message": "Using curated CSV product database."}


def _fresh_price_agent() -> KBeautyAgent:
    """Build a request-local ranking view using only current KRW offer prices."""

    summaries = commerce.product_summaries(product.id for product in agent.database.products)
    products = [
        replace(product, price_krw=summaries.get(product.id, {}).get("lowest_fresh_price_krw"))
        for product in agent.database.products
    ]
    database = ProductDatabase(
        products,
        catalog_updated_at=getattr(agent.database, "catalog_updated_at", None),
        catalog_freshness=getattr(agent.database, "catalog_freshness", None),
    )
    return KBeautyAgent(database)


def _structured_profile(profile: RecommendationProfileRequest | None) -> dict[str, object] | None:
    if profile is None:
        return None
    cleaned = sanitize_profile_patch(
        profile.model_dump(exclude_none=True),
        allow_unrecognized_ingredients=True,
    )
    if profile.max_price_krw is not None:
        cleaned["sensitivities"] = ["budget_preference"]
    return cleaned


def _public_profile_patch(payload: RecommendRequest) -> dict[str, object]:
    structured = _structured_profile(payload.profile)
    if structured is not None:
        return _sanitize_public_profile(structured)
    return _sanitize_public_profile(profile_to_dict(analyze_skin_query(payload.query)))


def _sanitize_public_profile(profile: dict[str, object]) -> dict[str, object]:
    """Keep only controlled cosmetic preferences in responses and persistence."""

    return sanitize_profile_patch(profile, allow_unrecognized_ingredients=True)


def _validate_public_profile(profile: dict[str, object], language: str) -> dict[str, object]:
    """Normalize and validate the final merged public cosmetic profile."""

    cleaned = _sanitize_public_profile(profile)
    primary_concern = cleaned.get("primary_concern")
    concerns = list(cleaned.get("concerns", []))
    if len(concerns) != len(set(concerns)):
        _raise_profile_validation("duplicate_concerns", language)

    additional_concerns = [concern for concern in concerns if concern != primary_concern]
    if primary_concern and len(additional_concerns) > 2:
        _raise_profile_validation("too_many_additional_concerns", language)

    avoided = {canonical_ingredient_key(value) for value in cleaned.get("avoid_ingredients", [])}
    preferred = {canonical_ingredient_key(value) for value in cleaned.get("preferred_ingredients", [])}
    conflicts = sorted(avoided & preferred)
    if conflicts:
        _raise_profile_validation("ingredient_conflict", language, conflicts=conflicts)
    return cleaned


def _raise_profile_validation(
    code: str,
    language: str,
    *,
    conflicts: list[str] | None = None,
) -> None:
    korean = language == "ko"
    if code == "duplicate_concerns":
        detail = (
            "피부 고민을 중복해서 선택할 수 없어요."
            if korean
            else "Skin concerns cannot be selected more than once."
        )
    elif code == "too_many_additional_concerns":
        detail = (
            "추가 피부 고민은 최대 2개까지 선택할 수 있어요."
            if korean
            else "Choose at most two additional skin concerns."
        )
    elif code == "ingredient_conflict":
        names = ", ".join(conflicts or [])
        detail = (
            f"선호 성분과 제외 성분이 겹쳐요: {names}. 한쪽 선택을 해제해 주세요."
            if korean
            else f"Preferred and excluded ingredients overlap: {names}. Remove one of the selections."
        )
    else:  # pragma: no cover - callers use the controlled codes above.
        detail = "프로필 선택값을 확인해 주세요." if korean else "Check the selected profile values."
    raise HTTPException(status_code=422, detail=detail)


def _profile_storage_query(profile: dict[str, object]) -> str:
    """Create a bounded non-free-text audit summary for legacy query columns."""

    return json.dumps(
        {"controlled_profile": profile},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )[:1200]


def _existing_session_for_click(request: Request) -> str | None:
    header_session = request.headers.get(SESSION_HEADER)
    if header_session and SESSION_ID_PATTERN.fullmatch(header_session):
        return header_session
    cookie_session = request.cookies.get(SESSION_COOKIE)
    if cookie_session and SESSION_ID_PATTERN.fullmatch(cookie_session):
        return cookie_session
    return None


def _selection_payload(session_id: str) -> dict[str, object]:
    selections = store.selections_for_session(session_id)
    saved_products = _products_for_ids(selections["saved"])
    compare_products = _products_for_ids(selections["compare"])
    summaries = commerce.product_summaries(
        product.id for product in [*saved_products, *compare_products]
    )
    saved_prices = {
        product.id: summaries.get(product.id, {}).get("lowest_fresh_price_krw")
        for product in saved_products
    }
    total_cost_krw = sum(price for price in saved_prices.values() if price is not None)
    missing_price_ids = [product_id for product_id, price in saved_prices.items() if price is None]
    return {
        "schema_version": 2,
        "saved_ids": [product.id for product in saved_products],
        "compare_ids": [product.id for product in compare_products],
        "saved_products": [
            product_to_v2_dict(product, summaries.get(product.id))
            for product in _routine_sort(saved_products)
        ],
        "compare_products": [
            product_to_v2_dict(product, summaries.get(product.id))
            for product in compare_products
        ],
        "total_cost_krw": total_cost_krw,
        "missing_price_ids": missing_price_ids,
    }


def _products_for_ids(product_ids: list[str]):
    products = []
    for product_id in product_ids:
        product = agent.database.get(product_id)
        if product is not None:
            products.append(product)
    return products


def _routine_sort(products):
    order = {"cleanser": 0, "toner": 1, "serum": 2, "ampoule": 2, "essence": 2, "moisturizer": 3, "sunscreen": 4}
    return sorted(products, key=lambda product: (order.get(product.category, 20), product.name.lower()))
