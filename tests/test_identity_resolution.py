from __future__ import annotations

from k_beauty_agent.identity_resolution import normalize_gtin, resolve_offer
from k_beauty_agent.models import Product
from k_beauty_agent.source_adapters.base import SourceOffer


def product(product_id: str, name: str, brand: str = "Round Lab") -> Product:
    return Product(
        id=product_id,
        name=name,
        brand=brand,
        category="toner",
        country="Korea",
        ingredients=("water",),
    )


def offer(title: str, *, gtin: str | None = None, variant: str | None = None) -> SourceOffer:
    return SourceOffer(
        source_id="test",
        retailer_id="test",
        retailer_name="Test",
        merchant_sku="sku-1",
        title=title,
        brand="Round Lab",
        landing_url="https://shop.example/product",
        currency="KRW",
        gtin=gtin,
        variant=variant,
    )


def test_exact_gtin_links_one_variant() -> None:
    candidate = product("p1", "1025 Dokdo Toner 200 ml")
    result = resolve_offer(
        offer("1025 Dokdo Toner 200ml", gtin="4006-3813-3393-1"),
        [candidate],
        identifiers={"4006381333931": {"p1"}},
    )
    assert result.product_id == "p1"
    assert result.auto_link


def test_gtin_normalization_requires_a_valid_checksum() -> None:
    assert normalize_gtin("4006 3813 3393 1") == "4006381333931"
    assert normalize_gtin("4006381333932") is None


def test_invalid_gtin_is_quarantined_instead_of_falling_back_to_text() -> None:
    candidate = product("p1", "1025 Dokdo Toner 200 ml")
    result = resolve_offer(offer("1025 Dokdo Toner 200ml", gtin="4006381333932"), [candidate])
    assert result.product_id is None
    assert result.status == "review"
    assert result.reason == "invalid_gtin"


def test_size_conflict_is_not_merged_even_with_gtin_mapping() -> None:
    candidate = product("p1", "1025 Dokdo Toner 500 ml")
    result = resolve_offer(offer("1025 Dokdo Toner 200ml", gtin="4006381333931"), [candidate], identifiers={"4006381333931": {"p1"}})
    assert result.product_id is None
    assert result.status == "new_candidate"


def test_variant_field_size_conflict_is_not_merged_with_exact_gtin() -> None:
    candidate = product("p1", "1025 Dokdo Toner 200 ml")
    result = resolve_offer(
        offer("1025 Dokdo Toner", gtin="4006381333931", variant="500ml"),
        [candidate],
        identifiers={"4006381333931": {"p1"}},
    )
    assert result.product_id is None
    assert result.status == "new_candidate"


def test_unknown_canonical_size_is_held_for_review_instead_of_merging_variants() -> None:
    candidate = product("p1", "1025 Dokdo Toner")
    result = resolve_offer(offer("1025 Dokdo Toner", variant="200ml"), [candidate])
    assert result.product_id is None
    assert result.status == "new_candidate"


def test_ambiguous_variants_are_queued_for_review() -> None:
    candidates = [
        product("p1", "1025 Dokdo Toner"),
        product("p2", "1025 Dokdo Toner Special"),
    ]
    result = resolve_offer(offer("Round Lab 1025 Dokdo Toner"), candidates)
    assert result.status == "review"
    assert result.product_id in {"p1", "p2"}


def test_different_brand_does_not_merge() -> None:
    result = resolve_offer(
        SourceOffer(
            source_id="test",
            retailer_id="test",
            retailer_name="Test",
            merchant_sku="sku",
            title="1025 Dokdo Toner",
            brand="Other Brand",
            landing_url="https://shop.example/product",
            currency="KRW",
        ),
        [product("p1", "1025 Dokdo Toner")],
    )
    assert result.status == "new_candidate"
