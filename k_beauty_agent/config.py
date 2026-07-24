from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PRODUCTS_CSV = BASE_DIR / "data" / "products_verified.csv"
DEFAULT_REVIEWS_CSV = BASE_DIR / "data" / "review_summaries.csv"
DEFAULT_GENERATED_CATALOG_CSV = BASE_DIR / "data" / "catalog_generated.csv"
DEFAULT_CATALOG_MANIFEST = BASE_DIR / "data" / "catalog_manifest.json"
DEFAULT_JSON_DB = BASE_DIR / "data" / "sample_products.json"
DEFAULT_SQLITE_PATH = BASE_DIR / "data" / "k_beauty_agent.sqlite3"
DEFAULT_EXTERNAL_CACHE_PATH = BASE_DIR / "data" / "external_product_cache.sqlite3"
PRODUCTION_SECRET_NAMES = (
    "ADMIN_TOKEN",
    "SESSION_SECRET",
    "AFFILIATE_REDIRECT_SECRET",
    "AFFILIATE_WEBHOOK_SECRET",
)


def database_url() -> str:
    return os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")


def product_source() -> str:
    return os.getenv("PRODUCT_SOURCE", "catalog_snapshot").lower()


def external_cache_path() -> Path:
    return sqlite_path_from_url(os.getenv("EXTERNAL_CACHE_URL", f"sqlite:///{DEFAULT_EXTERNAL_CACHE_PATH}"))


def sqlite_path_from_url(url: str | None = None) -> Path:
    value = url or database_url()
    if value.startswith("sqlite:///"):
        return Path(value.removeprefix("sqlite:///"))
    if value.startswith("sqlite://"):
        return Path(value.removeprefix("sqlite://"))
    if "://" in value:
        raise ValueError("Only SQLite DATABASE_URL values are supported by this build")
    return Path(value)


def admin_token() -> str:
    return _secret_env("ADMIN_TOKEN", "dev-admin-token")


def openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5.4-mini")


def public_llm_enabled() -> bool:
    default = "false" if is_production() else "true"
    return os.getenv("PUBLIC_LLM_ENABLED", default).lower() in {"1", "true", "yes", "on"}


def product_reason_llm_enabled() -> bool:
    enabled = os.getenv("PRODUCT_REASON_LLM_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    return enabled and bool(os.getenv("OPENAI_API_KEY"))


def youtube_api_key() -> str | None:
    value = os.getenv("YOUTUBE_API_KEY", "").strip()
    return value or None


def youtube_search_daily_limit() -> int:
    return max(1, min(100, int(os.getenv("YOUTUBE_SEARCH_DAILY_LIMIT", "90"))))


def youtube_review_cache_ttl_seconds() -> int:
    value = int(os.getenv("YOUTUBE_REVIEW_CACHE_TTL_SECONDS", "86400"))
    return max(300, min(24 * 60 * 60, value))


def session_secret() -> str:
    return _secret_env("SESSION_SECRET", "dev-session-secret-change-me")


def affiliate_redirect_secret() -> str:
    return _secret_env("AFFILIATE_REDIRECT_SECRET", "dev-affiliate-redirect-secret-change-me")


def affiliate_webhook_secret() -> str:
    """Optional secret for the normalized affiliate conversion callback."""

    value = os.getenv("AFFILIATE_WEBHOOK_SECRET", "")
    if value and is_production():
        _validate_production_secret("AFFILIATE_WEBHOOK_SECRET", value)
    return value


def validate_runtime_secrets() -> None:
    """Fail closed on weak, placeholder, or reused production secrets."""

    if not is_production():
        return
    values: dict[str, str] = {}
    for name in PRODUCTION_SECRET_NAMES:
        value = os.getenv(name, "")
        if name != "AFFILIATE_WEBHOOK_SECRET" and not value:
            raise RuntimeError(f"{name} must be configured in production")
        if value:
            _validate_production_secret(name, value)
            values[name] = value
    if len(values) != len(set(values.values())):
        raise RuntimeError("Production secrets must be distinct")


def active_affiliate_source_ids() -> set[str]:
    """Return only explicitly approved source IDs allowed to monetize offers."""

    values = {value.strip() for value in os.getenv("ACTIVE_AFFILIATE_SOURCE_IDS", "").split(",") if value.strip()}
    invalid = sorted(value for value in values if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", value))
    if invalid:
        raise ValueError("ACTIVE_AFFILIATE_SOURCE_IDS contains an invalid source ID")
    if {"coupang_partner_links", "coupang_partners"} <= values:
        raise ValueError(
            "Activate either coupang_partner_links or coupang_partners, not both"
        )
    return values


def is_production() -> bool:
    return os.getenv("RENDER") == "true" or os.getenv("ENVIRONMENT", "").lower() in {"prod", "production"}


def secure_cookies() -> bool:
    return os.getenv("SECURE_COOKIES", "true" if is_production() else "false").lower() in {"1", "true", "yes", "on"}


def cookie_samesite() -> str:
    value = os.getenv("COOKIE_SAMESITE", "lax").lower()
    if value not in {"lax", "strict", "none"}:
        raise ValueError("COOKIE_SAMESITE must be one of: lax, strict, none")
    return value


def cors_allow_origins() -> list[str]:
    value = os.getenv(
        "CORS_ALLOW_ORIGINS",
        (
            "https://k-beauty-agent.apps.tossmini.com,"
            "https://k-beauty-agent.private-apps.tossmini.com"
        ),
    )
    origins: list[str] = []
    for raw_origin in value.split(","):
        origin = raw_origin.strip().rstrip("/")
        if not origin:
            continue
        parsed = urlparse(origin)
        try:
            parsed_port = parsed.port
        except ValueError as exc:
            raise ValueError("CORS_ALLOW_ORIGINS contains an invalid port") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.params
            or parsed.query
            or parsed.fragment
            or "*" in origin
            or (parsed_port is not None and not 1 <= parsed_port <= 65535)
        ):
            raise ValueError("CORS_ALLOW_ORIGINS must contain exact HTTP(S) origins without paths or wildcards")
        if is_production() and parsed.scheme != "https":
            raise ValueError("Production CORS_ALLOW_ORIGINS must use HTTPS")
        origins.append(origin)
    return list(dict.fromkeys(origins))


def recommend_rate_limit_requests() -> int:
    return max(1, min(1_000, int(os.getenv("RECOMMEND_RATE_LIMIT_REQUESTS", "30"))))


def recommend_rate_limit_window_seconds() -> int:
    return max(1, min(3_600, int(os.getenv("RECOMMEND_RATE_LIMIT_WINDOW_SECONDS", "60"))))


def _secret_env(name: str, dev_default: str) -> str:
    value = os.getenv(name)
    if value:
        if is_production():
            _validate_production_secret(name, value)
        return value
    if is_production():
        raise RuntimeError(f"{name} must be configured in production")
    return dev_default


def _validate_production_secret(name: str, value: str) -> None:
    lowered = value.casefold()
    if len(value) < 32 or any(marker in lowered for marker in ("change-me", "changeme", "replace-me", "dev-")):
        raise RuntimeError(f"{name} must be a non-placeholder secret of at least 32 characters")
