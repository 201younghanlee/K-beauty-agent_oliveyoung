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


ALLOWED_SKIN_TYPES = set(SKIN_TYPE_TERMS) | {"unknown"}
ALLOWED_CONCERNS = set(CONCERN_TERMS) | {"dryness", "dullness"}
ALLOWED_CATEGORIES = set(CATEGORY_TERMS)
ALLOWED_SENSITIVITIES = set(SENSITIVITY_TERMS) | {"gentle_preference", "budget_preference"}
ALLOWED_SENSITIVITY_LEVELS = {"frequent", "occasional", "low"}
ALLOWED_TEXTURES = set(TEXTURE_TERMS) | {"watery", "lotion", "cream"}
ALLOWED_FINISHES = {"fresh", "low_sticky", "moist", "glow", "matte"}
LIST_FIELDS = ("concerns", "desired_categories", "preferred_ingredients", "sensitivities", "avoid_ingredients")

_INGREDIENT_CONTACT_PATTERN = re.compile(
    r"(?:[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|https?://|www\.)",
    re.IGNORECASE,
)
_PHONE_LIKE_PATTERN = re.compile(r"(?<!\d)(?:\+?\d[\d .()/-]{7,}\d)(?!\d)")
_NOTE_LIKE_PATTERN = re.compile(
    r"\b(?:my|me|this|that|please|remember|note|private|secret|about|want|avoid|using?)\b"
    r"|(?:개인\s*메모|비밀|기억해|메모해|해주세요|해줘|하고\s*싶|저는|제\s*이름)",
    re.IGNORECASE,
)
_CUSTOM_INGREDIENT_SUFFIXES = (
    "acid",
    "alcohol",
    "extract",
    "filtrate",
    "ferment",
    "oil",
    "water",
    "powder",
    "peptide",
    "peroxide",
    "oxide",
    "sulfate",
    "phosphate",
    "chloride",
    "carbonate",
    "acetate",
    "glucoside",
    "glycol",
    "glyceride",
    "polymer",
    "crosspolymer",
    "protein",
    "butter",
    "wax",
    "gum",
    "starch",
    "lactate",
    "salicylate",
    "hyaluronate",
    "추출물",
    "오일",
    "애씨드",
    "알코올",
    "발효",
    "여과물",
    "펩타이드",
    "세라마이드",
    "비타민",
)


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
        "Allowed fields: skin_type, sensitivity_level, primary_concern, concerns, desired_categories, "
        "preferred_ingredients, sensitivities, avoid_ingredients, max_price_usd, max_price_krw, "
        "min_price_usd, min_price_krw, texture_preference, finish_preference. "
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
                "sensitivity_level": sorted(ALLOWED_SENSITIVITY_LEVELS),
                "primary_concern": sorted(ALLOWED_CONCERNS),
                "concerns": sorted(ALLOWED_CONCERNS),
                "desired_categories": sorted(ALLOWED_CATEGORIES),
                "sensitivities": sorted(ALLOWED_SENSITIVITIES),
                "texture_preference": sorted(ALLOWED_TEXTURES),
                "finish_preference": sorted(ALLOWED_FINISHES),
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


def sanitize_profile_patch(
    data: Any,
    *,
    allow_unrecognized_ingredients: bool = False,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    patch: dict[str, Any] = {}

    sensitivity_level = _clean_token(data.get("sensitivity_level"))
    if sensitivity_level in ALLOWED_SENSITIVITY_LEVELS:
        patch["sensitivity_level"] = sensitivity_level

    skin_type = _clean_token(data.get("skin_type"))
    if skin_type in ALLOWED_SKIN_TYPES:
        if skin_type == "sensitive":
            # Backward compatibility for the former single-axis survey.
            # Explicit new sensitivity input wins when both are supplied.
            patch["skin_type"] = "unknown"
            patch.setdefault("sensitivity_level", "frequent")
        else:
            patch["skin_type"] = skin_type

    primary_concern = _clean_token(data.get("primary_concern"))
    if primary_concern in ALLOWED_CONCERNS:
        patch["primary_concern"] = primary_concern

    texture = _clean_token(data.get("texture_preference"))
    if texture in ALLOWED_TEXTURES:
        patch["texture_preference"] = texture

    finish = _clean_token(data.get("finish_preference"))
    if finish in ALLOWED_FINISHES:
        patch["finish_preference"] = finish

    for field, allowed in (
        ("concerns", ALLOWED_CONCERNS),
        ("desired_categories", ALLOWED_CATEGORIES),
        ("sensitivities", ALLOWED_SENSITIVITIES),
    ):
        values = [value for value in _clean_list(data.get(field), max_items=8) if value in allowed]
        if values:
            patch[field] = values

    for field in ("preferred_ingredients", "avoid_ingredients"):
        values = _clean_ingredient_preferences(
            data.get(field),
            allow_unrecognized=allow_unrecognized_ingredients,
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


def _clean_ingredient_preferences(value: Any, *, allow_unrecognized: bool) -> list[str]:
    """Canonicalize known aliases and optionally keep bounded INCI-style input.

    LLM follow-up patches stay on the allowlist so an explanation model cannot
    invent constraints. The structured public form may keep user-entered
    cosmetic ingredient names; the request layer separately rejects sensitive
    health text before this profile can be used or stored.
    """

    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, list):
        raw_values = value[:12]
    else:
        raw_values = []
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        if not isinstance(raw_value, str):
            continue
        # Public structured input is validated in its original form. Controlled
        # LLM output may first be stripped down to its allowlisted token so old
        # defensive behavior such as ``hyaluronic acid<script>`` remains safe.
        validation_value = raw_value if allow_unrecognized else (_clean_free_text(raw_value, max_len=50) or "")
        if not is_safe_cosmetic_ingredient_text(validation_value):
            continue
        normalized_raw = _clean_free_text(validation_value, max_len=50)
        if not normalized_raw:
            continue
        canonical = canonicalize_ingredient_preferences([normalized_raw])
        candidates = canonical or ([normalized_raw] if allow_unrecognized else [])
        for candidate in candidates:
            key = candidate.casefold()
            if key not in seen:
                cleaned.append(candidate)
                seen.add(key)
    return cleaned


def is_safe_cosmetic_ingredient_text(value: str) -> bool:
    """Accept bounded ingredient-like text while rejecting contact/private notes."""

    raw = value.strip()
    if not raw or len(raw) > 50:
        return False
    if (
        _INGREDIENT_CONTACT_PATTERN.search(raw)
        or _PHONE_LIKE_PATTERN.search(raw)
        or _NOTE_LIKE_PATTERN.search(raw)
    ):
        return False
    if not re.fullmatch(r"[0-9A-Za-z가-힣 _+./%()'-]+", raw):
        return False
    if re.search(r"\d{4,}", raw):
        return False
    words = re.findall(r"[0-9A-Za-z가-힣]+", raw)
    if not words or len(words) > 8:
        return False
    if canonicalize_ingredient_preferences([raw]):
        return True
    if len(words) == 1:
        return len(words[0]) >= 3
    normalized = " ".join(words).lower()
    return normalized.endswith(_CUSTOM_INGREDIENT_SUFFIXES)


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
