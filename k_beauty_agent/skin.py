from __future__ import annotations

import re

from .knowledge_base import normalize_token
from .models import SkinProfile

SKIN_TYPE_TERMS = {
    "oily": ("oily", "oiliness", "sebum", "지성", "유분", "번들", "피지"),
    "dry": ("dry", "dehydrated", "flaky", "건성", "건조", "당김", "각질"),
    "combination": ("combination", "combo", "복합성", "t zone", "t존"),
    "sensitive": ("sensitive", "reactive", "민감", "예민", "따가움", "홍조"),
    "normal": ("normal", "보통"),
}

CONCERN_TERMS = {
    "oil_control": ("oil control", "sebum", "유분", "피지", "번들", "matte"),
    "acne": ("acne", "breakout", "pimple", "여드름", "트러블"),
    "clogged_pores": ("blackhead", "whitehead", "clogged", "블랙헤드", "화이트헤드", "모공"),
    "hydration": ("hydration", "dehydrated", "수분", "보습", "속건조"),
    "barrier_support": ("barrier", "장벽", "손상", "진정"),
    "redness": ("redness", "홍조", "붉", "진정"),
    "hyperpigmentation": ("dark spot", "melasma", "pigmentation", "잡티", "색소", "기미"),
    "anti_aging": ("wrinkle", "fine line", "aging", "탄력", "주름", "안티에이징"),
    "texture": ("texture", "rough", "결", "요철"),
}

CATEGORY_TERMS = {
    "cleanser": ("cleanser", "cleansing", "foam", "oil cleanser", "balm", "폼", "클렌저", "클렌징", "세안", "클렌징오일", "클렌징 오일", "클렌징밤", "클렌징 밤"),
    "toner": ("toner", "toner pad", "mist", "토너", "스킨", "패드", "토너패드", "토너 패드", "미스트"),
    "serum": ("serum", "ampoule", "essence", "세럼", "앰플", "에센스"),
    "moisturizer": ("lotion", "emulsion", "moisturizer", "water cream", "cream", "수분크림", "수분 크림", "보습크림", "보습 크림", "크림", "에멀전", "로션", "보습제"),
    "sunscreen": ("sunscreen", "spf", "sun cream", "선크림", "자외선"),
    "basic": ("basic", "routine", "기초", "스킨케어", "루틴"),
}

SENSITIVITY_TERMS = {
    "fragrance_sensitive": ("fragrance", "perfume", "향료", "무향", "향에 민감"),
    "alcohol_sensitive": ("alcohol", "알코올"),
}

SENSITIVITY_LEVEL_TERMS = {
    "low": (
        "rarely sensitive",
        "not sensitive",
        "거의 민감하지 않",
        "민감하지 않",
    ),
    "occasional": (
        "sometimes sensitive",
        "occasionally sensitive",
        "가끔 예민",
        "가끔 민감",
    ),
    "frequent": (
        "easily stings",
        "easily gets red",
        "often sensitive",
        "쉽게 따갑",
        "쉽게 붉",
        "자주 예민",
        "자주 민감",
    ),
}

GENTLE_TERMS = (
    "gentle",
    "mild",
    "soothing",
    "non-irritating",
    "non irritating",
    "순한",
    "순하게",
    "순하",
    "순한거",
    "순한 걸",
    "순한 제품",
    "저자극",
    "자극없",
    "자극 없",
    "자극 적",
    "덜 자극",
    "약산성",
)
BUDGET_TERMS = (
    "cheap",
    "cheaper",
    "budget",
    "affordable",
    "low price",
    "저렴",
    "저렴한",
    "저렴하게",
    "싼",
    "싸게",
    "더 싸",
    "싼거",
    "싼 걸",
    "가격 낮",
    "가격대 낮",
    "가격",
    "저가",
    "가성비",
    "비싸지 않",
)

TEXTURE_TERMS = {
    "dewy": ("dewy", "glowy", "촉촉", "촉촉한", "윤광", "광나는"),
    "lightweight": ("lightweight", "fresh", "watery", "산뜻", "가벼운", "가볍", "워터리", "수분감"),
    "rich": ("rich", "thick", "cream", "꾸덕", "꾸덕한", "리치", "쫀쫀", "크림"),
    "gel": ("gel", "gel type", "젤", "젤타입", "젤 타입"),
}

INGREDIENT_TERMS = {
    "niacinamide": ("niacinamide", "나이아신아마이드", "나이아신", "비타민 b3"),
    "salicylic acid": ("salicylic acid", "bha", "betaine salicylate", "salicylate", "살리실산", "살리실레이트", "바하", "BHA"),
    "green tea extract": ("green tea", "green tea extract", "camellia sinensis", "camellia sinensis leaf extract", "녹차", "녹차 추출물", "카멜리아 시넨시스"),
    "panthenol": ("panthenol", "판테놀"),
    "ceramide np": ("ceramide", "ceramide np", "세라마이드"),
    "glycerin": ("glycerin", "글리세린"),
    "hyaluronic acid": ("hyaluronic acid", "sodium hyaluronate", "히알루론산", "히알루론", "소듐하이알루로네이트", "하이알루론산", "하이알루론"),
    "retinol": ("retinol", "retinal", "레티놀", "레티날"),
    "azelaic acid": ("azelaic acid", "아젤라익", "아젤라익애씨드"),
    "centella asiatica": ("centella", "centella asiatica", "centella asiatica extract", "cica", "병풀", "병풀추출물", "시카"),
    "zinc pca": ("zinc pca", "징크 pca", "징크피씨에이"),
    "fragrance": ("fragrance", "parfum", "perfume", "lavender oil", "limonene", "linalool", "essential oil", "향료", "향수", "라벤더오일", "리모넨", "리날룰", "에센셜오일"),
    "alcohol": ("alcohol", "ethanol", "알코올", "에탄올"),
    "snail": ("snail", "snail secretion filtrate", "달팽이", "스네일", "달팽이점액"),
    "tea tree": ("tea tree", "tea tree leaf oil", "tea tree extract", "tea tree leaf extract", "티트리", "티트리오일", "티트리추출물"),
    "rice extract": ("rice extract", "rice bran extract", "rice bran water", "oryza sativa", "쌀", "쌀추출물", "쌀겨", "미강"),
    "squalane": ("squalane", "스쿠알란"),
    "allantoin": ("allantoin", "알란토인"),
    "betaine": ("betaine", "베타인"),
    "propolis": ("propolis", "propolis extract", "프로폴리스"),
    "tranexamic acid": ("tranexamic acid", "트라넥사믹", "트라넥사믹애씨드"),
    "arbutin": ("arbutin", "알부틴"),
    "ascorbic acid": ("ascorbic acid", "ascorbyl glucoside", "vitamin c", "비타민 c", "비타민씨", "아스코빅애씨드", "아스코빌글루코사이드"),
    "zinc oxide": ("zinc oxide", "징크옥사이드", "산화아연"),
    "onion extract": ("onion", "allium cepa", "allium cepa onion bulb extract", "어니언", "양파", "양파추출물"),
    "mugwort": ("mugwort", "artemisia", "artemisia capillaris extract", "쑥", "약쑥"),
    "honey": ("honey", "honey extract", "꿀", "꿀추출물"),
    "ginseng": ("ginseng", "panax ginseng", "panax ginseng root water", "인삼", "진생"),
    "bifida ferment": ("bifida", "bifida ferment lysate", "비피다", "비피다발효"),
    "lactobacillus ferment": ("lactobacillus", "lactobacillus ferment", "락토바실러스", "락토바실러스발효"),
    "houttuynia cordata": ("houttuynia", "houttuynia cordata", "heartleaf", "어성초", "약모밀"),
    "madecassoside": ("madecassoside", "마데카소사이드"),
    "glutathione": ("glutathione", "글루타치온"),
}

FATTY_ALCOHOL_TERMS = (
    "cetearyl alcohol",
    "cetyl alcohol",
    "stearyl alcohol",
    "behenyl alcohol",
    "arachidyl alcohol",
    "세테아릴알코올",
    "세틸알코올",
    "스테아릴알코올",
    "베헤닐알코올",
    "아라키딜알코올",
)
NON_VOLATILE_ALCOHOL_TERMS = (
    *FATTY_ALCOHOL_TERMS,
    "benzyl alcohol",
    "phenethyl alcohol",
    "벤질알코올",
    "페네틸알코올",
)

AVOID_CONTEXT = ("빼고", "제외", "없는", "없이", "안", "싫", "피하", "알러지", "알레르기", "avoid", "without", "no ")


def analyze_skin_query(query: str) -> SkinProfile:
    text = query.lower()
    profile = SkinProfile()

    matched_skin_types = [
        skin_type
        for skin_type, terms in SKIN_TYPE_TERMS.items()
        if skin_type != "sensitive" and _contains_any(text, terms)
    ]
    profile.sensitivity_level = _extract_sensitivity_level(text)
    if "combination" in matched_skin_types or {"oily", "dry"}.issubset(matched_skin_types):
        profile.skin_type = "combination"
    elif matched_skin_types:
        profile.skin_type = matched_skin_types[0]
    elif profile.sensitivity_level:
        # Sensitivity is independent of oil/moisture type. Preserve the
        # explicit signal without guessing oily, dry, or combination skin.
        profile.skin_type = "unknown"

    for concern, terms in CONCERN_TERMS.items():
        if _contains_any(text, terms):
            profile.concerns.append(concern)

    for category, terms in CATEGORY_TERMS.items():
        if _category_matches(text, category, terms):
            profile.desired_categories.append(category)

    for sensitivity, terms in SENSITIVITY_TERMS.items():
        if _contains_any(text, terms):
            profile.sensitivities.append(sensitivity)
            if sensitivity == "fragrance_sensitive":
                profile.avoid_ingredients.extend(["fragrance", "parfum", "essential oil"])

    if _contains_any(text, GENTLE_TERMS):
        profile.concerns.extend(["barrier_support", "redness"])
        profile.sensitivities.extend(["gentle_preference", "fragrance_sensitive"])
        profile.avoid_ingredients.extend(["fragrance", "parfum", "essential oil"])

    if _contains_any(text, BUDGET_TERMS):
        profile.sensitivities.append("budget_preference")

    profile.avoid_ingredients.extend(_extract_avoid_ingredients(text))
    profile.preferred_ingredients.extend(_extract_preferred_ingredients(text))
    profile.texture_preference = _extract_texture_preference(text)
    profile.max_price_usd = _extract_max_price_usd(text)
    profile.max_price_krw = _extract_max_price_krw(text)
    profile.min_price_usd = _extract_min_price_usd(text)
    profile.min_price_krw = _extract_min_price_krw(text)
    if (
        profile.max_price_usd is not None
        or profile.max_price_krw is not None
        or profile.min_price_usd is not None
        or profile.min_price_krw is not None
    ) and "budget_preference" not in profile.sensitivities:
        profile.sensitivities.append("budget_preference")

    _infer_default_concerns(profile)

    explicit_avoids = re.findall(r"\b(?:avoid|without|no)\b\s+([a-zA-Z가-힣 ]{2,30})", query)
    explicit_avoids.extend(re.findall(r"(?:빼고|제외)\s*([a-zA-Z가-힣 ]{2,30})", query))
    explicit_avoids.extend(re.findall(r"([a-zA-Z가-힣 ]{2,30})(?:알러지|알레르기|피하고|피해야)", query))
    for item in explicit_avoids:
        cleaned = item.strip(" .,!?:;")
        if cleaned:
            profile.avoid_ingredients.extend(_canonical_ingredients(cleaned))

    _dedupe(profile.concerns)
    _dedupe(profile.desired_categories)
    _dedupe(profile.preferred_ingredients)
    _dedupe(profile.sensitivities)
    _dedupe(profile.allergies)
    _dedupe(profile.avoid_ingredients)

    if not profile.skin_type:
        profile.uncertainty.append("skin_type")
        profile.follow_up_questions.append("What is your oil/moisture skin type: oily, dry, combination, normal, or unknown?")
    if not profile.concerns:
        profile.uncertainty.append("concerns")
        profile.follow_up_questions.append("What are your top concerns: oil control, acne, hydration, redness, pigmentation, or aging?")
    if profile.sensitivity_level == "frequent" and not profile.avoid_ingredients:
        profile.follow_up_questions.append("Are there any cosmetic ingredient names you prefer to avoid?")

    return profile


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.lower() in text for term in terms)


def _extract_sensitivity_level(text: str) -> str | None:
    # Check explicit low/occasional/frequent phrases before the generic
    # "sensitive" vocabulary, because phrases such as "not sensitive" also
    # contain that generic word.
    for level in ("low", "occasional", "frequent"):
        if _contains_any(text, SENSITIVITY_LEVEL_TERMS[level]):
            return level
    if _contains_any(text, SKIN_TYPE_TERMS["sensitive"]):
        return "frequent"
    return None


def _category_matches(text: str, category: str, terms: tuple[str, ...]) -> bool:
    if not _contains_any(text, terms):
        return False
    if category != "moisturizer":
        return True

    sunscreen_mentioned = _contains_any(text, CATEGORY_TERMS["sunscreen"])
    if not sunscreen_mentioned:
        return True

    specific_moisturizer_terms = (
        "lotion",
        "emulsion",
        "moisturizer",
        "water cream",
        "수분크림",
        "수분 크림",
        "보습크림",
        "보습 크림",
        "에멀전",
        "로션",
        "보습제",
    )
    return _contains_any(text, specific_moisturizer_terms)


def _extract_preferred_ingredients(text: str) -> list[str]:
    values: list[str] = []
    for ingredient, terms in INGREDIENT_TERMS.items():
        if ingredient == "alcohol" and not _contains_volatile_alcohol(text):
            continue
        for term in terms:
            normalized_term = normalize_token(term)
            if normalized_term not in normalize_token(text):
                continue
            window = _term_window(text, term, radius=18)
            if any(marker in window for marker in AVOID_CONTEXT):
                continue
            if ingredient in {"fragrance", "alcohol"} and any(
                marker in window
                for marker in ("sensitive", "민감", "예민", "fragrance-free", "fragrance free", "무향")
            ):
                continue
            values.append(ingredient)
            break
    return values


def _extract_avoid_ingredients(text: str) -> list[str]:
    values: list[str] = []
    for ingredient, terms in INGREDIENT_TERMS.items():
        if ingredient == "alcohol" and not _contains_volatile_alcohol(text):
            continue
        for term in terms:
            normalized_term = normalize_token(term)
            if normalized_term not in normalize_token(text):
                continue
            window = _term_window(text, term, radius=24)
            if any(marker in window for marker in AVOID_CONTEXT):
                values.append(ingredient)
                break
    return values


def _canonical_ingredients(text: str) -> list[str]:
    found: list[str] = []
    normalized = normalize_token(text)
    for ingredient, terms in INGREDIENT_TERMS.items():
        if ingredient == "alcohol" and not _contains_volatile_alcohol(text):
            continue
        if any(normalize_token(term) in normalized for term in terms):
            found.append(ingredient)
    return found


def _contains_volatile_alcohol(text: str) -> bool:
    """Recognize ethanol-style alcohol without broadening fatty alcohols."""

    normalized = normalize_token(text)
    for non_volatile_alcohol in NON_VOLATILE_ALCOHOL_TERMS:
        normalized = normalized.replace(normalize_token(non_volatile_alcohol), " ")
    normalized = " ".join(normalized.split())
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", normalized)
        for marker in ("alcohol", "ethanol", "알코올", "에탄올")
    )


def canonicalize_ingredient_preferences(values: list[str]) -> list[str]:
    """Keep only supported ingredient names so free text cannot enter saved profiles."""

    canonical: list[str] = []
    for value in values:
        canonical.extend(_canonical_ingredients(str(value)))
    _dedupe(canonical)
    return canonical


def _extract_max_price_usd(text: str) -> float | None:
    normalized_text = text.replace(",", "")
    dollar_match = re.search(r"(?:\$|usd\s*)\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:달러|불|usd)", normalized_text, re.I)
    if dollar_match and _has_max_price_context(text, dollar_match.group(0)):
        value = dollar_match.group(1) or dollar_match.group(2)
        return float(value)

    return None


def _extract_min_price_usd(text: str) -> float | None:
    normalized_text = text.replace(",", "")
    dollar_match = re.search(r"(?:\$|usd\s*)\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:달러|불|usd)", normalized_text, re.I)
    if dollar_match and _has_min_price_context(text, dollar_match.group(0)):
        value = dollar_match.group(1) or dollar_match.group(2)
        return float(value)

    return None


def _extract_max_price_krw(text: str) -> int | None:
    normalized_text = text.replace(",", "")
    range_match = re.search(
        r"(?:\d+(?:\.\d+)?\s*만\s*(?:원)?|\d{4,7}\s*원|만원)\s*(?:이상|초과|부터)"
        r"[^\d]{0,12}((?:\d+(?:\.\d+)?)\s*만\s*(?:원)?|\d{4,7}\s*원|만원)\s*(?:이하|미만|아래|까지)",
        normalized_text,
    )
    if range_match:
        return _krw_amount(range_match.group(1))

    manwon_match = re.search(r"(\d+(?:\.\d+)?)\s*만\s*(?:원)?", normalized_text)
    if manwon_match and _has_max_price_context(text, manwon_match.group(0)):
        return int(float(manwon_match.group(1)) * 10000)

    plain_manwon_match = re.search(r"만원", normalized_text)
    if plain_manwon_match and _has_max_price_context(text, plain_manwon_match.group(0)):
        return 10000

    won_match = re.search(r"(\d{4,7})\s*원", normalized_text)
    if won_match and _has_max_price_context(text, won_match.group(0)):
        return int(float(won_match.group(1)))

    return None


def _extract_min_price_krw(text: str) -> int | None:
    normalized_text = text.replace(",", "")
    manwon_match = re.search(r"(\d+(?:\.\d+)?)\s*만\s*(?:원)?", normalized_text)
    if manwon_match and _has_min_price_context(text, manwon_match.group(0)):
        return int(float(manwon_match.group(1)) * 10000)

    plain_manwon_match = re.search(r"만원", normalized_text)
    if plain_manwon_match and _has_min_price_context(text, plain_manwon_match.group(0)):
        return 10000

    won_match = re.search(r"(\d{4,7})\s*원", normalized_text)
    if won_match and _has_min_price_context(text, won_match.group(0)):
        return int(float(won_match.group(1)))

    return None


def _krw_amount(text: str) -> int:
    normalized_text = text.replace(",", "")
    manwon_match = re.search(r"(\d+(?:\.\d+)?)\s*만\s*(?:원)?", normalized_text)
    if manwon_match:
        return int(float(manwon_match.group(1)) * 10000)
    if "만원" in normalized_text:
        return 10000
    won_match = re.search(r"(\d{4,7})\s*원", normalized_text)
    if won_match:
        return int(float(won_match.group(1)))
    return 0


def _extract_texture_preference(text: str) -> str | None:
    for texture, terms in TEXTURE_TERMS.items():
        if _contains_any(text, terms):
            return texture
    return None


def _has_max_price_context(text: str, match_text: str) -> bool:
    window = _term_window(text, match_text, radius=20)
    if _has_min_price_context(text, match_text) and not any(marker in window for marker in ("이하", "미만", "아래", "under", "less", "below", "까지", "넘지", "최대", "max", "maximum")):
        return False
    return any(
        marker in window
        for marker in (
            "이하",
            "미만",
            "아래",
            "under",
            "less",
            "below",
            "까지",
            "넘지",
            "예산",
            "가격",
            "금액",
            "최대",
            "budget",
            "max",
            "maximum",
            "대",
            "선",
            "정도",
        )
    )


def _has_min_price_context(text: str, match_text: str) -> bool:
    window = _term_window(text, match_text, radius=20)
    return any(
        marker in window
        for marker in (
            "이상",
            "초과",
            "넘는",
            "넘어",
            "보다 비싼",
            "보다 높은",
            "부터",
            "over",
            "above",
            "more than",
            "at least",
            "minimum",
            "min",
        )
    )


def _term_window(text: str, term: str, *, radius: int) -> str:
    index = normalize_token(text).find(normalize_token(term))
    if index < 0:
        index = text.find(term)
    if index < 0:
        return text
    return text[max(0, index - radius) : index + len(term) + radius]


def _dedupe(values: list[str]) -> None:
    seen: set[str] = set()
    values[:] = [item for item in values if not (item in seen or seen.add(item))]


def _infer_default_concerns(profile: SkinProfile) -> None:
    if profile.concerns or not profile.skin_type:
        return
    defaults = {
        "oily": ["oil_control"],
        "dry": ["hydration", "barrier_support"],
        "combination": ["oil_control", "hydration"],
    }
    profile.concerns.extend(defaults.get(profile.skin_type, []))
