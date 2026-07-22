from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .knowledge_base import normalize_token
from .models import Product, SkinProfile
from .skin import analyze_skin_query


PROFILE_LIST_FIELDS = (
    "concerns",
    "desired_categories",
    "preferred_ingredients",
    "sensitivities",
    "allergies",
    "avoid_ingredients",
)


def profile_to_dict(profile: SkinProfile) -> dict[str, Any]:
    data = asdict(profile)
    data.pop("uncertainty", None)
    data.pop("follow_up_questions", None)
    return data


def profile_from_dict(data: dict[str, Any] | None) -> SkinProfile:
    if not data:
        return SkinProfile()
    skin_type = data.get("skin_type")
    sensitivity_level = data.get("sensitivity_level")
    if skin_type == "sensitive":
        # Migrate the former combined skin-type value without discarding its
        # conservative safety signal.
        skin_type = "unknown"
        sensitivity_level = sensitivity_level or "frequent"
    return SkinProfile(
        skin_type=skin_type,
        sensitivity_level=sensitivity_level,
        primary_concern=data.get("primary_concern"),
        concerns=list(data.get("concerns") or []),
        desired_categories=list(data.get("desired_categories") or []),
        preferred_ingredients=list(data.get("preferred_ingredients") or []),
        sensitivities=list(data.get("sensitivities") or []),
        allergies=list(data.get("allergies") or []),
        avoid_ingredients=list(data.get("avoid_ingredients") or []),
        max_price_usd=data.get("max_price_usd"),
        max_price_krw=data.get("max_price_krw"),
        min_price_usd=data.get("min_price_usd"),
        min_price_krw=data.get("min_price_krw"),
        texture_preference=data.get("texture_preference"),
        finish_preference=data.get("finish_preference"),
        location_or_climate=data.get("location_or_climate"),
        pregnant_or_nursing=data.get("pregnant_or_nursing"),
    )


def merge_profiles(stored: dict[str, Any] | None, query: str, recent_queries: list[str] | None = None) -> SkinProfile:
    merged = profile_from_dict(stored)
    recent_text = " ".join((recent_queries or [])[-5:])
    recent_profile = analyze_skin_query(recent_text) if recent_text else SkinProfile()
    query_profile = analyze_skin_query(query)

    for profile in (recent_profile, query_profile):
        if profile.skin_type:
            merged.skin_type = profile.skin_type
        if profile.sensitivity_level:
            merged.sensitivity_level = profile.sensitivity_level
        if profile.primary_concern:
            merged.primary_concern = profile.primary_concern
        if profile.desired_categories:
            if profile is query_profile:
                merged.desired_categories = list(profile.desired_categories)
            else:
                _extend_unique(merged.desired_categories, profile.desired_categories)
        if profile.max_price_usd is not None:
            merged.max_price_usd = profile.max_price_usd
        if profile.max_price_krw is not None:
            merged.max_price_krw = profile.max_price_krw
        if profile.min_price_usd is not None:
            merged.min_price_usd = profile.min_price_usd
        if profile.min_price_krw is not None:
            merged.min_price_krw = profile.min_price_krw
        if profile.texture_preference:
            merged.texture_preference = profile.texture_preference
        if profile.finish_preference:
            merged.finish_preference = profile.finish_preference
        if profile.pregnant_or_nursing is not None:
            merged.pregnant_or_nursing = profile.pregnant_or_nursing
        for field in PROFILE_LIST_FIELDS:
            if field == "desired_categories":
                continue
            _extend_unique(getattr(merged, field), getattr(profile, field))

    if query_profile.location_or_climate:
        merged.location_or_climate = query_profile.location_or_climate
    _refresh_uncertainty(merged)
    return merged


def apply_profile_patch(stored: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    merged = profile_from_dict(stored)
    for field in PROFILE_LIST_FIELDS:
        values = patch.get(field)
        if isinstance(values, list):
            if field == "desired_categories":
                merged.desired_categories = list(values)
            else:
                _extend_unique(getattr(merged, field), values)

    for field in (
        "skin_type",
        "sensitivity_level",
        "primary_concern",
        "texture_preference",
        "finish_preference",
        "location_or_climate",
        "pregnant_or_nursing",
        "max_price_usd",
        "max_price_krw",
        "min_price_usd",
        "min_price_krw",
    ):
        if field in patch and patch[field] is not None:
            setattr(merged, field, patch[field])

    _refresh_uncertainty(merged)
    return profile_to_dict(merged)


def build_personalization(products: list[Product], feedback_rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    by_id = {product.id: product for product in products}
    signals: dict[str, set[str]] = {
        "liked_products": set(),
        "disliked_products": set(),
        "liked_brands": set(),
        "disliked_brands": set(),
        "liked_ingredients": set(),
        "disliked_ingredients": set(),
        "liked_concerns": set(),
        "disliked_concerns": set(),
        "liked_categories": set(),
        "disliked_categories": set(),
    }
    for row in feedback_rows:
        product_id = row.get("product_id")
        product = by_id.get(product_id or "")
        if not product:
            continue
        prefix = "liked" if row.get("feedback") == "liked" else "disliked"
        signals[f"{prefix}_products"].add(product.id)
        signals[f"{prefix}_brands"].add(normalize_token(product.brand))
        signals[f"{prefix}_categories"].add(normalize_token(product.category))
        signals[f"{prefix}_ingredients"].update(normalize_token(item) for item in product.ingredients)
        signals[f"{prefix}_concerns"].update(normalize_token(item) for item in product.concerns)
    return signals


def _extend_unique(target: list[str], values: list[str]) -> None:
    seen = set(target)
    for value in values:
        if value not in seen:
            target.append(value)
            seen.add(value)


def _refresh_uncertainty(profile: SkinProfile) -> None:
    profile.uncertainty = []
    profile.follow_up_questions = []
    if not profile.skin_type:
        profile.uncertainty.append("skin_type")
        profile.follow_up_questions.append(
            "What is your oil/moisture skin type: oily, dry, combination, normal, or unknown?"
        )
    if not profile.primary_concern and not profile.concerns:
        profile.uncertainty.append("concerns")
        profile.follow_up_questions.append(
            "What are your top concerns: oil control, acne, hydration, redness, pigmentation, or aging?"
        )
    if profile.sensitivity_level == "frequent" and not profile.avoid_ingredients:
        profile.follow_up_questions.append("Are there any cosmetic ingredient names you prefer to avoid?")
