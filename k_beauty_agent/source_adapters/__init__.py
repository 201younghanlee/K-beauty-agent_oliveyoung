"""Approved retailer and affiliate-feed integrations.

These adapters intentionally avoid scraping storefront HTML.  A source is
enabled only when its official API credentials or an explicitly approved feed
URL is configured by the operator.
"""

from .base import Availability, RetailerSource, SourceOffer, SourceSyncResult
from .coupang_partner_links import (
    COUPANG_PARTNERS_DISCLOSURE_EN,
    COUPANG_PARTNERS_DISCLOSURE_KO,
    CoupangPartnerLink,
    CoupangPartnerLinksAdapter,
)
from .coupang_partners import CoupangPartnersAdapter
from .partner_feed import PartnerFeedAdapter, PartnerFeedConfig
from .registry import configured_sources, source_status

__all__ = [
    "Availability",
    "COUPANG_PARTNERS_DISCLOSURE_EN",
    "COUPANG_PARTNERS_DISCLOSURE_KO",
    "CoupangPartnerLink",
    "CoupangPartnerLinksAdapter",
    "CoupangPartnersAdapter",
    "PartnerFeedAdapter",
    "PartnerFeedConfig",
    "RetailerSource",
    "SourceOffer",
    "SourceSyncResult",
    "configured_sources",
    "source_status",
]
