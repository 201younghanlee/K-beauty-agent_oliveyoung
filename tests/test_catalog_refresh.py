from __future__ import annotations

import csv
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from scripts.refresh_catalog import (
    ATTRIBUTION_URL,
    CATALOG_COLUMNS,
    CatalogRefreshError,
    MAX_SOURCE_AGE_DAYS,
    PUBLIC_RECOMMENDATION_CATEGORIES,
    RefreshStats,
    _front_image_url,
    _category,
    _ingredient_text,
    _ingredient_quality_reason,
    _normalize_record,
    _validate_catalog,
    _split_ingredients,
    main,
    refresh_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "open_beauty_facts_sample.jsonl"
FETCHED_AT = "2026-07-20T01:30:00Z"


def _refresh(tmp_path: Path, **overrides):
    options = {
        "csv_path": tmp_path / "catalog_generated.csv",
        "manifest_path": tmp_path / "catalog_manifest.json",
        "input_path": FIXTURE,
        "fetched_at": FETCHED_AT,
        "min_products": 5,
        "max_drop_ratio": 0.25,
        "max_duplicate_ratio": 0.25,
        "max_malformed_ratio": 0.0,
    }
    options.update(overrides)
    return refresh_catalog(**options)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_refresh_normalizes_supported_categories_and_writes_attribution(tmp_path: Path) -> None:
    result = _refresh(tmp_path)

    csv_path = tmp_path / "catalog_generated.csv"
    manifest_path = tmp_path / "catalog_manifest.json"
    rows = _rows(csv_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert result.product_count == 5
    assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)
    assert set(row["category"] for row in rows) == {
        "cleanser",
        "moisturizer",
        "serum",
        "sunscreen",
        "toner",
    }
    assert tuple(rows[0]) == CATALOG_COLUMNS
    assert not any("price" in column or "stock" in column for column in rows[0])

    sunscreen = next(row for row in rows if row["category"] == "sunscreen")
    assert sunscreen["name"] == "Daily Sun Cream SPF 50"
    assert sunscreen["country"] == "Unknown"
    assert sunscreen["ingredients"] == "Water|Niacinamide|Centella Asiatica (Leaf, Stem) Extract"
    assert sunscreen["source_url"].endswith("/8801234567890")
    assert sunscreen["ingredient_source_url"] == sunscreen["source_url"]
    assert sunscreen["source_updated_at"] == "2025-01-01T00:00:00Z"
    assert sunscreen["fetched_at"] == ""
    assert sunscreen["ingredient_status"] == "reported"
    assert sunscreen["recommendation_tier"] == "eligible"
    assert "ODbL-1.0" in sunscreen["data_license"]
    assert "CC-BY-SA-3.0" in sunscreen["data_license"]
    assert sunscreen["data_attribution_url"] == ATTRIBUTION_URL

    assert manifest["product_count"] == 5
    assert manifest["category_counts"] == {
        "cleanser": 1,
        "moisturizer": 1,
        "serum": 1,
        "sunscreen": 1,
        "toner": 1,
    }
    assert manifest["processing"]["duplicate_rows"] == 1
    assert manifest["processing"]["skipped"] == {
        "invalid_barcode": 1,
        "missing_image": 1,
        "missing_ingredients": 1,
        "too_few_ingredients": 1,
    }
    assert manifest["licenses"]["database"]["id"] == "ODbL-1.0"
    assert manifest["licenses"]["product_images"]["id"] == "CC-BY-SA-3.0"
    assert manifest["attribution"]["name"] == "Open Beauty Facts"
    assert manifest["attribution"]["url"] == ATTRIBUTION_URL
    assert manifest["data_quality"]["ingredient_status"] == "reported"
    assert "not guaranteed complete" in manifest["data_quality"]["notice"]
    assert manifest["safety_thresholds"]["max_source_age_days"] == MAX_SOURCE_AGE_DAYS
    assert manifest["record_freshness"]["as_of"] == FETCHED_AT
    assert manifest["record_freshness"]["dated_products"] == 5
    assert manifest["csv_sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()


def test_same_fixture_and_timestamp_produce_identical_outputs(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    _refresh(first)
    _refresh(second)

    assert (first / "catalog_generated.csv").read_bytes() == (second / "catalog_generated.csv").read_bytes()
    assert (first / "catalog_manifest.json").read_bytes() == (second / "catalog_manifest.json").read_bytes()


def test_front_image_url_is_derived_from_raw_export_image_metadata() -> None:
    record = {
        "lc": "en",
        "images": {
            "front_en": {
                "rev": "6",
                "sizes": {"100": {"w": 48, "h": 100}, "400": {"w": 192, "h": 400}},
            }
        },
    }

    assert _front_image_url(record, "0062600061065") == (
        "https://images.openbeautyfacts.org/images/products/006/260/006/1065/front_en.6.400.jpg"
    )


def test_ingredient_normalization_strips_markup_and_keeps_numeric_commas() -> None:
    from scripts.refresh_catalog import _clean_text, _split_ingredients

    text = _clean_text('Water, <span class="allergen">Shea Butter</span>, 1,2-Hexanediol')

    assert _split_ingredients(text) == ["Water", "Shea Butter", "1,2-Hexanediol"]
    assert _split_ingredients("Aqua. Glycerin. 1,2-Hexanediol") == ["Aqua", "Glycerin", "1,2-Hexanediol"]
    assert _split_ingredients("Aqua • Glycerin | Panthenol") == ["Aqua", "Glycerin", "Panthenol"]


def test_multilingual_label_markers_keep_only_the_ingredient_section() -> None:
    record = {
        "ingredients_text_es": (
            "PARA USO EXTERNO. INGREDIENTES: Aqua, Glycerin, Panthenol. "
            "HECHO EN TAILANDIA. FABRICADO POR: Example Labs"
        )
    }

    assert _split_ingredients(_ingredient_text(record)) == ["Aqua", "Glycerin", "Panthenol"]


@pytest.mark.parametrize(
    "name",
    [
        "Ampoules Hair Rescue",
        "Dry Essence Foot Pack",
        "Kids after sun lotion",
        "Mama Bear Face & Body Cream",
        "Nail Polish Remover",
        "Good-bye Cellulite Serum",
        "WC REINIGER",
        "Lift + Lissage immédiat Gel-Crème Sublime Regard",
        "CREEPY SKIN - WRINKLE SMOOTHENING CREAM",
        "Patch Anti-boutons Format Petit",
    ],
)
def test_non_facial_product_names_override_noisy_source_categories(name: str) -> None:
    assert _category({"categories_tags": ["en:facial-serums", "en:facial-creams"]}, name) is None


def test_generic_or_non_facial_source_categories_are_not_promoted() -> None:
    assert _category({"categories_tags": ["en:serums"]}, "Hydrating Serum") is None
    assert _category({"categories_tags": ["en:body-milks", "en:serums"]}, "Face Serum") is None
    assert _category({"categories_tags": ["en:facial-serums"]}, "Hydrating Serum") == "serum"


def test_hair_color_toner_is_not_promoted_to_facial_toner() -> None:
    record = {
        "categories_tags": ["en:toners"],
        "ingredients_text": "Water, Ammonia, Toluene-2,5-Diamine Sulfate, Ethanolamine",
    }

    assert _category(record, "Bright White Crème Toner Icy White") is None


@pytest.mark.parametrize(
    ("record", "name", "expected"),
    [
        ({"categories_tags": ["en:face-masks"]}, "Hydrating Sheet Mask", "face_mask"),
        ({"categories_tags": ["en:eye-creams"]}, "Replenishing Eye Cream", "eye_care"),
        ({"categories_tags": ["en:lip-balms"]}, "Ceramide Lip Balm", "lip_care"),
        ({"categories_tags": ["en:face-scrubs"]}, "Gentle Face Scrub", "exfoliator"),
        ({"categories_tags": ["en:shampoos"]}, "Repair Shampoo", "shampoo"),
        ({"categories_tags": ["en:hair-conditioners"]}, "Repair Conditioner", "conditioner"),
        ({"categories_tags": ["en:hair-masks"]}, "Repair Hair Mask", "hair_treatment"),
        ({"categories_tags": ["en:shower-gels"]}, "Daily Shower Gel", "body_cleanser"),
        ({"categories_tags": ["en:body-lotions"]}, "Daily Body Lotion", "body_moisturizer"),
        ({"categories_tags": ["en:body-scrubs"]}, "Daily Body Scrub", "body_exfoliator"),
        ({"categories_tags": ["en:face-makeup"]}, "Natural Finish Foundation", "base_makeup"),
        ({"categories_tags": ["en:eyes-makeup"]}, "Lengthening Mascara", "eye_makeup"),
        ({"categories_tags": ["en:lip-cosmetics"]}, "Satin Lipstick", "lip_makeup"),
    ],
)
def test_expanded_beauty_categories_require_explicit_product_forms(
    record: dict[str, object],
    name: str,
    expected: str,
) -> None:
    assert _category(record, name) == expected


@pytest.mark.parametrize(
    ("record", "name", "expected"),
    [
        ({"categories_tags": ["en:hair-masks"]}, "Repair Hair Mask", "hair_treatment"),
        ({"categories_tags": ["en:foot-care"]}, "Dry Essence Foot Pack", None),
        ({"categories_tags": ["en:eyes-makeup"]}, "Glitter Eye Shadow", "eye_makeup"),
        ({"categories_tags": ["en:facial-serums"]}, "Eyelash Growth Serum", None),
        ({"categories_tags": ["en:facial-creams"]}, "Baby Face Cream", None),
    ],
)
def test_expanded_categories_do_not_cross_product_scopes(
    record: dict[str, object],
    name: str,
    expected: str | None,
) -> None:
    assert _category(record, name) == expected


@pytest.mark.parametrize(
    ("record", "name", "expected"),
    [
        ({"categories_tags": ["en:face-makeup"]}, "Makeup Melt Jelly Cleanser", "cleanser"),
        ({"categories_tags": ["en:face-scrubs"]}, "Gentle Skin Cleanser", "cleanser"),
        (
            {"categories_tags": ["en:body-scrubs"]},
            "Cocoa Butter & Shea Gentle Body Wash",
            "body_cleanser",
        ),
        (
            {"categories_tags": ["en:shampoos-shower-gels"]},
            "Essentials Moisturizing Shower Gel",
            "body_cleanser",
        ),
        (
            {"categories_tags": ["en:shampoos"]},
            "Fresh Duschgel",
            "body_cleanser",
        ),
        (
            {"categories_tags": ["en:shampoos", "en:shower-gels"]},
            "Shower Gel & Shampoo 2 in 1",
            None,
        ),
        (
            {"categories_tags": ["en:hair-conditioners"]},
            "Blush care Soin régénérateur de couleur - Rouge",
            "conditioner",
        ),
        (
            {"categories_tags": ["en:lip-cosmetics"]},
            "Stick lèvres réparateur à l'huile de noix",
            "lip_care",
        ),
        (
            {"categories_tags": ["en:facial-creams"]},
            "Perles de Q10 sérum concentré",
            "serum",
        ),
        ({"categories_tags": ["en:face-masks"]}, "Repair Hair Mask", "hair_treatment"),
        ({"categories_tags": ["en:hair-masks"]}, "Hydrating Face Mask", "face_mask"),
        (
            {"code": "8809925136649", "categories_tags": ["en:body-creams"]},
            "Water Bank Hyaluronique Bleu",
            "moisturizer",
        ),
        (
            {"code": "5037156228144", "categories_tags": ["de:concealer"]},
            "concealer Root Blur",
            "hair_treatment",
        ),
        (
            {"code": "0694419061358", "categories_tags": ["en:face-makeup"]},
            "DD Cream",
            "body_moisturizer",
        ),
        (
            {"code": "7707305543203", "categories_tags": ["en:facial-creams"]},
            "Mascarilla hidratante nocturna",
            "face_mask",
        ),
        (
            {"code": "3380810108996", "categories_tags": ["en:body-creams"]},
            "Hydra-Essentiel Bi-Sérum",
            "serum",
        ),
        (
            {"categories_tags": ["en:face-makeup"]},
            "BB Crème Solaire Teinté SPF50",
            "sunscreen",
        ),
        ({"categories_tags": ["en:shampoos"]}, "Nizoral Psoriasis", None),
        ({"categories_tags": ["en:body-creams"]}, "Tolnaftate Cream USP, 1%", None),
        ({"categories_tags": ["en:shampoos"]}, "Shampooing anti poux et lentes", None),
        ({"categories_tags": ["en:shampoos"]}, "Bébé Shampooing très doux", None),
        ({"categories_tags": ["en:shampoos"]}, "Gentle Dog Shampoo", None),
        (
            {
                "generic_name": "Shampoing préventif anti-poux",
                "categories_tags": ["en:shampoos"],
            },
            "Papoo Shampooing des écoles",
            None,
        ),
        (
            {
                "generic_name": "Shampooing antipelliculaire pour chiens",
                "categories_tags": ["en:shampoos"],
            },
            "Shampooing antipelliculaire",
            None,
        ),
        (
            {"categories_tags": ["en:shampoos-for-children"]},
            "Gentle Daily Shampoo",
            None,
        ),
        (
            {
                "brands": "Dermaclay, Dermaclay Junior",
                "categories_tags": ["en:shampoos"],
            },
            "Shampooing abricot pêche lait de coton",
            None,
        ),
        (
            {"brands": "Pethead", "categories_tags": ["en:hair-conditioners"]},
            "I ♥ Pet Head",
            None,
        ),
        ({"categories_tags": ["en:body-creams"]}, "Hand Sanitizer Gel", None),
        (
            {"categories_tags": ["en:face", "en:body"]},
            "Universal Moisturizing Cream",
            None,
        ),
        ({"categories_tags": ["en:face-makeup"]}, "My Burberry Blush Eau de Parfum", None),
        ({"categories_tags": ["en:body-oils"]}, "Cuticle Rehab Oil", None),
        ({"categories_tags": ["en:hand-creams"]}, "Crème mains et ongles", None),
        ({"categories_tags": ["en:hand-creams"]}, "Hand- und Nagelpflege", None),
        ({"categories_tags": ["en:shampoos"]}, "Cottontouch Newborn Wash & Shampoo", None),
        (
            {
                "categories_tags": ["en:facial-cleansers"],
                "ingredients_text": "Benzoyl Peroxide 2.5%, Water, Glycerin",
            },
            "Renewing Cleanser",
            None,
        ),
        (
            {
                "categories_tags": ["en:shampoos"],
                "ingredients_text": "Water, Selenium Sulfide, Glycerin",
            },
            "Purifying Shampoo",
            None,
        ),
        (
            {
                "categories_tags": ["en:shampoos"],
                "ingredients_text": "Water, Zinc Pyrithione, Glycerin",
            },
            "Daily Shampoo",
            None,
        ),
        (
            {
                "categories_tags": ["en:eye-makeup"],
                "ingredients_text": "Water, Isopropylparaben, Glycerin",
            },
            "Daily Mascara",
            None,
        ),
        (
            {
                "categories_tags": ["en:body-lotions"],
                "ingredients_text": "Water, Chloroacetamide, Glycerin",
            },
            "Daily Body Lotion",
            None,
        ),
        (
            {
                "categories_tags": ["en:shampoos"],
                "ingredients_text": "Water, Pentasodium Pentetate, Glycerin",
            },
            "Daily Shampoo",
            None,
        ),
        ({"categories_tags": ["en:shampoos"]}, "2in1-Bart-Shampoo", None),
        ({"categories_tags": ["en:body-washes"]}, "Douche & Rasage", None),
        (
            {"categories_tags": ["en:ice-creams", "en:hand-creams"]},
            "Chocolate Banana Bar",
            None,
        ),
        (
            {
                "code": "8720354199138",
                "categories_tags": ["en:plant-based-foods", "en:shower-gels"],
            },
            "Peach Shower Gel",
            "body_cleanser",
        ),
        (
            {"code": "4084500380622", "categories_tags": ["en:hair-masks"]},
            "H&S Shampooing",
            "shampoo",
        ),
        (
            {"code": "4010355347329", "categories_tags": ["en:shampoos"]},
            "Spülung",
            "conditioner",
        ),
        (
            {"code": "4015100336764", "categories_tags": ["en:shampoos"]},
            "Spülung",
            "conditioner",
        ),
        (
            {
                "categories_tags": ["en:body-lotions"],
                "ingredients_text": "Water, Glycerin, Butylphenyl Methylpropional",
            },
            "Daily Body Lotion",
            None,
        ),
        (
            {
                "categories_tags": ["en:shampoos"],
                "ingredients_text": "Water, Hydroxyisohexyl 3-Cyclohexene Carboxaldehyde, Glycerin",
            },
            "Daily Shampoo",
            None,
        ),
        (
            {"code": "4058172703072", "categories_tags": ["en:shampoos"]},
            "Ocean Princess",
            None,
        ),
        (
            {"code": "0381371174614", "categories_tags": ["en:body-lotions"]},
            "Bedtime Lotion",
            None,
        ),
        (
            {"code": "0860001118643", "categories_tags": ["en:shampoos"]},
            "Hair + Body Wash",
            None,
        ),
        (
            {"code": "8718924879818", "categories_tags": ["en:lip-balms"]},
            "Emoji Movie Lip Balm",
            None,
        ),
        (
            {"code": "4005808134427", "categories_tags": ["en:shampoos"]},
            "Natural Oil",
            None,
        ),
        (
            {"code": "0190679004789", "categories_tags": ["en:shampoos"]},
            "Daily Clean",
            None,
        ),
        (
            {"code": "3760020733100", "categories_tags": ["en:facial-serums"]},
            "Contour yeux & lèvres",
            None,
        ),
        (
            {"code": "0884486453617", "categories_tags": ["en:shampoos"]},
            "Scalp Relief Shampoo",
            None,
        ),
        (
            {"code": "5410306882746", "categories_tags": ["en:shower-gels"]},
            "Douche 2 en 1",
            None,
        ),
        (
            {"code": "3760194652948", "categories_tags": ["en:shower-gels"]},
            "Gel douche",
            None,
        ),
        (
            {"code": "3600542298391", "categories_tags": ["en:facial-sunscreens"]},
            "Natural Bronze Mousse",
            None,
        ),
        (
            {"code": "8052862440090", "categories_tags": ["en:body-lotions"]},
            "Igienizzante mani",
            None,
        ),
        (
            {"code": "3256224363316", "categories_tags": ["en:body-creams"]},
            "Hygiène & Anti Odeur",
            None,
        ),
        (
            {"code": "0073930568964", "categories_tags": ["en:face-makeup"]},
            "Brush-on Striplash Adhesive",
            None,
        ),
        (
            {"code": "3760354680101", "categories_tags": ["en:body-creams"]},
            "Bougie de massage",
            None,
        ),
        (
            {"code": "7700304143955", "categories_tags": ["en:shampoos"]},
            "Acondicionador",
            "conditioner",
        ),
        (
            {"code": "0056594014169", "categories_tags": ["en:shampoos"]},
            "Cleanser Wash & Shampoo",
            None,
        ),
        (
            {"code": "5901887016601", "categories_tags": ["en:shampoos"]},
            "Yego",
            None,
        ),
        (
            {"code": "8015700169317", "categories_tags": ["en:styling-products"]},
            "Mousse per capelli",
            None,
        ),
        (
            {"brands": "bebe", "categories_tags": ["en:makeup-removers"]},
            "3in1 Shake and Clean",
            "cleanser",
        ),
        (
            {"code": "3574661516332", "categories_tags": ["en:bb-creams"]},
            "Natusan",
            None,
        ),
    ],
)
def test_catalog_rejects_or_corrects_known_scope_conflicts(
    record: dict[str, object],
    name: str,
    expected: str | None,
) -> None:
    assert _category(record, name) == expected


def test_soap_based_face_wash_is_not_mislabeled_as_moisturizer() -> None:
    record = {
        "categories_tags": ["en:facial-creams"],
        "ingredients_text": "Water, Potassium Hydroxide, Myristic Acid, Stearic Acid, Lauric Acid",
    }

    assert _category(record, "Effaclar Deep Cleaning Foaming Cream") == "cleanser"


def test_low_quality_ingredient_transcriptions_are_rejected() -> None:
    assert _ingredient_quality_reason(["Water", "Glycerin"]) == "too_few_ingredients"
    assert _ingredient_quality_reason(["Water", "Glycerin", "Manufactured by Example www.example.com"]) == (
        "packaging_text_in_ingredients"
    )
    assert _ingredient_quality_reason(["Water", "Glycerin", "Panthenol"]) is None
    assert _ingredient_quality_reason(
        ["<5% amphoteric surfactants", "<5% anionic surfactants", "water", "citric acid"]
    ) == "packaging_text_in_ingredients"
    assert _ingredient_quality_reason(["Water", "Glycerin", "18RO01 (continued on package)"]) == (
        "packaging_text_in_ingredients"
    )


def test_records_outside_the_source_age_limit_are_rejected() -> None:
    row, reason = _normalize_record(
        {
            "code": "8801234567000",
            "product_type": "beauty",
            "product_name": "Daily Face Moisturizer",
            "brands": "Example",
            "categories_tags": ["en:facial-moisturizers"],
            "ingredients_text": "Water, Glycerin, Panthenol",
            "last_modified_t": 1577836800,
            "image_front_url": "https://images.openbeautyfacts.org/example.jpg",
        },
        fetched_at=FETCHED_AT,
    )

    assert row is None
    assert reason == "stale_source_record"


@pytest.mark.parametrize(
    "preservative",
    ["Methylisothiazolinone", "Methylchloroisothiazolinone"],
)
def test_prohibited_leave_on_preservatives_are_rejected(preservative: str) -> None:
    row, reason = _normalize_record(
        {
            "code": "8801234567001",
            "product_type": "beauty",
            "product_name": "Daily Face Sunscreen",
            "brands": "Example",
            "categories_tags": ["en:facial-sunscreens"],
            "ingredients_text": f"Water, Glycerin, {preservative}",
            "last_modified_t": 1735689600,
            "image_front_url": "https://images.openbeautyfacts.org/example.jpg",
        },
        fetched_at=FETCHED_AT,
    )

    assert row is None
    assert reason == "prohibited_leave_on_ingredient"


def test_placeholder_product_names_are_rejected() -> None:
    row, reason = _normalize_record(
        {
            "code": "7627535303630",
            "product_type": "beauty",
            "product_name": "Wird geladen …",
            "brands": "Example",
            "categories_tags": ["en:shampoos"],
            "ingredients_text": "Water, Glycerin, Panthenol",
            "last_modified_t": 1735689600,
            "image_front_url": "https://images.openbeautyfacts.org/example.jpg",
        },
        fetched_at=FETCHED_AT,
    )

    assert row is None
    assert reason == "invalid_name"


def test_drop_threshold_preserves_previous_outputs(tmp_path: Path) -> None:
    csv_path = tmp_path / "catalog_generated.csv"
    manifest_path = tmp_path / "catalog_manifest.json"
    csv_path.write_bytes(b"existing catalog\n")
    previous_manifest = (
        '{"product_count": 10, "safety_thresholds": '
        f'{{"max_source_age_days": {MAX_SOURCE_AGE_DAYS}}}}}\n'
    )
    manifest_path.write_text(previous_manifest, encoding="utf-8")

    with pytest.raises(CatalogRefreshError, match="Catalog dropped from 10 to 5"):
        _refresh(
            tmp_path,
            csv_path=csv_path,
            manifest_path=manifest_path,
            max_drop_ratio=0.25,
        )

    assert csv_path.read_bytes() == b"existing catalog\n"
    assert manifest_path.read_text(encoding="utf-8") == previous_manifest


def test_first_source_age_policy_migration_allows_a_reviewable_large_drop() -> None:
    rows = [
        {"category": category}
        for category in ("cleanser", "toner", "serum", "moisturizer", "sunscreen")
    ]
    stats = RefreshStats(lines_seen=5, accepted_candidates=5)

    _validate_catalog(
        rows=rows,
        stats=stats,
        previous_count=20,
        previous_category_counts={},
        min_products=1,
        max_drop_ratio=0.25,
        max_duplicate_ratio=0.05,
        max_malformed_ratio=0.001,
        migration_max_drop_ratio=0.85,
    )


def test_category_drop_threshold_preserves_previous_outputs(tmp_path: Path) -> None:
    source = tmp_path / "without-toner.jsonl"
    source.write_text(
        "\n".join(
            line
            for line in FIXTURE.read_text(encoding="utf-8").splitlines()
            if '"code":"8801234567895"' not in line
        )
        + "\n",
        encoding="utf-8",
    )
    csv_path = tmp_path / "catalog_generated.csv"
    manifest_path = tmp_path / "catalog_manifest.json"
    csv_path.write_bytes(b"existing catalog\n")
    manifest_path.write_text(
        json.dumps(
            {
                "product_count": 5,
                "category_counts": {
                    "cleanser": 1,
                    "moisturizer": 1,
                    "serum": 1,
                    "sunscreen": 1,
                    "toner": 1,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(CatalogRefreshError, match="category toner has no eligible products"):
        _refresh(
            tmp_path,
            input_path=source,
            csv_path=csv_path,
            manifest_path=manifest_path,
            min_products=4,
        )

    assert csv_path.read_bytes() == b"existing catalog\n"


def test_legacy_category_counts_are_compared_to_migrated_subtype_totals() -> None:
    rows = [{"category": category} for category in PUBLIC_RECOMMENDATION_CATEGORIES]
    stats = RefreshStats(lines_seen=len(rows), accepted_candidates=len(rows))

    _validate_catalog(
        rows=rows,
        stats=stats,
        previous_count=None,
        previous_category_counts={"body_care": 7, "hair_care": 7, "makeup": 7},
        min_products=1,
        max_drop_ratio=0.25,
        max_duplicate_ratio=0.05,
        max_malformed_ratio=0.001,
    )

    with pytest.raises(CatalogRefreshError, match="category makeup dropped from 10 to 3"):
        _validate_catalog(
            rows=rows,
            stats=stats,
            previous_count=None,
            previous_category_counts={"body_care": 7, "hair_care": 7, "makeup": 10},
            min_products=1,
            max_drop_ratio=0.25,
            max_duplicate_ratio=0.05,
            max_malformed_ratio=0.001,
        )


def test_malformed_json_threshold_fails_without_publishing(tmp_path: Path) -> None:
    source = tmp_path / "malformed.jsonl"
    source.write_bytes(FIXTURE.read_bytes() + b"{not-json}\n")
    csv_path = tmp_path / "catalog_generated.csv"
    manifest_path = tmp_path / "catalog_manifest.json"

    with pytest.raises(CatalogRefreshError, match="Malformed JSON ratio"):
        _refresh(
            tmp_path,
            input_path=source,
            csv_path=csv_path,
            manifest_path=manifest_path,
            max_malformed_ratio=0.05,
        )

    assert not csv_path.exists()
    assert not manifest_path.exists()


def test_cli_accepts_local_gzip_fixture_without_network(tmp_path: Path) -> None:
    compressed_fixture = tmp_path / "sample.jsonl.gz"
    with gzip.GzipFile(filename=compressed_fixture, mode="wb", mtime=0) as handle:
        handle.write(FIXTURE.read_bytes())
    csv_path = tmp_path / "from-cli.csv"
    manifest_path = tmp_path / "from-cli-manifest.json"

    exit_code = main(
        [
            "--input",
            str(compressed_fixture),
            "--output",
            str(csv_path),
            "--manifest",
            str(manifest_path),
            "--fetched-at",
            FETCHED_AT,
            "--min-products",
            "5",
            "--max-duplicate-ratio",
            "0.25",
            "--max-malformed-ratio",
            "0",
        ]
    )

    assert exit_code == 0
    assert len(_rows(csv_path)) == 5
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["source_mode"] == "local_fixture"
