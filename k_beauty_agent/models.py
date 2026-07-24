from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EvidenceLevel = Literal["high", "moderate", "low", "insufficient"]
Decision = Literal["recommend", "fallback", "ask_more", "do_not_recommend"]


@dataclass(frozen=True)
class IngredientEvidence:
    name: str
    aliases: tuple[str, ...]
    supports: tuple[str, ...]
    suitable_for: tuple[str, ...]
    cautions: tuple[str, ...]
    evidence_level: EvidenceLevel
    rationale: str


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    brand: str
    category: str
    country: str
    ingredients: tuple[str, ...]
    display_name_ko: str | None = None
    claims: tuple[str, ...] = ()
    suited_skin_types: tuple[str, ...] = ()
    concerns: tuple[str, ...] = ()
    avoid_for: tuple[str, ...] = ()
    price_usd: float | None = None
    rating: float | None = None
    review_count: int | None = None
    reviews: tuple[str, ...] = ()
    evidence_notes: tuple[str, ...] = ()
    source_url: str | None = None
    ingredient_source_url: str | None = None
    verified_at: str | None = None
    review_summary: str | None = None
    review_summary_en: str | None = None
    positive_reviews: tuple[str, ...] = ()
    negative_reviews: tuple[str, ...] = ()
    positive_reviews_en: tuple[str, ...] = ()
    negative_reviews_en: tuple[str, ...] = ()
    review_source_url: str | None = None
    review_verified_at: str | None = None
    image_url: str | None = None
    image_verified_source: str | None = None
    image_source_type: str = "none"
    image_confidence: str | None = None
    image_view_type: str = "none"
    oliveyoung_url: str | None = None
    oliveyoung_price_krw: int | None = None
    official_url: str | None = None
    texture_tags: tuple[str, ...] = ()
    oliveyoung_verified_at: str | None = None
    catalog_source: str = "curated"
    source_product_id: str | None = None
    purchase_url: str | None = None
    retailer_name: str | None = None
    price_krw: int | None = None
    price_checked_at: str | None = None
    source_updated_at: str | None = None
    fetched_at: str | None = None
    ingredient_status: str = "complete"
    recommendation_tier: str = "verified"
    data_license: str | None = None
    data_attribution_url: str | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "Product":
        def tup(key: str) -> tuple[str, ...]:
            value = data.get(key, ())
            if value is None:
                return ()
            if isinstance(value, str):
                return tuple(item.strip() for item in value.replace(";", "|").split("|") if item.strip())
            return tuple(str(item).strip() for item in value if str(item).strip())

        catalog_source = str(data.get("catalog_source") or "curated")
        ingredients = tup("ingredients")

        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            display_name_ko=str(data["display_name_ko"]) if data.get("display_name_ko") else None,
            brand=str(data.get("brand", "Unknown")),
            category=str(data.get("category", "unknown")),
            country=str(data.get("country", "Korea")),
            ingredients=ingredients,
            claims=tup("claims"),
            suited_skin_types=tup("suited_skin_types"),
            concerns=tup("concerns"),
            avoid_for=tup("avoid_for"),
            price_usd=float(data["price_usd"]) if data.get("price_usd") is not None else None,
            rating=float(data["rating"]) if data.get("rating") is not None else None,
            review_count=int(data["review_count"]) if data.get("review_count") is not None else None,
            reviews=tup("reviews"),
            evidence_notes=tup("evidence_notes"),
            source_url=str(data["source_url"]) if data.get("source_url") else None,
            ingredient_source_url=str(data["ingredient_source_url"]) if data.get("ingredient_source_url") else None,
            verified_at=str(data["verified_at"]) if data.get("verified_at") else None,
            review_summary=str(data["review_summary"]) if data.get("review_summary") else None,
            review_summary_en=str(data["review_summary_en"]) if data.get("review_summary_en") else None,
            positive_reviews=tup("positive_reviews"),
            negative_reviews=tup("negative_reviews"),
            positive_reviews_en=tup("positive_reviews_en"),
            negative_reviews_en=tup("negative_reviews_en"),
            review_source_url=str(data["review_source_url"]) if data.get("review_source_url") else None,
            review_verified_at=str(data["review_verified_at"]) if data.get("review_verified_at") else None,
            image_url=str(data["image_url"]) if data.get("image_url") else None,
            image_verified_source=str(data["image_verified_source"]) if data.get("image_verified_source") else None,
            image_source_type=str(data["image_source_type"]) if data.get("image_source_type") else "none",
            image_confidence=str(data["image_confidence"]) if data.get("image_confidence") else None,
            image_view_type=str(data["image_view_type"]) if data.get("image_view_type") else "none",
            oliveyoung_url=str(data["oliveyoung_url"]) if data.get("oliveyoung_url") else None,
            oliveyoung_price_krw=int(float(data["oliveyoung_price_krw"])) if data.get("oliveyoung_price_krw") is not None else None,
            official_url=(
                str(data["official_url"])
                if data.get("official_url")
                else str(data["source_url"])
                if data.get("source_url") and str(data.get("catalog_source") or "curated") == "curated"
                else None
            ),
            texture_tags=tup("texture_tags"),
            oliveyoung_verified_at=str(data["oliveyoung_verified_at"]) if data.get("oliveyoung_verified_at") else None,
            catalog_source=catalog_source,
            source_product_id=str(data["source_product_id"]) if data.get("source_product_id") else None,
            purchase_url=(
                str(data["purchase_url"])
                if data.get("purchase_url")
                else str(data["oliveyoung_url"])
                if data.get("oliveyoung_url")
                else None
            ),
            retailer_name=(
                str(data["retailer_name"])
                if data.get("retailer_name")
                else "Olive Young"
                if data.get("oliveyoung_url")
                else None
            ),
            price_krw=(
                int(float(data["price_krw"]))
                if data.get("price_krw") is not None
                else int(float(data["oliveyoung_price_krw"]))
                if data.get("oliveyoung_price_krw") is not None
                else None
            ),
            price_checked_at=str(data["price_checked_at"]) if data.get("price_checked_at") else None,
            source_updated_at=str(data["source_updated_at"]) if data.get("source_updated_at") else None,
            fetched_at=str(data["fetched_at"]) if data.get("fetched_at") else None,
            ingredient_status=str(
                data.get("ingredient_status")
                or ("complete" if catalog_source == "curated" and ingredients else "missing")
            ),
            recommendation_tier=str(
                data.get("recommendation_tier") or ("verified" if catalog_source == "curated" else "discovery")
            ),
            data_license=str(data["data_license"]) if data.get("data_license") else None,
            data_attribution_url=str(data["data_attribution_url"]) if data.get("data_attribution_url") else None,
        )


@dataclass
class SkinProfile:
    skin_type: str | None = None
    sensitivity_level: str | None = None
    primary_concern: str | None = None
    concerns: list[str] = field(default_factory=list)
    desired_categories: list[str] = field(default_factory=list)
    preferred_ingredients: list[str] = field(default_factory=list)
    sensitivities: list[str] = field(default_factory=list)
    allergies: list[str] = field(default_factory=list)
    avoid_ingredients: list[str] = field(default_factory=list)
    max_price_usd: float | None = None
    max_price_krw: int | None = None
    min_price_usd: float | None = None
    min_price_krw: int | None = None
    texture_preference: str | None = None
    finish_preference: str | None = None
    location_or_climate: str | None = None
    pregnant_or_nursing: bool | None = None
    uncertainty: list[str] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)

    @property
    def has_minimum_signal(self) -> bool:
        return bool(
            self.skin_type
            or self.primary_concern
            or self.concerns
            or self.desired_categories
            or self.max_price_usd is not None
            or self.max_price_krw is not None
            or self.min_price_usd is not None
            or self.min_price_krw is not None
        )


@dataclass
class ProductScore:
    product: Product
    score: float
    score_components: dict[str, float] = field(
        default_factory=lambda: {
            "ingredient_evidence": 0.0,
            "skin_fit": 0.0,
            "category_match": 0.0,
            "review_confidence": 0.0,
            "personalization": 0.0,
            "penalties": 0.0,
        }
    )
    reasons: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    matched_ingredients: list[str] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    similar_products: list[Product] = field(default_factory=list)


@dataclass
class Recommendation:
    decision: Decision
    query: str
    profile: SkinProfile
    results: list[ProductScore] = field(default_factory=list)
    fallback_message: str | None = None
    review_summary: str | None = None
    guardrails: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines: list[str] = []
        if self.decision == "ask_more":
            lines.append("I need a little more information before recommending products.")
            for question in self.profile.follow_up_questions:
                lines.append(f"- {question}")
            return "\n".join(lines)

        if self.fallback_message:
            lines.append(self.fallback_message)
        if self.decision == "fallback" and self.profile.follow_up_questions:
            lines.append("")
            lines.append("To refine the search:")
            for question in self.profile.follow_up_questions:
                lines.append(f"- {question}")

        constraints = []
        if self.profile.preferred_ingredients:
            constraints.append(f"preferred ingredients: {', '.join(self.profile.preferred_ingredients)}")
        if self.profile.max_price_usd is not None:
            constraints.append(f"max price: ${self.profile.max_price_usd:.2f}")
        if self.profile.min_price_usd is not None:
            constraints.append(f"min price: ${self.profile.min_price_usd:.2f}")
        if constraints:
            lines.append("Applied follow-up constraints: " + "; ".join(constraints))

        if self.results:
            lines.append("Recommended options:")
            for index, item in enumerate(self.results, start=1):
                product = item.product
                price = f", ${product.price_usd:.2f}" if product.price_usd is not None else ""
                lines.append(f"{index}. {product.name} by {product.brand} ({product.category}{price})")
                lines.append(f"   Score: {item.score:.1f}")
                lines.append(f"   Why: {'; '.join(item.reasons) or 'No strong reason recorded.'}")
                if item.matched_ingredients:
                    lines.append(f"   Evidence ingredients: {', '.join(item.matched_ingredients)}")
                if item.cautions:
                    lines.append(f"   Cautions: {'; '.join(item.cautions)}")
                if item.missing_data:
                    lines.append(f"   Missing data: {', '.join(item.missing_data)}")

        if self.review_summary:
            lines.append("")
            lines.append("Review summary:")
            lines.append(self.review_summary)

        if self.guardrails:
            lines.append("")
            lines.append("Guardrails:")
            for guardrail in self.guardrails:
                lines.append(f"- {guardrail}")
        return "\n".join(lines)
