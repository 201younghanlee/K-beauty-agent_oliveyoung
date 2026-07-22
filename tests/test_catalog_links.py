from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from k_beauty_agent.catalog_links import information_links, retailer_links
from k_beauty_agent.database import ProductDatabase
from k_beauty_agent.models import Product
from k_beauty_agent.serializers import product_to_v2_dict


def _product() -> Product:
    return Product(
        id="etude-soonjung",
        name="SoonJung 2x Barrier Intensive Cream",
        brand="ETUDE",
        category="moisturizer",
        country="Korea",
        ingredients=("Panthenol",),
        purchase_url="https://www.oliveyoung.co.kr/store/search/getSearchMain.do?query=soonjung",
        retailer_name="Olive Young",
        oliveyoung_url="https://www.oliveyoung.co.kr/store/search/getSearchMain.do?query=soonjung",
        source_url="https://www.ulta.com/p/soonjung-2x-barrier-intensive-cream-pimprod2049666",
        official_url="https://www.etude.com/int/en/index.php/soonjung-2x-barrier-intensive-cream-60ml.html",
        ingredient_source_url="https://incidecoder.com/products/etude-house-soon-jung-2x-barrier-intensive-cream",
        review_source_url="https://www.ulta.com/p/soonjung-2x-barrier-intensive-cream-pimprod2049666",
        data_attribution_url="https://world.openbeautyfacts.org/product/123/example",
    )


def test_catalog_links_separate_retailers_from_product_information() -> None:
    product = _product()

    retailers = retailer_links(product)
    information = information_links(product)

    assert [(link.provider, link.source_field) for link in retailers] == [
        ("Olive Young", "purchase_url"),
        ("Ulta Beauty", "source_url"),
    ]
    assert [(link.kind, link.provider) for link in information] == [
        ("brand_official", "ETUDE"),
        ("ingredient_reference", "INCIDecoder"),
        ("review_reference", "Ulta Beauty"),
        ("data_reference", "Open Beauty Facts"),
    ]


def test_unreviewed_insecure_and_lookalike_links_fail_closed() -> None:
    product = replace(
        _product(),
        purchase_url=None,
        retailer_name="Unreviewed Shop",
        oliveyoung_url="https://www.oliveyoung.co.kr.attacker.example/product",
        source_url="http://www.ulta.com/product",
        official_url="https://unreviewed-shop.example/product",
        ingredient_source_url="https://incidecoder.com.attacker.example/product",
        review_source_url=None,
        data_attribution_url=None,
    )

    assert retailer_links(product) == []
    assert information_links(product) == []


def test_marks_and_spencer_is_a_retailer_but_brand_page_is_information() -> None:
    product = Product(
        id="boj-sun-stick",
        name="Matte Sun Stick",
        brand="Beauty of Joseon",
        category="sunscreen",
        country="Korea",
        ingredients=("Silica",),
        source_url="https://www.marksandspencer.com/matte-sun-stick/p/hbp61218671",
        official_url="https://beautyofjoseon.com/products/matte-sun-stick",
    )

    assert [link.provider for link in retailer_links(product)] == ["Marks & Spencer"]
    assert [link.kind for link in information_links(product)] == ["brand_official"]


def test_v2_serializer_exposes_information_links_without_raw_purchase_fields() -> None:
    data = product_to_v2_dict(_product())

    assert "purchase_url" not in data
    assert "oliveyoung_url" not in data
    assert {link["kind"] for link in data["external_links"]} == {
        "brand_official",
        "ingredient_reference",
        "data_reference",
        "review_reference",
    }
    assert all(link["url"].startswith("https://") for link in data["external_links"])


def test_review_summary_source_url_is_loaded_into_product_sources() -> None:
    data_dir = Path(__file__).resolve().parents[1] / "data"
    database = ProductDatabase.from_csv(
        data_dir / "products_verified.csv",
        data_dir / "review_summaries.csv",
    )

    product = database.get("etude-soonjung-2x-barrier-intensive-cream")

    assert product is not None
    assert product.review_source_url == (
        "https://www.ulta.com/p/soonjung-2x-barrier-intensive-cream-pimprod2049666"
    )
    review_links = [
        link for link in information_links(product) if link.kind == "review_reference"
    ]
    assert len(review_links) == 1
    assert review_links[0].provider == "Ulta Beauty"


def test_ingredient_or_regulatory_pages_are_not_labeled_as_review_evidence() -> None:
    data_dir = Path(__file__).resolve().parents[1] / "data"
    database = ProductDatabase.from_csv(
        data_dir / "products_verified.csv",
        data_dir / "review_summaries.csv",
    )

    for product_id in (
        "illiyoon-ceramide-ato-concentrate-cream",
        "dr-g-green-mild-up-sun-plus",
        "anua-heartleaf-silky-moisture-sun-cream",
    ):
        product = database.get(product_id)
        assert product is not None
        assert product.review_source_url is None
        assert product.review_verified_at is None
