from __future__ import annotations

from .knowledge_base import EVIDENCE_WEIGHT, find_evidence_for_ingredient, normalize_token
from .models import Product, ProductScore, SkinProfile

MIN_RECOMMENDATION_SCORE = 3.0
HARD_EXCLUSION_SCORE = -50.0
SAFETY_SENSITIVITIES = {"fragrance_sensitive", "gentle_preference"}


def needs_complete_ingredient_data(profile: SkinProfile) -> bool:
    return bool(
        profile.skin_type == "sensitive"
        or profile.avoid_ingredients
        or profile.allergies
        or profile.pregnant_or_nursing
        or SAFETY_SENSITIVITIES.intersection(profile.sensitivities)
    )


class IngredientHybridRecommender:
    """Rule-first recommender that exposes each scoring reason.

    The LLM layer should use this output as grounded context, not replace it.
    """

    def score_products(
        self,
        products: list[Product],
        profile: SkinProfile,
        personalization: dict[str, set[str]] | None = None,
    ) -> list[ProductScore]:
        scored = [self.score_product(product, profile, personalization=personalization) for product in products]
        viable = [item for item in scored if item.score >= MIN_RECOMMENDATION_SCORE]
        diverse = self._brand_diverse_sort(viable)
        return diverse

    def score_product(
        self,
        product: Product,
        profile: SkinProfile,
        personalization: dict[str, set[str]] | None = None,
    ) -> ProductScore:
        item = ProductScore(product=product, score=0.0)
        avoid_tokens = {normalize_token(value) for value in profile.avoid_ingredients + profile.allergies}
        product_ingredients = [normalize_token(value) for value in product.ingredients]
        preferred_ingredients = [normalize_token(value) for value in profile.preferred_ingredients]

        if product.recommendation_tier not in {"verified", "eligible"}:
            self._add(item, "penalties", -100.0)
            item.cautions.append("excluded because this catalog record is for discovery only")
        if product.ingredient_status != "complete":
            if needs_complete_ingredient_data(profile):
                self._add(item, "penalties", -100.0)
                item.cautions.append("excluded because the full ingredient list is not available")
            else:
                self._add(item, "penalties", -1.0)
                item.cautions.append("ingredient data is community-reported; verify the current package before use")

        if profile.skin_type and profile.skin_type in product.suited_skin_types:
            self._add(item, "skin_fit", 1.5)
            item.reasons.append(f"labeled as suitable for {profile.skin_type} skin")
        elif profile.skin_type and product.suited_skin_types:
            if profile.skin_type not in product.suited_skin_types:
                self._add(item, "penalties", -0.75)
                item.cautions.append(f"DB suitability does not include {profile.skin_type} skin")

        for category in profile.desired_categories:
            if category == "basic":
                if product.category in {"cleanser", "toner", "serum", "moisturizer", "sunscreen"}:
                    self._add(item, "category_match", 0.5)
            elif normalize_token(product.category) == normalize_token(category):
                self._add(item, "category_match", 1.0)
                item.reasons.append(f"matches requested category: {category}")

        for avoid in avoid_tokens:
            if not avoid:
                continue
            if any(_ingredient_matches(avoid, ingredient) or avoid in ingredient or ingredient in avoid for ingredient in product_ingredients):
                self._add(item, "penalties", -100.0)
                item.cautions.append(f"excluded because it contains avoided ingredient/allergy signal: {avoid}")

        for preferred in preferred_ingredients:
            if not preferred:
                continue
            if any(_ingredient_matches(preferred, ingredient) for ingredient in product_ingredients):
                self._add(item, "ingredient_evidence", 2.0)
                item.reasons.append(f"contains requested ingredient: {preferred}")
            else:
                self._add(item, "penalties", -100.0)
                item.cautions.append(f"does not contain requested ingredient: {preferred}")

        normalized_claims = {normalize_token(value) for value in product.claims}
        if "fragrance_sensitive" in profile.sensitivities and "fragrance free" in normalized_claims:
            self._add(item, "skin_fit", 0.75)
            item.reasons.append("claims to be fragrance-free for a lower-irritation routine")
        if "gentle_preference" in profile.sensitivities:
            gentle_claims = {"fragrance free", "minimal formula", "soothing", "barrier support", "low ph"}
            matched_claims = sorted(normalized_claims & gentle_claims)
            if matched_claims:
                self._add(item, "skin_fit", 0.5)
                item.reasons.append(f"matches gentle-routine signal: {', '.join(matched_claims)}")
        if (
            "budget_preference" in profile.sensitivities
            and profile.min_price_krw is None
            and profile.min_price_usd is None
            and profile.max_price_krw is None
            and profile.max_price_usd is None
        ):
            if product.price_krw is not None:
                budget_score = max(0.0, min(1.0, (40000.0 - product.price_krw) / 40000.0))
                if budget_score:
                    self._add(item, "personalization", budget_score)
                    item.reasons.append("lower checked price fits the budget preference")
            elif product.price_usd is None:
                item.missing_data.append("price")
            else:
                budget_score = max(0.0, min(1.0, (30.0 - product.price_usd) / 30.0))
                if budget_score:
                    self._add(item, "personalization", budget_score)
                    item.reasons.append("lower listed price fits the budget follow-up")
        if profile.max_price_krw is not None:
            if product.price_krw is None:
                self._add(item, "penalties", -1.0)
                item.missing_data.append("price")
                item.cautions.append(f"checked price is missing, so cannot verify under ₩{profile.max_price_krw:,}")
            elif product.price_krw <= profile.max_price_krw:
                self._add(item, "personalization", 3.0)
                item.reasons.append(f"checked price is within requested maximum: ₩{profile.max_price_krw:,}")
            else:
                self._add(item, "penalties", -100.0)
                item.cautions.append(f"excluded because checked price exceeds requested maximum: ₩{profile.max_price_krw:,}")
        if profile.min_price_krw is not None:
            if product.price_krw is None:
                self._add(item, "penalties", -1.0)
                item.missing_data.append("price")
                item.cautions.append(f"checked price is missing, so cannot verify over ₩{profile.min_price_krw:,}")
            elif product.price_krw >= profile.min_price_krw:
                self._add(item, "personalization", 3.0)
                item.reasons.append(f"checked price is within requested minimum: ₩{profile.min_price_krw:,}")
            else:
                self._add(item, "penalties", -100.0)
                item.cautions.append(f"excluded because checked price is below requested minimum: ₩{profile.min_price_krw:,}")
        if profile.max_price_usd is not None:
            if product.price_usd is None:
                self._add(item, "penalties", -1.0)
                item.missing_data.append("price")
                item.cautions.append(f"price is missing, so cannot verify under ${profile.max_price_usd:.2f}")
            elif product.price_usd <= profile.max_price_usd:
                self._add(item, "personalization", 3.0)
                item.reasons.append(f"listed price is within requested maximum: ${profile.max_price_usd:.2f}")
            else:
                self._add(item, "penalties", -100.0)
                item.cautions.append(f"excluded because listed price exceeds requested maximum: ${profile.max_price_usd:.2f}")
        if profile.min_price_usd is not None:
            if product.price_usd is None:
                self._add(item, "penalties", -1.0)
                item.missing_data.append("price")
                item.cautions.append(f"price is missing, so cannot verify over ${profile.min_price_usd:.2f}")
            elif product.price_usd >= profile.min_price_usd:
                self._add(item, "personalization", 3.0)
                item.reasons.append(f"listed price is within requested minimum: ${profile.min_price_usd:.2f}")
            else:
                self._add(item, "penalties", -100.0)
                item.cautions.append(f"excluded because listed price is below requested minimum: ${profile.min_price_usd:.2f}")

        if profile.texture_preference:
            texture_tags = {normalize_token(value) for value in product.texture_tags + product.claims}
            wanted_texture = normalize_token(profile.texture_preference)
            if wanted_texture in texture_tags:
                self._add(item, "skin_fit", 0.75)
                item.reasons.append(f"matches requested texture preference: {profile.texture_preference}")

        scored_evidence_names: set[str] = set()
        for ingredient in product.ingredients:
            evidence = find_evidence_for_ingredient(ingredient)
            if evidence is None or evidence.name in scored_evidence_names:
                continue
            scored_evidence_names.add(evidence.name)

            normalized_name = evidence.name
            matched_concerns = sorted(set(profile.concerns) & set(evidence.supports))
            skin_match = bool(profile.skin_type and profile.skin_type in evidence.suitable_for)
            if matched_concerns:
                weight = EVIDENCE_WEIGHT[evidence.evidence_level]
                self._add(item, "ingredient_evidence", weight * len(matched_concerns))
                item.matched_ingredients.append(normalized_name)
                item.evidence.append(f"{normalized_name}: {evidence.rationale}")
                item.reasons.append(
                    f"{normalized_name} supports {', '.join(matched_concerns)} "
                    f"({evidence.evidence_level} evidence)"
                )
            if skin_match:
                self._add(item, "skin_fit", 0.5)
            if evidence.name == "fragrance" and (profile.skin_type == "sensitive" or "fragrance_sensitive" in profile.sensitivities):
                self._add(item, "penalties", -3.0)
                item.cautions.append("contains fragrance-like components, which are a poor fit for sensitive users")
            if evidence.name in {"retinol", "salicylic acid"} and "gentle_preference" in profile.sensitivities:
                self._add(item, "penalties", -1.0)
                item.cautions.append(f"{evidence.name} can be less gentle for irritation-prone follow-ups")
            if evidence.name == "retinol" and profile.pregnant_or_nursing:
                self._add(item, "penalties", -100.0)
                item.cautions.append("retinoids are not recommended for pregnancy/nursing without clinician approval")
            if evidence.name == "salicylic acid" and "salicylate" in avoid_tokens:
                self._add(item, "penalties", -100.0)
                item.cautions.append("salicylic acid conflicts with salicylate allergy")

        for concern in profile.concerns:
            if concern in product.concerns:
                self._add(item, "ingredient_evidence", 0.75)
                item.reasons.append(f"product DB tags include {concern}")

        for flag in product.avoid_for:
            if (
                flag == profile.skin_type
                or flag in profile.concerns
                or flag in profile.sensitivities
                or flag in profile.allergies
                or flag in profile.avoid_ingredients
            ):
                self._add(item, "penalties", -2.0)
                item.cautions.append(f"product DB says avoid for {flag}")

        if not product.ingredients:
            self._add(item, "penalties", -2.0)
            item.missing_data.append("ingredient list")
        if product.rating is None or product.review_count is None:
            # Keep useful community catalog rows available, while preferring
            # products whose fit is supported by review evidence when scores
            # are otherwise close.
            self._add(item, "penalties", -0.75)
            item.missing_data.append("rating/review count")
        elif product.review_count > 0:
            self._add(item, "review_confidence", min(1.0, product.review_count / 2000.0))
        if not item.evidence and (profile.skin_type or profile.concerns or profile.preferred_ingredients):
            self._add(item, "penalties", -1.5)
            item.cautions.append("no recognized evidence-backed ingredient matched the user concern")

        self._apply_personalization(item, personalization)

        item.matched_ingredients = sorted(set(item.matched_ingredients))
        item.evidence = sorted(set(item.evidence))
        item.reasons = _dedupe(item.reasons)
        item.cautions = _dedupe(item.cautions)
        return item

    @staticmethod
    def _add(item: ProductScore, component: str, value: float) -> None:
        item.score += value
        item.score_components[component] = item.score_components.get(component, 0.0) + value

    def _apply_personalization(self, item: ProductScore, personalization: dict[str, set[str]] | None) -> None:
        if not personalization or item.score <= HARD_EXCLUSION_SCORE:
            return
        product = item.product
        adjustment = 0.0
        ingredients = {normalize_token(value) for value in product.ingredients}
        concerns = {normalize_token(value) for value in product.concerns}
        category = normalize_token(product.category)
        brand = normalize_token(product.brand)

        if product.id in personalization.get("liked_products", set()):
            adjustment += 0.5
        if product.id in personalization.get("disliked_products", set()):
            adjustment -= 1.5
        if brand in personalization.get("liked_brands", set()):
            adjustment += 0.25
        if brand in personalization.get("disliked_brands", set()):
            adjustment -= 0.5
        adjustment += 0.2 * len(ingredients & personalization.get("liked_ingredients", set()))
        adjustment -= 0.4 * len(ingredients & personalization.get("disliked_ingredients", set()))
        adjustment += 0.2 * len(concerns & personalization.get("liked_concerns", set()))
        adjustment -= 0.35 * len(concerns & personalization.get("disliked_concerns", set()))
        if category in personalization.get("liked_categories", set()):
            adjustment += 0.2
        if category in personalization.get("disliked_categories", set()):
            adjustment -= 0.35

        adjustment = max(-2.0, min(2.0, adjustment))
        if adjustment:
            self._add(item, "personalization", adjustment)
            direction = "boosted" if adjustment > 0 else "reduced"
            item.reasons.append(f"personalization {direction} score based on anonymous session feedback")

    @staticmethod
    def _brand_diverse_sort(items: list[ProductScore]) -> list[ProductScore]:
        ordered = sorted(items, key=lambda item: (-item.score, item.product.brand.lower(), item.product.name.lower()))
        selected: list[ProductScore] = []
        delayed: list[ProductScore] = []
        seen_brands: set[str] = set()
        for item in ordered:
            brand = item.product.brand.lower()
            if brand in seen_brands:
                delayed.append(item)
            else:
                selected.append(item)
                seen_brands.add(brand)
        return selected + delayed


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    return [item for item in values if not (item in seen or seen.add(item))]


def _ingredient_matches(preferred: str, product_ingredient: str) -> bool:
    preferred_evidence = find_evidence_for_ingredient(preferred)
    product_evidence = find_evidence_for_ingredient(product_ingredient)
    if preferred_evidence and product_evidence:
        return preferred_evidence.name == product_evidence.name
    return preferred in product_ingredient or product_ingredient in preferred
