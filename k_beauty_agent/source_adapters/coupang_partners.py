from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode, urlparse

import httpx

from .base import SourceOffer, SourceSyncResult
from .coupang_partner_links import (
    COUPANG_PARTNERS_DISCLOSURE_EN,
    COUPANG_PARTNERS_DISCLOSURE_KO,
)
from .security import host_matches, require_https_url, require_public_dns_resolution


DEFAULT_BASE_URL = "https://api-gateway.coupang.com"
DEFAULT_SEARCH_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/search"
COUPANG_DESTINATION_HOSTS = {"coupang.com", "link.coupang.com"}
MAX_COUPANG_RESPONSE_BYTES = 2_000_000


class CoupangPartnersAdapter:
    """Official Coupang Partners product-search API adapter.

    Credentials are read from the environment only.  No storefront HTML is
    requested, and stock remains ``unknown`` because the public Partners guide
    does not promise an inventory quantity/status field.
    """

    source_id = "coupang_partners"
    affiliate_program_name = "쿠팡 파트너스"
    affiliate_disclosure_ko = COUPANG_PARTNERS_DISCLOSURE_KO
    affiliate_disclosure_en = COUPANG_PARTNERS_DISCLOSURE_EN

    def __init__(
        self,
        *,
        access_key: str | None = None,
        secret_key: str | None = None,
        base_url: str | None = None,
        search_path: str | None = None,
        client: httpx.Client | None = None,
    ):
        self.access_key = access_key if access_key is not None else os.getenv("COUPANG_PARTNERS_ACCESS_KEY", "")
        self.secret_key = secret_key if secret_key is not None else os.getenv("COUPANG_PARTNERS_SECRET_KEY", "")
        self.base_url = (base_url or os.getenv("COUPANG_PARTNERS_API_BASE") or DEFAULT_BASE_URL).rstrip("/")
        self.search_path = search_path or os.getenv("COUPANG_PARTNERS_SEARCH_PATH") or DEFAULT_SEARCH_PATH
        require_https_url(self.base_url, allowed_hosts={"api-gateway.coupang.com"})
        if not self.search_path.startswith("/") or "?" in self.search_path:
            raise ValueError("COUPANG_PARTNERS_SEARCH_PATH must be an absolute path without a query string")
        self._validate_dns = client is None
        self.client = client or httpx.Client(timeout=12.0, follow_redirects=False)

    @property
    def enabled(self) -> bool:
        return bool(self.access_key and self.secret_key)

    def fetch(self, query: str, *, limit: int = 20) -> SourceSyncResult:
        if not self.enabled:
            raise RuntimeError("Coupang Partners credentials are not configured")
        if self._validate_dns:
            require_public_dns_resolution(self.base_url)
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("A product search query is required")
        safe_limit = max(1, min(int(limit), 100))
        params = {"keyword": normalized_query, "limit": str(safe_limit)}
        query_string = urlencode(params)
        signed_at = dt.datetime.now(dt.timezone.utc)
        authorization = create_authorization(
            access_key=self.access_key,
            secret_key=self.secret_key,
            method="GET",
            path=self.search_path,
            query=query_string,
            signed_at=signed_at,
        )
        with self.client.stream(
            "GET",
            f"{self.base_url}{self.search_path}?{query_string}",
            headers={"Authorization": authorization},
        ) as response:
            response.raise_for_status()
            declared_size = response.headers.get("content-length")
            if declared_size and declared_size.isdigit() and int(declared_size) > MAX_COUPANG_RESPONSE_BYTES:
                raise ValueError("Coupang response exceeds the configured response-size limit")
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_COUPANG_RESPONSE_BYTES:
                    raise ValueError("Coupang response exceeds the configured response-size limit")
        fetched_at = int(time.time())
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Coupang response must contain valid JSON") from exc
        rows = _product_rows(payload)
        offers: list[SourceOffer] = []
        warnings: list[str] = []
        for row in rows[:safe_limit]:
            offer = _normalize_product(row, fetched_at=fetched_at)
            if offer is None:
                warnings.append("A Coupang row was skipped because its product URL or identifier was invalid")
                continue
            offers.append(offer)
        return SourceSyncResult(
            source_id=self.source_id,
            offers=tuple(offers),
            fetched_at=fetched_at,
            warnings=tuple(warnings),
        )


def create_authorization(
    *,
    access_key: str,
    secret_key: str,
    method: str,
    path: str,
    query: str,
    signed_at: dt.datetime,
) -> str:
    utc_time = signed_at.astimezone(dt.timezone.utc)
    signed_date = utc_time.strftime("%y%m%dT%H%M%SZ")
    message = f"{signed_date}{method.upper()}{path}{query}"
    signature = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return (
        "CEA algorithm=HmacSHA256, "
        f"access-key={access_key}, signed-date={signed_date}, signature={signature}"
    )


def _product_rows(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        candidates = data.get("productData") or data.get("products") or data.get("items")
    else:
        candidates = data
    if not isinstance(candidates, list):
        return []
    return [row for row in candidates if isinstance(row, dict)]


def _normalize_product(row: dict[str, object], *, fetched_at: int) -> SourceOffer | None:
    product_id = _text(row.get("productId") or row.get("id"))
    product_url = _text(row.get("productUrl") or row.get("product_url") or row.get("url"))
    if not product_id or not product_url or not host_matches(product_url, COUPANG_DESTINATION_HOSTS):
        return None
    price = _integer(row.get("productPrice") or row.get("price"))
    return SourceOffer(
        source_id="coupang_partners",
        retailer_id="coupang",
        retailer_name="쿠팡",
        merchant_sku=product_id,
        title=_text(row.get("productName") or row.get("name")) or "쿠팡 상품",
        brand=_text(row.get("brand")),
        landing_url=product_url,
        currency="KRW",
        price=price,
        list_price=_integer(row.get("originalPrice") or row.get("listPrice")),
        availability="unknown",
        image_url=_safe_image_url(row.get("productImage") or row.get("imageUrl")),
        affiliate=True,
        observed_at=fetched_at,
        stale_after_seconds=7_200,
        raw=row,
    )


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _integer(value: object) -> int | None:
    try:
        return int(float(str(value))) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _safe_image_url(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    parsed = urlparse(text)
    return text if parsed.scheme == "https" and parsed.hostname else None
