from __future__ import annotations

from fastapi.testclient import TestClient

from k_beauty_agent import web
from k_beauty_agent.ingestion import SourceIngestionReport


class _FakeSource:
    source_id = "approved_feed"
    enabled = True


class _ManualCoupangSource:
    source_id = "coupang_partner_links"
    enabled = True


def test_admin_source_routes_require_auth_and_run_only_configured_source(monkeypatch) -> None:
    client = TestClient(web.app)
    source = _FakeSource()
    calls: list[tuple[str, int, tuple[str, ...]]] = []

    monkeypatch.setattr(web, "_source_registry", [source])
    monkeypatch.setattr(web, "active_affiliate_source_ids", lambda: {"approved_feed"})
    monkeypatch.setattr(
        web.commerce,
        "reconcile_source_activation",
        lambda **_kwargs: {"deactivated_programs": 0, "deactivated_offers": 0},
    )

    def fake_sync(commerce, products, *, query, sources, active_affiliate_source_ids, limit):
        del commerce, products
        calls.append((query, limit, tuple(item.source_id for item in sources)))
        return (
            SourceIngestionReport(
                source_id="approved_feed",
                run_id=len(calls),
                status="completed",
                fetched_at=1_784_505_600,
                offers_received=2,
                offers_persisted=1,
                observations_written=1,
                linked_product_ids=("example-serum",),
                review_candidates=1,
                skipped_offers=1,
                affiliate_active=True,
            ),
        )

    monkeypatch.setattr(web, "sync_retailer_sources", fake_sync)
    assert client.get("/api/admin/sources").status_code == 401
    assert client.post("/api/admin/sources/sync", json={"query": "serum"}).status_code == 401

    headers = {"X-Admin-Token": web.admin_token()}
    status = client.get("/api/admin/sources", headers=headers)
    assert status.status_code == 200
    assert status.json()["sources"] == [{"source_id": "approved_feed", "enabled": True}]
    assert status.json()["active_affiliate_source_ids"] == ["approved_feed"]

    response = client.post(
        "/api/admin/sources/sync",
        headers=headers,
        json={
            "query": "serum",
            "queries": ["serum", "cleanser"],
            "source_id": "approved_feed",
            "limit": 5,
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert [report["query"] for report in response.json()["reports"]] == ["serum", "cleanser"]
    assert calls == [("serum", 5, ("approved_feed",)), ("cleanser", 5, ("approved_feed",))]


def test_admin_source_sync_rejects_empty_or_unknown_source(monkeypatch) -> None:
    client = TestClient(web.app)
    monkeypatch.setattr(web, "_source_registry", [_FakeSource()])
    monkeypatch.setattr(web, "active_affiliate_source_ids", lambda: set())
    headers = {"X-Admin-Token": web.admin_token()}

    assert client.post("/api/admin/sources/sync", headers=headers, json={}).status_code == 400
    response = client.post(
        "/api/admin/sources/sync",
        headers=headers,
        json={"query": "serum", "source_id": "not_configured"},
    )
    assert response.status_code == 400
    assert "No enabled source" in response.json()["detail"]


def test_admin_reload_invalid_manual_config_deactivates_previous_source(monkeypatch) -> None:
    client = TestClient(web.app)
    monkeypatch.setattr(web, "_source_registry", [_ManualCoupangSource(), _FakeSource()])
    monkeypatch.setattr(web, "_build_agent", lambda: web.agent)
    monkeypatch.setattr(web.commerce, "sync_legacy_catalog", lambda _products: {})
    monkeypatch.setattr(
        web,
        "configured_sources",
        lambda **_kwargs: (_ for _ in ()).throw(
            ValueError("COUPANG_PARTNERS_LINKS_JSON must contain valid JSON")
        ),
    )
    monkeypatch.setattr(
        web,
        "active_affiliate_source_ids",
        lambda: {"coupang_partner_links", "approved_feed"},
    )
    reconciliations: list[dict[str, set[str]]] = []

    def reconcile(**kwargs):
        reconciliations.append(
            {
                "configured": set(kwargs["configured_source_ids"]),
                "approved": set(kwargs["approved_affiliate_source_ids"]),
            }
        )
        return {"programs_changed": 1, "offers_deactivated": 1}

    monkeypatch.setattr(web.commerce, "reconcile_source_activation", reconcile)
    response = client.post(
        "/api/admin/reload",
        headers={"X-Admin-Token": web.admin_token()},
    )

    assert response.status_code == 400
    assert "COUPANG_PARTNERS_LINKS_JSON" in response.json()["detail"]
    assert reconciliations == [
        {
            "configured": {"approved_feed"},
            "approved": {"coupang_partner_links", "approved_feed"},
        }
    ]


def test_admin_source_candidates_require_auth_and_forward_pagination(monkeypatch) -> None:
    calls: list[tuple[str | None, int, int]] = []

    class _FakeCommerce:
        def source_review_candidates(self, *, source_id, limit, cursor):
            calls.append((source_id, limit, cursor))
            return {
                "items": [{"source_record_id": "sku-1"}],
                "total": 1,
                "next_cursor": None,
                "policy": "manual_review_required",
            }

    monkeypatch.setattr(web, "commerce", _FakeCommerce())
    client = TestClient(web.app)
    assert client.get("/api/admin/source-candidates").status_code == 401

    response = client.get(
        "/api/admin/source-candidates?source_id=approved_feed&limit=25&cursor=5",
        headers={"X-Admin-Token": web.admin_token()},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["source_record_id"] == "sku-1"
    assert calls == [("approved_feed", 25, 5)]
