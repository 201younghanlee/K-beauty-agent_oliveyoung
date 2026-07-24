from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from k_beauty_agent.catalog_links import (
    information_links,
    retailer_links,
    retailer_search_links,
)
from k_beauty_agent.database import ProductDatabase
from k_beauty_agent.models import Product
from k_beauty_agent.serializers import product_to_v2_dict


def _product() -> Product:
    return Product(
        id="etude-soonjung",
        name="SoonJung 2x Barrier Intensive Cream",
        display_name_ko="에뛰드 순정 2x 베리어 인텐시브 크림",
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
    assert [link.link_type for link in retailers] == [
        "retailer_search",
        "product_page",
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


def test_retailer_search_links_expand_discovery_without_claiming_an_exact_listing() -> None:
    product = replace(
        _product(),
        brand="ETUDE",
        name="SoonJung 2x Barrier\nIntensive Cream",
        display_name_ko="에뛰드 순정 2x 베리어\n인텐시브 크림",
    )

    links = retailer_search_links(product)

    assert [link.provider for link in links] == [
        "Naver Shopping",
        "Coupang",
        "Musinsa Beauty",
        "YesStyle",
    ]
    assert all(link.kind == "retailer" for link in links)
    assert all(link.link_type == "retailer_search" for link in links)
    assert all(link.source_field == "retailer_search" for link in links)
    assert all(link.provider != "Olive Young" for link in links)
    assert all(link.url.startswith("https://") for link in links)
    queries = []
    for link in links:
        params = parse_qs(urlparse(link.url).query)
        queries.append(next(params[key][0] for key in ("query", "q", "keyword") if key in params))
    assert queries == ["에뛰드 순정 2x 베리어 인텐시브 크림"] * 4


def test_retailer_search_uses_korean_category_when_localized_name_is_missing() -> None:
    product = replace(
        _product(),
        name="ETUDE SoonJung 2x Barrier Intensive Cream",
        display_name_ko=None,
    )

    links = retailer_search_links(product)
    queries = []
    for link in links:
        params = parse_qs(urlparse(link.url).query)
        queries.append(next(params[key][0] for key in ("query", "q", "keyword") if key in params))

    assert queries == ["보습제 ETUDE SoonJung 2x Barrier Intensive Cream"] * 4
    assert all(any("가" <= character <= "힣" for character in query) for query in queries)


def test_untranslated_retailer_search_starts_with_korean_product_type() -> None:
    product = replace(
        _product(),
        brand="Aroma zone",
        name="Gel douche sorbet de verveine",
        display_name_ko=None,
        category="body_cleanser",
    )

    link = retailer_search_links(product)[0]
    query = parse_qs(urlparse(link.url).query)["query"][0]

    assert query == "바디워시 Aroma zone Gel douche sorbet de verveine"


def test_retailer_search_links_can_skip_a_retailer_with_a_specific_offer() -> None:
    links = retailer_search_links(_product(), exclude_providers={"coupang"})

    assert "Coupang" not in {link.provider for link in links}
    assert len(links) == 3


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
