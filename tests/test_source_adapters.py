from __future__ import annotations

import datetime as dt

import httpx
import pytest

from k_beauty_agent.source_adapters.coupang_partners import (
    MAX_COUPANG_RESPONSE_BYTES,
    CoupangPartnersAdapter,
    create_authorization,
)
from k_beauty_agent.source_adapters.partner_feed import MAX_FEED_BYTES, PartnerFeedAdapter, PartnerFeedConfig
from k_beauty_agent.source_adapters.security import require_https_url, require_public_dns_resolution
from k_beauty_agent.source_adapters.registry import configured_sources


def test_coupang_authorization_is_stable() -> None:
    header = create_authorization(
        access_key="access",
        secret_key="secret",
        method="GET",
        path="/v2/test",
        query="keyword=serum&limit=10",
        signed_at=dt.datetime(2026, 7, 20, 12, 34, 56, tzinfo=dt.timezone.utc),
    )
    assert header.startswith("CEA algorithm=HmacSHA256, access-key=access, signed-date=260720T123456Z")
    assert "signature=" in header
    assert len(header.rsplit("signature=", 1)[1]) == 64


def test_coupang_adapter_normalizes_offers_without_claiming_stock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.time", lambda: 1_750_000_000)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("CEA algorithm=HmacSHA256")
        return httpx.Response(
            200,
            json={
                "data": {
                    "productData": [
                        {
                            "productId": 123,
                            "productName": "Example Serum",
                            "productPrice": 21900,
                            "productUrl": "https://link.coupang.com/a/example",
                            "productImage": "https://image.coupangcdn.com/example.jpg",
                        }
                    ]
                }
            },
        )

    adapter = CoupangPartnersAdapter(
        access_key="access",
        secret_key="secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.fetch("serum", limit=1)
    assert len(result.offers) == 1
    assert result.offers[0].price == 21900
    assert result.offers[0].availability == "unknown"
    assert result.offers[0].affiliate is True


def test_coupang_adapter_rejects_oversized_response() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"{}",
            headers={"Content-Length": str(MAX_COUPANG_RESPONSE_BYTES + 1)},
        )

    adapter = CoupangPartnersAdapter(
        access_key="access",
        secret_key="secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ValueError, match="response-size"):
        adapter.fetch("serum")


def test_partner_feed_rejects_non_allowlisted_destination() -> None:
    config = PartnerFeedConfig(
        source_id="approved_feed",
        retailer_id="retailer",
        retailer_name="Retailer",
        feed_url="https://feed.example.com/products.json",
        feed_hosts=("feed.example.com",),
        destination_hosts=("shop.example.com",),
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": "safe", "name": "Safe serum", "url": "https://shop.example.com/p/safe", "price": 10},
                    {"id": "bad", "name": "Bad serum", "url": "https://attacker.example/p/bad", "price": 1},
                ]
            },
        )

    adapter = PartnerFeedAdapter(config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = adapter.fetch("serum")
    assert [offer.merchant_sku for offer in result.offers] == ["safe"]
    assert result.warnings


def test_partner_feed_preserves_non_krw_decimal_prices() -> None:
    config = PartnerFeedConfig(
        source_id="approved_feed",
        retailer_id="retailer",
        retailer_name="Retailer",
        feed_url="https://feed.example.com/products.json",
        feed_hosts=("feed.example.com",),
        destination_hosts=("shop.example.com",),
        currency="USD",
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "usd-serum",
                        "name": "USD serum",
                        "url": "https://shop.example.com/p/usd-serum",
                        "price": 19.99,
                        "list_price": "24.50",
                    }
                ]
            },
        )

    adapter = PartnerFeedAdapter(config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    offer = adapter.fetch("serum").offers[0]
    assert offer.price == 19.99
    assert offer.list_price == 24.5


def test_partner_feed_rejects_oversized_response_before_json_decode() -> None:
    config = PartnerFeedConfig(
        source_id="approved_feed",
        retailer_id="retailer",
        retailer_name="Retailer",
        feed_url="https://feed.example.com/products.json",
        feed_hosts=("feed.example.com",),
        destination_hosts=("shop.example.com",),
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"[]", headers={"Content-Length": str(MAX_FEED_BYTES + 1)})

    adapter = PartnerFeedAdapter(config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ValueError, match="response-size"):
        adapter.fetch("serum")


@pytest.mark.parametrize(
    "url,allowed_hosts",
    [
        ("https://127.0.0.1/feed.json", {"127.0.0.1"}),
        ("https://localhost/feed.json", {"localhost"}),
        ("https://feed.internal/feed.json", {"feed.internal"}),
        ("https://sub.feed.example.com/feed.json", {"feed.example.com"}),
        ("https://feed.example.com:8443/feed.json", {"feed.example.com"}),
    ],
)
def test_partner_url_validation_rejects_private_or_non_exact_hosts(
    url: str, allowed_hosts: set[str]
) -> None:
    with pytest.raises(ValueError):
        require_https_url(url, allowed_hosts=allowed_hosts)


def test_partner_feed_requires_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        PartnerFeedAdapter(
            PartnerFeedConfig(
                source_id="feed",
                retailer_id="retailer",
                retailer_name="Retailer",
                feed_url="http://feed.example.com/products.json",
                feed_hosts=("feed.example.com",),
                destination_hosts=("shop.example.com",),
            )
        )


def test_partner_dns_resolution_rejects_any_private_answer() -> None:
    def private_resolver(*_args, **_kwargs):
        return [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("169.254.169.254", 443)),
        ]

    with pytest.raises(ValueError, match="public addresses"):
        require_public_dns_resolution(
            "https://feed.example.com/products.json",
            resolver=private_resolver,
        )


def test_partner_dns_resolution_accepts_public_answers() -> None:
    def public_resolver(*_args, **_kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 443))]

    require_public_dns_resolution(
        "https://feed.example.com/products.json",
        resolver=public_resolver,
    )


def test_registry_requires_allowlisted_feed_and_destination_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COUPANG_PARTNERS_ACCESS_KEY", raising=False)
    monkeypatch.delenv("COUPANG_PARTNERS_SECRET_KEY", raising=False)
    monkeypatch.setenv(
        "PARTNER_FEEDS_JSON",
        """
        [{
          "source_id": "yesstyle_awin",
          "retailer_id": "yesstyle",
          "retailer_name": "YesStyle",
          "feed_url": "https://feed.example.com/products.json",
          "feed_hosts": ["feed.example.com"],
          "destination_hosts": ["yesstyle.com"],
          "currency": "USD"
        }]
        """,
    )
    sources = configured_sources()
    assert [source.source_id for source in sources] == ["yesstyle_awin"]


def test_registry_never_forwards_unrelated_application_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COUPANG_PARTNERS_ACCESS_KEY", raising=False)
    monkeypatch.delenv("COUPANG_PARTNERS_SECRET_KEY", raising=False)
    monkeypatch.setenv(
        "PARTNER_FEEDS_JSON",
        """
        [{
          "source_id": "malicious_feed",
          "retailer_id": "retailer",
          "retailer_name": "Retailer",
          "feed_url": "https://feed.example.com/products.json",
          "feed_hosts": ["feed.example.com"],
          "destination_hosts": ["shop.example.com"],
          "bearer_token_env": "ADMIN_TOKEN"
        }]
        """,
    )

    with pytest.raises(ValueError, match="PARTNER_FEED"):
        configured_sources()
