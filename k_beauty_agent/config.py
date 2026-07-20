from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PRODUCTS_CSV = BASE_DIR / "data" / "products_verified.csv"
DEFAULT_REVIEWS_CSV = BASE_DIR / "data" / "review_summaries.csv"
DEFAULT_GENERATED_CATALOG_CSV = BASE_DIR / "data" / "catalog_generated.csv"
DEFAULT_CATALOG_MANIFEST = BASE_DIR / "data" / "catalog_manifest.json"
DEFAULT_JSON_DB = BASE_DIR / "data" / "sample_products.json"
DEFAULT_SQLITE_PATH = BASE_DIR / "data" / "k_beauty_agent.sqlite3"
DEFAULT_EXTERNAL_CACHE_PATH = BASE_DIR / "data" / "external_product_cache.sqlite3"


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
    return Path(value)


def admin_token() -> str:
    return _secret_env("ADMIN_TOKEN", "dev-admin-token")


def openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-5.4-mini")


def public_llm_enabled() -> bool:
    default = "false" if is_production() else "true"
    return os.getenv("PUBLIC_LLM_ENABLED", default).lower() in {"1", "true", "yes", "on"}


def follow_up_llm_enabled() -> bool:
    enabled = os.getenv("FOLLOW_UP_LLM_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    return enabled and bool(os.getenv("OPENAI_API_KEY"))


def product_reason_llm_enabled() -> bool:
    enabled = os.getenv("PRODUCT_REASON_LLM_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    return enabled and bool(os.getenv("OPENAI_API_KEY"))


def session_secret() -> str:
    return _secret_env("SESSION_SECRET", "dev-session-secret-change-me")


def is_production() -> bool:
    return os.getenv("RENDER") == "true" or os.getenv("ENVIRONMENT", "").lower() in {"prod", "production"}


def secure_cookies() -> bool:
    return os.getenv("SECURE_COOKIES", "true" if is_production() else "false").lower() in {"1", "true", "yes", "on"}


def cookie_samesite() -> str:
    value = os.getenv("COOKIE_SAMESITE", "none" if is_production() else "lax").lower()
    if value not in {"lax", "strict", "none"}:
        raise ValueError("COOKIE_SAMESITE must be one of: lax, strict, none")
    return value


def cors_allow_origins() -> list[str]:
    value = os.getenv(
        "CORS_ALLOW_ORIGINS",
        (
            "https://yeonwo00.github.io,"
            "https://201younghanlee.github.io,"
            "https://k-beauty-agent.apps.tossmini.com,"
            "https://k-beauty-agent.private-apps.tossmini.com"
        ),
    )
    return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]


def recommend_rate_limit_requests() -> int:
    return max(1, min(1_000, int(os.getenv("RECOMMEND_RATE_LIMIT_REQUESTS", "30"))))


def recommend_rate_limit_window_seconds() -> int:
    return max(1, min(3_600, int(os.getenv("RECOMMEND_RATE_LIMIT_WINDOW_SECONDS", "60"))))


def _secret_env(name: str, dev_default: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    if is_production():
        raise RuntimeError(f"{name} must be configured in production")
    return dev_default
