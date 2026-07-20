from __future__ import annotations

import base64
import csv
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin

import httpx

from .database import ProductDatabase
from .knowledge_base import normalize_token
from .models import Product
from .skin import analyze_skin_query

CACHE_TTL_SECONDS = 24 * 60 * 60
BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OLIVEYOUNG_SNAPSHOT_CSV = BASE_DIR / "data" / "oliveyoung_snapshot.csv"
DEFAULT_OLIVEYOUNG_SNAPSHOT_HTML_DIR = BASE_DIR / "data" / "oliveyoung_snapshots"
DEFAULT_OLIVEYOUNG_STATIC_IMAGE_DIR = BASE_DIR / "static" / "oliveyoung_snapshots"
DEFAULT_OPEN_BEAUTY_FACTS_URL = "https://world.openbeautyfacts.org/cgi/search.pl"
DEFAULT_OPEN_BEAUTY_FACTS_PRODUCT_URL = "https://world.openbeautyfacts.org/product"
DEFAULT_COSING_API_URL = "https://ec.europa.eu/growth/tools-databases/cosing/api/ingredients"
OLIVEYOUNG_BASE_URL = "https://www.oliveyoung.co.kr"
KNOWN_K_BEAUTY_MARKERS = (
    "k-beauty",
    "k beauty",
    "korean skincare",
    "korean skin care",
    "cosrx",
    "anua",
    "round lab",
    "torriden",
    "skin1004",
    "beauty of joseon",
    "etude",
    "isntree",
    "haruharu",
    "numbuzin",
    "dr.g",
    "illiyoon",
    "aestura",
    "abib",
    "manyo",
    "ma:nyo",
    "mixsoon",
    "goodal",
    "axis-y",
    "banila",
    "mediheal",
    "needly",
    "tirtir",
    "i'm from",
)
CATEGORY_KEYWORDS = {
    "cleanser": "cleanser cleansing foam oil balm",
    "toner": "toner toner pad mist",
    "serum": "serum ampoule essence",
    "moisturizer": "moisturizer cream lotion emulsion",
    "sunscreen": "sunscreen SPF sun cream",
}


@dataclass(frozen=True)
class ExternalProduct:
    provider: str
    external_id: str
    title: str
    brand: str
    price: float | None
    currency: str | None
    image_url: str | None
    detail_url: str | None
    category_hint: str | None = None
    ingredients: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    raw: dict[str, Any] | None = None


class ProductProvider(Protocol):
    provider_name: str

    def search(self, query: str, *, limit: int, min_price_usd: float | None, max_price_usd: float | None) -> list[ExternalProduct]:
        ...


class IngredientProvider(Protocol):
    def ingredients_for(self, title: str, brand: str) -> list[str]:
        ...


class ExternalProductCache:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS external_product_cache (
                    provider TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    brand TEXT NOT NULL,
                    price REAL,
                    currency TEXT,
                    image_url TEXT,
                    detail_url TEXT,
                    category_hint TEXT,
                    features_json TEXT NOT NULL DEFAULT '[]',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    matched_curated_product_id TEXT,
                    ingredients_json TEXT NOT NULL DEFAULT '[]',
                    fetched_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    PRIMARY KEY (provider, external_id)
                )
                """
            )

    def fresh_products(self, provider: str | None = None, query_key: str | None = None) -> list[tuple[ExternalProduct, list[str], str | None]]:
        now = int(time.time())
        where = "expires_at > ?"
        params: list[Any] = [now]
        if provider:
            where += " AND provider = ?"
            params.append(provider)
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                f"""
                SELECT * FROM external_product_cache
                WHERE {where}
                ORDER BY fetched_at DESC
                LIMIT 80
                """,
                params,
            ).fetchall()
        products: list[tuple[ExternalProduct, list[str], str | None]] = []
        normalized_query = normalize_token(query_key or "")
        for row in rows:
            ingredients = list(json.loads(row["ingredients_json"] or "[]"))
            product = ExternalProduct(
                provider=row["provider"],
                external_id=row["external_id"],
                title=row["title"],
                brand=row["brand"],
                price=row["price"],
                currency=row["currency"],
                image_url=row["image_url"],
                detail_url=row["detail_url"],
                category_hint=row["category_hint"],
                features=tuple(json.loads(row["features_json"] or "[]")),
                ingredients=tuple(ingredients),
                raw=json.loads(row["raw_json"] or "{}"),
            )
            haystack = normalize_token(" ".join([product.title, product.brand, product.category_hint or "", *product.features]))
            if normalized_query and not any(token in haystack for token in normalized_query.split()):
                continue
            products.append((product, ingredients, row["matched_curated_product_id"]))
        return products

    def count_fresh(self, provider: str | None = None) -> int:
        now = int(time.time())
        with sqlite3.connect(self.path) as db:
            if provider:
                row = db.execute(
                    "SELECT COUNT(*) FROM external_product_cache WHERE provider = ? AND expires_at > ?",
                    (provider, now),
                ).fetchone()
            else:
                row = db.execute("SELECT COUNT(*) FROM external_product_cache WHERE expires_at > ?", (now,)).fetchone()
        return int(row[0] if row else 0)

    def save(self, product: ExternalProduct, *, ingredients: list[str], matched_curated_product_id: str | None) -> None:
        now = int(time.time())
        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                INSERT INTO external_product_cache (
                    provider, external_id, title, brand, price, currency, image_url, detail_url,
                    category_hint, features_json, raw_json, matched_curated_product_id,
                    ingredients_json, fetched_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, external_id) DO UPDATE SET
                    title = excluded.title,
                    brand = excluded.brand,
                    price = excluded.price,
                    currency = excluded.currency,
                    image_url = excluded.image_url,
                    detail_url = excluded.detail_url,
                    category_hint = excluded.category_hint,
                    features_json = excluded.features_json,
                    raw_json = excluded.raw_json,
                    matched_curated_product_id = excluded.matched_curated_product_id,
                    ingredients_json = excluded.ingredients_json,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                """,
                (
                    product.provider,
                    product.external_id,
                    product.title,
                    product.brand,
                    product.price,
                    product.currency,
                    product.image_url,
                    product.detail_url,
                    product.category_hint,
                    json.dumps(list(product.features)),
                    json.dumps(product.raw or {}),
                    matched_curated_product_id,
                    json.dumps(ingredients),
                    now,
                    now + CACHE_TTL_SECONDS,
                ),
            )


class OliveYoungSnapshotProvider:
    provider_name = "oliveyoung_snapshot"

    def __init__(self, *, csv_paths: list[Path] | None = None, html_dir: Path | None = None):
        env_csv = os.getenv("OLIVEYOUNG_SNAPSHOT_CSV")
        env_html_dir = os.getenv("OLIVEYOUNG_SNAPSHOT_HTML_DIR")
        self.csv_paths = csv_paths if csv_paths is not None else [Path(env_csv) if env_csv else DEFAULT_OLIVEYOUNG_SNAPSHOT_CSV]
        self.html_dir = html_dir if html_dir is not None else Path(env_html_dir) if env_html_dir else DEFAULT_OLIVEYOUNG_SNAPSHOT_HTML_DIR

    @property
    def configured(self) -> bool:
        return any(path.exists() for path in self.csv_paths) or self.html_dir.exists()

    def search(self, query: str, *, limit: int, min_price_usd: float | None, max_price_usd: float | None) -> list[ExternalProduct]:
        products = self._load_products()
        if not products:
            return []
        krw_per_usd = float(os.getenv("KRW_PER_USD", "1350"))
        min_price_krw = int(round(min_price_usd * krw_per_usd)) if min_price_usd is not None else None
        max_price_krw = int(round(max_price_usd * krw_per_usd)) if max_price_usd is not None else None
        desired_category = _infer_category(query)
        has_category_signal = desired_category != "serum" or any(token in normalize_token(query) for token in CATEGORY_KEYWORDS["serum"].split())
        query_tokens = _meaningful_query_tokens(query)
        filtered: list[ExternalProduct] = []
        for product in products:
            if min_price_krw is not None and (product.price is None or product.currency != "KRW" or product.price < min_price_krw):
                continue
            if max_price_krw is not None and (product.price is None or product.currency != "KRW" or product.price > max_price_krw):
                continue
            if has_category_signal and product.category_hint and product.category_hint != desired_category:
                continue
            if query_tokens and not _snapshot_matches_query(product, query_tokens, desired_category if has_category_signal else None):
                continue
            filtered.append(product)
            if len(filtered) >= limit:
                break
        return filtered

    def _load_products(self) -> list[ExternalProduct]:
        products: list[ExternalProduct] = []
        seen: set[str] = set()
        for path in self.csv_paths:
            for product in _oliveyoung_products_from_csv(path):
                if product.external_id in seen:
                    continue
                seen.add(product.external_id)
                products.append(product)
        for product in _oliveyoung_products_from_html_dir(self.html_dir):
            if product.external_id in seen:
                continue
            seen.add(product.external_id)
            products.append(product)
        return products


class OpenBeautyFactsProvider:
    provider_name = "open_beauty_facts"

    def __init__(self, *, endpoint: str | None = None):
        self.endpoint = endpoint or os.getenv("OPEN_BEAUTY_FACTS_API_URL", DEFAULT_OPEN_BEAUTY_FACTS_URL)

    @property
    def configured(self) -> bool:
        return True

    def search(self, query: str, *, limit: int, min_price_usd: float | None, max_price_usd: float | None) -> list[ExternalProduct]:
        products: list[ExternalProduct] = []
        seen: set[str] = set()
        try:
            with httpx.Client(timeout=8.0, headers={"User-Agent": "k-beauty-agent-live-api/0.1"}) as client:
                for search_terms in _open_beauty_queries(query):
                    params = {
                        "search_terms": search_terms,
                        "search_simple": 1,
                        "action": "process",
                        "json": 1,
                        "page_size": min(max(limit * 3, 10), 30),
                    }
                    response = client.get(self.endpoint, params=params)
                    response.raise_for_status()
                    for item in _extract_items(response.json()):
                        product = _open_beauty_product(item)
                        if product is None or product.external_id in seen:
                            continue
                        seen.add(product.external_id)
                        products.append(product)
                    if len(products) >= limit:
                        break
        except httpx.HTTPError:
            return products
        return products


class CosIngIngredientClient:
    provider_name = "cosing"

    def __init__(self, *, endpoint: str | None = None):
        self.endpoint = endpoint or os.getenv("COSING_API_URL", DEFAULT_COSING_API_URL)

    def ingredients_for(self, title: str, brand: str) -> list[str]:
        return []

    def ingredient_known(self, ingredient: str) -> bool:
        if os.getenv("COSING_API_URL") is None:
            return False
        try:
            with httpx.Client(timeout=6.0) as client:
                response = client.get(self.endpoint, params={"search": ingredient})
                response.raise_for_status()
        except httpx.HTTPError:
            return False
        return bool(_extract_items(response.json()))


class LiveProductDatabase:
    def __init__(
        self,
        fallback: ProductDatabase,
        *,
        cache_path: Path,
        providers: list[ProductProvider] | None = None,
        ingredient_provider: IngredientProvider | None = None,
        krw_per_usd: float | None = None,
    ):
        self.fallback = fallback
        self.cache = ExternalProductCache(cache_path)
        self.providers = providers or [OliveYoungSnapshotProvider(), OpenBeautyFactsProvider()]
        self.ingredient_provider = ingredient_provider or CosIngIngredientClient()
        self.krw_per_usd = krw_per_usd or float(os.getenv("KRW_PER_USD", "1350"))
        self._live_products: dict[str, Product] = {}
        self.last_source_status: dict[str, Any] = self.source_status()

    @property
    def products(self) -> list[Product]:
        merged = {product.id: product for product in self.fallback.products}
        merged.update(self._live_products)
        return list(merged.values())

    def get(self, product_id: str) -> Product | None:
        return self._live_products.get(product_id) or self.fallback.get(product_id)

    def source_status(self) -> dict[str, Any]:
        providers = [provider.provider_name for provider in self.providers]
        return {
            "product_source": "live_keyless",
            "source_priority": providers + ["external_cache", "curated_fallback"],
            "source_used": "not_queried",
            "oliveyoung_snapshot_configured": any(
                getattr(provider, "provider_name", "") == "oliveyoung_snapshot" and bool(getattr(provider, "configured", False))
                for provider in self.providers
            ),
            "open_beauty_facts_configured": True,
            "cosing_configured": True,
            "fresh_cache_count": self.cache.count_fresh(),
            "live_products_loaded": len(self._live_products),
            "message": "Keyless live providers have not been queried yet.",
        }

    def search(
        self,
        query: str = "",
        *,
        categories: list[str] | None = None,
        concerns: list[str] | None = None,
        ingredients: list[str] | None = None,
        exclude_ingredients: list[str] | None = None,
        require_complete_ingredients: bool = False,
        limit: int | None = 20,
    ) -> list[Product]:
        profile = analyze_skin_query(query)
        live_query = _live_query(query, categories or profile.desired_categories, ingredients or profile.preferred_ingredients)
        min_usd = profile.min_price_usd or _krw_to_usd(profile.min_price_krw, self.krw_per_usd)
        max_usd = profile.max_price_usd or _krw_to_usd(profile.max_price_krw, self.krw_per_usd)
        provider_products: list[tuple[str, ExternalProduct]] = []
        queried: list[str] = []
        provider_limit = limit if limit is not None else 100
        for provider in self.providers:
            queried.append(provider.provider_name)
            external = provider.search(live_query, limit=provider_limit, min_price_usd=min_usd, max_price_usd=max_usd)
            provider_products.extend((provider.provider_name, product) for product in external)
            if provider_products:
                break

        if not provider_products:
            cached = self.cache.fresh_products(query_key=live_query)
            if cached:
                provider_products = [(product.provider, product) for product, _, _ in cached]
                self.last_source_status = self.source_status() | {
                    "source_used": "external_cache",
                    "query": live_query,
                    "queried_sources": queried,
                    "message": "Keyless live providers returned no products; using fresh external cache.",
                }

        live_products: list[Product] = []
        used_source = provider_products[0][0] if provider_products else "curated_fallback"
        category_filter = {normalize_token(value) for value in (categories or profile.desired_categories or []) if value != "basic"}
        for _, external_product in provider_products:
            if not _is_k_beauty_relevant(external_product, self.fallback):
                continue
            product, ingredients_used, matched_id = self._normalize_external_product(external_product, profile)
            if not product:
                continue
            if category_filter and normalize_token(product.category) not in category_filter:
                continue
            self._live_products[product.id] = product
            self.cache.save(external_product, ingredients=ingredients_used, matched_curated_product_id=matched_id)
            live_products.append(product)

        if live_products:
            fallback_products = self.fallback.search(
                query,
                categories=categories,
                concerns=concerns,
                ingredients=ingredients,
                exclude_ingredients=exclude_ingredients,
                require_complete_ingredients=require_complete_ingredients,
                limit=limit,
            )
            seen_ids = {product.id for product in live_products}
            combined_products = live_products + [product for product in fallback_products if product.id not in seen_ids]
            self.last_source_status = self.source_status() | {
                "source_used": used_source,
                "query": live_query,
                "queried_sources": queried,
                "live_result_count": len(live_products),
                "curated_fallback_count": len(fallback_products),
                "message": f"Recommendation is using {used_source} live/cache products with curated fallback candidates.",
            }
            return combined_products if limit is None else combined_products[:limit]

        self.last_source_status = self.source_status() | {
            "source_used": "curated_fallback",
            "query": live_query,
            "queried_sources": queried,
            "live_result_count": 0,
            "message": "Keyless live providers returned no usable products; using curated CSV fallback.",
        }
        return self.fallback.search(
            query,
            categories=categories,
            concerns=concerns,
            ingredients=ingredients,
            exclude_ingredients=exclude_ingredients,
            require_complete_ingredients=require_complete_ingredients,
            limit=limit,
        )

    def _normalize_external_product(self, external_product: ExternalProduct, profile) -> tuple[Product | None, list[str], str | None]:
        matched = _best_curated_match(external_product, self.fallback.products)
        provider_ingredients = list(external_product.ingredients)
        enrichment_ingredients = self.ingredient_provider.ingredients_for(external_product.title, external_product.brand)
        ingredients = provider_ingredients or enrichment_ingredients or list(matched.ingredients if matched else ())
        if not ingredients and (profile.avoid_ingredients or profile.allergies):
            return None, [], matched.id if matched else None

        category = external_product.category_hint or (matched.category if matched else _infer_category(external_product.title))
        price_usd = external_product.price if external_product.currency in {None, "USD", "US$"} else None
        if external_product.currency == "KRW" and external_product.price is not None:
            price_krw = int(round(external_product.price))
        else:
            price_krw = int(round(price_usd * self.krw_per_usd)) if price_usd is not None else matched.oliveyoung_price_krw if matched else None
        source_type = external_product.provider
        is_oliveyoung_snapshot = source_type == "oliveyoung_snapshot"
        ingredients_from_verified_match = bool(matched and not provider_ingredients and not enrichment_ingredients)
        ingredient_status = "complete" if ingredients_from_verified_match else "reported" if ingredients else "missing"
        recommendation_tier = "verified" if ingredients_from_verified_match else "eligible" if ingredients else "discovery"
        raw_reviews = _review_fields_from_raw(external_product.raw or {})
        product_id = f"{source_type}-{_slug(external_product.external_id or external_product.title)}"
        return (
            Product(
                id=product_id,
                name=external_product.title,
                display_name_ko=matched.display_name_ko if matched and matched.display_name_ko else external_product.title,
                brand=external_product.brand or (matched.brand if matched else source_type),
                category=category,
                country="Korea" if is_oliveyoung_snapshot else "Unknown",
                ingredients=tuple(ingredients),
                claims=tuple(external_product.features) or (matched.claims if matched else ()),
                suited_skin_types=matched.suited_skin_types if matched else (),
                concerns=matched.concerns if matched else (),
                avoid_for=matched.avoid_for if matched else (),
                price_usd=price_usd,
                rating=matched.rating if matched else None,
                review_count=matched.review_count if matched else None,
                reviews=matched.reviews if matched else (),
                source_url=external_product.detail_url,
                ingredient_source_url=external_product.detail_url if provider_ingredients else matched.ingredient_source_url if matched else None,
                verified_at=_now_label(),
                review_summary=matched.review_summary if matched else None,
                review_summary_en=matched.review_summary_en if matched else None,
                positive_reviews=raw_reviews["positive_reviews"] or (matched.positive_reviews if matched else ()),
                negative_reviews=raw_reviews["negative_reviews"] or (matched.negative_reviews if matched else ()),
                positive_reviews_en=raw_reviews["positive_reviews_en"] or (matched.positive_reviews_en if matched else ()),
                negative_reviews_en=raw_reviews["negative_reviews_en"] or (matched.negative_reviews_en if matched else ()),
                review_source_url=raw_reviews["review_source_url"] or (matched.review_source_url if matched else None),
                image_url=external_product.image_url,
                image_verified_source=external_product.detail_url,
                image_source_type=source_type if external_product.image_url else "none",
                image_confidence=("verified" if is_oliveyoung_snapshot else "reported") if external_product.image_url else None,
                image_view_type="verified_product" if external_product.image_url else "none",
                oliveyoung_url=external_product.detail_url if is_oliveyoung_snapshot else None,
                oliveyoung_price_krw=price_krw,
                official_url=matched.official_url if matched else None,
                texture_tags=matched.texture_tags if matched else (),
                oliveyoung_verified_at=f"{'Olive Young snapshot' if is_oliveyoung_snapshot else source_type + ' live'} {_now_label()}" if price_krw else None,
                catalog_source=source_type,
                source_product_id=external_product.external_id,
                purchase_url=external_product.detail_url if is_oliveyoung_snapshot else None,
                retailer_name="Olive Young" if is_oliveyoung_snapshot else None,
                price_krw=price_krw,
                price_checked_at=_now_label() if price_krw is not None else None,
                source_updated_at=_now_label(),
                fetched_at=_now_label(),
                ingredient_status=ingredient_status,
                recommendation_tier=recommendation_tier,
                data_license=(
                    "ODbL-1.0 (database); CC-BY-SA-3.0 (product images)"
                    if source_type == "open_beauty_facts"
                    else None
                ),
                data_attribution_url=(
                    "https://world.openbeautyfacts.org/data"
                    if source_type == "open_beauty_facts"
                    else None
                ),
            ),
            ingredients,
            matched.id if matched else None,
        )


def _live_query(query: str, categories: list[str], ingredients: list[str]) -> str:
    parts = ["Korean skincare"]
    for category in categories:
        parts.append(CATEGORY_KEYWORDS.get(category, category))
    parts.extend(ingredients)
    if query and query.isascii():
        parts.append(query)
    return " ".join(parts)


def _open_beauty_queries(query: str) -> list[str]:
    normalized = normalize_token(query)
    queries: list[str] = []
    for marker in KNOWN_K_BEAUTY_MARKERS:
        if marker in normalized and marker not in queries:
            queries.append(marker)
    for category, keywords in CATEGORY_KEYWORDS.items():
        if category in normalized or any(token in normalized for token in keywords.split()):
            for marker in ("korean skincare", "k-beauty", *KNOWN_K_BEAUTY_MARKERS[4:]):
                candidate = f"{marker} {category}".strip()
                if candidate not in queries:
                    queries.append(candidate)
            break
    for fallback in ("korean skincare", "k-beauty", query):
        if fallback and fallback not in queries:
            queries.append(fallback)
    return queries[:12]


def _open_beauty_product(item: dict[str, Any]) -> ExternalProduct | None:
    title = item.get("product_name") or item.get("generic_name") or item.get("abbreviated_product_name")
    if not title:
        return None
    brand = str(item.get("brands") or item.get("brand_owner") or _brand_from_title(title)).split(",")[0].strip()
    code = str(item.get("code") or item.get("id") or _cache_key(title, brand))
    ingredients = _parse_ingredients(item.get("ingredients_text") or item.get("ingredients_text_en") or "")
    image_url = item.get("image_front_url") or item.get("image_url")
    detail_url = f"{DEFAULT_OPEN_BEAUTY_FACTS_PRODUCT_URL}/{code}"
    features = tuple(value for value in [item.get("categories"), item.get("labels"), item.get("quantity")] if value)
    return ExternalProduct(
        provider="open_beauty_facts",
        external_id=code,
        title=str(title),
        brand=brand,
        price=None,
        currency=None,
        image_url=str(image_url) if image_url else None,
        detail_url=detail_url,
        category_hint=_infer_category(str(title) + " " + " ".join(features)),
        ingredients=tuple(ingredients),
        features=tuple(str(value) for value in features),
        raw=item,
    )


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    candidates = (payload.get("products"), payload.get("items"), payload.get("results"))
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _parse_ingredients(text: str) -> list[str]:
    if not text:
        return []
    return [value.strip(" .") for value in text.replace(";", ",").split(",") if value.strip(" .")]


def _oliveyoung_products_from_csv(path: Path) -> list[ExternalProduct]:
    if not path.exists():
        return []
    products: list[ExternalProduct] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            product = _oliveyoung_product_from_row(row)
            if product:
                products.append(product)
    return products


def _oliveyoung_product_from_row(row: dict[str, str]) -> ExternalProduct | None:
    title = _first_value(row, "product_name", "name", "title", "goods_name", "goodsNm")
    if not title:
        return None
    brand = _first_value(row, "brand", "brand_name", "brandNm") or _brand_from_title(title)
    detail_url = _absolute_oliveyoung_url(_first_value(row, "oliveyoung_url", "url", "detail_url", "link"))
    price_krw = _parse_price(_first_value(row, "price_krw", "oliveyoung_price_krw", "sale_price", "price"))
    image_url = _absolute_oliveyoung_url(_first_value(row, "image_url", "img_url", "image", "imgPath"))
    category = _first_value(row, "category", "category_hint", "dispCatNm") or _infer_category(title)
    ingredients = _parse_ingredients(_first_value(row, "ingredients", "ingredient_text", "all_ingredients") or "")
    features = tuple(value for value in (_first_value(row, "claims", "features", "tags") or "").replace(";", "|").split("|") if value.strip())
    external_id = _first_value(row, "id", "external_id", "goods_no", "goodsNo") or _cache_key(title, brand)
    return ExternalProduct(
        provider="oliveyoung_snapshot",
        external_id=str(external_id),
        title=title,
        brand=brand,
        price=float(price_krw) if price_krw is not None else None,
        currency="KRW" if price_krw is not None else None,
        image_url=image_url,
        detail_url=detail_url,
        category_hint=category,
        ingredients=tuple(ingredients),
        features=features,
        raw={key: value for key, value in row.items() if value},
    )


def _review_fields_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "positive_reviews": _tuple_from_raw(raw.get("positive_reviews") or raw.get("good_reviews") or raw.get("pros_reviews")),
        "negative_reviews": _tuple_from_raw(raw.get("negative_reviews") or raw.get("bad_reviews") or raw.get("cons_reviews")),
        "positive_reviews_en": _tuple_from_raw(raw.get("positive_reviews_en") or raw.get("good_reviews_en") or raw.get("pros_reviews_en")),
        "negative_reviews_en": _tuple_from_raw(raw.get("negative_reviews_en") or raw.get("bad_reviews_en") or raw.get("cons_reviews_en")),
        "review_source_url": str(raw.get("review_source_url") or raw.get("reviews_url") or "").strip() or None,
    }


def _tuple_from_raw(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return tuple(item.strip() for item in str(value).replace(";", "|").split("|") if item.strip())


def _oliveyoung_products_from_html_dir(path: Path) -> list[ExternalProduct]:
    if not path.exists() or not path.is_dir():
        return []
    products: list[ExternalProduct] = []
    for html_path in sorted([*path.glob("*.html"), *path.glob("*.htm")]):
        products.extend(_oliveyoung_products_from_html(html_path))
    return products


def _oliveyoung_products_from_html(path: Path) -> list[ExternalProduct]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if _is_oliveyoung_wait_page(text):
        return []
    products = _oliveyoung_dom_products(text, path)
    products.extend(_oliveyoung_jsonld_products(text))
    products.extend(_oliveyoung_script_products(text))
    if not products:
        fallback = _oliveyoung_meta_product(text, path)
        if fallback:
            products.append(fallback)
    unique: dict[str, ExternalProduct] = {}
    for product in products:
        unique.setdefault(product.external_id, product)
    return list(unique.values())


def _oliveyoung_dom_products(text: str, path: Path) -> list[ExternalProduct]:
    partials: dict[str, dict[str, Any]] = {}
    for match in re.finditer(r"<a\b[^>]*data-ref-goodsno=[\"'][^\"']+[\"'][\s\S]*?</a>", text, re.IGNORECASE):
        block = match.group(0)
        goods_no = _extract_html_attr(block, "data-ref-goodsno")
        if not goods_no:
            continue
        current = partials.setdefault(goods_no, {"external_id": goods_no})
        href = _extract_html_attr(block, "href")
        disp_cat = _extract_html_attr(block, "data-ref-dispcatno")
        current["detail_url"] = current.get("detail_url") or _oliveyoung_detail_url(goods_no, href, disp_cat)
        current["brand"] = current.get("brand") or _extract_tag_text(block, "tx_brand")
        current["title"] = current.get("title") or _product_title_from_block(block)
        current["price"] = current.get("price") or _price_from_html_block(block)
        current["image_url"] = current.get("image_url") or _image_from_html_block(block, path)
    products: list[ExternalProduct] = []
    for goods_no, data in partials.items():
        title = str(data.get("title") or "").strip()
        if not title or title == "올리브영 온라인몰":
            continue
        brand = str(data.get("brand") or _brand_from_snapshot_title(title)).strip()
        products.append(
            ExternalProduct(
                provider="oliveyoung_snapshot",
                external_id=goods_no,
                title=html.unescape(title),
                brand=html.unescape(brand),
                price=float(data["price"]) if data.get("price") is not None else None,
                currency="KRW" if data.get("price") is not None else None,
                image_url=data.get("image_url"),
                detail_url=data.get("detail_url"),
                category_hint=_infer_category(title),
                features=("Olive Young saved HTML snapshot",),
                raw={"source": "saved_html_dom"},
            )
        )
    return products


def _is_oliveyoung_wait_page(text: str) -> bool:
    normalized = normalize_token(_strip_tags(text))
    return "잠시만 기다려 주세요" in text or "oliveyoung" in normalized and "wait" in normalized and "product" not in normalized


def _oliveyoung_jsonld_products(text: str) -> list[ExternalProduct]:
    products: list[ExternalProduct] = []
    for match in re.finditer(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", text, re.IGNORECASE | re.DOTALL):
        raw = html.unescape(match.group(1)).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in _jsonld_product_items(payload):
            title = str(item.get("name") or "").strip()
            if not title:
                continue
            brand_value = item.get("brand")
            brand = brand_value.get("name") if isinstance(brand_value, dict) else str(brand_value or _brand_from_title(title))
            offers = item.get("offers") if isinstance(item.get("offers"), dict) else {}
            image = item.get("image")
            if isinstance(image, list):
                image = image[0] if image else None
            detail_url = _absolute_oliveyoung_url(str(item.get("url") or offers.get("url") or ""))
            products.append(
                ExternalProduct(
                    provider="oliveyoung_snapshot",
                    external_id=_cache_key(title, str(brand)),
                    title=title,
                    brand=str(brand),
                    price=float(_parse_price(str(offers.get("price") or "")) or 0) or None,
                    currency="KRW",
                    image_url=_absolute_oliveyoung_url(str(image or "")),
                    detail_url=detail_url,
                    category_hint=_infer_category(title),
                    raw=item,
                )
            )
    return products


def _jsonld_product_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for value in payload for item in _jsonld_product_items(value)]
    if not isinstance(payload, dict):
        return []
    item_type = payload.get("@type")
    if item_type == "Product" or (isinstance(item_type, list) and "Product" in item_type):
        return [payload]
    items: list[dict[str, Any]] = []
    for value in payload.values():
        if isinstance(value, (dict, list)):
            items.extend(_jsonld_product_items(value))
    return items


def _oliveyoung_script_products(text: str) -> list[ExternalProduct]:
    products: list[ExternalProduct] = []
    for match in re.finditer(r"goodsNo['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_-]+)", text):
        start = max(0, match.start() - 2000)
        end = min(len(text), match.end() + 3000)
        block = text[start:end]
        title = _extract_js_value(block, "goodsNm", "goodsName", "productName", "prdNm")
        if not title:
            continue
        brand = _extract_js_value(block, "brandNm", "brandName") or _brand_from_title(title)
        price = _parse_price(_extract_js_value(block, "salePrc", "finalPrc", "price", "goodsPrice") or "")
        detail_url = _absolute_oliveyoung_url(_extract_js_value(block, "goodsUrl", "detailUrl", "linkUrl") or f"/store/goods/getGoodsDetail.do?goodsNo={match.group(1)}")
        image_url = _absolute_oliveyoung_url(_extract_js_value(block, "imgPath", "imageUrl", "imgUrl", "mainImg") or "")
        products.append(
            ExternalProduct(
                provider="oliveyoung_snapshot",
                external_id=match.group(1),
                title=html.unescape(title),
                brand=html.unescape(brand),
                price=float(price) if price is not None else None,
                currency="KRW" if price is not None else None,
                image_url=image_url,
                detail_url=detail_url,
                category_hint=_infer_category(title),
                raw={"source": "saved_html"},
            )
        )
    return products


def _oliveyoung_meta_product(text: str, path: Path | None = None) -> ExternalProduct | None:
    title = _meta_content(text, "og:title") or _title_content(text)
    if not title:
        return None
    title = re.sub(r"\s*[-|]\s*올리브영.*$", "", html.unescape(title)).strip()
    if not title:
        return None
    image_url = _snapshot_image_url(_meta_content(text, "og:image") or "", path)
    detail_url = _absolute_oliveyoung_url(_meta_content(text, "og:url") or _canonical_href(text) or "")
    price = _parse_price(_meta_content(text, "product:price:amount") or "")
    brand = _meta_content(text, "product:brand") or _brand_from_title(title)
    return ExternalProduct(
        provider="oliveyoung_snapshot",
        external_id=_cache_key(title, brand),
        title=title,
        brand=brand,
        price=float(price) if price is not None else None,
        currency="KRW" if price is not None else None,
        image_url=image_url,
        detail_url=detail_url,
        category_hint=_infer_category(title),
        raw={"source": "saved_html_meta"},
    )


def _first_value(row: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _parse_price(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else None


def _absolute_oliveyoung_url(value: str | None) -> str | None:
    if not value:
        return None
    url = html.unescape(str(value).strip())
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(OLIVEYOUNG_BASE_URL, url)


def _snapshot_image_url(value: str | None, html_path: Path | None) -> str | None:
    if not value:
        return None
    url = html.unescape(str(value).strip())
    if not url:
        return None
    if url.startswith(("http://", "https://", "//")):
        return _absolute_oliveyoung_url(url)
    if html_path is None:
        return _absolute_oliveyoung_url(url)
    relative = url.replace("./", "", 1)
    source = (html_path.parent / relative).resolve()
    if not source.exists():
        source = (BASE_DIR / "data" / relative).resolve()
    if not source.exists() or not source.is_file():
        return None
    DEFAULT_OLIVEYOUNG_STATIC_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = DEFAULT_OLIVEYOUNG_STATIC_IMAGE_DIR / source.name
    if not target.exists():
        shutil.copy2(source, target)
    return f"/static/oliveyoung_snapshots/{target.name}"


def _extract_html_attr(block: str, attr: str) -> str | None:
    match = re.search(rf"{re.escape(attr)}=[\"']([^\"']+)[\"']", block, re.IGNORECASE)
    return html.unescape(match.group(1).strip()) if match else None


def _extract_tag_text(block: str, class_name: str) -> str | None:
    match = re.search(rf"<[^>]+class=[\"'][^\"']*{re.escape(class_name)}[^\"']*[\"'][^>]*>(.*?)</[^>]+>", block, re.IGNORECASE | re.DOTALL)
    return _strip_tags(match.group(1)).strip() if match else None


def _product_title_from_block(block: str) -> str | None:
    title = _extract_tag_text(block, "tx_name")
    if title:
        return title
    image_alt = _extract_html_attr(block, "alt")
    if image_alt:
        return image_alt
    data_attr = _extract_html_attr(block, "data-attr")
    if data_attr:
        parts = [part.strip() for part in data_attr.split("^") if part.strip()]
        for part in reversed(parts):
            if not part.isdigit() and not part.startswith("홈"):
                return part
    return None


def _price_from_html_block(block: str) -> int | None:
    patterns = (
        r'class=["\']tx_cur["\'][\s\S]*?<span[^>]*class=["\']tx_num["\'][^>]*>([^<]+)</span>',
        r'<strong>[\s\S]*?<span[^>]*>([0-9,]+)</span>[\s\S]*?<span[^>]*class=["\']won["\']',
        r'class=["\']price["\'][\s\S]*?<strong>[\s\S]*?<span[^>]*>([0-9,]+)</span>',
    )
    for pattern in patterns:
        match = re.search(pattern, block, re.IGNORECASE)
        if match:
            price = _parse_price(match.group(1))
            if price:
                return price
    price_block = re.search(r'class=["\'][^"\']*price[^"\']*["\'][^>]*>([\s\S]{0,500})</(?:p|dd|div)>', block, re.IGNORECASE)
    if not price_block:
        return None
    numbers = [_parse_price(value) for value in re.findall(r'([0-9][0-9,]{2,})', price_block.group(1))]
    numbers = [value for value in numbers if value]
    return numbers[-1] if numbers else None


def _image_from_html_block(block: str, path: Path) -> str | None:
    image_match = re.search(r"<img\b[^>]*>", block, re.IGNORECASE)
    if not image_match:
        return None
    src = _extract_html_attr(image_match.group(0), "src") or _extract_html_attr(image_match.group(0), "data-src")
    return _snapshot_image_url(src, path)


def _oliveyoung_detail_url(goods_no: str, href: str | None, disp_cat_no: str | None) -> str:
    if href and not href.startswith("javascript"):
        return _absolute_oliveyoung_url(href) or f"{OLIVEYOUNG_BASE_URL}/store/goods/getGoodsDetail.do?goodsNo={goods_no}"
    suffix = f"&dispCatNo={disp_cat_no}" if disp_cat_no else ""
    return f"{OLIVEYOUNG_BASE_URL}/store/goods/getGoodsDetail.do?goodsNo={goods_no}{suffix}"


def _extract_js_value(block: str, *keys: str) -> str | None:
    for key in keys:
        patterns = (
            rf"{re.escape(key)}['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
            rf"['\"]{re.escape(key)}['\"]\s*:\s*['\"]([^'\"]+)['\"]",
            rf"{re.escape(key)}['\"]?\s*[:=]\s*([0-9,]+)",
        )
        for pattern in patterns:
            match = re.search(pattern, block)
            if match:
                return match.group(1).strip()
    return None


def _meta_content(text: str, prop: str) -> str | None:
    patterns = (
        rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(prop)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return html.unescape(match.group(1).strip())
    return None


def _title_content(text: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    return _strip_tags(match.group(1)).strip() if match else None


def _canonical_href(text: str) -> str | None:
    match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', text, re.IGNORECASE)
    return html.unescape(match.group(1).strip()) if match else None


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", html.unescape(text or ""))


def _meaningful_query_tokens(query: str) -> set[str]:
    generic = {"korean", "skincare", "skin", "care", "beauty", "k", "spf", "추천", "제품"}
    return {token for token in normalize_token(query).split() if len(token) > 1 and token not in generic}


def _snapshot_matches_query(product: ExternalProduct, query_tokens: set[str], desired_category: str | None) -> bool:
    haystack = normalize_token(" ".join([product.title, product.brand, product.category_hint or "", *product.features]))
    if desired_category and product.category_hint == desired_category:
        return True
    return any(token in haystack for token in query_tokens)


def _best_curated_match(external_product: ExternalProduct, products: list[Product]) -> Product | None:
    target = normalize_token(f"{external_product.brand} {external_product.title}")
    best_score = 0.0
    best_product: Product | None = None
    for product in products:
        source = normalize_token(f"{product.brand} {product.name} {product.display_name_ko or ''}")
        target_tokens = set(target.split())
        source_tokens = set(source.split())
        overlap = len(target_tokens & source_tokens) / max(1, min(len(source_tokens), len(target_tokens)))
        brand_bonus = 0.25 if normalize_token(product.brand) in target else 0.0
        score = overlap + brand_bonus
        if score > best_score:
            best_score = score
            best_product = product
    return best_product if best_score >= 0.38 else None


def _is_k_beauty_relevant(product: ExternalProduct, fallback: ProductDatabase) -> bool:
    if product.provider == "oliveyoung_snapshot":
        return True
    haystack = normalize_token(" ".join([product.title, product.brand, product.category_hint or "", *product.features]))
    if any(marker in haystack for marker in KNOWN_K_BEAUTY_MARKERS):
        return True
    curated_brands = {normalize_token(item.brand) for item in fallback.products}
    return any(brand and brand in haystack for brand in curated_brands)


def _infer_category(title: str) -> str:
    normalized = normalize_token(title)
    korean = title.lower()
    if any(
        token in korean
        for token in (
            "헤어",
            "샴푸",
            "트리트먼트",
            "아이섀도우",
            "팔레트",
            "파우더",
            "블러셔",
            "마스카라",
            "립",
            "향수",
            "치약",
            "칫솔",
            "구강",
            "생리대",
            "라이너",
            "속옷",
            "여성청결",
            "바디워시",
            "바디로션",
            "핸드크림",
        )
    ):
        return "unknown"
    if any(token in korean for token in ("선크림", "선세럼", "선스틱", "톤업 선", "자외선")):
        return "sunscreen"
    if any(token in korean for token in ("토너패드", "토너 패드", "토너", "패드")):
        return "toner"
    if any(token in korean for token in ("클렌징", "클렌저", "폼", "세안")):
        return "cleanser"
    if any(token in korean for token in ("수분크림", "수딩크림", "장벽크림", "크림", "로션")):
        return "moisturizer"
    if any(token in korean for token in ("세럼", "앰플", "에센스", "부스터")):
        return "serum"
    if any(token in normalized for token in ("sunscreen", "spf", "sun cream", "sun stick")):
        return "sunscreen"
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(token in normalized for token in keywords.split()):
            return category
    if re.search(r"[가-힣]", title):
        return "unknown"
    return "serum"


def _krw_to_usd(value: int | None, krw_per_usd: float) -> float | None:
    return round(value / krw_per_usd, 2) if value is not None else None


def _slug(value: str) -> str:
    normalized = normalize_token(value).replace(" ", "-")
    return "".join(ch for ch in normalized if ch.isalnum() or ch == "-")[:80] or _cache_key(value, "")


def _cache_key(title: str, brand: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha1(f"{brand}:{title}".encode()).digest())[:16].decode()


def _brand_from_title(title: str) -> str:
    return title.split()[0] if title.split() else "External"


def _brand_from_snapshot_title(title: str) -> str:
    value = re.sub(r"^\[[^\]]+\]\s*", "", title).strip()
    value = re.sub(r"^\([^)]*\)\s*", "", value).strip()
    return value.split()[0] if value.split() else _brand_from_title(title)


def _now_label() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
