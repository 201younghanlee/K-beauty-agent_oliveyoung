from __future__ import annotations

import json
import re
from typing import Any, Protocol

from .skin import (
    CATEGORY_TERMS,
    CONCERN_TERMS,
    SENSITIVITY_TERMS,
    SKIN_TYPE_TERMS,
    TEXTURE_TERMS,
    canonicalize_ingredient_preferences,
)


class CompletionClient(Protocol):
    def complete(self, system: str, user: str) -> str:
        ...


ALLOWED_SKIN_TYPES = set(SKIN_TYPE_TERMS)
ALLOWED_CONCERNS = set(CONCERN_TERMS) | {"dryness"}
ALLOWED_CATEGORIES = set(CATEGORY_TERMS)
ALLOWED_SENSITIVITIES = set(SENSITIVITY_TERMS) | {"gentle_preference", "budget_preference"}
ALLOWED_TEXTURES = set(TEXTURE_TERMS)
LIST_FIELDS = ("concerns", "desired_categories", "preferred_ingredients", "sensitivities", "avoid_ingredients")


def parse_follow_up_patch(
    query: str,
    *,
    stored_profile: dict[str, Any] | None,
    recent_queries: list[str] | None,
    client: CompletionClient,
    language: str = "ko",
) -> dict[str, Any]:
    system = (
        "You convert K-beauty follow-up requests into structured search constraints. "
        "Return JSON only. Do not recommend products. Do not infer health conditions or invent ingredients, prices, or concerns. "
        "Only include fields that are explicitly requested or strongly implied by the follow-up. "
        "Allowed fields: skin_type, concerns, desired_categories, preferred_ingredients, sensitivities, "
        "avoid_ingredients, max_price_usd, max_price_krw, min_price_usd, min_price_krw, texture_preference, "
        "Only use controlled cosmetic preference fields; never return health, allergy, pregnancy, nursing, or location data. "
        "Use canonical English tokens for categories/concerns/skin/texture. "
        "For Korean price phrases, '이하/under' maps to max_price_krw and '이상/over/at least' maps to min_price_krw."
    )
    user = json.dumps(
        {
            "language": language,
            "current_profile": stored_profile or {},
            "recent_queries": recent_queries or [],
            "follow_up": query,
            "allowed_values": {
                "skin_type": sorted(ALLOWED_SKIN_TYPES),
                "concerns": sorted(ALLOWED_CONCERNS),
                "desired_categories": sorted(ALLOWED_CATEGORIES),
                "sensitivities": sorted(ALLOWED_SENSITIVITIES),
                "texture_preference": sorted(ALLOWED_TEXTURES),
            },
            "examples": [
                {
                    "follow_up": "3만원 이상의 세럼으로 바꿔줘",
                    "json": {"desired_categories": ["serum"], "min_price_krw": 30000},
                },
                {
                    "follow_up": "히알루론산은 빼고 더 산뜻한 선크림",
                    "json": {
                        "desired_categories": ["sunscreen"],
                        "avoid_ingredients": ["hyaluronic acid"],
                        "texture_preference": "lightweight",
                    },
                },
            ],
        },
        ensure_ascii=False,
    )
    return sanitize_profile_patch(_json_from_text(client.complete(system=system, user=user)))


def sanitize_profile_patch(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    patch: dict[str, Any] = {}

    skin_type = _clean_token(data.get("skin_type"))
    if skin_type in ALLOWED_SKIN_TYPES:
        patch["skin_type"] = skin_type

    texture = _clean_token(data.get("texture_preference"))
    if texture in ALLOWED_TEXTURES:
        patch["texture_preference"] = texture

    for field, allowed in (
        ("concerns", ALLOWED_CONCERNS),
        ("desired_categories", ALLOWED_CATEGORIES),
        ("sensitivities", ALLOWED_SENSITIVITIES),
    ):
        values = [value for value in _clean_list(data.get(field), max_items=8) if value in allowed]
        if values:
            patch[field] = values

    for field in ("preferred_ingredients", "avoid_ingredients"):
        values = canonicalize_ingredient_preferences(
            _clean_list(data.get(field), max_items=12, max_len=50)
        )
        if values:
            patch[field] = values

    for field, limit in (("max_price_krw", 2_000_000), ("min_price_krw", 2_000_000)):
        value = _clean_int(data.get(field), limit)
        if value is not None:
            patch[field] = value

    for field, limit in (("max_price_usd", 1000.0), ("min_price_usd", 1000.0)):
        value = _clean_float(data.get(field), limit)
        if value is not None:
            patch[field] = value

    return patch


def _json_from_text(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if match:
        cleaned = match.group(0)
    return json.loads(cleaned)


def _clean_list(value: Any, *, max_items: int, max_len: int = 40) -> list[str]:
    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, list):
        raw_values = value
    else:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        token = _clean_free_text(item, max_len=max_len)
        if token and token not in seen:
            cleaned.append(token)
            seen.add(token)
        if len(cleaned) >= max_items:
            break
    return cleaned


def _clean_token(value: Any) -> str | None:
    text = _clean_free_text(value, max_len=40)
    return text.lower().replace(" ", "_") if text else None


def _clean_free_text(value: Any, *, max_len: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"[^0-9A-Za-z가-힣 _+./%-]+", " ", value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text[:max_len] if text else None


def _clean_int(value: Any, limit: int) -> int | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    if 0 <= number <= limit:
        return number
    return None


def _clean_float(value: Any, limit: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if 0 <= number <= limit:
        return number
    return None
