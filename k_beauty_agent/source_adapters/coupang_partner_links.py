from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from .base import SourceOffer, SourceSyncResult
from .security import require_https_url


COUPANG_PARTNER_LINK_SOURCE_ID = "coupang_partner_links"
COUPANG_PARTNER_LINK_RETAILER_ID = "coupang-partner-links"
COUPANG_PARTNER_LINK_HOST = "link.coupang.com"
COUPANG_PARTNERS_DISCLOSURE_KO = (
    "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
)
COUPANG_PARTNERS_DISCLOSURE_EN = (
    "This content is part of Coupang Partners activities, and we may receive a commission."
)
MAX_COUPANG_PARTNER_LINKS = 100
_PRODUCT_ID = re.compile(r"[A-Za-z0-9_.:-]{1,160}")
_PARTNER_LINK_PATH = re.compile(r"/a/[A-Za-z0-9_-]{3,128}")
_ENTRY_FIELDS = frozenset({"product_id", "affiliate_url"})


@dataclass(frozen=True)
class CoupangPartnerLink:
    product_id: str
    affiliate_url: str


class CoupangPartnerLinksAdapter:
    """A fail-closed source for operator-created Coupang Partners short links.

    This source is intentionally separate from the Coupang Partners product
    API. It accepts only links copied from the Partners UI and never upgrades a
    normal Coupang product URL into an affiliate URL.
    """

    source_id = COUPANG_PARTNER_LINK_SOURCE_ID
    authoritative_snapshot = True
    link_only = True
    affiliate_program_name = "쿠팡 파트너스"
    affiliate_disclosure_ko = COUPANG_PARTNERS_DISCLOSURE_KO
    affiliate_disclosure_en = COUPANG_PARTNERS_DISCLOSURE_EN

    def __init__(self, raw_config: str = ""):
        self.links = parse_coupang_partner_links(raw_config)

    @property
    def enabled(self) -> bool:
        return bool(self.links)

    @property
    def canonical_product_ids(self) -> dict[str, str]:
        return {link.product_id: link.product_id for link in self.links}

    @property
    def required_sync_limit(self) -> int:
        return len(self.links)

    def status_details(self) -> dict[str, object]:
        return {
            "kind": "manual_affiliate_links",
            "configured_links": len(self.links),
            "authoritative_snapshot": True,
        }

    def fetch(self, query: str, *, limit: int = 20) -> SourceSyncResult:
        if not self.enabled:
            raise RuntimeError("COUPANG_PARTNERS_LINKS_JSON is not configured")
        if not query.strip():
            raise ValueError("A source sync label is required")
        safe_limit = max(1, min(int(limit), MAX_COUPANG_PARTNER_LINKS))
        if safe_limit < len(self.links):
            raise ValueError(
                "The sync limit is lower than the number of configured Coupang partner links"
            )
        fetched_at = int(time.time())
        offers = tuple(
            SourceOffer(
                source_id=self.source_id,
                retailer_id=COUPANG_PARTNER_LINK_RETAILER_ID,
                retailer_name="쿠팡",
                merchant_sku=link.product_id,
                title=link.product_id,
                brand=None,
                landing_url=link.affiliate_url,
                currency="KRW",
                availability="unknown",
                affiliate=True,
                observed_at=fetched_at,
                stale_after_seconds=30 * 24 * 60 * 60,
                raw={"product_id": link.product_id},
            )
            for link in self.links
        )
        return SourceSyncResult(
            source_id=self.source_id,
            offers=offers,
            fetched_at=fetched_at,
        )


def parse_coupang_partner_links(raw: str) -> tuple[CoupangPartnerLink, ...]:
    if not raw.strip():
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("COUPANG_PARTNERS_LINKS_JSON must contain valid JSON") from exc
    if not isinstance(payload, list):
        raise ValueError("COUPANG_PARTNERS_LINKS_JSON must be a JSON array")
    if len(payload) > MAX_COUPANG_PARTNER_LINKS:
        raise ValueError(
            f"COUPANG_PARTNERS_LINKS_JSON supports at most {MAX_COUPANG_PARTNER_LINKS} links"
        )

    links: list[CoupangPartnerLink] = []
    seen_product_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"COUPANG_PARTNERS_LINKS_JSON entry {index} must be an object")
        extra_fields = set(item) - _ENTRY_FIELDS
        missing_fields = _ENTRY_FIELDS - set(item)
        if extra_fields or missing_fields:
            raise ValueError(
                "Every COUPANG_PARTNERS_LINKS_JSON entry must contain exactly "
                "product_id and affiliate_url"
            )
        product_id = item["product_id"]
        affiliate_url = item["affiliate_url"]
        if not isinstance(product_id, str) or _PRODUCT_ID.fullmatch(product_id) is None:
            raise ValueError(
                "Coupang partner link product_id must be a safe 1-160 character identifier"
            )
        if not isinstance(affiliate_url, str):
            raise ValueError("Coupang partner affiliate_url must be a string")
        _validate_affiliate_url(affiliate_url)
        if product_id in seen_product_ids:
            raise ValueError(f"Duplicate Coupang partner product_id: {product_id}")
        if affiliate_url in seen_urls:
            raise ValueError("Duplicate Coupang partner affiliate_url")
        seen_product_ids.add(product_id)
        seen_urls.add(affiliate_url)
        links.append(CoupangPartnerLink(product_id=product_id, affiliate_url=affiliate_url))
    return tuple(links)


def _validate_affiliate_url(url: str) -> None:
    require_https_url(url, allowed_hosts={COUPANG_PARTNER_LINK_HOST})
    parsed = urlparse(url)
    if (
        parsed.hostname != COUPANG_PARTNER_LINK_HOST
        or parsed.port is not None
        or _PARTNER_LINK_PATH.fullmatch(parsed.path) is None
        or parsed.params
        or parsed.fragment
    ):
        raise ValueError(
            "Coupang affiliate_url must be a portal-created https://link.coupang.com/a/... link"
        )
