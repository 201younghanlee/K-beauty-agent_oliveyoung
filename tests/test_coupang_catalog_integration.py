from __future__ import annotations

import json
from pathlib import Path

from k_beauty_agent.database import ProductDatabase
from k_beauty_agent.source_adapters.coupang_partner_links import (
    COUPANG_PARTNERS_DISCLOSURE_KO,
    CoupangPartnerLinksAdapter,
    parse_coupang_partner_links,
)
from k_beauty_agent.source_adapters.registry import configured_sources


ROOT = Path(__file__).resolve().parents[1]
LINKS_PATH = ROOT / "data" / "coupang_partner_links.json"
EXPANSION_PATH = ROOT / "data" / "products_official_expansion.json"
EXACT_DISCLOSURE = (
    "이 포스팅은 쿠팡 파트너스 활동의 일환으로, "
    "이에 따른 일정액의 수수료를 제공받습니다."
)


def test_official_expansion_and_partner_links_share_exact_catalog_ids() -> None:
    curated = ProductDatabase.from_csv(ROOT / "data" / "products_verified.csv")
    expansion = ProductDatabase.from_json(EXPANSION_PATH)
    catalog = ProductDatabase.combine(curated, expansion)
    links = parse_coupang_partner_links(LINKS_PATH.read_text(encoding="utf-8"))

    catalog_ids = {product.id for product in catalog.products}
    link_ids = {link.product_id for link in links}

    assert len(expansion.products) == 31
    assert len(links) == 49
    assert len(link_ids) == 49
    assert link_ids <= catalog_ids
    assert "official-kiehls-rare-earth-deep-pore-cleansing-masque" in catalog_ids
    assert "official-kiehls-rare-earth-deep-pore-cleansing-masque" not in link_ids
    assert all(product.official_url for product in expansion.products)
    assert all(product.ingredient_status == "missing" for product in expansion.products)
    assert all(product.recommendation_tier == "eligible" for product in expansion.products)


def test_git_managed_coupang_file_is_loaded_and_uses_exact_disclosure(
    monkeypatch,
) -> None:
    monkeypatch.setenv("COUPANG_PARTNERS_LINKS_FILE", "data/coupang_partner_links.json")
    monkeypatch.delenv("COUPANG_PARTNERS_LINKS_JSON", raising=False)
    monkeypatch.delenv("COUPANG_PARTNERS_ACCESS_KEY", raising=False)
    monkeypatch.delenv("COUPANG_PARTNERS_SECRET_KEY", raising=False)
    monkeypatch.delenv("PARTNER_FEEDS_JSON", raising=False)

    sources = configured_sources()
    manual = next(
        source for source in sources if isinstance(source, CoupangPartnerLinksAdapter)
    )

    assert len(manual.links) == 49
    assert manual.affiliate_disclosure_ko == EXACT_DISCLOSURE
    assert COUPANG_PARTNERS_DISCLOSURE_KO == EXACT_DISCLOSURE
    assert json.loads(LINKS_PATH.read_text(encoding="utf-8"))[0] == {
        "product_id": "cosrx-low-ph-good-morning-gel-cleanser",
        "affiliate_url": "https://link.coupang.com/a/fJiY9wwnYH",
    }
