from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from k_beauty_agent.agent import KBeautyAgent
from k_beauty_agent.config import admin_token, session_secret
from k_beauty_agent.database import ProductDatabase
from k_beauty_agent.followup_parser import parse_follow_up_patch, sanitize_profile_patch
from k_beauty_agent.knowledge_base import find_evidence_for_ingredient
from k_beauty_agent.personalization import (
    apply_profile_patch,
    build_personalization,
    merge_profiles,
    profile_from_dict,
    profile_to_dict,
)
from k_beauty_agent.recommender import IngredientHybridRecommender
from k_beauty_agent.serializers import product_to_dict
from k_beauty_agent.storage import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_CSV = ROOT / "data" / "products_verified.csv"
REVIEWS_CSV = ROOT / "data" / "review_summaries.csv"


class FakeCompletionClient:
    def __init__(self, text: str):
        self.text = text
        self.system = ""
        self.user = ""

    def complete(self, system: str, user: str) -> str:
        self.system = system
        self.user = user
        return self.text


class PersonalizedServiceUnitTest(unittest.TestCase):
    def test_session_profile_merge_prioritizes_recent_query(self) -> None:
        stored = profile_to_dict(merge_profiles(None, "dry skin hydration cream", []))
        merged = merge_profiles(stored, "지성 피부에 맞는 가벼운 토너", ["dry skin hydration cream"])

        self.assertEqual(merged.skin_type, "oily")
        self.assertIn("hydration", merged.concerns)
        self.assertIn("oil_control", merged.concerns)

    def test_follow_up_preference_keeps_context_and_adds_gentle_signals(self) -> None:
        stored = profile_to_dict(merge_profiles(None, "지성 피부에 맞는 기초 제품을 추천해줘", []))
        merged = merge_profiles(stored, "그럼 더 순하고 저렴한 걸로 바꿔줘", ["지성 피부에 맞는 기초 제품을 추천해줘"])

        self.assertEqual(merged.skin_type, "oily")
        self.assertIn("oil_control", merged.concerns)
        self.assertIn("barrier_support", merged.concerns)
        self.assertIn("gentle_preference", merged.sensitivities)
        self.assertIn("budget_preference", merged.sensitivities)
        self.assertEqual(merged.uncertainty, [])

    def test_follow_up_ingredient_and_price_constraints_are_applied(self) -> None:
        agent = KBeautyAgent.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        first = agent.recommend("지성 피부에 맞는 기초 제품을 추천해줘", limit=3)
        follow_up = agent.recommend(
            "나이아신아마이드 성분 들어간 20달러 이하 제품으로 바꿔줘",
            limit=5,
            stored_profile=profile_to_dict(first.profile),
            recent_queries=["지성 피부에 맞는 기초 제품을 추천해줘"],
        )

        self.assertEqual(follow_up.profile.max_price_usd, 20.0)
        self.assertIn("niacinamide", follow_up.profile.preferred_ingredients)
        self.assertTrue(follow_up.results)
        for item in follow_up.results:
            self.assertIsNotNone(item.product.price_usd)
            self.assertLessEqual(item.product.price_usd, 20.0)
        self.assertIn(
            "niacinamide",
            " ".join(follow_up.results[0].product.ingredients).lower(),
        )

    def test_legacy_sensitive_skin_type_migrates_to_separate_sensitivity_axis(self) -> None:
        stored = profile_from_dict({"skin_type": "sensitive", "concerns": ["redness"]})
        patch = sanitize_profile_patch({"skin_type": "sensitive"})
        explicit_patch = sanitize_profile_patch(
            {"skin_type": "sensitive", "sensitivity_level": "occasional"}
        )

        self.assertEqual(stored.skin_type, "unknown")
        self.assertEqual(stored.sensitivity_level, "frequent")
        self.assertEqual(patch["skin_type"], "unknown")
        self.assertEqual(patch["sensitivity_level"], "frequent")
        self.assertEqual(explicit_patch["skin_type"], "unknown")
        self.assertEqual(explicit_patch["sensitivity_level"], "occasional")

    def test_follow_up_product_category_replaces_previous_category(self) -> None:
        stored = profile_to_dict(merge_profiles(None, "지성 피부 선크림 추천", []))
        merged = merge_profiles(stored, "히알루론산 빼고 3만원 이상의 산뜻한 세럼으로 바꿔줘", ["지성 피부 선크림 추천"])

        self.assertEqual(merged.skin_type, "oily")
        self.assertEqual(merged.desired_categories, ["serum"])
        self.assertEqual(merged.min_price_krw, 30000)
        self.assertIn("hyaluronic acid", merged.avoid_ingredients)
        self.assertEqual(merged.texture_preference, "lightweight")

    def test_korean_follow_up_variants_are_understood(self) -> None:
        stored = profile_to_dict(merge_profiles(None, "지성 피부에 맞는 기초 제품을 추천해줘", []))
        phrases = [
            "자극 없는 걸로 바꿔줘",
            "가격 낮은 제품으로 다시 추천해줘",
            "비싸지 않고 순한 제품으로 보여줘",
        ]

        merged = merge_profiles(stored, " ".join(phrases), ["지성 피부에 맞는 기초 제품을 추천해줘"])

        self.assertEqual(merged.skin_type, "oily")
        self.assertIn("gentle_preference", merged.sensitivities)
        self.assertIn("budget_preference", merged.sensitivities)
        self.assertIn("barrier_support", merged.concerns)

    def test_llm_follow_up_patch_can_extend_profile_safely(self) -> None:
        stored = profile_to_dict(merge_profiles(None, "지성 피부에 맞는 기초 제품을 추천해줘", []))
        client = FakeCompletionClient(
            '{"desired_categories":["serum"],"min_price_krw":30000,'
            '"avoid_ingredients":["hyaluronic acid"],"texture_preference":"lightweight"}'
        )

        patch = parse_follow_up_patch(
            "히알루론산 빼고 3만원 이상의 산뜻한 세럼으로 바꿔줘",
            stored_profile=stored,
            recent_queries=["지성 피부에 맞는 기초 제품을 추천해줘"],
            client=client,
            language="ko",
        )
        enriched = apply_profile_patch(stored, patch)
        merged = merge_profiles(enriched, "히알루론산 빼고 3만원 이상의 산뜻한 세럼으로 바꿔줘", [])

        self.assertEqual(merged.skin_type, "oily")
        self.assertIn("serum", merged.desired_categories)
        self.assertEqual(merged.min_price_krw, 30000)
        self.assertIn("hyaluronic acid", merged.avoid_ingredients)
        self.assertEqual(merged.texture_preference, "lightweight")

    def test_llm_follow_up_patch_rejects_unknown_control_fields(self) -> None:
        patch = sanitize_profile_patch(
            {
                "skin_type": "dragon",
                "desired_categories": ["sunscreen", "injectable"],
                "concerns": ["oil_control", "medical_diagnosis"],
                "avoid_ingredients": ["hyaluronic acid<script>", "niacinamide"],
                "max_price_krw": 999999999,
                "min_price_krw": 30000,
                "delete_all_filters": True,
            }
        )

        self.assertNotIn("skin_type", patch)
        self.assertEqual(patch["desired_categories"], ["sunscreen"])
        self.assertEqual(patch["concerns"], ["oil_control"])
        self.assertEqual(patch["avoid_ingredients"], ["hyaluronic acid", "niacinamide"])
        self.assertNotIn("max_price_krw", patch)
        self.assertEqual(patch["min_price_krw"], 30000)
        self.assertNotIn("delete_all_filters", patch)

    def test_quiz_texture_and_krw_budget_are_understood(self) -> None:
        merged = merge_profiles(None, "지성 피부, 선크림 추천, 주요 고민은 유분, 산뜻 제형 선호, 20000원 이하", [])

        self.assertEqual(merged.skin_type, "oily")
        self.assertIn("sunscreen", merged.desired_categories)
        self.assertNotIn("moisturizer", merged.desired_categories)
        self.assertIn("oil_control", merged.concerns)
        self.assertEqual(merged.texture_preference, "lightweight")
        self.assertEqual(merged.max_price_krw, 20000)
        self.assertIn("budget_preference", merged.sensitivities)

    def test_sunscreen_text_does_not_match_generic_moisturizer_cream(self) -> None:
        sunscreen = merge_profiles(None, "선크림 20000원 이하 추천", [])
        moisturizer = merge_profiles(None, "수분크림 20000원 이하 추천", [])

        self.assertEqual(sunscreen.desired_categories, ["sunscreen"])
        self.assertIn("moisturizer", moisturizer.desired_categories)

    def test_korean_budget_phrases_are_understood_as_price_limits(self) -> None:
        cases = [
            "예산 20000원 제품 추천",
            "가격은 20,000원 제품 추천",
            "2만원대 제품 추천",
            "만원 이하 제품 추천",
        ]

        expected = [20000, 20000, 20000, 10000]
        for query, max_price in zip(cases, expected, strict=True):
            with self.subTest(query=query):
                merged = merge_profiles(None, query, [])
                self.assertEqual(merged.max_price_krw, max_price)
                self.assertIn("budget_preference", merged.sensitivities)

    def test_krw_budget_filters_against_oliveyoung_snapshot_price(self) -> None:
        agent = KBeautyAgent.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        recommendation = agent.recommend("지성 피부 선크림 유분 산뜻 20000원 이하", limit=5)

        self.assertTrue(recommendation.results)
        for item in recommendation.results:
            self.assertIsNotNone(item.product.oliveyoung_price_krw)
            self.assertLessEqual(item.product.oliveyoung_price_krw, 20000)

    def test_budget_only_query_returns_only_products_under_krw_limit(self) -> None:
        agent = KBeautyAgent.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        recommendation = agent.recommend("예산 20000원 제품 추천", limit=5)

        self.assertEqual(recommendation.profile.max_price_krw, 20000)
        self.assertTrue(recommendation.results)
        for item in recommendation.results:
            self.assertIsNotNone(item.product.oliveyoung_price_krw)
            self.assertLessEqual(item.product.oliveyoung_price_krw, 20000)

    def test_krw_minimum_budget_query_returns_only_products_over_limit(self) -> None:
        agent = KBeautyAgent.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        recommendation = agent.recommend("3만원 이상의 제품 추천", limit=5)

        self.assertIsNone(recommendation.profile.max_price_krw)
        self.assertEqual(recommendation.profile.min_price_krw, 30000)
        self.assertTrue(recommendation.results)
        for item in recommendation.results:
            self.assertIsNotNone(item.product.oliveyoung_price_krw)
            self.assertGreaterEqual(item.product.oliveyoung_price_krw, 30000)

    def test_krw_budget_range_applies_minimum_and_maximum(self) -> None:
        agent = KBeautyAgent.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        recommendation = agent.recommend("2만원 이상 4만원 이하 제품 추천", limit=5)

        self.assertEqual(recommendation.profile.min_price_krw, 20000)
        self.assertEqual(recommendation.profile.max_price_krw, 40000)
        self.assertTrue(recommendation.results)
        for item in recommendation.results:
            self.assertIsNotNone(item.product.oliveyoung_price_krw)
            self.assertGreaterEqual(item.product.oliveyoung_price_krw, 20000)
            self.assertLessEqual(item.product.oliveyoung_price_krw, 40000)

    def test_korean_allergy_blocks_matching_ingredient_from_full_ingredient_list(self) -> None:
        agent = KBeautyAgent.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        recommendation = agent.recommend("지성 피부 선크림 추천, 히알루론산 알러지라 피하고 싶어", limit=5)

        self.assertIn("hyaluronic acid", recommendation.profile.avoid_ingredients)
        self.assertTrue(recommendation.results)
        for item in recommendation.results:
            ingredients = " ".join(item.product.ingredients).lower()
            self.assertNotIn("hyaluronic", ingredients)
            self.assertNotIn("sodium hyaluronate", ingredients)

    def test_expanded_allergy_aliases_are_understood(self) -> None:
        agent = KBeautyAgent.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        cases = [
            ("어성초 알레르기 있어서 토너 추천", "houttuynia cordata", ["Houttuynia Cordata"]),
            ("마데카소사이드 알러지 수분 패드 추천", "madecassoside", ["Madecassoside"]),
            ("라벤더오일 알러지 토너 추천", "fragrance", ["Lavender Oil"]),
            ("비피다 알러지 세럼 추천", "bifida ferment", ["Bifida Ferment"]),
            ("프로폴리스 알러지 세럼 추천", "propolis", ["Propolis"]),
        ]

        for query, blocked, blocked_terms in cases:
            with self.subTest(query=query):
                recommendation = agent.recommend(query, limit=5)
                self.assertIn(blocked, recommendation.profile.avoid_ingredients)
                for item in recommendation.results:
                    ingredients = " ".join(item.product.ingredients)
                    for term in blocked_terms:
                        self.assertNotIn(term, ingredients)

    def test_allergy_exclusion_removes_matching_products_without_empty_results(self) -> None:
        agent = KBeautyAgent.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        recommendation = agent.recommend("지성 피부 선크림 추천, 나이아신아마이드 알러지라 피하고 싶어", limit=5)

        self.assertIn("niacinamide", recommendation.profile.avoid_ingredients)
        self.assertTrue(recommendation.results)
        for item in recommendation.results:
            ingredients = " ".join(item.product.ingredients).lower()
            self.assertNotIn("niacinamide", ingredients)

    def test_product_serializer_exposes_commerce_and_ingredient_modal_fields(self) -> None:
        db = ProductDatabase.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        product = db.get("beauty-of-joseon-relief-sun-rice-probiotics")
        self.assertIsNotNone(product)

        data = product_to_dict(product)

        self.assertIn("image_url", data)
        self.assertIn("display_name_ko", data)
        self.assertEqual(data["display_name_ko"], "조선미녀 맑은쌀 선크림")
        self.assertEqual(data["image_source_type"], "official")
        self.assertEqual(data["image_confidence"], "verified")
        self.assertIn(data["image_view_type"], {"single_product", "verified_product"})
        self.assertTrue(data["image_verified_source"])
        self.assertIn("oliveyoung_url", data)
        self.assertIn("oliveyoung_price_krw", data)
        self.assertIn("official_url", data)
        self.assertIsNone(data["review_summary_en"])
        self.assertEqual(data["positive_reviews"], [])
        self.assertEqual(data["negative_reviews"], [])
        self.assertEqual(data["positive_reviews_en"], [])
        self.assertEqual(data["negative_reviews_en"], [])
        self.assertIsNone(data["rating"])
        self.assertIsNone(data["review_count"])
        self.assertIn("review_source_url", data)
        self.assertIn("ingredient_explanations", data)
        self.assertTrue(data["ingredient_explanations"])

    def test_product_image_metadata_policy(self) -> None:
        db = ProductDatabase.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        source_types = {product.image_source_type for product in db.products}

        self.assertIn("glowpick", source_types)
        for product in db.products:
            image_url = product.image_url or ""
            self.assertNotIn("placehold.co", image_url)
            self.assertNotIn("product-placeholder", image_url)
            self.assertIn(product.image_source_type, {"official", "hwahae", "glowpick", "retailer", "none"})
            self.assertIn(product.image_view_type, {"single_product", "verified_product", "none"})
            if product.image_source_type in {"official", "hwahae", "glowpick", "retailer"}:
                self.assertTrue(product.image_url, product.id)
                self.assertTrue(product.image_verified_source, product.id)
                self.assertEqual(product.image_confidence, "verified", product.id)
                self.assertIn(product.image_view_type, {"single_product", "verified_product"}, product.id)
            if product.image_source_type == "none":
                self.assertIsNone(product.image_url, product.id)
                self.assertIsNone(product.image_verified_source, product.id)
                self.assertIsNone(product.image_confidence, product.id)
                self.assertEqual(product.image_view_type, "none", product.id)

    def test_verified_product_database_quality_floor(self) -> None:
        db = ProductDatabase.from_csv(PRODUCTS_CSV, REVIEWS_CSV)

        self.assertGreaterEqual(len(db.products), 50)
        for product in db.products:
            self.assertTrue(product.id)
            self.assertTrue(product.name)
            self.assertTrue(product.display_name_ko, product.id)
            self.assertTrue(product.ingredients, product.id)
            self.assertTrue(product.category, product.id)
            self.assertTrue(product.concerns, product.id)
            self.assertTrue(product.source_url, product.id)
            self.assertTrue(product.ingredient_source_url, product.id)
            self.assertTrue(product.verified_at, product.id)
            self.assertTrue(product.review_summary, product.id)
            self.assertTrue(product.review_summary_en, product.id)
            self.assertIn(product.image_source_type, {"official", "hwahae", "glowpick", "retailer", "none"})
            self.assertIn(product.image_view_type, {"single_product", "verified_product", "none"})
            if product.image_source_type in {"official", "hwahae", "glowpick", "retailer"}:
                self.assertTrue(product.image_url, product.id)
                self.assertTrue(product.image_verified_source, product.id)
                self.assertEqual(product.image_confidence, "verified", product.id)
                self.assertIn(product.image_view_type, {"single_product", "verified_product"}, product.id)

    def test_expanded_database_returns_depth_by_core_category(self) -> None:
        db = ProductDatabase.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        categories = ["sunscreen", "serum", "moisturizer", "cleanser", "toner"]

        for category in categories:
            with self.subTest(category=category):
                products = db.search(categories=[category], limit=10)
                self.assertGreaterEqual(len(products), 5)

    def test_allergy_filters_cover_expanded_ingredient_database(self) -> None:
        agent = KBeautyAgent.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        cases = [
            ("히알루론산 알러지 수분 선크림 추천", ["hyaluronic", "sodium hyaluronate"]),
            ("나이아신아마이드 알러지 수분 세럼 추천", ["niacinamide"]),
            ("달팽이 알러지 수분 세럼 추천", ["snail"]),
            ("티트리 알러지 수분 클렌저 추천", ["tea tree"]),
        ]

        for query, blocked_terms in cases:
            with self.subTest(query=query):
                recommendation = agent.recommend(query, limit=5)
                self.assertTrue(recommendation.results)
                for item in recommendation.results:
                    ingredients = " ".join(item.product.ingredients).lower()
                    for term in blocked_terms:
                        self.assertNotIn(term, ingredients)

    def test_hwahae_image_metadata_serializes_when_public_fallback_exists(self) -> None:
        product = ProductDatabase.from_csv(PRODUCTS_CSV, REVIEWS_CSV).products[0]
        hwahae_product = product.__class__(
            **{
                **product.__dict__,
                "image_url": "https://www.hwahae.co.kr/product-image/example.jpg",
                "image_verified_source": "https://www.hwahae.co.kr/search?q=example",
                "image_source_type": "hwahae",
                "image_confidence": "verified",
                "image_view_type": "single_product",
            }
        )

        data = product_to_dict(hwahae_product)

        self.assertEqual(data["image_source_type"], "hwahae")
        self.assertEqual(data["image_confidence"], "verified")
        self.assertEqual(data["image_view_type"], "single_product")
        self.assertTrue(data["image_url"])
        self.assertTrue(data["image_verified_source"])

    def test_frontend_does_not_use_placeholder_image_fallbacks(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("이미지 없음", (ROOT / "static" / "styles.css").read_text(encoding="utf-8"))
        self.assertNotIn("fallbackImage", app_js)
        self.assertNotIn("product-placeholder.svg", app_js)
        self.assertNotIn("placehold.co", app_js)
        self.assertNotIn('class="score"', app_js)
        self.assertNotIn(".score", (ROOT / "static" / "styles.css").read_text(encoding="utf-8"))

    def test_public_quiz_exposes_expanded_product_forms(self) -> None:
        index_html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

        for value in (
            "마스크팩",
            "아이케어",
            "립케어",
            "각질 제거",
            "바디워시",
            "바디로션",
            "바디스크럽",
            "샴푸",
            "컨디셔너",
            "트리트먼트",
            "베이스 메이크업",
            "아이 메이크업",
            "립 메이크업",
        ):
            self.assertIn(f'name="productType" value="{value}"', index_html)
        for category in (
            "body_cleanser",
            "body_moisturizer",
            "body_exfoliator",
            "shampoo",
            "conditioner",
            "hair_treatment",
            "base_makeup",
            "eye_makeup",
            "lip_makeup",
        ):
            self.assertIn(f"{category}:", app_js)

    def test_frontend_localization_and_compare_auto_update_hooks(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("const valueLabels = {", app_js)
        self.assertIn("ko: {", app_js)
        self.assertIn("en: {", app_js)
        self.assertIn('text("compareStandard")', app_js)
        self.assertIn("function reviewSummary(product, emptyKey)", app_js)
        self.assertIn("function cleanReviewSummary(summary)", app_js)
        self.assertIn("큐레이션 리뷰 신호", app_js)
        self.assertIn("Curated review signal", app_js)
        self.assertIn('if (listType === "compare" || !document.querySelector("#compareTable").classList.contains("hidden")) renderCompareTable();', app_js)
        self.assertIn('const LANGUAGE_STORAGE_KEY = "kBeautyAgentLanguage";', app_js)
        self.assertIn("function readStoredLanguage()", app_js)
        self.assertIn("function storeLanguage(lang)", app_js)
        self.assertIn("window.localStorage?.setItem(LANGUAGE_STORAGE_KEY, lang)", app_js)
        self.assertIn("renderCompareSummary();\n  renderCompareTable();\n  renderCatalogs();", app_js)
        self.assertIn("function parseCommand(query)", app_js)
        self.assertIn("resetCriteria", app_js)
        self.assertIn('addCurrentResultsToSelection("compare")', app_js)
        self.assertIn('addCurrentResultsToSelection("saved")', app_js)
        self.assertIn('await apiJson("/api/profile", { method: "DELETE" })', app_js)
        self.assertIn('const API_BASE_URL = "";', app_js)
        self.assertNotIn("RENDER_API_BASE_URL", app_js)
        self.assertIn('credentials: "omit"', app_js)
        self.assertIn('"X-KBeauty-Session": getAnonymousSessionToken()', app_js)
        self.assertIn("function rotateAnonymousSessionToken()", app_js)
        self.assertNotIn('credentials: "include"', app_js)
        self.assertNotIn("IS_STATIC_DEMO", app_js)
        self.assertIn("state.currentResults = normalizeRecommendationItems(data.results)", app_js)
        self.assertIn('const path = isFollowUp ? "/api/v2/follow-up" : "/api/v2/recommend";', app_js)
        self.assertIn("function normalizeOffer(raw, index = 0)", app_js)
        self.assertIn("offer.clickUrl", app_js)
        self.assertIn("item.personalized_reason", app_js)
        self.assertIn("glowpick: text(\"glowpickImage\")", app_js)
        self.assertIn("retailer: text(\"retailerImage\")", app_js)
        self.assertIn("function displayProductName(product)", app_js)
        self.assertIn("function displayIngredient(ingredient)", app_js)
        self.assertIn("function displayIngredients(ingredients, limit = 8)", app_js)
        self.assertIn("displayProductName(product)", app_js)
        self.assertIn("displayIngredients(product.ingredients, 8)", app_js)
        self.assertIn('blockedIngredients: "차단 성분"', app_js)
        self.assertIn('blockedIngredients: "Blocked ingredients"', app_js)
        self.assertIn("blocked-ingredients", app_js)
        self.assertIn('oliveyoung: "Olive Young"', app_js)
        self.assertIn('official: "브랜드 공식몰"', app_js)
        self.assertIn("function backendRedirectUrl(value)", app_js)
        self.assertIn('parsed.origin !== apiOrigin || !parsed.pathname.startsWith("/r/")', app_js)
        self.assertIn('href="${escapeHtml(offer.clickUrl)}"', app_js)
        self.assertIn('rel="nofollow sponsored noreferrer"', app_js)
        self.assertNotIn("const koreanOfficialMallByBrand = {", app_js)
        self.assertNotIn("function globalOliveYoungUrl(product)", app_js)
        self.assertNotIn("function koreanOfficialMall(product)", app_js)
        self.assertNotIn('productLink(product, "buy")', app_js)

        clear_compare = app_js.split("async function clearCompareSelections()", 1)[1].split(
            "\nfunction renderRoutine()", 1
        )[0]
        reset_session = app_js.split("async function resetSession()", 1)[1].split(
            "\nfunction renderCatalogs()", 1
        )[0]
        self.assertNotIn("privacyConsent", clear_compare)
        self.assertIn('document.querySelector("#privacyConsent")', reset_session)
        self.assertIn("privacyConsent.checked = false", reset_session)

    def test_bare_betaine_does_not_match_salicylate(self) -> None:
        self.assertIsNone(find_evidence_for_ingredient("Betaine"))
        evidence = find_evidence_for_ingredient("Betaine Salicylate")
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence.name, "salicylic acid")

    def test_feedback_updates_conservative_personalization(self) -> None:
        db = ProductDatabase.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "feedback.sqlite3")
            session_id = "test-session"
            store.ensure_session(session_id)
            store.add_feedback(session_id, "product", "liked", product_id="anua-heartleaf-77-soothing-toner")
            signals = build_personalization(db.products, store.feedback_for_session(session_id))

        self.assertIn("anua-heartleaf-77-soothing-toner", signals["liked_products"])
        self.assertIn("toner", signals["liked_categories"])

    def test_ingredient_exclusions_override_personalization(self) -> None:
        db = ProductDatabase.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        profile = merge_profiles(None, "avoid snail, sensitive serum hydration", [])
        product = db.get("cosrx-advanced-snail-96-mucin-power-essence")
        self.assertIsNotNone(product)
        scored = IngredientHybridRecommender().score_product(
            product,
            profile,
            personalization={"liked_products": {product.id}},
        )

        self.assertIn("snail", profile.avoid_ingredients)
        self.assertLess(scored.score, 0)
        self.assertLess(scored.score_components["penalties"], -50)

    def test_similar_products_and_score_components(self) -> None:
        agent = KBeautyAgent.from_csv(PRODUCTS_CSV, REVIEWS_CSV)
        recommendation = agent.recommend("sensitive skin hydration serum", limit=2)

        self.assertTrue(recommendation.results)
        first = recommendation.results[0]
        self.assertGreaterEqual(len(first.similar_products), 3)
        self.assertLessEqual(len(first.similar_products), 5)
        self.assertAlmostEqual(first.score, sum(first.score_components.values()), places=5)

    def test_security_secrets_fail_closed_in_production(self) -> None:
        original = {key: os.environ.get(key) for key in ("RENDER", "ENVIRONMENT", "ADMIN_TOKEN", "SESSION_SECRET")}
        try:
            os.environ["ENVIRONMENT"] = "production"
            os.environ.pop("ADMIN_TOKEN", None)
            os.environ.pop("SESSION_SECRET", None)
            with self.assertRaises(RuntimeError):
                admin_token()
            with self.assertRaises(RuntimeError):
                session_secret()
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class PersonalizedServiceApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(self.tempdir.name) / 'service.sqlite3'}"
        os.environ["ADMIN_TOKEN"] = "test-admin-token"
        os.environ["SESSION_SECRET"] = "test-session-secret"
        os.environ["SECURE_COOKIES"] = "false"
        os.environ["COOKIE_SAMESITE"] = "lax"
        os.environ["RECOMMEND_RATE_LIMIT_REQUESTS"] = "1000"
        os.environ["RECOMMEND_RATE_LIMIT_WINDOW_SECONDS"] = "60"
        os.environ["CORS_ALLOW_ORIGINS"] = (
            "https://web.kbeauty.example,"
            "https://k-beauty-agent.apps.tossmini.com,"
            "https://k-beauty-agent.private-apps.tossmini.com"
        )
        os.environ.pop("OPENAI_API_KEY", None)
        import k_beauty_agent.web as web

        self.web = importlib.reload(web)
        from fastapi.testclient import TestClient

        self.client = TestClient(self.web.app)

    def test_session_cookie_created_and_reused(self) -> None:
        first = self.client.get("/api/session")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["cache-control"], "no-store")
        cookie = first.cookies.get(self.web.SESSION_COOKIE)
        self.assertTrue(cookie)

        second = self.client.get("/api/session", cookies={self.web.SESSION_COOKIE: cookie})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["session_id_hash"], second.json()["session_id_hash"])

    def test_apps_in_toss_header_session_is_reused_without_cookies(self) -> None:
        token = "miniapp-session_1234567890"
        first = self.client.get(
            "/api/session",
            headers={self.web.SESSION_HEADER: token},
        )
        second = self.client.get(
            "/api/session",
            headers={self.web.SESSION_HEADER: token},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["session_id_hash"], second.json()["session_id_hash"])
        self.assertEqual(first.json()["session_id_hash"], self.web.hash_session(token))

    def test_apps_in_toss_header_session_rejects_unsafe_tokens(self) -> None:
        response = self.client.get(
            "/api/session",
            headers={self.web.SESSION_HEADER: "too short/unsafe"},
        )

        self.assertEqual(response.status_code, 400)

    def test_profile_rejects_duplicate_concerns_with_localized_422(self) -> None:
        response = self.client.post(
            "/api/v2/recommend",
            json={
                "query": "hydrating serum",
                "use_openai": False,
                "language": "en",
                "profile": {
                    "skin_type": "dry",
                    "concerns": ["hydration", "hydration"],
                    "desired_categories": ["serum"],
                },
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("cannot be selected more than once", response.json()["detail"])

    def test_profile_rejects_more_than_two_additional_concerns(self) -> None:
        response = self.client.post(
            "/api/v2/recommend",
            json={
                "query": "세럼 추천",
                "use_openai": False,
                "language": "ko",
                "profile": {
                    "skin_type": "combination",
                    "primary_concern": "acne",
                    "concerns": ["hydration", "redness", "texture"],
                    "desired_categories": ["serum"],
                },
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("최대 2개", response.json()["detail"])

    def test_profile_rejects_preferred_and_avoid_alias_conflict(self) -> None:
        response = self.client.post(
            "/api/v2/recommend",
            json={
                "query": "gentle serum",
                "use_openai": False,
                "language": "en",
                "profile": {
                    "skin_type": "unknown",
                    "concerns": ["redness"],
                    "desired_categories": ["serum"],
                    "preferred_ingredients": ["fragrance"],
                    "avoid_ingredients": ["parfum"],
                },
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("overlap: fragrance", response.json()["detail"])

    def test_profile_rejects_evidence_alias_conflict(self) -> None:
        response = self.client.post(
            "/api/v2/recommend",
            json={
                "query": "gentle serum",
                "use_openai": False,
                "language": "en",
                "profile": {
                    "skin_type": "unknown",
                    "concerns": ["redness"],
                    "desired_categories": ["serum"],
                    "avoid_ingredients": ["niacinamide"],
                    "preferred_ingredients": ["nicotinamide"],
                },
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("overlap: niacinamide", response.json()["detail"])

    def test_structured_custom_avoid_ingredient_is_not_silently_dropped(self) -> None:
        response = self.client.post(
            "/api/v2/recommend",
            json={
                "query": "acne serum",
                "use_openai": False,
                "language": "en",
                "profile": {
                    "skin_type": "oily",
                    "concerns": ["acne"],
                    "desired_categories": ["serum"],
                    "avoid_ingredients": ["benzoyl peroxide"],
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["profile"]["avoid_ingredients"], ["benzoyl peroxide"])

    def test_follow_up_validates_conflict_after_merging_saved_profile(self) -> None:
        session_id = "miniapp-merged-conflict_123456"
        headers = {self.web.SESSION_HEADER: session_id}
        first = self.client.post(
            "/api/v2/recommend",
            headers=headers,
            json={
                "query": "수분 세럼 추천",
                "use_openai": False,
                "privacy_consent": True,
                "language": "ko",
                "profile": {
                    "skin_type": "dry",
                    "concerns": ["hydration"],
                    "desired_categories": ["serum"],
                    "avoid_ingredients": ["niacinamide"],
                },
            },
        )
        self.assertEqual(first.status_code, 200)

        follow_up = self.client.post(
            "/api/v2/follow-up",
            headers=headers,
            json={
                "query": "나이아신아마이드 선호로 바꿔줘",
                "use_openai": False,
                "privacy_consent": True,
                "language": "ko",
                "profile": {
                    "skin_type": "dry",
                    "concerns": ["hydration"],
                    "desired_categories": ["serum"],
                    "preferred_ingredients": ["niacinamide"],
                },
            },
        )

        self.assertEqual(follow_up.status_code, 422)
        self.assertIn("선호 성분과 제외 성분이 겹쳐요", follow_up.json()["detail"])

    def test_structured_legacy_sensitive_value_is_normalized_in_response(self) -> None:
        response = self.client.post(
            "/api/v2/recommend",
            json={
                "query": "hydrating serum",
                "use_openai": False,
                "language": "en",
                "profile": {
                    "skin_type": "sensitive",
                    "concerns": ["hydration"],
                    "desired_categories": ["serum"],
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["profile"]["skin_type"], "unknown")
        self.assertEqual(response.json()["profile"]["sensitivity_level"], "frequent")

    def test_public_recommendation_rejects_sensitive_health_text_before_storage(self) -> None:
        response = self.client.post(
            "/api/recommend",
            headers={self.web.SESSION_HEADER: "miniapp-sensitive_1234567890"},
            json={
                "query": "임신 중이고 라놀린 알레르기가 있어요",
                "limit": 3,
                "use_openai": False,
                "privacy_consent": True,
                "language": "ko",
                "profile": {
                    "skin_type": "sensitive",
                    "concerns": ["hydration"],
                    "desired_categories": ["moisturizer"],
                    "avoid_ingredients": ["lanolin"],
                },
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("민감정보", response.json()["detail"])
        with self.web.store.connect() as connection:
            stored = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?",
                ("miniapp-sensitive_1234567890",),
            ).fetchone()
        self.assertIsNone(stored)

    def test_structured_profile_cannot_bypass_sensitive_health_text_block(self) -> None:
        response = self.client.post(
            "/api/recommend",
            headers={self.web.SESSION_HEADER: "miniapp-sensitive-profile_123456"},
            json={
                "query": "민감성 피부용 보습제를 추천해줘",
                "limit": 3,
                "use_openai": False,
                "privacy_consent": True,
                "language": "ko",
                "profile": {
                    "skin_type": "sensitive",
                    "concerns": ["hydration"],
                    "desired_categories": ["moisturizer"],
                    "avoid_ingredients": ["임신 중 피해야 하는 성분"],
                },
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_preferred_ingredient_cannot_bypass_sensitive_health_text_block(self) -> None:
        for index, sensitive_value in enumerate(("pregnancy medication", "임신 약물")):
            session_id = f"miniapp-sensitive-preferred-{index}_123456"
            with self.subTest(sensitive_value=sensitive_value):
                response = self.client.post(
                    "/api/recommend",
                    headers={self.web.SESSION_HEADER: session_id},
                    json={
                        "query": "순한 세럼 추천",
                        "limit": 3,
                        "use_openai": False,
                        "privacy_consent": True,
                        "language": "ko",
                        "profile": {
                            "skin_type": "unknown",
                            "concerns": ["hydration"],
                            "desired_categories": ["serum"],
                            "preferred_ingredients": [sensitive_value],
                        },
                    },
                )

                self.assertEqual(response.status_code, 422)
                with self.web.store.connect() as connection:
                    stored = connection.execute(
                        "SELECT 1 FROM sessions WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                self.assertIsNone(stored)

    def test_contact_or_note_text_is_rejected_before_profile_storage(self) -> None:
        for index, value in enumerate((
            "younghan@example.com",
            "010-1234-5678",
            "https://example.com/private-note",
            "private niacinamide note",
            "this is a long private note that is not an ingredient name",
        )):
            session_id = f"miniapp-private-note-{index}_123456"
            with self.subTest(value=value):
                response = self.client.post(
                    "/api/recommend",
                    headers={self.web.SESSION_HEADER: session_id},
                    json={
                        "query": "순한 세럼 추천",
                        "use_openai": False,
                        "privacy_consent": True,
                        "language": "ko",
                        "profile": {
                            "skin_type": "unknown",
                            "concerns": ["hydration"],
                            "desired_categories": ["serum"],
                            "preferred_ingredients": [value],
                        },
                    },
                )

                self.assertEqual(response.status_code, 422)
                with self.web.store.connect() as connection:
                    stored = connection.execute(
                        "SELECT 1 FROM sessions WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                self.assertIsNone(stored)

    def test_public_recommendation_persists_only_controlled_profile_not_raw_query(self) -> None:
        session_id = "miniapp-controlled-profile_123456"
        raw_query = "지성 피부 세럼 추천, 향료는 빼고 개인 메모 codename-orchid"
        response = self.client.post(
            "/api/recommend",
            headers={self.web.SESSION_HEADER: session_id},
            json={
                "query": raw_query,
                "limit": 3,
                "use_openai": False,
                "privacy_consent": True,
                "language": "ko",
            },
        )

        self.assertEqual(response.status_code, 200)
        with self.web.store.connect() as connection:
            stored_query = connection.execute(
                "SELECT query FROM recommendations WHERE session_id = ?",
                (session_id,),
            ).fetchone()["query"]
            stored_profile = json.loads(
                connection.execute(
                    "SELECT profile_json FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()["profile_json"]
            )
        self.assertNotIn("codename-orchid", stored_query)
        self.assertIn("controlled_profile", stored_query)
        self.assertNotIn("allergies", stored_profile)
        self.assertNotIn("pregnant_or_nursing", stored_profile)

    def test_one_time_recommendation_writes_no_session_or_behavior_rows(self) -> None:
        tables = (
            "sessions",
            "privacy_consents",
            "conversation_turns",
            "recommendations",
            "feedback",
            "openai_calls",
            "app_events",
            "selections",
        )
        with self.web.store.connect() as connection:
            before = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }

        response = self.client.post(
            "/api/v2/recommend",
            headers={self.web.SESSION_HEADER: "miniapp-one-time_1234567890"},
            json={
                "query": "수분 세럼 추천",
                "use_openai": False,
                "privacy_consent": False,
                "language": "ko",
                "profile": {
                    "skin_type": "dry",
                    "concerns": ["hydration"],
                    "desired_categories": ["serum"],
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["recommendation_id"])
        self.assertFalse(response.json()["privacy"]["stored"])
        with self.web.store.connect() as connection:
            after = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }
        self.assertEqual(after, before)

    def test_previous_policy_consent_is_stateless_until_current_notice_is_accepted(self) -> None:
        session_id = "miniapp-previous-policy_1234567890"
        tables = (
            "sessions",
            "privacy_consents",
            "conversation_turns",
            "recommendations",
            "feedback",
            "openai_calls",
            "app_events",
            "selections",
        )
        with self.web.store.connect() as connection:
            before = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }

        response = self.client.post(
            "/api/v2/recommend",
            headers={self.web.SESSION_HEADER: session_id},
            json={
                "query": "수분 세럼 추천",
                "use_openai": False,
                "privacy_consent": True,
                "privacy_policy_version": "2026-07-20",
                "language": "ko",
                "profile": {
                    "skin_type": "dry",
                    "concerns": ["hydration"],
                    "desired_categories": ["serum"],
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["recommendation_id"])
        self.assertEqual(
            response.json()["privacy"],
            {
                "stored": False,
                "policy_version": None,
                "required_policy_version": self.web.PRIVACY_POLICY_VERSION,
                "consent_refresh_required": True,
            },
        )
        with self.web.store.connect() as connection:
            after = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }
        self.assertEqual(after, before)

    def test_feedback_rejects_free_text_comment_field(self) -> None:
        response = self.client.post(
            "/api/feedback",
            json={
                "recommendation_id": 1,
                "target": "result",
                "feedback": "liked",
                "comment": "free text must not be accepted",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_feedback_rejects_unbounded_or_unexposed_product_ids(self) -> None:
        too_long = self.client.post(
            "/api/feedback",
            json={
                "recommendation_id": 1,
                "target": "product",
                "product_id": "x" * 161,
                "feedback": "liked",
            },
        )
        self.assertEqual(too_long.status_code, 422)

        recommendation = self.client.post(
            "/api/recommend",
            json={
                "query": "건성 피부 수분 세럼 추천",
                "limit": 1,
                "use_openai": False,
                "privacy_consent": True,
                "language": "ko",
            },
        )
        self.assertEqual(recommendation.status_code, 200)
        data = recommendation.json()
        exposed_ids = {
            item["product"]["id"]
            for item in data["results"]
        }
        exposed_ids.update(
            product["id"]
            for item in data["results"]
            for product in item.get("similar_products", [])
        )
        unexposed_id = next(product.id for product in self.web.agent.database.products if product.id not in exposed_ids)

        response = self.client.post(
            "/api/feedback",
            json={
                "recommendation_id": data["recommendation_id"],
                "target": "product",
                "product_id": unexposed_id,
                "feedback": "liked",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("referenced recommendation", response.json()["detail"])

    def test_apps_in_toss_header_takes_priority_and_isolates_profiles(self) -> None:
        cookie_session = self.client.get("/api/session")
        self.assertEqual(cookie_session.status_code, 200)
        header_token = "miniapp-profile_1234567890"

        recommendation = self.client.post(
            "/api/recommend",
            headers={self.web.SESSION_HEADER: header_token},
            json={
                "query": "이 문장은 구조화 입력보다 우선하면 안 됩니다",
                "limit": 3,
                "use_openai": False,
                "privacy_consent": True,
                "language": "ko",
                "profile": {
                    "skin_type": "dry",
                    "concerns": ["hydration"],
                    "desired_categories": ["moisturizer"],
                    "avoid_ingredients": ["fragrance"],
                    "max_price_krw": 30000,
                },
            },
        )
        self.assertEqual(recommendation.status_code, 200)

        header_session = self.client.get(
            "/api/session",
            headers={self.web.SESSION_HEADER: header_token},
        )
        self.assertEqual(header_session.json()["session_id_hash"], self.web.hash_session(header_token))
        self.assertEqual(header_session.json()["profile"]["skin_type"], "dry")
        self.assertEqual(cookie_session.json()["profile"], {})

    def test_structured_miniapp_profile_preserves_skin_and_avoid_constraints(self) -> None:
        response = self.client.post(
            "/api/recommend",
            headers={self.web.SESSION_HEADER: "miniapp-constraints_1234567890"},
            json={
                "query": (
                    "피부 타입은 보통(normal)이고 토너를 추천해줘. "
                    "건조함과 유분 조절이 고민이고 살리실산, 티트리 없이 보여줘."
                ),
                "limit": 5,
                "use_openai": False,
                "privacy_consent": True,
                "language": "ko",
                "profile": {
                    "skin_type": "normal",
                    "concerns": ["dryness", "oil_control"],
                    "desired_categories": ["toner"],
                    "avoid_ingredients": ["salicylic acid", "tea tree"],
                    "max_price_krw": 30000,
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        profile = data["profile"]
        self.assertEqual(profile["skin_type"], "normal")
        self.assertEqual(profile["concerns"], ["dryness", "oil_control"])
        self.assertEqual(profile["desired_categories"], ["toner"])
        self.assertEqual(profile["avoid_ingredients"], ["salicylic acid", "tea tree"])
        self.assertEqual(profile["preferred_ingredients"], [])
        self.assertIsNone(profile["texture_preference"])
        self.assertTrue(data["results"])

        forbidden = {"salicylic acid", "tea tree"}
        for item in data["results"]:
            self.assertEqual(item["product"]["category"], "toner")
            canonical_ingredients = {
                evidence.name
                for ingredient in item["product"]["ingredients"]
                if (evidence := find_evidence_for_ingredient(ingredient)) is not None
            }
            self.assertFalse(canonical_ingredients & forbidden)

    def test_recommendation_endpoint_rate_limits_by_ip_and_session(self) -> None:
        os.environ["RECOMMEND_RATE_LIMIT_REQUESTS"] = "2"
        self.web._rate_limit_buckets.clear()
        payload = {
            "query": "지성 피부 토너 추천",
            "limit": 1,
            "use_openai": False,
            "privacy_consent": True,
            "language": "ko",
        }
        headers = {self.web.SESSION_HEADER: "miniapp-rate-limit_1234567890"}
        try:
            first = self.client.post("/api/recommend", headers=headers, json=payload)
            second = self.client.post("/api/recommend", headers=headers, json=payload)
            limited = self.client.post("/api/recommend", headers=headers, json=payload)
        finally:
            os.environ["RECOMMEND_RATE_LIMIT_REQUESTS"] = "1000"
            self.web._rate_limit_buckets.clear()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers["retry-after"], "60")

    def test_secure_cookie_can_be_enabled(self) -> None:
        os.environ["SECURE_COOKIES"] = "true"
        self.web = importlib.reload(self.web)
        from fastapi.testclient import TestClient

        client = TestClient(self.web.app)
        response = client.get("/api/session")

        self.assertIn("secure", response.headers["set-cookie"].lower())

    def test_cross_origin_cookie_and_cors_for_explicit_dedicated_web_origin(self) -> None:
        os.environ["SECURE_COOKIES"] = "true"
        os.environ["COOKIE_SAMESITE"] = "none"
        self.web = importlib.reload(self.web)
        from fastapi.testclient import TestClient

        client = TestClient(self.web.app)
        session = client.get("/api/session")
        cookie = session.headers["set-cookie"].lower()
        self.assertIn("samesite=none", cookie)
        self.assertIn("secure", cookie)

        preflight = client.options(
            "/api/recommend",
            headers={
                "Origin": "https://web.kbeauty.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(preflight.headers["access-control-allow-origin"], "https://web.kbeauty.example")
        self.assertNotIn("access-control-allow-credentials", preflight.headers)

        toss_preflight = client.options(
            "/api/recommend",
            headers={
                "Origin": "https://k-beauty-agent.private-apps.tossmini.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-kbeauty-session",
            },
        )
        self.assertEqual(toss_preflight.status_code, 200)
        self.assertEqual(
            toss_preflight.headers["access-control-allow-origin"],
            "https://k-beauty-agent.private-apps.tossmini.com",
        )

    def test_recommend_followup_feedback_and_openai_fallback(self) -> None:
        response = self.client.post(
            "/api/recommend",
            json={
                "query": "지성 피부에 맞는 기초 제품을 추천해줘",
                "limit": 3,
                "use_openai": True,
                "privacy_consent": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["decision"], "recommend")
        self.assertEqual(data["openai_status"], "fallback")
        self.assertTrue(data["results"])
        self.assertIn("score_components", data["results"][0])

        feedback = self.client.post(
            "/api/feedback",
            json={
                "recommendation_id": data["recommendation_id"],
                "target": "product",
                "product_id": data["results"][0]["product"]["id"],
                "feedback": "liked",
                "reason_tags": ["liked_ingredients"],
            },
        )
        self.assertEqual(feedback.status_code, 200)

        follow_up = self.client.post(
            "/api/follow-up",
            json={
                "query": "make it gentler and fragrance-free",
                "limit": 3,
                "use_openai": False,
                "privacy_consent": True,
            },
        )
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn("oil_control", follow_up.text)

    def test_profile_reset_keeps_session_but_clears_search_criteria(self) -> None:
        response = self.client.post(
            "/api/recommend",
            json={
                "query": "지성 피부 선크림 3만원 이하 추천",
                "limit": 3,
                "use_openai": False,
                "privacy_consent": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["profile"]["skin_type"], "oily")

        cleared = self.client.delete("/api/profile")
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["profile"], {})

        session = self.client.get("/api/session")
        self.assertEqual(session.status_code, 200)
        self.assertEqual(session.json()["profile"], {})

    def test_selection_api_tracks_saved_compare_and_total_cost(self) -> None:
        consent = self.client.post(
            "/api/recommend",
            json={
                "query": "선크림 추천",
                "limit": 1,
                "use_openai": False,
                "privacy_consent": True,
                "language": "ko",
            },
        )
        self.assertEqual(consent.status_code, 200)

        response = self.client.post(
            "/api/selections",
            json={
                "product_id": "beauty-of-joseon-relief-sun-rice-probiotics",
                "list_type": "saved",
                "selected": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["saved_ids"], ["beauty-of-joseon-relief-sun-rice-probiotics"])
        self.assertEqual(data["total_cost_krw"], 0)
        self.assertEqual(data["missing_price_ids"], ["beauty-of-joseon-relief-sun-rice-probiotics"])

        compare = self.client.post(
            "/api/selections",
            json={
                "product_id": "axis-y-dark-spot-correcting-glow-serum",
                "list_type": "compare",
                "selected": True,
            },
        )
        self.assertEqual(compare.status_code, 200)
        self.assertEqual(compare.json()["compare_ids"], ["axis-y-dark-spot-correcting-glow-serum"])

        cleared = self.client.post(
            "/api/selections",
            json={
                "product_id": "beauty-of-joseon-relief-sun-rice-probiotics",
                "list_type": "saved",
                "selected": False,
            },
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["saved_ids"], [])

    def test_korean_language_response_is_localized(self) -> None:
        response = self.client.post(
            "/api/recommend",
            json={
                "query": "지성 피부에 맞는 기초 제품을 추천해줘",
                "limit": 2,
                "use_openai": False,
                "privacy_consent": True,
                "language": "ko",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("추천 제품", data["grounded_explanation"])
        self.assertIn("추천 이유", data["grounded_explanation"])
        self.assertIn("display_reasons", data["results"][0])
        self.assertIn("personalized_reason", data["results"][0])
        self.assertTrue(data["results"][0]["personalized_reason"])
        self.assertTrue(any("피부" in reason or "성분" in reason for reason in data["results"][0]["display_reasons"]))

    def test_english_language_response_uses_source_terms(self) -> None:
        response = self.client.post(
            "/api/recommend",
            json={
                "query": "oily skin sunscreen for oil control",
                "limit": 2,
                "use_openai": False,
                "privacy_consent": True,
                "language": "en",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("Recommended options", data["grounded_explanation"])
        self.assertIn("review_summary_en", data["results"][0]["product"])
        self.assertTrue(data["results"][0]["product"]["review_summary_en"])
        self.assertIn("display_reasons", data["results"][0])
        self.assertIn("personalized_reason", data["results"][0])
        self.assertFalse(any("피부" in reason or "성분" in reason for reason in data["results"][0]["display_reasons"]))

    def test_admin_endpoints_are_protected(self) -> None:
        unauthorized = self.client.get("/api/admin/metrics")
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized.headers["cache-control"], "no-store")

        authorized = self.client.get("/api/admin/metrics", headers={"x-admin-token": "test-admin-token"})
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.headers["cache-control"], "no-store")
        self.assertIn("total_sessions", authorized.json())

    def test_compare_and_routine_pages_are_served(self) -> None:
        compare = self.client.get("/compare")
        routine = self.client.get("/routine")

        self.assertEqual(compare.status_code, 200)
        self.assertEqual(routine.status_code, 200)
        self.assertIn("제품 비교", compare.text)
        self.assertIn("개인 루틴", routine.text)

    def test_cleanup_endpoint(self) -> None:
        response = self.client.post("/api/admin/cleanup", headers={"x-admin-token": "test-admin-token"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("deleted", response.json())


if __name__ == "__main__":
    unittest.main()
