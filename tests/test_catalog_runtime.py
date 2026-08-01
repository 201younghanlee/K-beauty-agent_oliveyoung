from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace

import pytest

from k_beauty_agent.agent import KBeautyAgent
from k_beauty_agent.config import DEFAULT_CATALOG_MANIFEST, DEFAULT_GENERATED_CATALOG_CSV
from k_beauty_agent.database import ProductDatabase
from k_beauty_agent.knowledge_base import canonical_ingredient_key, find_evidence_for_ingredient, ingredient_name_matches
from k_beauty_agent.models import Product, SkinProfile
from k_beauty_agent.recommender import IngredientHybridRecommender
from k_beauty_agent.serializers import product_to_dict
from k_beauty_agent.followup_parser import sanitize_profile_patch
from k_beauty_agent.skin import analyze_skin_query, canonicalize_ingredient_preferences
from k_beauty_agent.web import RecommendationProfileRequest, _load_generated_catalog
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
    sensitive_skin = SkinProfile(
        skin_type="dry",
        sensitivity_level="frequent",
        concerns=["redness"],
        desired_categories=["serum"],
    )
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

    assert profile.skin_type == "oily"
    assert profile.sensitivity_level == "frequent"
    assert fragrance_profile.skin_type == "unknown"
    assert fragrance_profile.sensitivity_level == "frequent"
    assert "fragrance" in fragrance_profile.avoid_ingredients
    assert "fragrance" not in fragrance_profile.preferred_ingredients


def test_preferred_ingredient_is_a_ranking_boost_not_a_hard_filter() -> None:
    without_preference = replace(
        _product("without-preference", tier="verified", ingredient_status="complete", source="curated"),
        brand="Other Lab",
    )
    with_preference = replace(
        _product("with-preference", tier="verified", ingredient_status="complete", source="curated"),
        ingredients=("Glycerin", "Panthenol", "Niacinamide"),
    )
    profile = SkinProfile(
        skin_type="dry",
        concerns=["hydration"],
        desired_categories=["serum"],
        preferred_ingredients=["niacinamide"],
    )

    scored = IngredientHybridRecommender().score_products(
        [without_preference, with_preference],
        profile,
    )

    assert [item.product.id for item in scored] == ["with-preference", "without-preference"]
    assert any("contains requested ingredient" in reason for reason in scored[0].reasons)


def test_clogged_pores_matches_pores_catalog_and_evidence_aliases() -> None:
    product = replace(
        _product("pores", tier="verified", ingredient_status="complete", source="curated"),
        ingredients=("Niacinamide",),
        concerns=("pores",),
    )
    profile = SkinProfile(
        skin_type="oily",
        primary_concern="clogged_pores",
        desired_categories=["serum"],
    )

    score = IngredientHybridRecommender().score_product(product, profile)
    found = ProductDatabase([product]).search(concerns=["clogged_pores"], limit=10)

    assert "niacinamide" in score.matched_ingredients
    assert any("primary concern clogged_pores" in reason for reason in score.reasons)
    assert [item.id for item in found] == ["pores"]


def test_dullness_search_matches_hyperpigmentation_catalog_tag() -> None:
    product = replace(
        _product("tone", tier="verified", ingredient_status="complete", source="curated"),
        concerns=("hyperpigmentation",),
    )

    found = ProductDatabase([product]).search(concerns=["dullness"], limit=10)

    assert [item.id for item in found] == ["tone"]


def test_budget_price_known_partition_precedes_brand_diversity() -> None:
    base = _product("known-one", tier="verified", ingredient_status="complete", source="curated")
    products = [
        replace(base, brand="Same Brand", price_krw=10_000, rating=5.0, review_count=2_000),
        replace(
            base,
            id="known-two",
            name="Known Two",
            brand="Same Brand",
            price_krw=12_000,
            rating=4.8,
            review_count=1_500,
        ),
        replace(
            base,
            id="unknown-price",
            name="Unknown Price",
            brand="Other Brand",
            price_krw=None,
            rating=4.7,
            review_count=1_000,
        ),
    ]
    profile = SkinProfile(
        skin_type="dry",
        concerns=["hydration"],
        desired_categories=["serum"],
        max_price_krw=20_000,
    )

    ordered = IngredientHybridRecommender().score_products(products, profile)

    assert [item.product.id for item in ordered[:2]] == ["known-one", "known-two"]
    assert ordered[2].product.id == "unknown-price"


def test_basic_category_expands_to_normal_skin_care_steps() -> None:
    serum = _product("basic-serum", tier="verified", ingredient_status="complete", source="curated")
    cleanser = replace(serum, id="basic-cleanser", name="Basic Cleanser", category="cleanser")
    shampoo = replace(serum, id="basic-hair", name="Repair Shampoo", category="shampoo")

    found = ProductDatabase([serum, cleanser, shampoo]).search(categories=["basic"], limit=10)

    assert {product.id for product in found} == {"basic-serum", "basic-cleanser"}


def test_explicit_expanded_category_can_recommend_a_reported_catalog_row() -> None:
    product = replace(_product("hair-care"), name="Repair Shampoo", category="shampoo")
    profile = SkinProfile(desired_categories=["shampoo"])

    score = IngredientHybridRecommender().score_product(product, profile)

    assert score.score >= 3.0
    assert score.score_components["category_match"] == 7.0
    assert "ingredient data is community-reported" in " ".join(score.cautions)


@pytest.mark.parametrize(
    "category",
    [
        "face_mask",
        "eye_care",
        "lip_care",
        "exfoliator",
        "body_cleanser",
        "body_moisturizer",
        "body_exfoliator",
        "shampoo",
        "conditioner",
        "hair_treatment",
        "base_makeup",
        "eye_makeup",
        "lip_makeup",
    ],
)
def test_public_structured_profile_accepts_expanded_categories(category: str) -> None:
    profile = RecommendationProfileRequest(skin_type="unknown", desired_categories=[category])

    assert profile.desired_categories == [category]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("lip balm", ["lip_care"]),
        ("eye cream", ["eye_care"]),
        ("body lotion", ["body_moisturizer"]),
        ("hair serum", ["hair_treatment"]),
        ("exfoliating toner", ["exfoliator"]),
        ("eye serum and moisturizer", ["moisturizer", "eye_care"]),
    ],
)
def test_specific_beauty_query_does_not_add_an_overlapping_core_category(
    query: str,
    expected: list[str],
) -> None:
    assert analyze_skin_query(query).desired_categories == expected


def test_volatile_alcohol_avoid_does_not_match_fatty_or_benzyl_alcohol() -> None:
    base = _product("cetearyl", tier="verified", ingredient_status="complete", source="curated")
    products = [
        replace(base, ingredients=("Cetearyl Alcohol",)),
        replace(base, id="benzyl", name="Benzyl Serum", ingredients=("Benzyl Alcohol",)),
        replace(base, id="denat", name="Denat Serum", ingredients=("Alcohol Denat.",)),
    ]

    found = ProductDatabase(products).search(
        categories=["serum"],
        exclude_ingredients=["alcohol"],
        require_complete_ingredients=True,
        limit=10,
    )

    assert {product.id for product in found} == {"cetearyl", "benzyl"}
    assert ingredient_name_matches("alcohol", "Cetearyl Alcohol") is False
    assert ingredient_name_matches("alcohol", "Benzyl Alcohol") is False
    assert ingredient_name_matches("alcohol", "Alcohol Denat.") is True
    assert ingredient_name_matches("ethanol", "Phenoxyethanol") is False
    assert ingredient_name_matches("ethanol", "Methanol") is False
    assert canonical_ingredient_key("phenoxyethanol") == "phenoxyethanol"


def test_unrecognized_ingredient_matching_uses_phrase_boundaries() -> None:
    assert ingredient_name_matches("rose", "sucrose") is False
    assert ingredient_name_matches("tea", "stearic acid") is False
    assert ingredient_name_matches("rose", "rose extract") is True
    assert ingredient_name_matches("tea tree", "tea tree leaf oil") is True
    assert ingredient_name_matches("rose water", "water") is False
    assert ingredient_name_matches("coconut oil", "oil") is False
    assert ingredient_name_matches("rose extract", "extract") is False


def test_review_count_only_affects_ranking_with_a_verified_source() -> None:
    unsourced = replace(_product("unsourced-review"), rating=4.9, review_count=5_000)
    sourced = replace(
        unsourced,
        id="sourced-review",
        review_source_url="https://www.ulta.com/p/example",
        review_verified_at="2026-07-20",
    )
    recommender = IngredientHybridRecommender()

    unsourced_score = recommender.score_product(unsourced, SkinProfile())
    sourced_score = recommender.score_product(sourced, SkinProfile())

    assert unsourced_score.score_components["review_confidence"] == 0.0
    assert sourced_score.score_components["review_confidence"] == 1.0


def test_nonvolatile_alcohol_names_are_not_canonicalized_as_broad_alcohol() -> None:
    assert canonicalize_ingredient_preferences(["cetearyl alcohol"]) == []
    assert canonicalize_ingredient_preferences(["benzyl alcohol"]) == []
    assert canonicalize_ingredient_preferences(["alcohol"]) == ["alcohol"]
    assert canonicalize_ingredient_preferences(["ethanol"]) == ["alcohol"]
    assert canonical_ingredient_key("Alcohol Denat.") == "alcohol"
    assert canonical_ingredient_key("Cetearyl Alcohol") == "cetearyl alcohol"
    assert canonical_ingredient_key("nicotinamide") == "niacinamide"


def test_structured_profile_can_preserve_bounded_unrecognized_ingredient_names() -> None:
    public_patch = sanitize_profile_patch(
        {
            "avoid_ingredients": ["benzoyl peroxide", "cetearyl alcohol"],
            "preferred_ingredients": ["ectoin"],
        },
        allow_unrecognized_ingredients=True,
    )
    llm_patch = sanitize_profile_patch(
        {"avoid_ingredients": ["benzoyl peroxide"]},
    )

    assert public_patch["avoid_ingredients"] == ["benzoyl peroxide", "cetearyl alcohol"]
    assert public_patch["preferred_ingredients"] == ["ectoin"]
    assert "avoid_ingredients" not in llm_patch


def test_structured_profile_rejects_contact_details_urls_and_note_sentences() -> None:
    patch = sanitize_profile_patch(
        {
            "avoid_ingredients": [
                "benzoyl peroxide",
                "ectoin",
                "cetearyl alcohol",
                "younghan@example.com",
                "010-1234-5678",
                "https://example.com/private-note",
                "private niacinamide note",
                "this is a long private note that is not an ingredient name",
            ],
        },
        allow_unrecognized_ingredients=True,
    )

    assert patch["avoid_ingredients"] == ["benzoyl peroxide", "ectoin", "cetearyl alcohol"]


def test_unrecognized_avoid_ingredient_is_still_a_hard_catalog_filter() -> None:
    base = _product("benzoyl", tier="verified", ingredient_status="complete", source="curated")
    products = [
        replace(base, ingredients=("Benzoyl Peroxide", "Glycerin")),
        replace(base, id="safe", name="Safe Serum", ingredients=("Glycerin", "Panthenol")),
    ]

    found = ProductDatabase(products).search(
        categories=["serum"],
        exclude_ingredients=["benzoyl peroxide"],
        require_complete_ingredients=True,
        limit=10,
    )

    assert [product.id for product in found] == ["safe"]


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


def test_official_brand_missing_ingredients_do_not_claim_community_reporting() -> None:
    product = Product.from_mapping(
        {
            "id": "official-example-mask",
            "name": "Example Mask",
            "brand": "Example",
            "category": "face_mask",
            "country": "Korea",
            "source_url": "https://example.com/products/mask",
            "official_url": "https://example.com/products/mask",
            "verified_at": "2026-08-02",
            "catalog_source": "official_brand",
            "ingredient_status": "missing",
            "recommendation_tier": "eligible",
        }
    )

    score = KBeautyAgent(ProductDatabase([product])).recommender.score_product(
        product,
        SkinProfile(desired_categories=["face_mask"]),
    )

    assert "the full ingredient list is not recorded" in " ".join(score.cautions)
    assert "community-reported" not in " ".join(score.cautions)


def test_official_brand_products_rank_ahead_of_community_rows_for_the_same_category() -> None:
    community = replace(
        _product("community-mask"),
        name="A Community Mask",
        category="face_mask",
        ingredients=(),
        ingredient_status="missing",
    )
    official = Product.from_mapping(
        {
            "id": "official-example-mask",
            "name": "Z Official Mask",
            "brand": "Official Lab",
            "category": "face_mask",
            "country": "Korea",
            "source_url": "https://example.com/products/mask",
            "official_url": "https://example.com/products/mask",
            "verified_at": "2026-08-02",
            "catalog_source": "official_brand",
            "ingredient_status": "missing",
            "recommendation_tier": "eligible",
        }
    )
    database = ProductDatabase([community, official])
    profile = SkinProfile(desired_categories=["face_mask"])

    assert database.search(categories=["face_mask"], limit=2) == [official, community]
    official_score = IngredientHybridRecommender().score_product(official, profile)
    community_score = IngredientHybridRecommender().score_product(community, profile)
    assert official_score.score_components["source_confidence"] == 2.5
    assert official_score.score > community_score.score


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


@pytest.mark.parametrize(
    "category",
    [
        "face_mask",
        "eye_care",
        "lip_care",
        "exfoliator",
        "body_cleanser",
        "body_moisturizer",
        "body_exfoliator",
        "shampoo",
        "conditioner",
        "hair_treatment",
        "base_makeup",
        "eye_makeup",
        "lip_makeup",
    ],
)
def test_frequent_sensitivity_never_broadens_to_an_unrelated_category(
    category: str,
) -> None:
    reported_target = replace(
        _product(f"reported-{category}"),
        name=f"Example {category}",
        category=category,
    )
    verified_core = _product(
        "verified-core",
        tier="verified",
        ingredient_status="complete",
        source="curated",
    )
    agent = KBeautyAgent(ProductDatabase([reported_target, verified_core]))

    recommendation = agent.recommend(
        f"{category} recommendation",
        structured_profile={
            "skin_type": "normal",
            "sensitivity_level": "frequent",
            "primary_concern": "hydration",
            "concerns": ["hydration"],
            "desired_categories": [category],
        },
    )

    assert recommendation.decision == "fallback"
    assert recommendation.results == []


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
