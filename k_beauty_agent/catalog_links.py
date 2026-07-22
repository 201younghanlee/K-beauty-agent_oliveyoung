from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from .models import Product
from .source_adapters.security import require_https_url

CatalogLinkKind = Literal[
    "retailer",
    "brand_official",
    "ingredient_reference",
    "data_reference",
    "review_reference",
]


@dataclass(frozen=True)
class CatalogLink:
    kind: CatalogLinkKind
    label: str
    provider: str
    url: str
    source_field: str

    def to_public_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "label": self.label,
            "provider": self.provider,
            "url": self.url,
        }


_RETAILERS = {
    "www.oliveyoung.co.kr": "Olive Young",
    "www.ulta.com": "Ulta Beauty",
    "www.marksandspencer.com": "Marks & Spencer",
}

_REFERENCES: dict[str, tuple[CatalogLinkKind, str, str]] = {
    "incidecoder.com": ("ingredient_reference", "성분 정보 · INCIDecoder", "INCIDecoder"),
    "dailymed.nlm.nih.gov": ("data_reference", "공공 제품 정보 · DailyMed", "DailyMed"),
    "fda.report": ("data_reference", "제품 문서 · FDA.report", "FDA.report"),
    "world.openbeautyfacts.org": (
        "data_reference",
        "공개 상품 데이터 · Open Beauty Facts",
        "Open Beauty Facts",
    ),
}

# Curated catalog links were reviewed product by product. Keep this an exact
# brand-to-host mapping so a lookalike or unrelated shop can never become an
# official product source merely because its URL appeared in a CSV field.
_BRAND_HOSTS: dict[str, frozenset[str]] = {
    "abib": frozenset({"en.abib.com"}),
    "aestura": frozenset({"int.aestura.com"}),
    "anua": frozenset({"anua.com", "anuakorea.com"}),
    "axis-y": frozenset({"www.axis-y.com"}),
    "banila co": frozenset({"banilausa.com"}),
    "beauty of joseon": frozenset({"beautyofjoseon.com"}),
    "cosrx": frozenset({"www.cosrx.com"}),
    "dr.g": frozenset({"dr-g.com"}),
    "etude": frozenset({"www.etude.com"}),
    "goodal": frozenset({"goodalcosmetic.jp"}),
    "haruharu wonder": frozenset({"haruharuwonder.com"}),
    "isntree": frozenset({"isntree-global.com", "www.isntree.com"}),
    "ma:nyo": frozenset({"manyo.us"}),
    "mediheal": frozenset({"medihealus.com"}),
    "mixsoon": frozenset({"mixsoon.us"}),
    "needly": frozenset({"needly.us"}),
    "numbuzin": frozenset({"us.numbuzin.com"}),
    "round lab": frozenset({"roundlab.com"}),
    "skin1004": frozenset({"skin1004.com", "www.skin1004.com"}),
    "tirtir": frozenset({"tirtir.us"}),
    "torriden": frozenset({"torriden.us", "www.torriden.com"}),
}


def catalog_links(product: Product) -> list[CatalogLink]:
    """Return reviewed public links without confusing sources and sellers."""

    candidates = (
        ("purchase_url", product.purchase_url),
        ("oliveyoung_url", product.oliveyoung_url),
        ("official_url", product.official_url),
        ("source_url", product.source_url),
        ("ingredient_source_url", product.ingredient_source_url),
        ("review_source_url", product.review_source_url),
        ("data_attribution_url", product.data_attribution_url),
    )
    links: list[CatalogLink] = []
    seen_links: set[tuple[CatalogLinkKind, str]] = set()
    for source_field, raw_url in candidates:
        safe_url = _safe_https_url(raw_url)
        if not safe_url:
            continue
        host = _host(safe_url)
        if not host:
            continue

        retailer = _RETAILERS.get(host)
        if source_field == "review_source_url" and retailer:
            link = CatalogLink(
                "review_reference",
                f"리뷰 정보 · {retailer}",
                retailer,
                safe_url,
                source_field,
            )
        elif retailer:
            link = CatalogLink("retailer", retailer, retailer, safe_url, source_field)
        elif host in _BRAND_HOSTS.get(product.brand.strip().casefold(), frozenset()):
            link = CatalogLink(
                "brand_official",
                f"{product.brand} 공식 제품 정보",
                product.brand,
                safe_url,
                source_field,
            )
        elif host in _REFERENCES:
            kind, label, provider = _REFERENCES[host]
            link = CatalogLink(kind, label, provider, safe_url, source_field)
        else:
            continue

        link_key = (link.kind, safe_url)
        if link_key in seen_links:
            continue
        seen_links.add(link_key)
        links.append(link)
    return links


def retailer_links(product: Product) -> list[CatalogLink]:
    return [link for link in catalog_links(product) if link.kind == "retailer"]


def information_links(product: Product) -> list[CatalogLink]:
    links: list[CatalogLink] = []
    seen_providers: set[tuple[CatalogLinkKind, str]] = set()
    for link in catalog_links(product):
        if link.kind == "retailer":
            continue
        provider_key = (link.kind, link.provider.casefold())
        if provider_key in seen_providers:
            continue
        seen_providers.add(provider_key)
        links.append(link)
    return links


def _safe_https_url(value: str | None) -> str | None:
    if not value:
        return None
    url = value.strip()
    try:
        require_https_url(url)
        parsed = urlparse(url)
        port = parsed.port
    except (ValueError, UnicodeError):
        return None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or "%" in parsed.netloc
        or "\\" in url
        or any(ord(character) <= 32 for character in url)
        or (port is not None and port != 443)
    ):
        return None
    return url


def _host(url: str) -> str | None:
    try:
        hostname = urlparse(url).hostname
        return hostname.rstrip(".").lower().encode("idna").decode("ascii") if hostname else None
    except UnicodeError:
        return None
