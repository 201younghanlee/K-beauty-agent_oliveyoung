from __future__ import annotations

import csv
import hashlib
import json

import pytest

from k_beauty_agent.agent import KBeautyAgent
from k_beauty_agent.config import DEFAULT_CATALOG_MANIFEST, DEFAULT_GENERATED_CATALOG_CSV
from k_beauty_agent.database import ProductDatabase
from k_beauty_agent.knowledge_base import find_evidence_for_ingredient
from k_beauty_agent.models import Product, SkinProfile
from k_beauty_agent.recommender import IngredientHybridRecommender
from k_beauty_agent.serializers import product_to_dict
from k_beauty_agent.skin import analyze_skin_query
from k_beauty_agent.web import _load_generated_catalog
from scripts.refresh_catalog import CATALOG_COLUMNS


def _product(
    product_id: str,
    *,
    tier: str = "eligible",
    ingredient_status: str = "reported",
    source: str = "open_beauty_facts",
) -> Product:
    return Product(
        id=product_id,
        name=f"Barrier Serum {product_id}",
        brand="Example Lab",
        category="serum",
        country="Korea",
        ingredients=("Glycerin", "Panthenol"),
        catalog_source=source,
        source_product_id=product_id,
        source_url=f"https://world.openbeautyfacts.org/product/{product_id}",
        source_updated_at="2026-07-20T00:00:00Z",
        ingredient_status=ingredient_status,
        recommendation_tier=tier,
        data_license="ODbL-1.0 (database); CC-BY-SA-3.0 (product images)",
        data_attribution_url="https://world.openbeautyfacts.org/data",
    )


def test_combined_catalog_keeps_verified_product_on_duplicate_id() -> None:
    verified = _product("same-id", tier="verified", ingredient_status="complete", source="curated")
    generated = _product("same-id")

    database = ProductDatabase.combine(ProductDatabase([verified]), ProductDatabase([generated]))

    assert len(database.products) == 1
    assert database.get("same-id") is verified
    assert database.source_status()["source_counts"] == {"curated": 1}


def test_discovery_rows_are_searchable_in_catalog_but_not_recommendable() -> None:
    eligible = _product("eligible")
    discovery = _product("discovery", tier="discovery")
    database = ProductDatabase([eligible, discovery])

    page, total = database.catalog_page(category="serum", limit=10)
    recommendation_candidates = database.search(categories=["serum"], limit=10)

    assert total == 2
    assert {product.id for product in page} == {"eligible", "discovery"}
    assert [product.id for product in recommendation_candidates] == ["eligible"]


def test_reported_ingredients_are_allowed_for_general_matching_but_blocked_for_avoid_lists() -> None:
    product = _product("reported")
    recommender = IngredientHybridRecommender()
    general = SkinProfile(skin_type="dry", concerns=["hydration"], desired_categories=["serum"])
    allergy_sensitive = SkinProfile(
        skin_type="dry",
        concerns=["hydration"],
        desired_categories=["serum"],
        avoid_ingredients=["fragrance"],
    )
    sensitive_skin = SkinProfile(skin_type="sensitive", concerns=["redness"], desired_categories=["serum"])
    pregnancy = SkinProfile(skin_type="dry", concerns=["hydration"], desired_categories=["serum"], pregnant_or_nursing=True)

    general_score = recommender.score_product(product, general)
    allergy_score = recommender.score_product(product, allergy_sensitive)
    sensitive_score = recommender.score_product(product, sensitive_skin)
    pregnancy_score = recommender.score_product(product, pregnancy)

    assert general_score.score >= 3.0
    assert allergy_score.score < -50.0
    assert sensitive_score.score < -50.0
    assert pregnancy_score.score < -50.0
    assert any("full ingredient list" in caution for caution in allergy_score.cautions)


def test_ingredient_evidence_matching_uses_token_boundaries() -> None:
    assert find_evidence_for_ingredient("Zinc Oxide") is None
    assert find_evidence_for_ingredient("Ethylhexylglycerin") is None
    assert find_evidence_for_ingredient("Zinc PCA").name == "zinc pca"
    assert find_evidence_for_ingredient("Glycerin").name == "glycerin"


def test_ingredient_aliases_do_not_score_the_same_evidence_twice() -> None:
    profile = SkinProfile(skin_type="dry", concerns=["hydration"], desired_categories=["serum"])
    single = _product("single")
    duplicate_alias = Product(
        **{
            **single.__dict__,
            "id": "duplicate-alias",
            "ingredients": ("Glycerin", "Glycerol", "Panthenol"),
        }
    )
    recommender = IngredientHybridRecommender()

    assert recommender.score_product(single, profile).score == recommender.score_product(duplicate_alias, profile).score


def test_free_text_sensitive_skin_is_parsed_conservatively() -> None:
    profile = analyze_skin_query("oily sensitive skin hydrating moisturizer")
    fragrance_profile = analyze_skin_query("fragrance sensitive serum")

    assert profile.skin_type == "sensitive"
    assert fragrance_profile.skin_type == "sensitive"
    assert "fragrance" in fragrance_profile.avoid_ingredients
    assert "fragrance" not in fragrance_profile.preferred_ingredients


def test_normal_skin_does_not_trigger_the_english_no_avoid_parser() -> None:
    profile = analyze_skin_query("normal skin moisturizer")

    assert profile.skin_type == "normal"
    assert profile.avoid_ingredients == []


def test_catalog_metadata_is_serialized_for_the_miniapp() -> None:
    data = product_to_dict(_product("metadata"))

    assert data["catalog_source"] == "open_beauty_facts"
    assert data["source_product_id"] == "metadata"
    assert data["source_updated_at"] == "2026-07-20T00:00:00Z"
    assert data["ingredient_status"] == "reported"
    assert data["recommendation_tier"] == "eligible"
    assert data["data_license"].startswith("ODbL")
    assert data["data_attribution_url"] == "https://world.openbeautyfacts.org/data"


def test_community_source_page_is_not_labeled_as_an_official_brand_page() -> None:
    product = Product.from_mapping(
        {
            "id": "open-beauty-facts-12345678",
            "name": "Example Serum",
            "brand": "Example",
            "category": "serum",
            "country": "Unknown",
            "ingredients": ["Glycerin"],
            "source_url": "https://world.openbeautyfacts.org/product/12345678",
            "catalog_source": "open_beauty_facts",
        }
    )

    assert product.source_url == "https://world.openbeautyfacts.org/product/12345678"
    assert product.official_url is None
    assert product.ingredient_status == "missing"
    assert product.recommendation_tier == "discovery"


def test_safety_filter_runs_before_candidate_limit() -> None:
    reported = [_product(f"reported-{index:03d}") for index in range(350)]
    verified = _product("verified-safe", tier="verified", ingredient_status="complete", source="curated")
    agent = KBeautyAgent(ProductDatabase([*reported, verified]))

    recommendation = agent.recommend(
        "dry hydrating serum without fragrance",
        limit=1,
        structured_profile={
            "skin_type": "dry",
            "concerns": ["hydration"],
            "desired_categories": ["serum"],
            "avoid_ingredients": ["fragrance"],
        },
    )

    assert [item.product.id for item in recommendation.results] == ["verified-safe"]


def test_runtime_validates_generated_catalog_against_manifest(tmp_path) -> None:
    csv_path = tmp_path / "catalog.csv"
    manifest_path = tmp_path / "manifest.json"
    row = {column: "" for column in CATALOG_COLUMNS}
    row.update(
        {
            "id": "open-beauty-facts-12345678",
            "name": "Example Serum",
            "brand": "Example",
            "category": "serum",
            "country": "Unknown",
            "ingredients": "Water|Glycerin|Panthenol",
            "source_url": "https://world.openbeautyfacts.org/product/12345678",
            "image_url": "https://images.openbeautyfacts.org/example.jpg",
            "catalog_source": "open_beauty_facts",
            "source_product_id": "12345678",
            "ingredient_status": "reported",
            "recommendation_tier": "eligible",
            "data_license": "ODbL-1.0 (database); CC-BY-SA-3.0 (product images)",
            "data_attribution_url": "https://world.openbeautyfacts.org/data",
        }
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CATALOG_COLUMNS)
        writer.writeheader()
        writer.writerow(row)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "catalog_source": "open_beauty_facts",
                "product_count": 1,
                "category_counts": {"serum": 1},
                "generated_at": "2026-07-20T01:30:00Z",
                "record_freshness": {
                    "as_of": "2026-07-20T01:30:00Z",
                    "dated_products": 1,
                },
                "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    database = _load_generated_catalog(csv_path, manifest_path)
    assert len(database.products) == 1
    assert database.source_status()["catalog_updated_at"] == "2026-07-20T01:30:00Z"
    assert database.source_status()["record_freshness"]["dated_products"] == 1
    csv_path.write_text(csv_path.read_text(encoding="utf-8") + "tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        _load_generated_catalog(csv_path, manifest_path)


def test_checked_in_catalog_excludes_known_non_facial_false_positives() -> None:
    database = _load_generated_catalog(DEFAULT_GENERATED_CATALOG_CSV, DEFAULT_CATALOG_MANIFEST)
    by_source_id = {product.source_product_id: product for product in database.products}

    assert "5708048047029" not in by_source_id  # household WC cleaner
    assert "5033102850858" not in by_source_id  # hair-color toner
    assert "3178040695160" not in by_source_id  # eye-contour cream
    assert "0810400037267" not in by_source_id  # body cream
    assert "3605971132988" not in by_source_id  # explicitly continued ingredient label
    assert "3760293232164" not in by_source_id  # acne patch, not a cleanser
    assert by_source_id["3433422404366"].category == "cleanser"
    assert by_source_id["8901030937521"].category == "cleanser"
    cleaned_spanish_label = " ".join(by_source_id["7702006301480"].ingredients).lower()
    assert "hecho en" not in cleaned_spanish_label
    assert "fabricado" not in cleaned_spanish_label
    assert all(product.fetched_at is None for product in database.products)
