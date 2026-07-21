from pathlib import Path
import unittest

from k_beauty_agent.agent import KBeautyAgent
from k_beauty_agent.database import ProductDatabase
from k_beauty_agent.models import SkinProfile
from k_beauty_agent.recommender import IngredientHybridRecommender
from k_beauty_agent.skin import analyze_skin_query

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sample_products.json"


class KBeautyAgentTest(unittest.TestCase):
    def test_korean_oily_basic_query_gets_oil_control_products(self) -> None:
        agent = KBeautyAgent.from_json(DB_PATH)
        recommendation = agent.recommend("지성 피부에 맞는 기초 제품을 추천해줘", limit=3)

        self.assertEqual(recommendation.decision, "recommend")
        self.assertTrue(recommendation.results)
        text = recommendation.to_text().lower()
        self.assertIn("oil_control", text)
        self.assertTrue(any("niacinamide" in item.matched_ingredients for item in recommendation.results))

    def test_sensitive_fragrance_query_downgrades_fragrant_product(self) -> None:
        db = ProductDatabase.from_json(DB_PATH)
        profile = analyze_skin_query("민감성 피부라 향료 없는 세럼을 추천해줘")
        recommender = IngredientHybridRecommender()
        products = db.search("serum", categories=["serum"], limit=10)
        scored = recommender.score_products(products, profile)

        names = [item.product.name for item in scored]
        self.assertNotIn("Fragrant Glow Serum", names)

    def test_insufficient_query_asks_questions(self) -> None:
        agent = KBeautyAgent.from_json(DB_PATH)
        recommendation = agent.recommend("추천해줘")

        self.assertEqual(recommendation.decision, "ask_more")
        self.assertGreaterEqual(len(recommendation.profile.follow_up_questions), 2)

    def test_pregnancy_excludes_retinol(self) -> None:
        db = ProductDatabase.from_json(DB_PATH)
        profile = SkinProfile(
            skin_type="oily",
            concerns=["anti_aging"],
            desired_categories=["serum"],
            pregnant_or_nursing=True,
        )
        recommender = IngredientHybridRecommender()
        products = db.search("retinol serum", categories=["serum"], concerns=["anti_aging"], limit=10)
        scored = recommender.score_products(products, profile)

        self.assertFalse(any(item.product.name == "Gentle Retinol Night Serum" for item in scored))


if __name__ == "__main__":
    unittest.main()
