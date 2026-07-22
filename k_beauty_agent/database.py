from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from .knowledge_base import find_evidence_for_ingredient, ingredient_name_matches, normalize_token
from .models import Product


_REVIEW_EVIDENCE_HOSTS = {
    "glowpick.com",
    "www.glowpick.com",
    "glowpick.co.kr",
    "www.oliveyoung.co.kr",
    "oliveyoung.co.kr",
    "www.ulta.com",
    "ulta.com",
    "www.marksandspencer.com",
    "marksandspencer.com",
}


class ProductDatabase:
    def __init__(
        self,
        products: list[Product],
        *,
        catalog_updated_at: str | None = None,
        catalog_freshness: dict[str, object] | None = None,
    ):
        unique: dict[str, Product] = {}
        for product in products:
            unique.setdefault(product.id, product)
        self.products = list(unique.values())
        self.catalog_updated_at = catalog_updated_at
        self.catalog_freshness = dict(catalog_freshness or {})
        self._by_id = unique
        self._by_category: dict[str, list[Product]] = {}
        self._search_text: dict[str, str] = {}
        self._normalized_ingredients: dict[str, set[str]] = {}
        self._inferred_concerns: dict[str, set[str]] = {}
        for product in self.products:
            category = normalize_token(product.category)
            self._by_category.setdefault(category, []).append(product)
            self._search_text[product.id] = self._product_text(product)
            ingredients = {normalize_token(item) for item in product.ingredients}
            self._normalized_ingredients[product.id] = ingredients
            inferred = {normalize_token(item) for item in product.concerns}
            for ingredient in product.ingredients:
                evidence = find_evidence_for_ingredient(ingredient)
                if evidence:
                    inferred.update(normalize_token(item) for item in evidence.supports)
            self._inferred_concerns[product.id] = inferred

    @classmethod
    def from_json(cls, path: str | Path) -> "ProductDatabase":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Product DB must be a JSON array.")
        return cls([Product.from_mapping(item) for item in data])

    @classmethod
    def from_csv(
        cls,
        products_path: str | Path,
        reviews_path: str | Path | None = None,
        *,
        catalog_updated_at: str | None = None,
        catalog_freshness: dict[str, object] | None = None,
    ) -> "ProductDatabase":
        reviews = _load_review_summaries(reviews_path) if reviews_path else {}
        products: list[Product] = []
        with Path(products_path).open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                product_id = row.get("id", "")
                review_data = reviews.get(product_id, {})
                merged = {**row, **review_data}
                products.append(Product.from_mapping(_coerce_row(merged)))
        return cls(
            products,
            catalog_updated_at=catalog_updated_at,
            catalog_freshness=catalog_freshness,
        )

    @classmethod
    def combine(cls, *databases: "ProductDatabase") -> "ProductDatabase":
        products: list[Product] = []
        seen: set[str] = set()
        for database in databases:
            for product in database.products:
                if product.id in seen:
                    continue
                seen.add(product.id)
                products.append(product)
        catalog_updated_at = max(
            (database.catalog_updated_at for database in databases if database.catalog_updated_at),
            default=None,
        )
        catalog_freshness = next(
            (database.catalog_freshness for database in reversed(databases) if database.catalog_freshness),
            {},
        )
        return cls(
            products,
            catalog_updated_at=catalog_updated_at,
            catalog_freshness=catalog_freshness,
        )

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
        query_tokens = set(normalize_token(query).split())
        category_set = {normalize_token(item) for item in categories or []}
        concern_set = {normalize_token(item) for item in concerns or []}
        if "clogged pores" in concern_set:
            concern_set.add("pores")
        if "pores" in concern_set:
            concern_set.add("clogged pores")
        if "dullness" in concern_set:
            concern_set.add("hyperpigmentation")
        if "hyperpigmentation" in concern_set:
            concern_set.add("dullness")
        ingredient_set = {normalize_token(item) for item in ingredients or []}
        excluded_ingredient_set = {normalize_token(item) for item in exclude_ingredients or []}

        candidates = self._candidate_products(category_set)
        scored: list[tuple[float, int, Product]] = []
        for product in candidates:
            if product.recommendation_tier not in {"verified", "eligible"}:
                continue
            if require_complete_ingredients and product.ingredient_status != "complete":
                continue
            product_ingredients = self._normalized_ingredients[product.id]
            if excluded_ingredient_set and any(
                _ingredient_in_product(ingredient, product_ingredients) for ingredient in excluded_ingredient_set
            ):
                continue
            score = 0.0
            haystack = self._search_text[product.id]
            product_category = normalize_token(product.category)
            if category_set and "basic" not in category_set and product_category not in category_set:
                continue
            if query_tokens:
                score += sum(1.0 for token in query_tokens if token in haystack)
            if category_set:
                if "basic" in category_set and product_category in {
                    "cleanser",
                    "toner",
                    "serum",
                    "moisturizer",
                    "sunscreen",
                }:
                    # "Basic" means the user wants help choosing a routine
                    # step, not a literal catalog category.
                    score += 1.0
                elif product_category in category_set:
                    score += 4.0
            if concern_set:
                product_concerns = self._inferred_concerns[product.id]
                score += 2.0 * len(product_concerns & concern_set)
            if ingredient_set:
                score += 3.0 * sum(
                    1 for ingredient in ingredient_set if _ingredient_in_product(ingredient, product_ingredients)
                )

            if not any((query_tokens, category_set, concern_set, ingredient_set)):
                score = 1.0

            if score > 0:
                tier_rank = 0 if product.recommendation_tier == "verified" else 1
                scored.append((score, tier_rank, product))

        scored.sort(key=lambda item: (-item[0], item[1], item[2].brand.lower(), item[2].name.lower()))
        selected = scored if limit is None else scored[:limit]
        return [product for _, _, product in selected]

    def get(self, product_id: str) -> Product | None:
        return self._by_id.get(product_id)

    def catalog_page(
        self,
        *,
        query: str = "",
        category: str | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Product], int]:
        normalized_query = normalize_token(query)
        query_tokens = set(normalized_query.split())
        normalized_category = normalize_token(category or "")
        normalized_source = normalize_token(source or "")
        candidates = self._by_category.get(normalized_category, []) if normalized_category else self.products
        filtered: list[Product] = []
        for product in candidates:
            if normalized_source and normalize_token(product.catalog_source) != normalized_source:
                continue
            if query_tokens and not all(token in self._search_text[product.id] for token in query_tokens):
                continue
            filtered.append(product)
        return filtered[offset : offset + limit], len(filtered)

    def source_status(self) -> dict[str, object]:
        source_counts = Counter(product.catalog_source for product in self.products)
        tier_counts = Counter(product.recommendation_tier for product in self.products)
        ingredient_counts = Counter(product.ingredient_status for product in self.products)
        has_generated = any(key != "curated" for key in source_counts)
        fetched_at_values = [product.fetched_at for product in self.products if product.fetched_at]
        return {
            "product_source": "catalog_snapshot",
            "source_used": "generated_snapshot" if has_generated else "curated_csv",
            "total_products": len(self.products),
            "recommendation_eligible_products": sum(
                count for tier, count in tier_counts.items() if tier in {"verified", "eligible"}
            ),
            "source_counts": dict(sorted(source_counts.items())),
            "recommendation_tier_counts": dict(sorted(tier_counts.items())),
            "ingredient_status_counts": dict(sorted(ingredient_counts.items())),
            "catalog_updated_at": self.catalog_updated_at or max(fetched_at_values, default=None),
            "record_freshness": self.catalog_freshness,
            "products_with_checked_price": sum(product.price_krw is not None for product in self.products),
            "message": (
                "Using the checked-in multi-source catalog snapshot; prices and stock are not live."
                if has_generated
                else "Using the curated CSV product database."
            ),
        }

    def _candidate_products(self, categories: set[str]) -> list[Product]:
        concrete = [category for category in categories if category != "basic"]
        if not concrete:
            return self.products
        candidates: list[Product] = []
        seen: set[str] = set()
        for category in sorted(concrete):
            for product in self._by_category.get(category, []):
                if product.id in seen:
                    continue
                seen.add(product.id)
                candidates.append(product)
        return candidates

    @staticmethod
    def _product_text(product: Product) -> str:
        values = [
            product.name,
            product.brand,
            product.category,
            *product.ingredients,
            *product.claims,
            *product.suited_skin_types,
            *product.concerns,
        ]
        return normalize_token(" ".join(values))


def _coerce_row(row: dict[str, str]) -> dict[str, object]:
    list_fields = {
        "ingredients",
        "claims",
        "suited_skin_types",
        "concerns",
        "avoid_for",
        "reviews",
        "evidence_notes",
        "texture_tags",
    }
    numeric_fields = {"price_usd", "rating", "review_count", "oliveyoung_price_krw", "price_krw"}
    coerced: dict[str, object] = {}
    for key, value in row.items():
        if value is None:
            continue
        if isinstance(value, tuple):
            coerced[key] = value
            continue
        stripped = value.strip()
        if not stripped:
            continue
        if key in list_fields:
            coerced[key] = tuple(item.strip() for item in stripped.replace(";", "|").split("|") if item.strip())
        elif key in numeric_fields:
            coerced[key] = float(stripped) if key != "review_count" else int(float(stripped))
        else:
            coerced[key] = stripped
    return coerced


def _load_review_summaries(path: str | Path | None) -> dict[str, dict[str, object]]:
    if not path or not Path(path).exists():
        return {}
    summaries: dict[str, dict[str, object]] = {}
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            product_id = (row.get("product_id") or "").strip()
            if not product_id:
                continue
            reviews = [
                row.get("summary", ""),
                f"Common positives: {row.get('common_positives', '')}",
                f"Common cautions: {row.get('common_cautions', '')}",
            ]
            review_source_url = _review_evidence_url(row)
            summaries[product_id] = {
                "review_summary": row.get("summary", "").strip(),
                "review_summary_en": row.get("summary_en", "").strip(),
                "reviews": tuple(item.strip() for item in reviews if item.strip()),
                "positive_reviews": _split_review_field(row.get("positive_reviews", "")),
                "negative_reviews": _split_review_field(row.get("negative_reviews", "")),
                "positive_reviews_en": _split_review_field(row.get("positive_reviews_en", "")),
                "negative_reviews_en": _split_review_field(row.get("negative_reviews_en", "")),
                "review_source_url": review_source_url,
                "review_verified_at": (row.get("verified_at") or "").strip() if review_source_url else "",
            }
    return summaries


def _review_evidence_url(row: dict[str, str]) -> str:
    """Return only URLs that can substantiate customer-review metadata.

    The legacy ``source_url`` column also contains brand, ingredient, and
    regulatory pages. Those remain useful product references elsewhere but do
    not verify a rating, review count, or review-summary freshness.
    """

    explicit = (row.get("review_source_url") or "").strip()
    candidate = explicit or (row.get("source_url") or "").strip()
    if not candidate:
        return ""
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return ""
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    if explicit:
        return candidate
    return candidate if parsed.hostname.lower() in _REVIEW_EVIDENCE_HOSTS else ""


def _split_review_field(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.replace(";", "|").split("|") if item.strip())


def _ingredient_in_product(ingredient: str, product_ingredients: set[str]) -> bool:
    return any(ingredient_name_matches(ingredient, product_ingredient) for product_ingredient in product_ingredients)
