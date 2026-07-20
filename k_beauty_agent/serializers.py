from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .knowledge_base import normalize_token
from .knowledge_base import find_evidence_for_ingredient
from .localization import (
    format_recommendation_text,
    missing_label,
    score_component_label,
    term,
    translate_caution,
    translate_evidence,
    translate_reason,
)
from .models import Product, ProductScore, Recommendation, SkinProfile


def product_to_dict(product: Product) -> dict[str, Any]:
    return {
        "id": product.id,
        "name": product.name,
        "display_name_ko": product.display_name_ko,
        "brand": product.brand,
        "category": product.category,
        "country": product.country,
        "ingredients": list(product.ingredients),
        "claims": list(product.claims),
        "suited_skin_types": list(product.suited_skin_types),
        "concerns": list(product.concerns),
        "avoid_for": list(product.avoid_for),
        "price_usd": product.price_usd,
        "rating": product.rating,
        "review_count": product.review_count,
        "source_url": product.source_url,
        "ingredient_source_url": product.ingredient_source_url,
        "verified_at": product.verified_at,
        "review_summary": product.review_summary,
        "review_summary_en": product.review_summary_en,
        "positive_reviews": list(product.positive_reviews),
        "negative_reviews": list(product.negative_reviews),
        "positive_reviews_en": list(product.positive_reviews_en),
        "negative_reviews_en": list(product.negative_reviews_en),
        "review_source_url": product.review_source_url,
        "image_url": product.image_url,
        "image_verified_source": product.image_verified_source,
        "image_source_type": product.image_source_type,
        "image_confidence": product.image_confidence,
        "image_view_type": product.image_view_type,
        "oliveyoung_url": product.oliveyoung_url,
        "oliveyoung_price_krw": product.oliveyoung_price_krw,
        "official_url": product.official_url,
        "texture_tags": list(product.texture_tags),
        "oliveyoung_verified_at": product.oliveyoung_verified_at,
        "catalog_source": product.catalog_source,
        "source_product_id": product.source_product_id,
        "purchase_url": product.purchase_url,
        "retailer_name": product.retailer_name,
        "price_krw": product.price_krw,
        "price_checked_at": product.price_checked_at,
        "source_updated_at": product.source_updated_at,
        "fetched_at": product.fetched_at,
        "ingredient_status": product.ingredient_status,
        "recommendation_tier": product.recommendation_tier,
        "data_license": product.data_license,
        "data_attribution_url": product.data_attribution_url,
        "ingredient_explanations": ingredient_explanations(product.ingredients),
    }


def product_to_v2_dict(product: Product, commerce_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    """Serialize a normalized product master without bypassing safe offer links.

    Version 1 keeps its legacy retailer fields. Version 2 deliberately removes
    those fields and exposes them through the commerce summary and offer API.
    """

    data = product_to_dict(product)
    for key in (
        "price_usd",
        "oliveyoung_url",
        "oliveyoung_price_krw",
        "oliveyoung_verified_at",
        "purchase_url",
        "retailer_name",
        "price_krw",
        "price_checked_at",
    ):
        data.pop(key, None)
    data["commerce"] = commerce_summary or {
        "offer_count": 0,
        "retailer_count": 0,
        "fresh_offer_count": 0,
        "stale_offer_count": 0,
        "unknown_offer_count": 0,
        "best_current_price": None,
        "lowest_fresh_price_krw": None,
        "has_affiliate_offers": False,
        "offers_url": f"/api/v2/products/{product.id}/offers",
    }
    return data


def score_to_dict(score: ProductScore, language: str | None = "en", personalized_reason: str | None = None) -> dict[str, Any]:
    return {
        "product": product_to_dict(score.product),
        "score": round(score.score, 2),
        "score_components": {key: round(value, 2) for key, value in score.score_components.items()},
        "display_score_components": {
            score_component_label(key, language): round(value, 2) for key, value in score.score_components.items()
        },
        "reasons": score.reasons,
        "display_reasons": [translate_reason(reason, language) for reason in score.reasons],
        "cautions": score.cautions,
        "display_cautions": [translate_caution(caution, language) for caution in score.cautions],
        "evidence": score.evidence,
        "display_evidence": [translate_evidence(evidence, language) for evidence in score.evidence],
        "matched_ingredients": score.matched_ingredients,
        "display_matched_ingredients": [term(ingredient, language) for ingredient in score.matched_ingredients],
        "missing_data": score.missing_data,
        "display_missing_data": [missing_label(item, language) for item in score.missing_data],
        "similar_products": [product_to_dict(product) for product in score.similar_products],
        "personalized_reason": personalized_reason or fallback_personalized_reason(score, language),
    }


def profile_to_public_dict(profile: SkinProfile) -> dict[str, Any]:
    data = asdict(profile)
    for field in ("allergies", "pregnant_or_nursing", "location_or_climate"):
        data.pop(field, None)
    return data


def ingredient_explanations(ingredients: tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
    explanations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ingredient in ingredients:
        evidence = find_evidence_for_ingredient(ingredient)
        if evidence is None or evidence.name in seen:
            continue
        seen.add(evidence.name)
        explanations.append(
            {
                "name": evidence.name,
                "label": ingredient,
                "supports": list(evidence.supports),
                "suitable_for": list(evidence.suitable_for),
                "cautions": list(evidence.cautions),
                "evidence_level": evidence.evidence_level,
                "rationale": evidence.rationale,
                "display_name_ko": term(evidence.name, "ko"),
                "display_supports_ko": [term(value, "ko") for value in evidence.supports],
                "display_suitable_for_ko": [term(value, "ko") for value in evidence.suitable_for],
                "display_cautions_ko": [translate_caution(value, "ko") for value in evidence.cautions],
                "display_rationale_ko": translate_evidence(f"{evidence.name}: {evidence.rationale}", "ko").split(": ", 1)[-1],
            }
        )
    return explanations


def recommendation_to_dict(
    recommendation: Recommendation,
    *,
    recommendation_id: int | None = None,
    grounded_explanation: str | None = None,
    openai_status: str = "not_used",
    language: str | None = "en",
    product_reasons: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "recommendation_id": recommendation_id,
        "decision": recommendation.decision,
        "query": recommendation.query,
        "profile": profile_to_public_dict(recommendation.profile),
        "results": [
            score_to_dict(item, language, personalized_reason=(product_reasons or {}).get(item.product.id))
            for item in recommendation.results
        ],
        "fallback_message": recommendation.fallback_message,
        "review_summary": recommendation.review_summary,
        "guardrails": recommendation.guardrails,
        "grounded_explanation": grounded_explanation or format_recommendation_text(recommendation, language),
        "openai_status": openai_status,
    }


def fallback_personalized_reason(score: ProductScore, language: str | None = "en") -> str:
    reasons = [translate_reason(reason, language) for reason in score.reasons[:3]]
    cautions = [translate_caution(caution, language) for caution in score.cautions[:1]]
    if language == "ko":
        if reasons and cautions:
            return f"검색 조건과 맞는 근거는 {' '.join(reasons)} 다만 {cautions[0]}"
        if reasons:
            return "검색 조건과 맞는 근거는 " + " ".join(reasons)
        return "현재 검색 조건과 제품 DB의 카테고리, 피부 적합도, 성분 근거를 기준으로 추천되었습니다."
    if reasons and cautions:
        return f"This matches your criteria because {' '.join(reasons)} Note: {cautions[0]}"
    if reasons:
        return "This matches your criteria because " + " ".join(reasons)
    return "This was recommended based on the current category, skin-fit, and ingredient evidence in the product database."


def similarity_score(base: Product, candidate: Product) -> float:
    if base.id == candidate.id:
        return -1.0
    score = 0.0
    if normalize_token(base.category) == normalize_token(candidate.category):
        score += 3.0
    base_ingredients = {normalize_token(item) for item in base.ingredients}
    candidate_ingredients = {normalize_token(item) for item in candidate.ingredients}
    base_concerns = {normalize_token(item) for item in base.concerns}
    candidate_concerns = {normalize_token(item) for item in candidate.concerns}
    score += 1.5 * len(base_ingredients & candidate_ingredients)
    score += 2.0 * len(base_concerns & candidate_concerns)
    if normalize_token(base.brand) != normalize_token(candidate.brand):
        score += 0.25
    if candidate.rating:
        score += min(0.5, max(0.0, (candidate.rating - 3.5) / 2.0))
    return score
