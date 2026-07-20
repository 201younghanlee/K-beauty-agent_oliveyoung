from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .base import Availability, SourceOffer, SourceSyncResult
from .security import host_matches, require_https_url, require_public_dns_resolution


VALID_AVAILABILITY: set[str] = {"in_stock", "out_of_stock", "backorder", "preorder", "unknown"}
MAX_FEED_BYTES = 5_000_000
MAX_FEED_ROWS = 10_000


@dataclass(frozen=True)
class PartnerFeedConfig:
    source_id: str
    retailer_id: str
    retailer_name: str
    feed_url: str
    feed_hosts: tuple[str, ...]
    destination_hosts: tuple[str, ...]
    currency: str = "KRW"
    affiliate: bool = True
    stale_after_seconds: int = 129_600
    bearer_token: str | None = None


class PartnerFeedAdapter:
    """Adapter for a contractually approved normalized JSON product feed.

    The endpoint must return either a JSON array or ``{"items": [...]}``.
    This intentionally does not attempt to scrape or guess arbitrary partner
    HTML and validates both feed and destination hosts.
    """

    def __init__(self, config: PartnerFeedConfig, *, client: httpx.Client | None = None):
        self.config = config
        self.source_id = config.source_id
        require_https_url(config.feed_url, allowed_hosts=set(config.feed_hosts))
        if not config.destination_hosts:
            raise ValueError("At least one destination host is required")
        self._validate_dns = client is None
        self.client = client or httpx.Client(timeout=20.0, follow_redirects=False)

    @property
    def enabled(self) -> bool:
        return True

    def fetch(self, query: str, *, limit: int = 20) -> SourceSyncResult:
        if self._validate_dns:
            require_public_dns_resolution(self.config.feed_url)
        headers = {"Accept": "application/json"}
        if self.config.bearer_token:
            headers["Authorization"] = f"Bearer {self.config.bearer_token}"
        with self.client.stream("GET", self.config.feed_url, headers=headers) as response:
            response.raise_for_status()
            declared_size = response.headers.get("content-length")
            if declared_size and declared_size.isdigit() and int(declared_size) > MAX_FEED_BYTES:
                raise ValueError("Partner feed exceeds the configured response-size limit")
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_FEED_BYTES:
                    raise ValueError("Partner feed exceeds the configured response-size limit")
        fetched_at = int(time.time())
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Partner feed must contain valid JSON") from exc
        rows = payload.get("items", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("Partner feed must be an array or an object with an items array")
        if len(rows) > MAX_FEED_ROWS:
            raise ValueError("Partner feed exceeds the configured row limit")
        needle = query.casefold().strip()
        offers: list[SourceOffer] = []
        warnings: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            haystack = f"{row.get('name', '')} {row.get('brand', '')}".casefold()
            if needle and needle not in haystack:
                continue
            offer = self._normalize(row, fetched_at=fetched_at)
            if offer is None:
                warnings.append("A partner-feed row was skipped because its ID or destination URL was invalid")
                continue
            offers.append(offer)
            if len(offers) >= max(1, min(int(limit), 500)):
                break
        return SourceSyncResult(self.source_id, tuple(offers), fetched_at, tuple(warnings))

    def _normalize(self, row: dict[str, object], *, fetched_at: int) -> SourceOffer | None:
        merchant_sku = _text(row.get("merchant_sku") or row.get("id") or row.get("sku"))
        landing_url = _text(row.get("affiliate_url") or row.get("landing_url") or row.get("url"))
        if not merchant_sku or not landing_url:
            return None
        if not host_matches(landing_url, set(self.config.destination_hosts)):
            return None
        availability_value = (_text(row.get("availability")) or "unknown").lower()
        availability: Availability = (
            availability_value if availability_value in VALID_AVAILABILITY else "unknown"
        )  # type: ignore[assignment]
        return SourceOffer(
            source_id=self.config.source_id,
            retailer_id=self.config.retailer_id,
            retailer_name=self.config.retailer_name,
            merchant_sku=merchant_sku,
            title=_text(row.get("name") or row.get("title")) or merchant_sku,
            brand=_text(row.get("brand")),
            landing_url=landing_url,
            currency=(_text(row.get("currency")) or self.config.currency).upper(),
            price=_number(row.get("price")),
            list_price=_number(row.get("list_price")),
            availability=availability,
            image_url=_safe_image_url(row.get("image_url")),
            gtin=_text(row.get("gtin") or row.get("ean") or row.get("upc")),
            variant=_text(row.get("variant")),
            affiliate=self.config.affiliate,
            observed_at=fetched_at,
            stale_after_seconds=max(300, self.config.stale_after_seconds),
            raw=row,
        )


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: object) -> int | float | None:
    try:
        number = float(str(value)) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None
    if number is None or not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _safe_image_url(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    parsed = urlparse(text)
    return text if parsed.scheme == "https" and parsed.hostname else None
