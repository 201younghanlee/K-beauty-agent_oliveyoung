from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from k_beauty_agent.commerce import CommerceService
from k_beauty_agent.ingestion import sync_retailer_sources
from k_beauty_agent.models import Product
from k_beauty_agent.source_adapters.base import SourceOffer, SourceSyncResult
from k_beauty_agent.storage import SQLiteStore


FETCHED_AT = 1_800_000_000


def _product(product_id: str = "dokdo-200", name: str = "1025 Dokdo Toner 200 ml") -> Product:
    return Product(
        id=product_id,
        name=name,
        brand="Round Lab",
        category="toner",
        country="Korea",
        ingredients=("water",),
    )


def _offer(
    sku: str,
    *,
    url: str = "https://checkout.shop.example/products/dokdo",
    title: str = "1025 Dokdo Toner 200 ml",
    gtin: str | None = None,
    affiliate: bool = False,
    availability: str = "in_stock",
    price: int = 21_000,
) -> SourceOffer:
    return SourceOffer(
        source_id="approved_feed",
        retailer_id="approved-shop",
        retailer_name="Approved Shop",
        merchant_sku=sku,
        title=title,
        brand="Round Lab",
        landing_url=url,
        currency="KRW",
        price=price,
        availability=availability,  # type: ignore[arg-type]
        gtin=gtin,
        affiliate=affiliate,
        observed_at=FETCHED_AT,
        stale_after_seconds=3_600,
        raw={"sku": sku, "price": price},
    )


@dataclass
class FakeSource:
    result: SourceSyncResult
    enabled: bool = True

    def __post_init__(self) -> None:
        self.source_id = self.result.source_id
        self.calls: list[tuple[str, int]] = []

    def fetch(self, query: str, *, limit: int = 20) -> SourceSyncResult:
        self.calls.append((query, limit))
        return self.result


def _service(tmp_path: Path, products: list[Product]) -> tuple[SQLiteStore, CommerceService]:
    store = SQLiteStore(tmp_path / "ingestion.sqlite3")
    service = CommerceService(store, "ingestion-test-signing-secret")
    service.sync_legacy_catalog(products)
    return store, service


def test_affiliate_offer_stays_inactive_until_source_is_explicitly_approved(tmp_path: Path) -> None:
    product = _product()
    store, service = _service(tmp_path, [product])
    source = FakeSource(
        SourceSyncResult(
            "approved_feed",
            (_offer("sku-1", affiliate=True, availability="backorder"),),
            FETCHED_AT,
        )
    )

    pending = sync_retailer_sources(
        service,
        [product],
        query="dokdo toner",
        sources=[source],
        explicit_product_id=product.id,
    )[0]

    assert pending.status == "completed"
    assert pending.offers_persisted == 1
    assert pending.affiliate_active is False
    assert source.calls == [("dokdo toner", 20)]
    with store.connect() as connection:
        retailer = connection.execute("SELECT * FROM retailers WHERE id = 'approved-shop'").fetchone()
        program = connection.execute("SELECT * FROM affiliate_programs").fetchone()
        offer = connection.execute(
            "SELECT * FROM offers WHERE source_kind = 'approved_source:approved_feed'"
        ).fetchone()
        source_record = connection.execute("SELECT * FROM source_records").fetchone()
        candidate = connection.execute("SELECT * FROM match_candidates").fetchone()
        run = connection.execute("SELECT * FROM ingestion_runs WHERE id = ?", (pending.run_id,)).fetchone()
    assert json.loads(retailer["allowed_domains_json"]) == ["checkout.shop.example"]
    assert retailer["base_url"] == "https://checkout.shop.example"
    assert program["status"] == "pending"
    assert offer["active"] == 0
    assert offer["stock_status"] == "unknown"
    assert offer["availability_text"] == "backorder"
    assert source_record["product_id"] == product.id
    source_metadata = json.loads(source_record["metadata_json"])
    assert source_metadata["price"] == 21_000
    assert source_metadata["currency"] == "KRW"
    assert source_metadata["availability"] == "backorder"
    assert candidate["status"] == "linked"
    assert candidate["match_strategy"] == "explicit_product_id"
    assert run["status"] == "completed"

    active = sync_retailer_sources(
        service,
        [product],
        query="dokdo toner",
        sources=[source],
        explicit_product_id=product.id,
        active_affiliate_source_ids={"approved_feed"},
    )[0]

    assert active.status == "completed"
    assert active.affiliate_active is True
    assert active.observations_written == 0
    with store.connect() as connection:
        program = connection.execute("SELECT * FROM affiliate_programs").fetchone()
        offer = connection.execute(
            "SELECT * FROM offers WHERE source_kind = 'approved_source:approved_feed'"
        ).fetchone()
        assert connection.execute("SELECT COUNT(*) FROM source_records").fetchone()[0] == 1
    assert program["status"] == "active"
    assert offer["active"] == 1
    assert offer["affiliate_url"] == "https://checkout.shop.example/products/dokdo"

    source.result = SourceSyncResult("approved_feed", (), FETCHED_AT + 60)
    deactivated = sync_retailer_sources(
        service,
        [product],
        query="dokdo toner",
        sources=[source],
        explicit_product_id=product.id,
    )[0]

    assert deactivated.status == "completed"
    assert deactivated.offers_persisted == 0
    assert deactivated.affiliate_active is False
    with store.connect() as connection:
        program = connection.execute("SELECT * FROM affiliate_programs").fetchone()
        offer = connection.execute(
            "SELECT * FROM offers WHERE source_kind = 'approved_source:approved_feed'"
        ).fetchone()
    assert program["status"] == "pending"
    assert offer["active"] == 0


def test_only_explicit_or_safe_auto_links_are_persisted(tmp_path: Path) -> None:
    products = [
        _product("dokdo-200", "1025 Dokdo Toner"),
        _product("dokdo-special", "1025 Dokdo Toner Special"),
    ]
    store, service = _service(tmp_path, products)
    auto = _offer("sku-auto", title="1025 Dokdo Toner", gtin="4006-3813-3393-1")
    review = _offer("sku-review", title="Round Lab 1025 Dokdo Toner")
    new_candidate = _offer("sku-new", title="Completely Different Cream")
    source = FakeSource(SourceSyncResult("approved_feed", (auto, review, new_candidate), FETCHED_AT))

    report = sync_retailer_sources(
        service,
        products,
        query="dokdo",
        sources=[source],
        identifiers={"4006381333931": {"dokdo-200"}},
    )[0]

    assert report.status == "completed"
    assert report.offers_received == 3
    assert report.offers_persisted == 1
    assert report.review_candidates == 2
    assert report.skipped_offers == 2
    assert report.linked_product_ids == ("dokdo-200",)
    with store.connect() as connection:
        offers = connection.execute(
            "SELECT external_product_id FROM offers WHERE source_kind = 'approved_source:approved_feed'"
        ).fetchall()
        records = connection.execute(
            "SELECT source_record_id, product_id FROM source_records ORDER BY source_record_id"
        ).fetchall()
        candidates = connection.execute(
            "SELECT candidate_product_id, status FROM match_candidates ORDER BY status"
        ).fetchall()
        gtin = connection.execute("SELECT * FROM product_identifiers WHERE identifier_type = 'gtin'").fetchone()
    assert [row["external_product_id"] for row in offers] == ["sku-auto"]
    assert [(row["source_record_id"], row["product_id"]) for row in records] == [
        ("sku-auto", "dokdo-200"),
        ("sku-new", None),
        ("sku-review", None),
    ]
    assert {row["status"] for row in candidates} == {"linked", "pending"}
    assert gtin["identifier_value"] == "4006381333931"


def test_large_price_change_is_quarantined_before_it_changes_public_offer(tmp_path: Path) -> None:
    product = _product()
    store, service = _service(tmp_path, [product])
    safe_source = FakeSource(
        SourceSyncResult("approved_feed", (_offer("sku-price", price=21_000),), FETCHED_AT)
    )
    safe = sync_retailer_sources(
        service,
        [product],
        query="dokdo",
        sources=[safe_source],
        explicit_product_id=product.id,
    )[0]
    assert safe.offers_persisted == 1

    anomalous_source = FakeSource(
        SourceSyncResult("approved_feed", (_offer("sku-price", price=210),), FETCHED_AT + 60)
    )
    anomalous = sync_retailer_sources(
        service,
        [product],
        query="dokdo",
        sources=[anomalous_source],
        explicit_product_id=product.id,
    )[0]

    assert anomalous.status == "completed"
    assert anomalous.offers_persisted == 0
    assert anomalous.review_candidates == 1
    assert any("price_anomaly:price_changed_more_than_5x" in warning for warning in anomalous.warnings)
    with store.connect() as connection:
        offer = connection.execute(
            "SELECT price_amount, active FROM offers WHERE external_product_id = 'sku-price'"
        ).fetchone()
        source_record = connection.execute(
            "SELECT product_id, metadata_json FROM source_records WHERE source_record_id = 'sku-price'"
        ).fetchone()
        candidate = connection.execute(
            "SELECT status, match_strategy FROM match_candidates"
        ).fetchone()
    assert offer["price_amount"] == 21_000
    assert offer["active"] == 1
    assert source_record["product_id"] is None
    assert json.loads(source_record["metadata_json"])["price"] == 210
    assert candidate["status"] == "pending"
    assert candidate["match_strategy"] == "price_anomaly:price_changed_more_than_5x"


def test_current_source_hosts_replace_retired_retailer_domains(tmp_path: Path) -> None:
    product = _product()
    store, service = _service(tmp_path, [product])
    first_source = FakeSource(
        SourceSyncResult(
            "approved_feed",
            (_offer("sku-old", url="https://old.shop.example/products/dokdo"),),
            FETCHED_AT,
        )
    )
    sync_retailer_sources(
        service,
        [product],
        query="dokdo",
        sources=[first_source],
        explicit_product_id=product.id,
    )

    second_source = FakeSource(
        SourceSyncResult(
            "approved_feed",
            (_offer("sku-new", url="https://new.shop.example/products/dokdo"),),
            FETCHED_AT + 60,
        )
    )
    sync_retailer_sources(
        service,
        [product],
        query="dokdo",
        sources=[second_source],
        explicit_product_id=product.id,
    )

    with store.connect() as connection:
        retailer = connection.execute(
            "SELECT allowed_domains_json FROM retailers WHERE id = 'approved-shop'"
        ).fetchone()
        offers = connection.execute(
            "SELECT external_product_id, active FROM offers WHERE source_kind = 'approved_source:approved_feed'"
        ).fetchall()
    assert json.loads(retailer["allowed_domains_json"]) == ["new.shop.example"]
    assert {row["external_product_id"]: row["active"] for row in offers} == {
        "sku-old": 0,
        "sku-new": 1,
    }


def test_invalid_offer_preflight_fails_run_without_partially_persisting_safe_rows(tmp_path: Path) -> None:
    product = _product()
    store, service = _service(tmp_path, [product])
    source = FakeSource(
        SourceSyncResult(
            "approved_feed",
            (
                _offer("safe"),
                _offer("unsafe", url="http://attacker.example/products/unsafe"),
            ),
            FETCHED_AT,
        )
    )

    report = sync_retailer_sources(
        service,
        [product],
        query="dokdo",
        sources=[source],
        explicit_product_id=product.id,
    )[0]

    assert report.status == "failed"
    assert report.offers_persisted == 0
    assert "HTTPS" in str(report.error)
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM retailers WHERE id = 'approved-shop'").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM offers WHERE source_kind = 'approved_source:approved_feed'"
        ).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM source_records").fetchone()[0] == 0
        run = connection.execute("SELECT * FROM ingestion_runs WHERE id = ?", (report.run_id,)).fetchone()
        source_row = connection.execute("SELECT * FROM data_sources WHERE id = 'approved_feed'").fetchone()
    assert run["status"] == "failed"
    assert run["error_text"]
    assert source_row["source_type"] == "approved_retailer_adapter"


def test_public_upsert_failure_compensates_prior_mutations_and_records_failed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _product()
    store, service = _service(tmp_path, [product])
    source = FakeSource(
        SourceSyncResult(
            "approved_feed",
            (
                _offer("first", url="https://shop.example/first"),
                _offer("second", url="https://shop.example/second"),
            ),
            FETCHED_AT,
        )
    )
    original_upsert = service.upsert_offer
    calls = 0

    def fail_second_upsert(**kwargs: object):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated database failure")
        return original_upsert(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service, "upsert_offer", fail_second_upsert)

    report = sync_retailer_sources(
        service,
        [product],
        query="dokdo",
        sources=[source],
        explicit_product_id=product.id,
    )[0]

    assert report.status == "failed"
    assert report.offers_persisted == 0
    assert "simulated database failure" in str(report.error)
    with store.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM offers WHERE source_kind = 'approved_source:approved_feed'"
        ).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM retailers WHERE id = 'approved-shop'").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM source_records").fetchone()[0] == 0
        run = connection.execute("SELECT * FROM ingestion_runs WHERE id = ?", (report.run_id,)).fetchone()
    assert run["status"] == "failed"
    assert json.loads(run["metadata_json"])["rolled_back_offers"] == 1


def test_sync_requires_query_and_does_not_accept_a_runtime_url(tmp_path: Path) -> None:
    product = _product()
    _, service = _service(tmp_path, [product])
    source = FakeSource(SourceSyncResult("approved_feed", (), FETCHED_AT))

    with pytest.raises(ValueError, match="non-empty"):
        sync_retailer_sources(service, [product], query=" ", sources=[source])

    assert source.calls == []
    assert "url" not in sync_retailer_sources.__annotations__


def test_internally_created_source_clients_are_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from k_beauty_agent import ingestion

    product = _product()
    _, service = _service(tmp_path, [product])
    source = FakeSource(SourceSyncResult("approved_feed", (), FETCHED_AT))

    class ClientSpy:
        closed = False

        def close(self) -> None:
            self.closed = True

    client = ClientSpy()
    source.client = client  # type: ignore[attr-defined]
    monkeypatch.setattr(ingestion, "configured_sources", lambda: [source])

    sync_retailer_sources(service, [product], query="dokdo")

    assert client.closed is True
