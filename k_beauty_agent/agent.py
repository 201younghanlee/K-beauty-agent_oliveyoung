from __future__ import annotations

from pathlib import Path

from .database import ProductDatabase
from .llm import HybridExplainer, LLMClient
from .models import Recommendation
from .personalization import merge_profiles, profile_from_dict
from .recommender import IngredientHybridRecommender, needs_complete_ingredient_data
from .reviews import summarize_reviews
from .serializers import similarity_score
from .skin import analyze_skin_query


DEFAULT_GUARDRAILS = [
    "Recommendations are ingredient- and evidence-based, not paid placements.",
    "Products without enough ingredient data are downgraded or excluded.",
    "Brand diversity is applied after scoring to reduce brand bias.",
    "This is cosmetic guidance, not medical diagnosis or treatment.",
]
class KBeautyAgent:
    def __init__(self, database: ProductDatabase, llm_client: LLMClient | None = None):
        self.database = database
        self.recommender = IngredientHybridRecommender()
        self.explainer = HybridExplainer(llm_client)

    @classmethod
    def from_json(cls, path: str | Path, llm_client: LLMClient | None = None) -> "KBeautyAgent":
        return cls(ProductDatabase.from_json(path), llm_client=llm_client)

    @classmethod
    def from_csv(
        cls,
        products_path: str | Path,
        reviews_path: str | Path | None = None,
        llm_client: LLMClient | None = None,
    ) -> "KBeautyAgent":
        return cls(ProductDatabase.from_csv(products_path, reviews_path), llm_client=llm_client)

    def answer(self, query: str, *, limit: int = 3, use_llm: bool = False) -> str:
        recommendation = self.recommend(query, limit=limit)
        if use_llm:
            return self.explainer.explain(recommendation)
        return recommendation.to_text()

    def recommend(
        self,
        query: str,
        *,
        limit: int = 3,
        stored_profile: dict | None = None,
        recent_queries: list[str] | None = None,
        personalization: dict[str, set[str]] | None = None,
        structured_profile: dict | None = None,
    ) -> Recommendation:
        if structured_profile is not None:
            profile = profile_from_dict(structured_profile)
            profile_concerns = _ordered_concerns(profile)
            search_query = " ".join(
                [*profile.desired_categories, *profile_concerns]
            )
        else:
            profile = merge_profiles(stored_profile, query, recent_queries) if stored_profile or recent_queries else analyze_skin_query(query)
            profile_concerns = _ordered_concerns(profile)
            search_query = query
        if not profile.has_minimum_signal:
            return Recommendation(
                decision="ask_more",
                query=query,
                profile=profile,
                guardrails=DEFAULT_GUARDRAILS,
            )

        candidates = self.database.search(
            search_query,
            categories=profile.desired_categories,
            concerns=profile_concerns,
            ingredients=None,
            exclude_ingredients=[*profile.avoid_ingredients, *profile.allergies],
            require_complete_ingredients=needs_complete_ingredient_data(profile),
            limit=None,
        )
        if not candidates and not profile.desired_categories:
            candidates = self.database.search(limit=None)
        scored = self.recommender.score_products(candidates, profile, personalization=personalization)
        top = scored[:limit]

        if not top:
            profile.follow_up_questions.extend(
                [
                    "Which cosmetic ingredient names, if any, do you prefer to avoid?",
                    "Which product form are you looking for—for example cleanser, toner, serum, moisturizer, sunscreen, face mask, body wash/body lotion/body scrub, shampoo/conditioner/hair treatment, or base makeup/eye makeup/lip makeup?",
                ]
            )
            return Recommendation(
                decision="fallback",
                query=query,
                profile=profile,
                fallback_message=(
                    "I could not find a product with enough evidence-backed ingredient matches in the current DB. "
                    "Fallback: use a simple, fragrance-free routine and add actives only after confirming tolerance."
                ),
                guardrails=DEFAULT_GUARDRAILS,
            )

        for item in top:
            item.similar_products = self.similar_products(item.product, profile, limit=5)

        return Recommendation(
            decision="recommend",
            query=query,
            profile=profile,
            results=top,
            fallback_message=None,
            review_summary=summarize_reviews([item.product for item in top]),
            guardrails=DEFAULT_GUARDRAILS,
        )

    def similar_products(self, product, profile, *, limit: int = 5):
        similar_candidates = self.database.search(
            categories=[product.category],
            concerns=_ordered_concerns(profile),
            ingredients=None,
            exclude_ingredients=[*profile.avoid_ingredients, *profile.allergies],
            require_complete_ingredients=needs_complete_ingredient_data(profile),
            limit=None,
        )
        safe_scores = self.recommender.score_products(similar_candidates, profile)
        safe_ids = {item.product.id for item in safe_scores}
        candidates = [
            candidate
            for candidate in similar_candidates
            if candidate.id != product.id and candidate.id in safe_ids
        ]
        scored = [(similarity_score(product, candidate), candidate) for candidate in candidates]
        scored = [item for item in scored if item[0] > 0]
        scored.sort(key=lambda item: (-item[0], item[1].brand.lower(), item[1].name.lower()))
        selected = []
        seen_brands = set()
        delayed = []
        for _, candidate in scored:
            brand = candidate.brand.lower()
            if brand in seen_brands:
                delayed.append(candidate)
            else:
                selected.append(candidate)
                seen_brands.add(brand)
        return (selected + delayed)[:limit]


def _ordered_concerns(profile) -> list[str]:
    ordered: list[str] = []
    for concern in [profile.primary_concern, *profile.concerns]:
        if concern and concern not in ordered:
            ordered.append(concern)
    return ordered
