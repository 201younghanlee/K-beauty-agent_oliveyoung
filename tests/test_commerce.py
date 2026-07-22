from __future__ import annotations

import sqlite3
import hashlib
import hmac
import json
import time
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from k_beauty_agent.agent import KBeautyAgent
from k_beauty_agent.commerce import CommerceService, RedirectTokenError
from k_beauty_agent.database import ProductDatabase
from k_beauty_agent.knowledge_base import INGREDIENT_EVIDENCE
from k_beauty_agent.localization import translate_caution
from k_beauty_agent.models import Product, ProductScore
from k_beauty_agent.serializers import (
    _date_status,
    fallback_personalized_reason,
    ingredient_explanations,
    score_to_dict,
)
from k_beauty_agent.storage import SQLiteStore, hash_session


def _product(product_id: str = "example-serum", *, name: str = "Example Serum") -> Product:
    return Product(
        id=product_id,
        name=name,
        brand="Example Lab",
        category="serum",
        country="Korea",
        ingredients=("Glycerin", "Panthenol"),
        suited_skin_types=("dry",),
        concerns=("hydration",),
        purchase_url=f"https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo={product_id}",
        retailer_name="Olive Young",
        price_krw=19_000,
        price_checked_at="2026-07-20T00:00:00Z",
    )


def _service(tmp_path: Path, products: list[Product] | None = None) -> tuple[SQLiteStore, CommerceService]:
    store = SQLiteStore(tmp_path / "commerce.sqlite3")
    service = CommerceService(store, "commerce-test-signing-secret")
    service.sync_legacy_catalog(products or [_product()])
    return store, service


def test_commerce_schema_and_legacy_backfill_are_idempotent(tmp_path: Path) -> None:
    store, service = _service(tmp_path)

    second = service.sync_legacy_catalog([_product()])

    expected_tables = {
        "products",
        "product_variants",
        "retailers",
        "offers",
        "offer_observations",
        "affiliate_programs",
        "affiliate_clicks",
        "affiliate_conversions",
        "ingestion_runs",
        "data_sources",
        "product_identifiers",
        "source_records",
        "ingredient_snapshots",
        "match_candidates",
        "legacy_product_ids",
    }
    with store.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        assert expected_tables <= tables
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM product_variants").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM legacy_product_ids").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM offers").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM offer_observations").fetchone()[0] == 1
    assert second == {"products_seen": 1, "offers_seen": 1, "observations_written": 0}


def test_legacy_catalog_adds_verified_retailers_without_reusing_oliveyoung_price(
    tmp_path: Path,
) -> None:
    product = Product(
        id="etude-soonjung",
        name="SoonJung 2x Barrier Intensive Cream",
        brand="ETUDE",
        category="moisturizer",
        country="Korea",
        ingredients=("Panthenol",),
        purchase_url="https://www.oliveyoung.co.kr/store/search/getSearchMain.do?query=soonjung",
        retailer_name="Olive Young",
        oliveyoung_url="https://www.oliveyoung.co.kr/store/search/getSearchMain.do?query=soonjung",
        price_krw=23_000,
        price_checked_at="2026-07-20T00:00:00Z",
        source_url="https://www.ulta.com/p/soonjung-2x-barrier-intensive-cream-pimprod2049666",
        official_url="https://www.etude.com/int/en/index.php/soonjung-2x-barrier-intensive-cream.html",
        ingredient_source_url="https://incidecoder.com/products/etude-house-soon-jung",
    )
    store, service = _service(tmp_path, [product])

    second = service.sync_legacy_catalog([product])
    bundle = service.offers_for_product(product.id)

    assert bundle["summary"]["offer_count"] == 2
    assert bundle["summary"]["retailer_count"] == 2
    assert {offer["retailer"]["name"] for offer in bundle["offers"]} == {
        "Olive Young",
        "Ulta Beauty",
    }
    assert all(offer["link_only"] is True for offer in bundle["offers"])
    assert all(offer["redirect_url"].startswith("/r/") for offer in bundle["offers"])
    with store.connect() as connection:
        rows = connection.execute(
            """
            SELECT r.display_name, o.destination_url, o.price_amount, o.checked_at
            FROM offers o JOIN retailers r ON r.id = o.retailer_id
            ORDER BY r.display_name
            """
        ).fetchall()
    by_retailer = {row["display_name"]: dict(row) for row in rows}
    assert by_retailer["Olive Young"]["price_amount"] == 23_000
    assert by_retailer["Olive Young"]["checked_at"] is not None
    assert by_retailer["Ulta Beauty"]["price_amount"] is None
    assert by_retailer["Ulta Beauty"]["checked_at"] is None
    assert all("incidecoder.com" not in row["destination_url"] for row in rows)
    assert all("etude.com" not in row["destination_url"] for row in rows)
    assert second == {"products_seen": 1, "offers_seen": 2, "observations_written": 0}


def test_open_beauty_facts_gtin_is_seeded_for_first_retailer_match(tmp_path: Path) -> None:
    obf_product = replace(
        _product(),
        catalog_source="open_beauty_facts",
        source_product_id="4006381333931",
    )
    store, _ = _service(tmp_path, [obf_product])

    with store.connect() as connection:
        row = connection.execute(
            "SELECT product_id, identifier_value, confidence FROM product_identifiers"
        ).fetchone()

    assert dict(row) == {
        "product_id": "example-serum",
        "identifier_value": "4006381333931",
        "confidence": 1.0,
    }


def test_stale_offer_hides_price_and_stock_but_keeps_checked_time(tmp_path: Path) -> None:
    _, service = _service(tmp_path)

    bundle = service.offers_for_product("example-serum", now=1_784_676_000)

    offer = bundle["offers"][0]
    assert offer["freshness"]["status"] == "stale"
    assert offer["price"] == {"amount": None, "currency": "KRW", "status": "stale"}
    assert offer["stock_status"] == "unknown"
    assert offer["freshness"]["checked_at"] == "2026-07-20T00:00:00Z"
    assert offer["link_only"] is True
    assert offer["redirect_url"].startswith("/r/")
    token = offer["redirect_url"].removeprefix("/r/")
    assert service.resolve_redirect_token(token, now=1_784_676_000).url == (
        "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=example-serum"
    )
    assert bundle["summary"]["best_current_price"] is None


def test_redirect_token_stops_working_when_offer_becomes_stale(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    service.upsert_retailer(
        retailer_id="live-shop",
        display_name="Live Shop",
        base_url="https://live.example.com",
        allowed_domains=["live.example.com"],
    )
    service.upsert_offer(
        product_id="example-serum",
        retailer_id="live-shop",
        destination_url="https://live.example.com/products/example-serum",
        source_kind="approved_partner_feed",
        offer_id="live-offer",
        checked_at=100,
        ttl_seconds=60,
    )

    token = service.create_redirect_token("live-offer", now=100)
    with pytest.raises(RedirectTokenError, match="stale"):
        service.resolve_redirect_token(token, now=161)


def test_price_diagnostics_do_not_leak_into_customer_copy() -> None:
    score = ProductScore(
        product=_product(),
        score=5.0,
        reasons=["category matches requested type: serum"],
        cautions=["checked price is missing, so cannot verify under ₩50,000"],
    )

    assert "checked" not in translate_caution(score.cautions[0], "ko")
    assert "가격" not in fallback_personalized_reason(score, "ko")
    serialized = score_to_dict(score, "ko")
    assert len(serialized["display_reasons"]) == 3
    assert serialized["fit_reasons"] == serialized["display_reasons"]
    assert len(serialized["display_cautions"]) == 1
    assert serialized["caution"] == serialized["display_cautions"][0]
    assert "checked" not in serialized["caution"]
    assert "가격" not in serialized["caution"]


def test_customer_cautions_localize_skin_and_ingredient_without_internal_terms() -> None:
    skin_caution = translate_caution("DB suitability does not include oily skin", "ko")
    ingredient_caution = translate_caution(
        "salicylic acid can be less gentle for irritation-prone follow-ups",
        "ko",
    )

    assert skin_caution == "제품 정보에서 지성 피부 적합 표시를 확인할 수 없어 사용 전 확인이 필요합니다."
    assert ingredient_caution == "살리실산/BHA 성분은 예민한 피부에 자극이 될 수 있어 천천히 사용해 주세요."
    assert "DB" not in skin_caution
    assert "follow-up" not in ingredient_caution

    avoid_caution = translate_caution("product DB says avoid for sensitive", "ko")
    assert avoid_caution == "제품 정보상 민감 반응이 잦은 피부에는 주의가 필요해요. 처음에는 소량으로 시험해 주세요."
    assert "DB" not in avoid_caution
    assert "sensitive" not in avoid_caution


def test_review_confidence_requires_a_verified_review_source_url() -> None:
    product = replace(
        _product(),
        rating=4.8,
        review_count=500,
        review_source_url=None,
        review_verified_at="2026-07-20",
    )
    serialized = score_to_dict(ProductScore(product=product, score=1.0), "ko")

    reviews = serialized["data_confidence"]["factors"]["reviews"]
    assert reviews["status"] == "missing"
    assert reviews["checked_at"] is None
    assert reviews["label_ko"] == "리뷰 근거 부족"
    assert serialized["product"]["rating"] is None
    assert serialized["product"]["review_count"] is None
    assert serialized["score_components"]["review_confidence"] == 0.0


def test_all_ingredient_explanation_display_fields_are_localized_to_korean() -> None:
    explanations = ingredient_explanations([item.name for item in INGREDIENT_EVIDENCE])

    assert len(explanations) == len(INGREDIENT_EVIDENCE)
    for explanation, evidence in zip(explanations, INGREDIENT_EVIDENCE, strict=True):
        assert explanation["display_name_ko"] != evidence.name
        assert len(explanation["display_supports_ko"]) == len(evidence.supports)
        assert all("_" not in value for value in explanation["display_supports_ko"])
        assert all(value not in evidence.supports for value in explanation["display_supports_ko"])
        assert len(explanation["display_cautions_ko"]) == len(evidence.cautions)
        assert all(value not in evidence.cautions for value in explanation["display_cautions_ko"])
        assert all(not any("a" <= character.lower() <= "z" for character in value) for value in explanation["display_cautions_ko"])


def test_future_data_date_is_treated_as_missing() -> None:
    future_date = (date.today() + timedelta(days=1)).isoformat()

    assert _date_status(future_date) == "missing"


def test_krw_budget_does_not_claim_an_unrelated_usd_catalog_price() -> None:
    product = replace(_product(), price_krw=None, price_usd=12.0)
    recommendation = KBeautyAgent(ProductDatabase([product])).recommend(
        "controlled profile",
        structured_profile={
            "skin_type": "dry",
            "concerns": ["hydration"],
            "desired_categories": ["serum"],
            "sensitivities": ["budget_preference"],
            "max_price_krw": 50_000,
        },
    )

    assert recommendation.results
    assert all(
        "lower listed price" not in reason
        for reason in recommendation.results[0].reasons
    )


def test_mixed_currency_offers_use_only_krw_for_krw_lowest_price(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    service.upsert_retailer(
        retailer_id="usd-shop",
        display_name="USD Shop",
        base_url="https://usd.example.com",
        allowed_domains=["usd.example.com"],
    )
    service.upsert_offer(
        product_id="example-serum",
        retailer_id="usd-shop",
        destination_url="https://usd.example.com/products/example-serum",
        source_kind="approved_partner_feed",
        offer_id="usd-offer",
        price_amount=1,
        currency="USD",
        stock_status="in_stock",
        checked_at=1_784_505_600,
        ttl_seconds=3_600,
    )

    bundle = service.offers_for_product("example-serum", now=1_784_505_700)
    summary = service.product_summary("example-serum", now=1_784_505_700)

    assert {offer["price"]["currency"] for offer in bundle["offers"]} == {"KRW", "USD"}
    assert bundle["summary"]["lowest_fresh_price_krw"] == 19_000
    assert bundle["summary"]["best_current_price"] == {
        "amount": 19_000,
        "currency": "KRW",
        "retailer_name": "Olive Young",
    }
    assert summary["lowest_fresh_price_krw"] == 19_000
    assert summary["best_current_price"]["currency"] == "KRW"


def test_out_of_stock_offer_is_not_used_as_current_lowest_price(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    service.upsert_retailer(
        retailer_id="sold-out-shop",
        display_name="Sold Out Shop",
        base_url="https://soldout.example.com",
        allowed_domains=["soldout.example.com"],
    )
    service.upsert_offer(
        product_id="example-serum",
        retailer_id="sold-out-shop",
        destination_url="https://soldout.example.com/products/example-serum",
        source_kind="approved_partner_feed",
        offer_id="sold-out-offer",
        price_amount=1_000,
        currency="KRW",
        stock_status="out_of_stock",
        checked_at=1_784_505_600,
        ttl_seconds=3_600,
    )

    bundle = service.offers_for_product("example-serum", now=1_784_505_700)
    summary = service.product_summary("example-serum", now=1_784_505_700)

    assert bundle["summary"]["lowest_fresh_price_krw"] == 19_000
    assert bundle["summary"]["best_current_price"]["retailer_name"] == "Olive Young"
    assert summary["lowest_fresh_price_krw"] == 19_000


def test_only_out_of_stock_offer_leaves_current_price_unknown(tmp_path: Path) -> None:
    product = replace(
        _product("sold-out-only"),
        purchase_url=None,
        retailer_name=None,
        price_krw=None,
        price_checked_at=None,
    )
    _, service = _service(tmp_path, [product])
    service.upsert_retailer(
        retailer_id="sold-out-shop",
        display_name="Sold Out Shop",
        base_url="https://soldout.example.com",
        allowed_domains=["soldout.example.com"],
    )
    service.upsert_offer(
        product_id=product.id,
        retailer_id="sold-out-shop",
        destination_url=f"https://soldout.example.com/products/{product.id}",
        source_kind="approved_partner_feed",
        offer_id="sold-out-only-offer",
        price_amount=9_000,
        currency="KRW",
        stock_status="out_of_stock",
        checked_at=1_784_505_600,
        ttl_seconds=3_600,
    )

    bundle = service.offers_for_product(product.id, now=1_784_505_700)
    summary = service.product_summary(product.id, now=1_784_505_700)

    assert bundle["summary"]["lowest_fresh_price_krw"] is None
    assert bundle["summary"]["best_current_price"] is None
    assert summary["lowest_fresh_price_krw"] is None


def test_signed_redirect_rejects_tampering_expiry_and_non_allowlisted_target(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    offer_id = service.offers_for_product("example-serum", now=100)["offers"][0]["id"]
    token = service.create_redirect_token(offer_id, now=100, ttl_seconds=60)

    target = service.resolve_redirect_token(token, now=120)
    assert target.url == (
        "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=example-serum"
    )
    tampered = f"{token[:-1]}{'A' if token[-1] != 'A' else 'B'}"
    with pytest.raises(RedirectTokenError):
        service.resolve_redirect_token(tampered, now=120)
    payload_segment, signature_segment = token.split(".", 1)
    with pytest.raises(RedirectTokenError):
        service.resolve_redirect_token(f"{payload_segment}.{signature_segment[:2]}$${signature_segment[2:]}", now=120)
    with pytest.raises(RedirectTokenError, match="expired"):
        service.resolve_redirect_token(token, now=161)

    with store.connect() as connection:
        connection.execute(
            "UPDATE offers SET destination_url = 'https://attacker.example/steal' WHERE id = ?",
            (offer_id,),
        )
    with pytest.raises(RedirectTokenError):
        service.resolve_redirect_token(token, now=120)
    with pytest.raises(RedirectTokenError, match="allowlisted"):
        service.create_redirect_token(offer_id, now=120)


def test_redirect_endpoint_logs_only_hashed_session_and_never_redirects_from_raw_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from k_beauty_agent import web

    store, service = _service(tmp_path)
    monkeypatch.setattr(web, "store", store)
    monkeypatch.setattr(web, "commerce", service)
    client = TestClient(web.app)
    bundle = service.offers_for_product("example-serum")
    redirect_url = bundle["offers"][0]["redirect_url"]
    session_id = "A" * 24
    store.ensure_session(session_id)
    store.record_privacy_consent(session_id, web.PRIVACY_POLICY_VERSION)

    response = client.get(redirect_url, headers={web.SESSION_HEADER: session_id}, follow_redirects=False)
    repeated = client.get(redirect_url, headers={web.SESSION_HEADER: session_id}, follow_redirects=False)

    assert response.status_code == 302
    assert repeated.status_code == 302
    assert response.headers["location"] == (
        "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=example-serum"
    )
    assert response.headers["cache-control"] == "no-store"
    with store.connect() as connection:
        row = connection.execute("SELECT * FROM affiliate_clicks").fetchone()
        assert connection.execute("SELECT COUNT(*) FROM affiliate_clicks").fetchone()[0] == 1
    assert row["session_hash"] == hash_session(session_id)
    assert row["redirect_token_hash"]
    assert session_id not in tuple(str(value) for value in row)
    unconsented_url = f"/r/{service.create_redirect_token(row['offer_id'])}"
    assert client.get(
        unconsented_url,
        headers={web.SESSION_HEADER: "C" * 24},
        follow_redirects=False,
    ).status_code == 302
    with store.connect() as connection:
        unconsented = connection.execute(
            "SELECT session_hash FROM affiliate_clicks ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert unconsented["session_hash"] is None
    assert client.get("/r/https://attacker.example", follow_redirects=False).status_code == 404


def test_v2_products_and_recommendations_use_normalized_offers_without_commission_ranking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from k_beauty_agent import web

    products = [_product("alpha", name="Alpha Serum"), _product("beta", name="Beta Serum")]
    store, service = _service(tmp_path, products)
    local_agent = KBeautyAgent(ProductDatabase(products))
    monkeypatch.setattr(web, "store", store)
    monkeypatch.setattr(web, "commerce", service)
    monkeypatch.setattr(web, "agent", local_agent)
    with store.connect() as connection:
        retailer_id = connection.execute("SELECT id FROM retailers").fetchone()["id"]
        now = 1_784_505_600
        connection.execute(
            """
            INSERT INTO affiliate_programs(
                id, retailer_id, program_name, status, disclosure_ko, disclosure_en,
                metadata_json, created_at, updated_at
            ) VALUES ('affiliate-example', ?, 'Example Partner', 'active', '제휴 고지', 'Affiliate disclosure', '{}', ?, ?)
            """,
            (retailer_id, now, now),
        )
        connection.execute(
            """
            UPDATE offers
            SET affiliate_program_id = 'affiliate-example',
                affiliate_url = destination_url || '?affiliate=1',
                commission_bps = CASE WHEN destination_url LIKE '%beta' THEN 9999 ELSE 0 END
            """
        )
    client = TestClient(web.app)

    catalog_response = client.get("/api/v2/products?limit=10")
    assert catalog_response.status_code == 200
    catalog = catalog_response.json()
    assert catalog["schema_version"] == 2
    assert catalog["affiliate_disclosure"]["required"] is True
    assert all("purchase_url" not in product for product in catalog["products"])
    assert all(product["commerce"]["offer_count"] == 1 for product in catalog["products"])
    public_status = client.get("/api/v2/catalog/status").json()["commerce"]
    assert {"clicks", "conversions", "active_affiliate_programs", "last_ingestion_run"}.isdisjoint(public_status)

    payload = {
        "query": "dry hydrating serum",
        "limit": 2,
        "use_openai": False,
        "privacy_consent": True,
        "language": "ko",
        "profile": {
            "skin_type": "dry",
            "concerns": ["hydration"],
            "desired_categories": ["serum"],
        },
    }
    response = client.post("/api/v2/recommend", json=payload, headers={web.SESSION_HEADER: "B" * 24})
    assert response.status_code == 200
    result = response.json()
    expected = local_agent.recommend(
        "dry hydrating serum",
        limit=2,
        structured_profile={
            "skin_type": "dry",
            "concerns": ["hydration"],
            "desired_categories": ["serum"],
        },
    )
    assert [item["product"]["id"] for item in result["results"]] == [item.product.id for item in expected.results]
    assert [item["score"] for item in result["results"]] == [round(item.score, 2) for item in expected.results]
    assert result["affiliate_disclosure"]["required"] is True
    assert "수수료" in result["ranking_policy"]
    assert all("purchase_url" not in item["product"] for item in result["results"])
    raw_retailer_fields = {
        "price_usd",
        "oliveyoung_url",
        "oliveyoung_price_krw",
        "oliveyoung_verified_at",
        "purchase_url",
        "retailer_name",
        "price_krw",
        "price_checked_at",
    }
    similar_products = [
        product
        for item in result["results"]
        for product in item["similar_products"]
    ]
    assert similar_products
    assert all(raw_retailer_fields.isdisjoint(product) for product in similar_products)
    assert all("commerce" in product for product in similar_products)

    follow_up = client.post(
        "/api/v2/follow-up",
        json={**payload, "query": "더 순한 제품으로"},
        headers={web.SESSION_HEADER: "B" * 24},
    )
    assert follow_up.status_code == 200
    follow_up_similar = [
        product
        for item in follow_up.json()["results"]
        for product in item["similar_products"]
    ]
    assert follow_up_similar
    assert all(raw_retailer_fields.isdisjoint(product) for product in follow_up_similar)


def test_budget_ranking_uses_current_krw_offer_instead_of_catalog_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from k_beauty_agent import web

    products = [
        replace(_product("alpha", name="Alpha Serum"), price_krw=50_000, oliveyoung_price_krw=50_000),
        replace(_product("beta", name="Beta Serum"), price_krw=50_000, oliveyoung_price_krw=50_000),
        replace(
            _product("gamma", name="Gamma Serum"),
            purchase_url=None,
            retailer_name=None,
            price_krw=None,
            oliveyoung_price_krw=None,
            price_checked_at=None,
        ),
    ]
    store, service = _service(tmp_path, products)
    now = int(time.time())
    with store.connect() as connection:
        connection.execute("UPDATE offers SET checked_at = ?, stale_after = ?", (now, now + 3600))
    service.upsert_retailer(
        retailer_id="fresh-shop",
        display_name="Fresh Shop",
        base_url="https://fresh.example.com",
        allowed_domains=["fresh.example.com"],
    )
    service.upsert_offer(
        product_id="alpha",
        retailer_id="fresh-shop",
        destination_url="https://fresh.example.com/alpha",
        source_kind="approved_test_feed",
        price_amount=19_000,
        currency="KRW",
        checked_at=now,
        ttl_seconds=3600,
    )
    monkeypatch.setattr(web, "store", store)
    monkeypatch.setattr(web, "commerce", service)
    monkeypatch.setattr(web, "agent", KBeautyAgent(ProductDatabase(products)))

    response = TestClient(web.app).post(
        "/api/v2/recommend",
        json={
            "query": "2만원 이하 수분 세럼",
            "limit": 2,
            "use_openai": False,
            "language": "ko",
            "profile": {
                "skin_type": "dry",
                "concerns": ["hydration"],
                "desired_categories": ["serum"],
                "max_price_krw": 20_000,
            },
        },
    )
    assert response.status_code == 200
    assert [item["product"]["id"] for item in response.json()["results"]] == ["alpha"]
    assert response.json()["results"][0]["product"]["commerce"]["lowest_fresh_price_krw"] == 19_000
    assert [item["product"]["id"] for item in response.json()["additional_candidates"]] == ["gamma"]
    assert (
        response.json()["additional_candidates"][0]["product"]["commerce"]["lowest_fresh_price_krw"]
        is None
    )


def test_source_review_candidates_lists_only_unlinked_records(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    now = 1_784_505_600
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO data_sources(
                id, name, source_type, active, metadata_json, created_at, updated_at
            ) VALUES ('approved-feed', 'Approved Feed', 'partner_feed', 1, '{}', ?, ?)
            """,
            (now, now),
        )
        record = connection.execute(
            """
            INSERT INTO source_records(
                source_id, source_record_id, source_url, payload_hash,
                fetched_at, source_updated_at, metadata_json
            ) VALUES ('approved-feed', 'sku-unlinked', 'https://shop.example.com/products/new',
                      'hash-unlinked', ?, ?, ?)
            """,
            (
                now,
                now - 60,
                json.dumps(
                    {
                        "title": "Candidate Serum",
                        "brand": "Example Lab",
                        "price": 12.5,
                        "currency": "USD",
                        "availability": "in_stock",
                        "match_status": "review",
                    }
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO match_candidates(
                source_record_id, candidate_product_id, match_strategy,
                confidence, status, created_at
            ) VALUES (?, 'example-serum', 'ambiguous_text_match', 0.81, 'pending', ?)
            """,
            (int(record.lastrowid), now),
        )
        variant_id = connection.execute(
            "SELECT id FROM product_variants WHERE product_id = 'example-serum'"
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO source_records(
                source_id, source_record_id, product_id, variant_id, source_url,
                payload_hash, fetched_at, metadata_json
            ) VALUES ('approved-feed', 'sku-linked', 'example-serum', ?,
                      'https://shop.example.com/products/example-serum',
                      'hash-linked', ?, '{}')
            """,
            (variant_id, now),
        )

    page = service.source_review_candidates(source_id="approved-feed", limit=10)

    assert page["total"] == 1
    assert page["next_cursor"] is None
    assert page["policy"] == "manual_review_required"
    assert page["items"][0]["source_record_id"] == "sku-unlinked"
    assert page["items"][0]["source_product"]["price"] == 12.5
    assert page["items"][0]["source_product"]["currency"] == "USD"
    assert page["items"][0]["candidate_products"] == [
        {
            "product_id": "example-serum",
            "name": "Example Serum",
            "brand": "Example Lab",
            "category": "serum",
            "strategy": "ambiguous_text_match",
            "confidence": 0.81,
            "status": "pending",
            "reviewed_at": None,
            "reviewer_note": None,
        }
    ]
    assert service.source_review_candidates(source_id="other-source")["total"] == 0
    with pytest.raises(ValueError, match="source_id"):
        service.source_review_candidates(source_id="invalid/source")


def test_source_activation_reconciliation_fails_closed(tmp_path: Path) -> None:
    store, service = _service(tmp_path)
    service.upsert_retailer(
        retailer_id="approved-shop",
        display_name="Approved Shop",
        base_url="https://approved.example",
    )
    service.upsert_affiliate_program(
        program_id="approved-program",
        retailer_id="approved-shop",
        program_name="Approved Program",
        status="active",
        metadata={"source_id": "approved-feed"},
    )
    service.upsert_offer(
        product_id="example-serum",
        retailer_id="approved-shop",
        destination_url="https://approved.example/product",
        affiliate_url="https://approved.example/go",
        affiliate_program_id="approved-program",
        source_kind="approved_source:approved-feed",
        offer_id="approved-source-offer",
        price_amount=20_000,
        checked_at=int(time.time()),
    )

    unchanged = service.reconcile_source_activation(
        configured_source_ids={"approved-feed"},
        approved_affiliate_source_ids={"approved-feed"},
    )
    deactivated = service.reconcile_source_activation(
        configured_source_ids=set(),
        approved_affiliate_source_ids={"approved-feed"},
    )

    assert unchanged == {"programs_changed": 0, "offers_deactivated": 0}
    assert deactivated == {"programs_changed": 1, "offers_deactivated": 1}
    with store.connect() as connection:
        assert connection.execute(
            "SELECT status FROM affiliate_programs WHERE id = 'approved-program'"
        ).fetchone()["status"] == "pending"
        assert connection.execute(
            "SELECT active FROM offers WHERE id = 'approved-source-offer'"
        ).fetchone()["active"] == 0


def test_connection_rolls_back_failed_transaction(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "rollback.sqlite3")

    with pytest.raises(sqlite3.IntegrityError):
        with store.connect() as connection:
            connection.execute(
                "INSERT INTO sessions(session_id, profile_json, created_at, updated_at, expires_at) VALUES ('one', '{}', 1, 1, 1)"
            )
            connection.execute(
                "INSERT INTO sessions(session_id, profile_json, created_at, updated_at, expires_at) VALUES ('one', '{}', 1, 1, 1)"
            )

    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_public_ingestion_and_signed_conversion_are_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, service = _service(tmp_path)
    retailer = service.upsert_retailer(
        retailer_id="approved-shop",
        display_name="Approved Shop",
        base_url="https://approved.example",
        allowed_domains=["checkout.approved.example"],
    )
    assert retailer.created is True
    program = service.upsert_affiliate_program(
        program_id="approved-partner",
        retailer_id="approved-shop",
        program_name="Approved Partner",
        status="active",
    )
    assert program.created is True

    first = service.upsert_offer(
        product_id="example-serum",
        retailer_id="approved-shop",
        destination_url="https://approved.example/product/1",
        affiliate_url="https://checkout.approved.example/go/1",
        affiliate_program_id="approved-partner",
        source_kind="partner_api",
        offer_id="approved-offer",
        price_amount=18_000,
        list_price_amount=22_000,
        stock_status="in_stock",
        checked_at="2026-07-20T12:00:00Z",
    )
    repeated = service.upsert_offer(
        product_id="example-serum",
        retailer_id="approved-shop",
        destination_url="https://approved.example/product/1",
        affiliate_url="https://checkout.approved.example/go/1",
        affiliate_program_id="approved-partner",
        source_kind="partner_api",
        offer_id="approved-offer",
        price_amount=18_000,
        list_price_amount=22_000,
        stock_status="in_stock",
        checked_at="2026-07-20T12:30:00Z",
    )
    assert first.created is True and first.observation_written is True
    assert repeated.created is False and repeated.observation_written is False
    assert service.offers_for_product("example-serum", now=1_784_550_600)["offers"][0]["list_price"]["amount"] == 22_000

    secret = "webhook-secret"
    signed_at = 1_784_554_700
    conversion_payload = {
        "affiliate_program_id": "approved-partner",
        "external_conversion_id": "order-1",
        "status": "pending",
        "occurred_at": "2026-07-20T12:45:00Z",
        "order_amount": 18_000,
        "commission_amount": 900,
        "currency": "KRW",
    }
    raw_payload = json.dumps(conversion_payload, separators=(",", ":")).encode()
    signature = hmac.new(
        secret.encode(), f"{signed_at}.".encode() + raw_payload, hashlib.sha256
    ).hexdigest()
    conversion = service.record_signed_conversion(
        raw_payload=raw_payload,
        signature=f"sha256={signature}",
        signed_at=signed_at,
        webhook_secret=secret,
        now=signed_at,
    )
    approved_payload = {**conversion_payload, "status": "approved"}
    approved_raw = json.dumps(approved_payload, separators=(",", ":")).encode()
    approved_signature = hmac.new(
        secret.encode(), f"{signed_at}.".encode() + approved_raw, hashlib.sha256
    ).hexdigest()
    duplicate = service.record_signed_conversion(
        raw_payload=approved_raw,
        signature=approved_signature,
        signed_at=signed_at,
        webhook_secret=secret,
        now=signed_at,
    )
    assert conversion.created is True
    assert duplicate.created is False
    with pytest.raises(ValueError, match="signature"):
        service.record_signed_conversion(
            raw_payload=raw_payload,
            signature="0" * 64,
            signed_at=signed_at,
            webhook_secret=secret,
            now=signed_at,
        )
    fractional_payload = {**conversion_payload, "external_conversion_id": "fractional", "order_amount": 19.99}
    fractional_raw = json.dumps(fractional_payload, separators=(",", ":")).encode()
    fractional_signature = hmac.new(
        secret.encode(), f"{signed_at}.".encode() + fractional_raw, hashlib.sha256
    ).hexdigest()
    with pytest.raises(ValueError, match="minor-unit"):
        service.record_signed_conversion(
            raw_payload=fractional_raw,
            signature=fractional_signature,
            signed_at=signed_at,
            webhook_secret=secret,
            now=signed_at,
        )
    metadata_payload = {
        **conversion_payload,
        "external_conversion_id": "order-with-metadata",
        "metadata": {"customer_email": "customer@example.com"},
    }
    metadata_raw = json.dumps(metadata_payload, separators=(",", ":")).encode()
    metadata_signature = hmac.new(
        secret.encode(), f"{signed_at}.".encode() + metadata_raw, hashlib.sha256
    ).hexdigest()
    with pytest.raises(ValueError, match="Unsupported conversion fields"):
        service.record_signed_conversion(
            raw_payload=metadata_raw,
            signature=metadata_signature,
            signed_at=signed_at,
            webhook_secret=secret,
            now=signed_at,
        )
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM offer_observations WHERE offer_id = 'approved-offer'").fetchone()[0] == 1
        row = connection.execute("SELECT status FROM affiliate_conversions").fetchone()
    assert row["status"] == "approved"

    from k_beauty_agent import web

    monkeypatch.setattr(web, "store", store)
    monkeypatch.setattr(web, "commerce", service)
    monkeypatch.setattr(web, "affiliate_webhook_secret", lambda: secret)
    client = TestClient(web.app)
    webhook_time = int(time.time())
    webhook_payload = {
        **conversion_payload,
        "external_conversion_id": "order-webhook",
        "occurred_at": webhook_time,
    }
    webhook_raw = json.dumps(webhook_payload, separators=(",", ":")).encode()
    webhook_signature = hmac.new(
        secret.encode(), f"{webhook_time}.".encode() + webhook_raw, hashlib.sha256
    ).hexdigest()
    assert client.post(
        "/api/integrations/affiliate/conversions",
        content=webhook_raw,
        headers={
            "Content-Type": "application/json",
            "X-Affiliate-Timestamp": str(webhook_time),
            "X-Affiliate-Signature": webhook_signature,
        },
    ).json()["created"] is True
    assert client.post(
        "/api/integrations/affiliate/conversions",
        content=webhook_raw,
        headers={"Content-Type": "application/json"},
    ).status_code == 401
    admin_payload = {
        **conversion_payload,
        "external_conversion_id": "order-2",
        "status": "approved",
    }
    assert client.post("/api/admin/conversions", json=admin_payload).status_code == 401
    metadata_admin = {**admin_payload, "external_conversion_id": "order-admin-pii", "metadata": {"email": "x@example.com"}}
    rejected_metadata = client.post(
        "/api/admin/conversions",
        headers={"X-Admin-Token": web.admin_token()},
        json=metadata_admin,
    )
    assert rejected_metadata.status_code == 422
    response = client.post(
        "/api/admin/conversions",
        headers={"X-Admin-Token": web.admin_token()},
        json=admin_payload,
    )
    assert response.status_code == 200
    assert response.json()["created"] is True
