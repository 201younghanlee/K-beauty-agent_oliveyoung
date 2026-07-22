from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from k_beauty_agent.agent import KBeautyAgent
from k_beauty_agent.database import ProductDatabase
from k_beauty_agent.live_products import ExternalProduct, LiveProductDatabase, OliveYoungSnapshotProvider

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_CSV = ROOT / "data" / "products_verified.csv"
REVIEWS_CSV = ROOT / "data" / "review_summaries.csv"


class FakeKeylessProvider:
    provider_name = "open_beauty_facts"

    def __init__(self, products: list[ExternalProduct]):
        self.products = products
        self.calls: list[dict[str, object]] = []

    def search(self, query: str, *, limit: int, min_price_usd: float | None, max_price_usd: float | None) -> list[ExternalProduct]:
        self.calls.append(
            {
                "query": query,
                "limit": limit,
                "min_price_usd": min_price_usd,
                "max_price_usd": max_price_usd,
            }
        )
        results = []
        for product in self.products:
            if min_price_usd is not None and (product.price is None or product.price < min_price_usd):
                continue
            if max_price_usd is not None and (product.price is None or product.price > max_price_usd):
                continue
            results.append(product)
        return results[:limit]


class FakeIngredientProvider:
    def __init__(self, ingredients: list[str] | None):
        self.ingredients = ingredients or []

    def ingredients_for(self, title: str, brand: str) -> list[str]:
        return list(self.ingredients)


class LiveProductDatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.tempdir.name) / "external_product_cache.sqlite3"
        self.fallback = ProductDatabase.from_csv(PRODUCTS_CSV, REVIEWS_CSV)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_fake_keyless_product_normalizes_to_existing_product_shape(self) -> None:
        provider = FakeKeylessProvider(
            [
                ExternalProduct(
                    provider="open_beauty_facts",
                    external_id="B0TEST",
                    title="COSRX Advanced Snail 96 Mucin Power Essence",
                    brand="COSRX",
                    price=18.5,
                    currency="USD",
                    image_url="https://example.com/cosrx.jpg",
                    detail_url="https://world.openbeautyfacts.org/product/B0TEST",
                    features=("Korean skincare essence",),
                )
            ]
        )
        db = LiveProductDatabase(
            self.fallback,
            cache_path=self.cache_path,
            providers=[provider],
            ingredient_provider=FakeIngredientProvider(["Snail Secretion Filtrate", "Betaine"]),
        )

        products = db.search("snail essence under $30", categories=["serum"], limit=5)

        self.assertTrue(products)
        product = products[0]
        self.assertTrue(product.id.startswith("open_beauty_facts-"))
        self.assertEqual(product.brand, "COSRX")
        self.assertEqual(product.price_usd, 18.5)
        self.assertEqual(product.image_source_type, "open_beauty_facts")
        self.assertEqual(
            product.official_url,
            "https://www.cosrx.com/products/advanced-snail-96-mucin-power-essence",
        )
        self.assertEqual(product.source_url, "https://world.openbeautyfacts.org/product/B0TEST")
        self.assertIsNone(product.oliveyoung_url)
        self.assertEqual(product.catalog_source, "open_beauty_facts")
        self.assertEqual(product.ingredient_status, "reported")
        self.assertIn("Snail Secretion Filtrate", product.ingredients)

    def test_krw_budget_is_converted_for_keyless_search_and_filtered(self) -> None:
        provider = FakeKeylessProvider(
            [
                ExternalProduct("open_beauty_facts", "LOW", "COSRX Low Price Korean Skincare Serum", "COSRX", 10.0, "USD", None, "https://world.openbeautyfacts.org/product/LOW"),
                ExternalProduct("open_beauty_facts", "HIGH", "COSRX High Price Korean Skincare Serum", "COSRX", 35.0, "USD", None, "https://world.openbeautyfacts.org/product/HIGH"),
            ]
        )
        db = LiveProductDatabase(
            self.fallback,
            cache_path=self.cache_path,
            providers=[provider],
            ingredient_provider=FakeIngredientProvider(["Niacinamide"]),
            krw_per_usd=1000,
        )

        products = db.search("3만원 이상의 제품 추천", limit=5)

        self.assertEqual(provider.calls[0]["min_price_usd"], 30.0)
        self.assertEqual([product.name for product in products], ["COSRX High Price Korean Skincare Serum"])
        self.assertGreaterEqual(products[0].oliveyoung_price_krw or 0, 30000)
        self.assertGreaterEqual(products[0].price_krw or 0, 30000)

    def test_cosing_empty_result_uses_curated_ingredient_match(self) -> None:
        provider = FakeKeylessProvider(
            [
                ExternalProduct(
                    "open_beauty_facts",
                    "BOJ",
                    "Beauty of Joseon Relief Sun Rice + Probiotics",
                    "Beauty of Joseon",
                    14.0,
                    "USD",
                    None,
                    "https://world.openbeautyfacts.org/product/BOJ",
                    features=("Korean skincare sunscreen",),
                )
            ]
        )
        db = LiveProductDatabase(
            self.fallback,
            cache_path=self.cache_path,
            providers=[provider],
            ingredient_provider=FakeIngredientProvider([]),
        )

        products = db.search("sunscreen under $20", categories=["sunscreen"], limit=5)

        self.assertTrue(products)
        self.assertIn("Niacinamide", products[0].ingredients)
        self.assertTrue(products[0].ingredient_source_url)

    def test_allergy_query_excludes_live_product_without_ingredients(self) -> None:
        provider = FakeKeylessProvider(
            [
                ExternalProduct(
                    "open_beauty_facts",
                    "UNKNOWN",
                    "Korean Skincare Mystery Serum",
                    "Unknown",
                    25.0,
                    "USD",
                    None,
                    "https://world.openbeautyfacts.org/product/UNKNOWN",
                    features=("Korean skincare serum",),
                )
            ]
        )
        db = LiveProductDatabase(
            self.fallback,
            cache_path=self.cache_path,
            providers=[provider],
            ingredient_provider=FakeIngredientProvider([]),
        )

        products = db.search("히알루론산 알러지 세럼", categories=["serum"], limit=5)

        self.assertTrue(products)
        self.assertNotIn("open_beauty_facts-unknown", {product.id for product in products})

    def test_empty_keyless_provider_falls_back_to_curated_database(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPEN_BEAUTY_FACTS_API_URL": "",
                "COSING_API_URL": "",
                "UNUSED_SECRET": "",
                "UNUSED_PARTNER": "",
            },
        ):
            db = LiveProductDatabase(self.fallback, cache_path=self.cache_path)

        products = db.search("선크림 20000원 이하 추천", categories=["sunscreen"], limit=5)

        self.assertTrue(products)
        self.assertTrue(all(not product.id.startswith("open_beauty_facts-") for product in products))
        self.assertEqual(db.last_source_status["source_used"], "curated_fallback")
        self.assertIn("Keyless live providers", db.last_source_status["message"])

    def test_agent_with_live_database_keeps_recommendation_response_shape(self) -> None:
        provider = FakeKeylessProvider(
            [
                ExternalProduct(
                    "open_beauty_facts",
                    "SUN",
                    "Beauty of Joseon Relief Sun Rice + Probiotics",
                    "Beauty of Joseon",
                    14.0,
                    "USD",
                    "https://example.com/sun.jpg",
                    "https://world.openbeautyfacts.org/product/SUN",
                    features=("Korean skincare SPF sunscreen",),
                )
            ]
        )
        db = LiveProductDatabase(
            self.fallback,
            cache_path=self.cache_path,
            providers=[provider],
            ingredient_provider=FakeIngredientProvider([]),
        )
        agent = KBeautyAgent(db)

        recommendation = agent.recommend("oily sunscreen under $30", limit=3)

        self.assertEqual(recommendation.decision, "recommend")
        self.assertTrue(recommendation.results)
        self.assertTrue(recommendation.results[0].product.id)
        self.assertTrue(recommendation.results[0].reasons)

    def test_live_database_exposes_source_status(self) -> None:
        provider = FakeKeylessProvider([])
        db = LiveProductDatabase(
            self.fallback,
            cache_path=self.cache_path,
            providers=[provider],
            ingredient_provider=FakeIngredientProvider([]),
        )

        db.search("sunscreen under $20", categories=["sunscreen"], limit=3)

        self.assertEqual(db.last_source_status["source_used"], "curated_fallback")
        self.assertEqual(db.last_source_status["product_source"], "live_keyless")

    def test_frontend_maps_open_beauty_facts_image_badge(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        index_html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn("openBeautyFactsImage", app_js)
        self.assertIn("open_beauty_facts: text(\"openBeautyFactsImage\")", app_js)
        self.assertIn("oliveyoungSnapshotImage", app_js)
        self.assertIn("oliveyoung_snapshot: text(\"oliveyoungSnapshotImage\")", app_js)
        self.assertIn("function reviewExcerpts(product", app_js)
        self.assertIn("positive_reviews", app_js)
        self.assertIn("negative_reviews", app_js)
        self.assertIn("20260720-commerce-v2", index_html)
        self.assertIn('id="offerModal"', index_html)
        self.assertIn('/api/v2/products/${encodeURIComponent(productId)}/offers', app_js)
        self.assertIn("offer.clickUrl", app_js)

    def test_oliveyoung_snapshot_csv_is_first_live_source_and_uses_krw_budget(self) -> None:
        snapshot_csv = Path(self.tempdir.name) / "oliveyoung_snapshot.csv"
        snapshot_csv.write_text(
            "\n".join(
                [
                    "product_name,brand,category,price_krw,oliveyoung_url,image_url,ingredients",
                    "COSRX Aloe Soothing Sun Cream,COSRX,sunscreen,18000,https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A1,https://image.oliveyoung.co.kr/a1.jpg,Aloe Barbadensis Leaf Extract|Niacinamide",
                    "COSRX Expensive Sun Cream,COSRX,sunscreen,42000,https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A2,,Niacinamide",
                ]
            ),
            encoding="utf-8",
        )
        provider = OliveYoungSnapshotProvider(csv_paths=[snapshot_csv], html_dir=Path(self.tempdir.name) / "missing")
        db = LiveProductDatabase(
            self.fallback,
            cache_path=self.cache_path,
            providers=[provider, FakeKeylessProvider([])],
            ingredient_provider=FakeIngredientProvider([]),
            krw_per_usd=1000,
        )

        products = db.search("선크림 3만원 이하", categories=["sunscreen"], limit=5)

        self.assertTrue(products)
        product = products[0]
        self.assertTrue(product.id.startswith("oliveyoung_snapshot-"))
        self.assertEqual(product.oliveyoung_price_krw, 18000)
        self.assertEqual(product.price_krw, 18000)
        self.assertEqual(product.purchase_url, product.oliveyoung_url)
        self.assertEqual(product.oliveyoung_url, "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A1")
        self.assertEqual(product.image_source_type, "oliveyoung_snapshot")
        self.assertEqual(db.last_source_status["source_used"], "oliveyoung_snapshot")
        self.assertGreaterEqual(db.cache.count_fresh("oliveyoung_snapshot"), 1)

    def test_oliveyoung_snapshot_csv_preserves_positive_and_negative_review_excerpts(self) -> None:
        snapshot_csv = Path(self.tempdir.name) / "oliveyoung_snapshot.csv"
        snapshot_csv.write_text(
            "\n".join(
                [
                    "product_name,brand,category,price_krw,oliveyoung_url,ingredients,positive_reviews,negative_reviews,positive_reviews_en,negative_reviews_en,review_source_url",
                    "Anua Heartleaf Test Serum,Anua,serum,22000,https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=R1,Houttuynia Cordata Extract,진정감이 좋았어요,끈적임이 조금 남아요,It felt calming,It stayed a little sticky,https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=R1#review",
                ]
            ),
            encoding="utf-8",
        )
        provider = OliveYoungSnapshotProvider(csv_paths=[snapshot_csv], html_dir=Path(self.tempdir.name) / "missing")
        db = LiveProductDatabase(
            self.fallback,
            cache_path=self.cache_path,
            providers=[provider],
            ingredient_provider=FakeIngredientProvider([]),
        )

        products = db.search("세럼", categories=["serum"], limit=5)

        self.assertTrue(products)
        self.assertEqual(products[0].positive_reviews, ("진정감이 좋았어요",))
        self.assertEqual(products[0].negative_reviews, ("끈적임이 조금 남아요",))
        self.assertEqual(products[0].positive_reviews_en, ("It felt calming",))
        self.assertEqual(products[0].negative_reviews_en, ("It stayed a little sticky",))
        self.assertEqual(products[0].review_source_url, "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=R1#review")

    def test_oliveyoung_snapshot_saved_html_imports_product_and_ignores_wait_page(self) -> None:
        html_dir = Path(self.tempdir.name) / "html"
        html_dir.mkdir()
        (html_dir / "product.html").write_text(
            """
            <html><head>
              <meta property="og:title" content="Anua Heartleaf 77 Clear Pad - 올리브영" />
              <meta property="og:image" content="//image.oliveyoung.co.kr/uploads/anua-pad.jpg" />
              <meta property="og:url" content="https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=P1" />
              <meta property="product:price:amount" content="26000" />
            </head><body></body></html>
            """,
            encoding="utf-8",
        )
        (html_dir / "wait.html").write_text(
            "<html><head><title>잠시만 기다려 주세요 - 올리브영</title></head><body>wait</body></html>",
            encoding="utf-8",
        )
        provider = OliveYoungSnapshotProvider(csv_paths=[], html_dir=html_dir)

        products = provider.search("toner pad under 30000", limit=5, min_price_usd=None, max_price_usd=30.0)

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].title, "Anua Heartleaf 77 Clear Pad")
        self.assertEqual(products[0].price, 26000)
        self.assertEqual(products[0].currency, "KRW")
        self.assertEqual(products[0].image_url, "https://image.oliveyoung.co.kr/uploads/anua-pad.jpg")
