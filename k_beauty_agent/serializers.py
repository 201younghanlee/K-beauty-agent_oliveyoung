from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from .catalog_links import information_links
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


_OPERATIONAL_PRICE_CAUTION_PREFIXES = (
    "price is missing, so cannot verify under",
    "checked price is missing, so cannot verify under",
    "checked price is missing, so cannot verify over",
    "Olive Young price is missing, so cannot verify under",
    "excluded because listed price exceeds requested maximum",
    "excluded because checked price exceeds requested maximum",
    "excluded because checked price is below requested minimum",
    "excluded because Olive Young snapshot price exceeds requested maximum",
)


def _customer_cautions(score: ProductScore, language: str | None) -> list[str]:
    """Return safety and product-fit cautions, not ranking diagnostics.

    Missing or stale price is represented by the commerce UI. Repeating an
    internal budget-check message inside the recommendation reason makes the
    product copy noisy and can expose implementation terminology.
    """

    return [
        translate_caution(caution, language)
        for caution in score.cautions
        if not caution.startswith(_OPERATIONAL_PRICE_CAUTION_PREFIXES)
    ]


def _public_cautions(score: ProductScore, language: str | None) -> list[str]:
    cautions = _customer_cautions(score, language)
    if cautions:
        return cautions[:1]
    if (language or "en").lower().startswith("ko"):
        return ["피부 반응에는 개인차가 있어 처음 사용할 때는 국소 부위에서 먼저 확인해 주세요."]
    return ["Individual reactions vary; patch test on a small area before first use."]


def _public_reasons(score: ProductScore, language: str | None) -> list[str]:
    """Return three distinct, grounded fit statements for a product card."""

    selected: list[str] = []
    seen_groups: set[str] = set()
    for reason in score.reasons:
        group = _reason_group(reason)
        if group in seen_groups:
            continue
        seen_groups.add(group)
        selected.append(translate_reason(reason, language))
        if len(selected) == 3:
            return selected

    korean = (language or "en").lower().startswith("ko")
    product = score.product
    fallback: list[tuple[str, str]] = []
    if product.ingredient_status == "complete" and product.ingredients:
        fallback.append(
            (
                "ingredient_data",
                "전체 성분표가 있어 성분 조건을 확인할 수 있습니다."
                if korean
                else "A complete ingredient list is available for checking ingredient criteria.",
            )
        )
    elif product.ingredients:
        fallback.append(
            (
                "ingredient_data",
                "등록된 성분 정보가 있으며 현재 포장에서 재확인이 필요합니다."
                if korean
                else "Reported ingredient data is available but should be checked against the current package.",
            )
        )
    if product.source_url and (product.verified_at or product.source_updated_at or product.fetched_at):
        fallback.append(
            (
                "source_data",
                "제품 출처와 정보 확인일이 기록되어 있습니다."
                if korean
                else "The product source and its information date are recorded.",
            )
        )
    if product.rating is not None and product.review_count is not None and product.review_source_url:
        fallback.append(
            (
                "review_data",
                "평점과 리뷰 수 데이터가 함께 제공됩니다."
                if korean
                else "Rating and review-count data are available.",
            )
        )
    for group, text in fallback:
        if group in seen_groups:
            continue
        seen_groups.add(group)
        selected.append(text)
        if len(selected) == 3:
            return selected

    insufficient = (
        [
            "추가 피부 적합 근거 데이터가 부족합니다.",
            "사용감 근거 데이터가 부족합니다.",
            "개인별 반응 근거 데이터가 부족합니다.",
        ]
        if korean
        else [
            "Additional skin-fit evidence is insufficient.",
            "Texture and wear evidence is insufficient.",
            "Individual-response evidence is insufficient.",
        ]
    )
    for text in insufficient:
        selected.append(text)
        if len(selected) == 3:
            break
    return selected


def _reason_group(reason: str) -> str:
    if "primary concern" in reason:
        return "primary_concern"
    if reason.startswith("matches requested category"):
        return "category"
    if reason == "product identity verified on an official brand page":
        return "product_source"
    if reason.startswith("labeled as suitable"):
        return "skin_type"
    if reason.startswith("contains requested ingredient"):
        return "preferred_ingredient"
    if reason.startswith("matches requested texture"):
        return "texture"
    if reason.startswith("matches requested finish"):
        return "finish"
    if "price is within requested" in reason or reason.startswith("lower checked price"):
        return "budget"
    if reason.startswith(("claims to be fragrance-free", "matches gentle-routine")):
        return "sensitivity"
    if " supports " in reason or reason.startswith("product DB tags include"):
        return "concern_evidence"
    if reason.startswith("personalization"):
        return "personalization"
    return reason


def product_to_dict(product: Product) -> dict[str, Any]:
    has_review_evidence = bool(
        product.review_source_url
        and product.rating is not None
        and product.review_count is not None
    )
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
        "rating": product.rating if has_review_evidence else None,
        "review_count": product.review_count if has_review_evidence else None,
        "source_url": product.source_url,
        "ingredient_source_url": product.ingredient_source_url,
        "verified_at": product.verified_at,
        "review_summary": product.review_summary if has_review_evidence else None,
        "review_summary_en": product.review_summary_en if has_review_evidence else None,
        "positive_reviews": list(product.positive_reviews) if has_review_evidence else [],
        "negative_reviews": list(product.negative_reviews) if has_review_evidence else [],
        "positive_reviews_en": list(product.positive_reviews_en) if has_review_evidence else [],
        "negative_reviews_en": list(product.negative_reviews_en) if has_review_evidence else [],
        "review_source_url": product.review_source_url,
        "review_verified_at": product.review_verified_at,
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
        "external_links": [link.to_public_dict() for link in information_links(product)],
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
    public_reasons = _public_reasons(score, language)
    public_cautions = _public_cautions(score, language)
    return {
        "product": product_to_dict(score.product),
        "score": round(score.score, 2),
        "score_components": {key: round(value, 2) for key, value in score.score_components.items()},
        "display_score_components": {
            score_component_label(key, language): round(value, 2) for key, value in score.score_components.items()
        },
        "reasons": score.reasons,
        "display_reasons": public_reasons,
        "fit_reasons": public_reasons,
        "cautions": score.cautions,
        "display_cautions": public_cautions,
        "caution": public_cautions[0],
        "evidence": score.evidence,
        "display_evidence": [translate_evidence(evidence, language) for evidence in score.evidence],
        "matched_ingredients": score.matched_ingredients,
        "display_matched_ingredients": [term(ingredient, language) for ingredient in score.matched_ingredients],
        "missing_data": score.missing_data,
        "display_missing_data": [missing_label(item, language) for item in score.missing_data],
        "data_confidence": _data_confidence(score),
        "similar_products": [product_to_dict(product) for product in score.similar_products],
        "personalized_reason": personalized_reason or fallback_personalized_reason(score, language),
    }


def _data_confidence(score: ProductScore) -> dict[str, Any]:
    """Describe evidence completeness separately from recommendation fit."""

    product = score.product
    ingredient_status = (
        "verified" if product.ingredient_status == "complete" and product.ingredients
        else "reported" if product.ingredients
        else "missing"
    )
    source_kind, source_checked_at = next(
        (
            (kind, value)
            for kind, value in (
                ("product_source_updated_at", product.source_updated_at),
                ("catalog_verified_at", product.verified_at),
                ("catalog_fetched_at", product.fetched_at),
            )
            if value
        ),
        (None, None),
    )
    source_status = _date_status(source_checked_at)
    review_status = "missing"
    if (
        product.rating is not None
        and product.review_count is not None
        and product.review_source_url
    ):
        review_status = _date_status(product.review_verified_at)
        if review_status == "missing":
            review_status = "undated"

    confidence_points = {
        "verified": 2,
        "reported": 1,
        "missing": 0,
    }[ingredient_status]
    confidence_points += 2 if source_status == "current" else 0
    confidence_points += 1 if review_status == "current" else 0
    if confidence_points >= 5:
        level = "high"
        label_ko = "근거 신뢰도 높음"
        label_en = "High evidence confidence"
    elif confidence_points >= 2:
        level = "medium"
        label_ko = "근거 신뢰도 보통"
        label_en = "Medium evidence confidence"
    else:
        level = "low"
        label_ko = "근거 데이터 제한적"
        label_en = "Limited evidence data"

    return {
        "level": level,
        "label_ko": label_ko,
        "label_en": label_en,
        "factors": {
            "ingredients": {
                "status": ingredient_status,
                "label_ko": {
                    "verified": "전체 성분표 확인",
                    "reported": "등록 성분 정보 - 현재 포장 재확인 필요",
                    "missing": "성분 정보 없음",
                }[ingredient_status],
            },
            "product_source": {
                "status": source_status,
                "date_kind": source_kind,
                "checked_at": source_checked_at,
                "label_ko": {
                    "current": "상품 정보 최근 확인",
                    "stale": "상품 정보 업데이트 필요",
                    "missing": "상품 정보 확인일 없음",
                }[source_status],
            },
            "reviews": {
                "status": review_status,
                "checked_at": product.review_verified_at if product.review_source_url else None,
                "source_url": product.review_source_url,
                "label_ko": {
                    "current": "리뷰 정보 최근 확인",
                    "stale": "리뷰 정보 업데이트 필요",
                    "undated": "리뷰 확인일 없음",
                    "missing": "리뷰 근거 부족",
                }[review_status],
            },
        },
    }


def _date_status(value: str | None) -> str:
    if not value:
        return "missing"
    try:
        checked = date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return "missing"
    age_days = (date.today() - checked).days
    if age_days < 0:
        return "missing"
    return "current" if age_days <= 365 else "stale"


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
    reasons = _public_reasons(score, language)
    cautions = _public_cautions(score, language)
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
