from __future__ import annotations

from .models import Recommendation

Language = str

SKIN_KO = {
    "oily": "지성",
    "dry": "건성",
    "combination": "복합성",
    "sensitive": "민감성",
    "normal": "보통",
}

CONCERN_KO = {
    "oil_control": "유분 조절",
    "acne": "여드름",
    "clogged_pores": "막힌 모공",
    "exfoliation": "각질 관리",
    "hydration": "수분 보습",
    "barrier_support": "피부 장벽",
    "redness": "붉은기 진정",
    "hyperpigmentation": "잡티/색소",
    "anti_aging": "탄력/주름",
    "texture": "피부결",
    "dryness": "건조",
    "pores": "모공",
}

CATEGORY_KO = {
    "cleanser": "클렌저",
    "toner": "토너",
    "serum": "세럼",
    "moisturizer": "보습제",
    "sunscreen": "선크림",
    "basic": "기초 루틴",
}

TEXTURE_KO = {
    "dewy": "촉촉",
    "lightweight": "산뜻",
    "rich": "꾸덕/리치",
    "gel": "젤",
}

INGREDIENT_KO = {
    "niacinamide": "나이아신아마이드",
    "salicylic acid": "살리실산/BHA",
    "green tea extract": "녹차 추출물",
    "panthenol": "판테놀",
    "ceramide np": "세라마이드 NP",
    "glycerin": "글리세린",
    "hyaluronic acid": "히알루론산",
    "retinol": "레티놀",
    "azelaic acid": "아젤라익애씨드",
    "centella asiatica": "병풀/시카",
    "zinc pca": "징크 PCA",
    "fragrance": "향료",
}

COMPONENT_KO = {
    "ingredient_evidence": "성분 근거",
    "skin_fit": "피부 타입 적합도",
    "category_match": "제품군 일치",
    "review_confidence": "리뷰 신뢰도",
    "personalization": "개인화 반영",
    "penalties": "주의/감점",
}

MISSING_KO = {
    "ingredient list": "성분표",
    "rating/review count": "평점/리뷰 수",
    "price": "가격",
    "oliveyoung price": "올리브영 가격",
}

RATIONALE_KO = {
    "niacinamide": "피부 장벽 보조, 피지 조절, 톤 개선에 대한 인체 사용 근거가 있는 성분입니다.",
    "salicylic acid": "지성 및 여드름성 피부의 막힌 모공 관리에 널리 쓰이는 지용성 각질 관리 성분입니다.",
    "green tea extract": "진정, 항산화, 피지 관련 고민에 보조 근거가 있는 성분입니다.",
    "panthenol": "수분 유지와 피부 컨디셔닝에 흔히 쓰이는 보습 성분입니다.",
    "ceramide np": "피부 장벽 지질을 보충하는 데 적합한 성분입니다.",
    "glycerin": "다양한 피부 타입에 쓰이는 대표적인 보습 성분입니다.",
    "hyaluronic acid": "피부 수분감을 높이는 데 쓰이는 보습 성분입니다.",
    "retinol": "여드름, 피부결, 광노화 관련 고민에 강한 근거가 있으나 자극과 임신/수유 주의가 필요합니다.",
    "azelaic acid": "여드름, 붉은기, 고르지 않은 톤에 임상적으로 쓰이는 성분입니다.",
    "centella asiatica": "진정과 장벽 보조에 쓰이는 병풀 유래 성분입니다.",
    "zinc pca": "피지 고민 피부에 흔히 쓰이며 보조 근거가 있는 성분입니다.",
    "fragrance": "피부 관리상 필수 이점은 적고 민감 피부에는 자극 위험이 될 수 있습니다.",
}


def is_korean(language: Language | None) -> bool:
    return (language or "en").lower().startswith("ko")


def term(value: str, language: Language | None) -> str:
    if not is_korean(language):
        return value
    key = value.lower()
    return INGREDIENT_KO.get(key) or CONCERN_KO.get(key) or CATEGORY_KO.get(key) or SKIN_KO.get(key) or TEXTURE_KO.get(key) or value


def score_component_label(value: str, language: Language | None) -> str:
    if not is_korean(language):
        return value.replace("_", " ")
    return COMPONENT_KO.get(value, value)


def missing_label(value: str, language: Language | None) -> str:
    if not is_korean(language):
        return value
    return MISSING_KO.get(value, value)


def translate_reason(reason: str, language: Language | None) -> str:
    if not is_korean(language):
        return reason
    if reason.startswith("labeled as suitable for ") and reason.endswith(" skin"):
        skin = reason.removeprefix("labeled as suitable for ").removesuffix(" skin")
        return f"{term(skin, language)} 피부에 적합하다고 표시된 제품입니다."
    if reason.startswith("matches requested category: "):
        category = reason.removeprefix("matches requested category: ")
        return f"요청한 제품군({term(category, language)})과 일치합니다."
    if reason.startswith("product DB tags include "):
        concern = reason.removeprefix("product DB tags include ")
        return f"제품 DB 태그가 {term(concern, language)} 고민과 일치합니다."
    if reason == "claims to be fragrance-free for a lower-irritation routine":
        return "향료 프리 표시가 있어 저자극 루틴에 더 잘 맞습니다."
    if reason.startswith("matches gentle-routine signal: "):
        claims = reason.removeprefix("matches gentle-routine signal: ").split(", ")
        claim_text = ", ".join(
            {
                "fragrance free": "향료 프리",
                "minimal formula": "단순 처방",
                "soothing": "진정",
                "barrier support": "장벽 보조",
                "low ph": "저 pH",
            }.get(claim, claim)
            for claim in claims
        )
        return f"순한 루틴 신호와 일치합니다: {claim_text}."
    if reason == "lower listed price fits the budget follow-up":
        return "표기 가격이 낮아 예산을 고려한 후속 요청에 맞습니다."
    if reason == "lower Olive Young snapshot price fits the budget preference":
        return "올리브영 기준 스냅샷 가격이 낮아 예산 선호에 맞습니다."
    if reason == "lower checked price fits the budget preference":
        return "최근 확인된 가격이 낮아 예산 선호에 맞습니다."
    if reason.startswith("contains requested ingredient: "):
        ingredient = reason.removeprefix("contains requested ingredient: ")
        return f"후속 요청한 성분({term(ingredient, language)})을 포함합니다."
    if reason.startswith("listed price is within requested maximum: "):
        price = reason.removeprefix("listed price is within requested maximum: ")
        return f"표기 가격이 요청한 최대 가격({price}) 이내입니다."
    if reason.startswith("Olive Young snapshot price is within requested maximum: "):
        price = reason.removeprefix("Olive Young snapshot price is within requested maximum: ")
        return f"올리브영 스냅샷 가격이 요청한 최대 가격({price}) 이내입니다."
    if reason.startswith("checked price is within requested maximum: "):
        price = reason.removeprefix("checked price is within requested maximum: ")
        return f"최근 확인된 가격이 요청한 최대 가격({price}) 이내입니다."
    if reason.startswith("checked price is within requested minimum: "):
        price = reason.removeprefix("checked price is within requested minimum: ")
        return f"최근 확인된 가격이 요청한 최소 가격({price}) 이상입니다."
    if reason.startswith("matches requested texture preference: "):
        texture = reason.removeprefix("matches requested texture preference: ")
        return f"선호 제형({term(texture, language)})과 일치합니다."
    if " supports " in reason:
        ingredient, rest = reason.split(" supports ", 1)
        concerns = rest.split(" (", 1)[0].split(", ")
        evidence = rest.split("(", 1)[1].split(" evidence", 1)[0] if "(" in rest else ""
        concern_text = ", ".join(term(item, language) for item in concerns)
        evidence_text = {"high": "높은", "moderate": "중간", "low": "낮은"}.get(evidence, evidence)
        return f"{term(ingredient, language)} 성분이 {concern_text}에 도움될 수 있습니다({evidence_text} 근거)."
    if reason.startswith("personalization "):
        return "익명 세션의 liked/disliked 피드백을 보수적으로 반영했습니다."
    return reason


def translate_caution(caution: str, language: Language | None) -> str:
    if not is_korean(language):
        return caution
    # Match the more specific price messages before the generic
    # ``price is missing`` fragment. Otherwise a message such as
    # ``checked price is missing`` is partially translated and leaks the
    # internal word "checked" into Korean customer copy.
    replacements = {
        "DB suitability does not include": "제품 DB 적합 피부에 포함되지 않음:",
        "excluded because it contains avoided ingredient/allergy signal": "피해야 할 성분/알레르기 신호와 충돌:",
        "contains fragrance-like components, which are a poor fit for sensitive users": "향료 유사 성분은 민감성 피부에 맞지 않을 수 있습니다.",
        "retinoids are not recommended for pregnancy/nursing without clinician approval": "임신/수유 중 레티노이드는 전문가 확인 없이 추천하지 않습니다.",
        "salicylic acid conflicts with salicylate allergy": "살리실산은 살리실레이트 알레르기와 충돌합니다.",
        "can be less gentle for irritation-prone follow-ups": "자극을 줄이고 싶은 후속 요청에는 덜 순할 수 있습니다.",
        "does not contain requested ingredient": "후속 요청한 성분을 포함하지 않음",
        "excluded because this catalog record is for discovery only": "둘러보기 전용 상품이라 맞춤 추천에서 제외했습니다.",
        "excluded because the full ingredient list is not available": "전체 성분 정보가 없어 맞춤 추천에서 제외했습니다.",
        "ingredient data may be incomplete": "성분 정보가 불완전할 수 있습니다.",
        "ingredient data is community-reported; verify the current package before use": "커뮤니티가 등록한 성분 정보이므로 사용 전 현재 포장을 다시 확인해 주세요.",
        "checked price is missing, so cannot verify under": "최근 확인된 가격이 없어 최대 가격 조건을 확인할 수 없음:",
        "checked price is missing, so cannot verify over": "최근 확인된 가격이 없어 최소 가격 조건을 확인할 수 없음:",
        "Olive Young price is missing, so cannot verify under": "올리브영 가격 데이터가 없어 최대 가격 조건을 확인할 수 없음:",
        "price is missing, so cannot verify under": "가격 데이터가 없어 최대 가격 조건을 확인할 수 없음:",
        "excluded because listed price exceeds requested maximum": "표기 가격이 요청한 최대 가격을 초과해 제외:",
        "excluded because checked price exceeds requested maximum": "최근 확인된 가격이 요청한 최대 가격을 초과해 제외:",
        "excluded because checked price is below requested minimum": "최근 확인된 가격이 요청한 최소 가격보다 낮아 제외:",
        "excluded because Olive Young snapshot price exceeds requested maximum": "올리브영 스냅샷 가격이 요청한 최대 가격을 초과해 제외:",
        "product DB says avoid for": "제품 DB상 피해야 하는 조건:",
        "no recognized evidence-backed ingredient matched the user concern": "사용자 고민과 직접 매칭되는 근거 성분이 부족합니다.",
    }
    translated = caution
    for source, target in replacements.items():
        translated = translated.replace(source, target)
    return translated


def translate_evidence(evidence: str, language: Language | None) -> str:
    if not is_korean(language):
        return evidence
    ingredient = evidence.split(":", 1)[0].strip().lower()
    rationale = RATIONALE_KO.get(ingredient)
    if rationale:
        return f"{term(ingredient, language)}: {rationale}"
    return evidence


def format_recommendation_text(recommendation: Recommendation, language: Language | None = "en") -> str:
    if not is_korean(language):
        return recommendation.to_text()

    if recommendation.decision == "ask_more":
        questions = recommendation.profile.follow_up_questions or ["피부 타입, 주요 고민, 피해야 할 성분을 알려주세요."]
        return "추천 전에 정보가 조금 더 필요합니다.\n\n" + "\n".join(f"- {translate_question(q)}" for q in questions)

    lines: list[str] = []
    if recommendation.fallback_message:
        lines.append("현재 DB에서 충분한 근거 성분 매칭을 찾지 못했습니다.")
        lines.append("대안: 향료가 적은 단순 루틴으로 시작하고, 활성 성분은 피부 반응을 확인한 뒤 추가하세요.")

    constraints = []
    if recommendation.profile.preferred_ingredients:
        ingredients = ", ".join(term(value, language) for value in recommendation.profile.preferred_ingredients)
        constraints.append(f"선호 성분: {ingredients}")
    if recommendation.profile.max_price_usd is not None:
        constraints.append(f"최대 가격: ${recommendation.profile.max_price_usd:.2f}")
    if recommendation.profile.max_price_krw is not None:
        constraints.append(f"최대 가격: ₩{recommendation.profile.max_price_krw:,}")
    if recommendation.profile.texture_preference:
        constraints.append(f"선호 제형: {term(recommendation.profile.texture_preference, language)}")
    if constraints:
        lines.append("반영된 후속 조건")
        for constraint in constraints:
            lines.append(f"- {constraint}")
        lines.append("")

    if recommendation.results:
        lines.append("추천 제품")
        for index, item in enumerate(recommendation.results, start=1):
            product = item.product
            price = f", ${product.price_usd:.2f}" if product.price_usd is not None else ""
            lines.append("")
            lines.append(f"{index}. {product.name} / {product.brand} ({term(product.category, language)}{price})")
            lines.append(f"   점수: {item.score:.1f}")
            lines.append("   추천 이유:")
            for reason in item.reasons:
                lines.append(f"   - {translate_reason(reason, language)}")
            if item.matched_ingredients:
                ingredients = ", ".join(term(value, language) for value in item.matched_ingredients)
                lines.append(f"   근거 성분: {ingredients}")
            if item.cautions:
                lines.append("   주의점:")
                for caution in item.cautions:
                    lines.append(f"   - {translate_caution(caution, language)}")
            if item.missing_data:
                missing = ", ".join(missing_label(value, language) for value in item.missing_data)
                lines.append(f"   누락 데이터: {missing}")

    if recommendation.review_summary:
        lines.append("")
        lines.append("리뷰 요약")
        lines.append(translate_review_summary(recommendation.review_summary))

    lines.append("")
    lines.append("추천 기준")
    lines.append("- 성분과 근거 중심으로 추천하며 광고성 순위가 아닙니다.")
    lines.append("- 성분 정보가 부족한 제품은 감점하거나 제외합니다.")
    lines.append("- 특정 브랜드 편향을 줄이기 위해 브랜드 다양성을 반영합니다.")
    lines.append("- 화장품 선택 보조이며 의학적 진단이나 치료가 아닙니다.")
    return "\n".join(lines)


def translate_question(question: str) -> str:
    replacements = {
        "What is your skin type: oily, dry, combination, sensitive, or normal?": "피부 타입이 지성, 건성, 복합성, 민감성, 보통 중 어디에 가까운가요?",
        "What are your top concerns: oil control, acne, hydration, redness, pigmentation, or aging?": "가장 큰 고민은 유분, 여드름, 수분, 붉은기, 잡티, 탄력 중 무엇인가요?",
        "Do you react to fragrance, essential oils, alcohol, acids, or retinoids?": "향료, 에센셜오일, 알코올, 산 성분, 레티노이드에 민감하게 반응하나요?",
    }
    return replacements.get(question, question)


def translate_review_summary(summary: str) -> str:
    text = summary
    replacements = {
        "Analyzed": "분석한 리뷰 스니펫:",
        "DB review snippets across": "개, 대상 제품:",
        "product(s).": "개.",
        "Common positives:": "자주 언급된 장점:",
        "Common cautions:": "자주 언급된 주의점:",
        "Reviews did not contain enough known sentiment signals for a reliable summary.": "신뢰도 높은 리뷰 요약을 만들기에는 감성 신호가 부족합니다.",
        "lightweight": "가벼운 사용감",
        "hydrating": "보습감",
        "matte": "보송한 마무리",
        "absorbs": "빠른 흡수",
        "drying": "건조함",
        "stinging": "따가움",
        "gentle": "순함",
        "soothing": "진정감",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text
