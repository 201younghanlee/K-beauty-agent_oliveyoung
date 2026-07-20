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
    _front_image_url,
    _category,
    _ingredient_text,
    _ingredient_quality_reason,
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
        "unsupported_category": 1,
    }
    assert manifest["licenses"]["database"]["id"] == "ODbL-1.0"
    assert manifest["licenses"]["product_images"]["id"] == "CC-BY-SA-3.0"
    assert manifest["attribution"]["name"] == "Open Beauty Facts"
    assert manifest["attribution"]["url"] == ATTRIBUTION_URL
    assert manifest["data_quality"]["ingredient_status"] == "reported"
    assert "not guaranteed complete" in manifest["data_quality"]["notice"]
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


def test_drop_threshold_preserves_previous_outputs(tmp_path: Path) -> None:
    csv_path = tmp_path / "catalog_generated.csv"
    manifest_path = tmp_path / "catalog_manifest.json"
    csv_path.write_bytes(b"existing catalog\n")
    manifest_path.write_text('{"product_count": 10}\n', encoding="utf-8")

    with pytest.raises(CatalogRefreshError, match="Catalog dropped from 10 to 5"):
        _refresh(
            tmp_path,
            csv_path=csv_path,
            manifest_path=manifest_path,
            max_drop_ratio=0.25,
        )

    assert csv_path.read_bytes() == b"existing catalog\n"
    assert manifest_path.read_text(encoding="utf-8") == '{"product_count": 10}\n'


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
