from __future__ import annotations

import json
from pathlib import Path

import pytest

from k_beauty_agent.commerce import CommerceService, RedirectTokenError
from k_beauty_agent.ingestion import sync_retailer_sources
from k_beauty_agent.models import Product
from k_beauty_agent.source_adapters.coupang_partner_links import (
    COUPANG_PARTNERS_DISCLOSURE_KO,
    MAX_COUPANG_PARTNER_LINKS,
    CoupangPartnerLinksAdapter,
    parse_coupang_partner_links,
)
from k_beauty_agent.source_adapters.coupang_partners import CoupangPartnersAdapter
from k_beauty_agent.source_adapters.registry import configured_sources, source_status
from k_beauty_agent.storage import SQLiteStore


def _product(product_id: str) -> Product:
    return Product(
        id=product_id,
        name=f"Product {product_id}",
        brand="Example",
        category="serum",
        country="Korea",
        ingredients=("water",),
    )


def _adapter(*entries: dict[str, str]) -> CoupangPartnerLinksAdapter:
    return CoupangPartnerLinksAdapter(json.dumps(entries))


def _service(tmp_path: Path, products: list[Product]) -> tuple[SQLiteStore, CommerceService]:
    store = SQLiteStore(tmp_path / "manual-coupang.sqlite3")
    service = CommerceService(store, "manual-coupang-test-signing-secret")
    service.sync_legacy_catalog(products)
    return store, service


def test_coupang_api_and_manual_links_use_the_same_official_disclosure() -> None:
    assert CoupangPartnersAdapter.affiliate_program_name == "쿠팡 파트너스"
    assert CoupangPartnersAdapter.affiliate_disclosure_ko == COUPANG_PARTNERS_DISCLOSURE_KO


def test_manual_coupang_link_config_is_strict_and_shown_in_source_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = json.dumps(
        [
            {
                "product_id": "example-serum",
                "affiliate_url": "https://link.coupang.com/a/example?traceid=abc",
            }
        ]
    )
    monkeypatch.delenv("COUPANG_PARTNERS_ACCESS_KEY", raising=False)
    monkeypatch.delenv("COUPANG_PARTNERS_SECRET_KEY", raising=False)
    monkeypatch.delenv("PARTNER_FEEDS_JSON", raising=False)
    monkeypatch.setenv("COUPANG_PARTNERS_LINKS_JSON", raw)

    sources = configured_sources()
    assert [source.source_id for source in sources] == ["coupang_partner_links"]
    assert source_status(sources) == [
        {
            "source_id": "coupang_partner_links",
            "enabled": True,
            "kind": "manual_affiliate_links",
            "configured_links": 1,
            "authoritative_snapshot": True,
        }
    ]


@pytest.mark.parametrize(
    "entry",
    [
        {
            "product_id": "example-serum",
            "affiliate_url": "https://www.coupang.com/vp/products/1",
        },
        {
            "product_id": "example-serum",
            "affiliate_url": "http://link.coupang.com/a/example",
        },
        {
            "product_id": "example-serum",
            "affiliate_url": "https://sub.link.coupang.com/a/example",
        },
        {
            "product_id": "example-serum",
            "affiliate_url": "https://link.coupang.com/",
        },
        {
            "product_id": "example-serum",
            "affiliate_url": "https://link.coupang.com/re/SHARE123",
        },
        {
            "product_id": "example-serum",
            "affiliate_url": "https://link.coupang.com/a/example#fragment",
        },
        {
            "product_id": "example-serum",
            "affiliate_url": "https://link.coupang.com/a/example",
            "title": "untrusted extra field",
        },
    ],
)
def test_manual_coupang_link_config_rejects_non_partner_or_extra_data(
    entry: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        parse_coupang_partner_links(json.dumps([entry]))


def test_manual_coupang_link_config_rejects_duplicates_and_excessive_count() -> None:
    with pytest.raises(ValueError, match="Duplicate.*product_id"):
        parse_coupang_partner_links(
            json.dumps(
                [
                    {
                        "product_id": "same",
                        "affiliate_url": "https://link.coupang.com/a/one",
                    },
                    {
                        "product_id": "same",
                        "affiliate_url": "https://link.coupang.com/a/two",
                    },
                ]
            )
        )
    with pytest.raises(ValueError, match="Duplicate.*affiliate_url"):
        parse_coupang_partner_links(
            json.dumps(
                [
                    {
                        "product_id": "one",
                        "affiliate_url": "https://link.coupang.com/a/same",
                    },
                    {
                        "product_id": "two",
                        "affiliate_url": "https://link.coupang.com/a/same",
                    },
                ]
            )
        )
    too_many = [
        {
            "product_id": f"product-{index}",
            "affiliate_url": f"https://link.coupang.com/a/{index}",
        }
        for index in range(MAX_COUPANG_PARTNER_LINKS + 1)
    ]
    with pytest.raises(ValueError, match="at most"):
        parse_coupang_partner_links(json.dumps(too_many))


def test_manual_coupang_links_require_exact_catalog_products_and_explicit_activation(
    tmp_path: Path,
) -> None:
    product = _product("example-serum")
    store, service = _service(tmp_path, [product])
    source = _adapter(
        {
            "product_id": product.id,
            "affiliate_url": "https://link.coupang.com/a/example",
        }
    )

    pending = sync_retailer_sources(
        service,
        [product],
        query="configured-manual-links",
        sources=[source],
    )[0]
    assert pending.status == "completed"
    assert pending.affiliate_active is False
    with store.connect() as connection:
        offer = connection.execute(
            "SELECT id, active FROM offers WHERE source_kind = 'approved_source:coupang_partner_links'"
        ).fetchone()
    assert offer["active"] == 0
    with store.connect() as connection:
        connection.execute("UPDATE offers SET active = 1 WHERE id = ?", (offer["id"],))
    inconsistent = service.offers_for_product(product.id)
    pending_offer = next(item for item in inconsistent["offers"] if item["id"] == offer["id"])
    assert pending_offer["redirect_url"] is None
    with pytest.raises(RedirectTokenError, match="inactive"):
        service.create_redirect_token(str(offer["id"]))

    active = sync_retailer_sources(
        service,
        [product],
        query="configured-manual-links",
        sources=[source],
        active_affiliate_source_ids={"coupang_partner_links"},
    )[0]
    assert active.status == "completed"
    assert active.affiliate_active is True
    with store.connect() as connection:
        program = connection.execute(
            "SELECT * FROM affiliate_programs WHERE status = 'active'"
        ).fetchone()
        offer = connection.execute(
            """
            SELECT active, affiliate_url, metadata_json
            FROM offers WHERE source_kind = 'approved_source:coupang_partner_links'
            """
        ).fetchone()
    assert program["program_name"] == "쿠팡 파트너스"
    assert program["disclosure_ko"] == COUPANG_PARTNERS_DISCLOSURE_KO
    assert json.loads(program["metadata_json"])["manual_affiliate_links"] is True
    assert offer["active"] == 1
    assert offer["affiliate_url"] == "https://link.coupang.com/a/example"
    assert json.loads(offer["metadata_json"])["link_only"] is True

    unknown = _adapter(
        {
            "product_id": "not-in-catalog",
            "affiliate_url": "https://link.coupang.com/a/unknown",
        }
    )
    failed = sync_retailer_sources(
        service,
        [product],
        query="configured-manual-links",
        sources=[unknown],
        active_affiliate_source_ids={"coupang_partner_links"},
    )[0]
    assert failed.status == "failed"
    assert "not in the catalog" in (failed.error or "")
    with store.connect() as connection:
        assert connection.execute(
            """
            SELECT active FROM offers
            WHERE source_kind = 'approved_source:coupang_partner_links'
            """
        ).fetchone()["active"] == 0
        assert connection.execute(
            "SELECT status FROM affiliate_programs WHERE retailer_id = 'coupang-partner-links'"
        ).fetchone()["status"] == "pending"


def test_manual_coupang_snapshot_is_idempotent_and_deactivates_removed_links(
    tmp_path: Path,
) -> None:
    products = [_product("first"), _product("second")]
    store, service = _service(tmp_path, products)
    first_source = _adapter(
        {
            "product_id": "first",
            "affiliate_url": "https://link.coupang.com/a/first",
        },
        {
            "product_id": "second",
            "affiliate_url": "https://link.coupang.com/a/second",
        },
    )
    for _ in range(2):
        report = sync_retailer_sources(
            service,
            products,
            query="configured-manual-links",
            sources=[first_source],
            active_affiliate_source_ids={"coupang_partner_links"},
        )[0]
        assert report.status == "completed"
    with store.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM offers WHERE source_kind = 'approved_source:coupang_partner_links'"
        ).fetchone()[0] == 2

    second_source = _adapter(
        {
            "product_id": "second",
            "affiliate_url": "https://link.coupang.com/a/second-updated",
        }
    )
    sync_retailer_sources(
        service,
        products,
        query="configured-manual-links",
        sources=[second_source],
        active_affiliate_source_ids={"coupang_partner_links"},
    )
    with store.connect() as connection:
        rows = connection.execute(
            """
            SELECT p.id AS product_id, o.active, o.affiliate_url
            FROM offers o
            JOIN product_variants v ON v.id = o.variant_id
            JOIN products p ON p.id = v.product_id
            WHERE o.source_kind = 'approved_source:coupang_partner_links'
            ORDER BY p.id
            """
        ).fetchall()
    assert [(row["product_id"], row["active"], row["affiliate_url"]) for row in rows] == [
        ("first", 0, "https://link.coupang.com/a/first"),
        ("second", 1, "https://link.coupang.com/a/second-updated"),
    ]


def test_only_marked_manual_link_only_offer_can_redirect_when_stale(tmp_path: Path) -> None:
    product = _product("example-serum")
    store, service = _service(tmp_path, [product])
    source = _adapter(
        {
            "product_id": product.id,
            "affiliate_url": "https://link.coupang.com/a/example",
        }
    )
    sync_retailer_sources(
        service,
        [product],
        query="configured-manual-links",
        sources=[source],
        active_affiliate_source_ids={"coupang_partner_links"},
    )
    with store.connect() as connection:
        row = connection.execute(
            "SELECT id FROM offers WHERE source_kind = 'approved_source:coupang_partner_links'"
        ).fetchone()
        offer_id = str(row["id"])
        connection.execute(
            "UPDATE offers SET checked_at = 1, stale_after = 2 WHERE id = ?",
            (offer_id,),
        )

    public = service.offers_for_product(product.id, now=10)
    offer = next(item for item in public["offers"] if item["id"] == offer_id)
    assert offer["freshness"]["status"] == "stale"
    assert offer["link_only"] is True
    assert offer["redirect_url"]
    token = offer["redirect_url"].removeprefix("/r/")
    assert service.resolve_redirect_token(token, now=10).url == (
        "https://link.coupang.com/a/example"
    )

    with store.connect() as connection:
        connection.execute(
            """
            UPDATE offers
            SET source_kind = 'approved_source:other',
                metadata_json = '{"link_only":true,"stale_redirect_allowed":true}'
            WHERE id = ?
            """,
            (offer_id,),
        )
    with pytest.raises(RedirectTokenError, match="stale"):
        service.create_redirect_token(offer_id, now=10)
