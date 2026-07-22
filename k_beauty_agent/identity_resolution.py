from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from .models import Product
from .source_adapters.base import SourceOffer


SIZE_PATTERN = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*(ml|g|kg|oz)(?![a-z])", re.IGNORECASE)
NOISE_TOKENS = {
    "official",
    "global",
    "korea",
    "korean",
    "new",
    "sale",
    "set",
    "special",
    "기획",
    "공식",
    "단독",
    "세트",
}


@dataclass(frozen=True)
class MatchDecision:
    product_id: str | None
    confidence: float
    status: str
    reason: str

    @property
    def auto_link(self) -> bool:
        return self.status == "auto_link"


def resolve_offer(
    offer: SourceOffer,
    products: Iterable[Product],
    *,
    identifiers: dict[str, set[str]] | None = None,
) -> MatchDecision:
    """Resolve a retailer offer without silently merging ambiguous variants."""

    product_list = list(products)
    offer_identity_text = f"{offer.title} {offer.variant or ''}".strip()
    normalized_gtin = normalize_gtin(offer.gtin)
    if offer.gtin and normalized_gtin is None:
        return MatchDecision(None, 0.0, "review", "invalid_gtin")
    if normalized_gtin and identifiers:
        exact_ids = sorted(identifiers.get(normalized_gtin, set()))
        if len(exact_ids) == 1:
            candidate = next((item for item in product_list if item.id == exact_ids[0]), None)
            if candidate and not _size_conflict(offer_identity_text, candidate.name):
                return MatchDecision(candidate.id, 1.0, "auto_link", "exact_gtin")
        if len(exact_ids) > 1:
            return MatchDecision(None, 0.99, "review", "gtin_maps_to_multiple_variants")

    ranked: list[tuple[float, Product]] = []
    offer_brand = _normalize(offer.brand or "")
    offer_tokens = _tokens(offer_identity_text)
    if offer_brand:
        offer_tokens -= set(offer_brand.split())
    for product in product_list:
        product_brand = _normalize(product.brand)
        if offer_brand and product_brand and offer_brand != product_brand:
            continue
        if _size_conflict(offer_identity_text, product.name):
            continue
        product_tokens = _tokens(product.name)
        score = _jaccard(offer_tokens, product_tokens)
        if offer_brand and product_brand == offer_brand:
            score = min(1.0, score + 0.12)
        if score:
            ranked.append((score, product))
    if not ranked:
        return MatchDecision(None, 0.0, "new_candidate", "no_safe_candidate")
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    best_score, best = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
    if best_score >= 0.92 and best_score - runner_up >= 0.08:
        return MatchDecision(best.id, round(best_score, 4), "auto_link", "brand_name_variant_match")
    if best_score >= 0.75:
        return MatchDecision(best.id, round(best_score, 4), "review", "ambiguous_text_match")
    return MatchDecision(None, round(best_score, 4), "new_candidate", "low_confidence")


def normalize_gtin(value: str | None) -> str | None:
    """Return a checksum-valid GTIN-8/12/13/14 with display separators removed."""

    text = unicodedata.normalize("NFKC", value or "").strip()
    if not text:
        return None
    digits = re.sub(r"[\s-]", "", text)
    if not digits.isascii() or not digits.isdigit() or len(digits) not in {8, 12, 13, 14}:
        return None
    body = digits[:-1]
    weighted = sum(
        int(digit) * (3 if index % 2 == 0 else 1)
        for index, digit in enumerate(reversed(body))
    )
    expected = (10 - weighted % 10) % 10
    return digits if expected == int(digits[-1]) else None


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[0-9a-z가-힣]+", normalized))


def _tokens(value: str) -> set[str]:
    return {token for token in _normalize(value).split() if token not in NOISE_TOKENS and len(token) > 1}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _sizes(value: str) -> set[tuple[float, str]]:
    sizes: set[tuple[float, str]] = set()
    for amount, unit in SIZE_PATTERN.findall(unicodedata.normalize("NFKC", value)):
        normalized_unit = unit.lower()
        normalized_amount = float(amount)
        if normalized_unit == "kg":
            normalized_amount *= 1000
            normalized_unit = "g"
        sizes.add((normalized_amount, normalized_unit))
    return sizes


def _size_conflict(left: str, right: str) -> bool:
    left_sizes = _sizes(left)
    right_sizes = _sizes(right)
    return bool(left_sizes or right_sizes) and left_sizes != right_sizes
