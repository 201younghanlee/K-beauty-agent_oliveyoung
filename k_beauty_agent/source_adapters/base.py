from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


Availability = Literal["in_stock", "out_of_stock", "backorder", "preorder", "unknown"]


@dataclass(frozen=True)
class SourceOffer:
    """Normalized offer returned by an approved partner source."""

    source_id: str
    retailer_id: str
    retailer_name: str
    merchant_sku: str
    title: str
    brand: str | None
    landing_url: str
    currency: str
    price: int | float | None = None
    list_price: int | float | None = None
    availability: Availability = "unknown"
    image_url: str | None = None
    gtin: str | None = None
    variant: str | None = None
    affiliate: bool = False
    observed_at: int | None = None
    stale_after_seconds: int = 86_400
    raw: dict[str, object] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class SourceSyncResult:
    source_id: str
    offers: tuple[SourceOffer, ...]
    fetched_at: int
    warnings: tuple[str, ...] = ()


class RetailerSource(Protocol):
    source_id: str

    @property
    def enabled(self) -> bool:
        ...

    def fetch(self, query: str, *, limit: int = 20) -> SourceSyncResult:
        ...
