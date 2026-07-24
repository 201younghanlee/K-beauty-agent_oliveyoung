from __future__ import annotations

import json
import os
import re
from typing import Iterable

from .base import RetailerSource
from .coupang_partner_links import CoupangPartnerLinksAdapter
from .coupang_partners import CoupangPartnersAdapter
from .partner_feed import PartnerFeedAdapter, PartnerFeedConfig


def configured_sources(*, include_disabled: bool = False) -> list[RetailerSource]:
    """Build only sources explicitly enabled by credentials/configuration.

    ``PARTNER_FEEDS_JSON`` is deliberately a JSON configuration rather than a
    free-form URL.  Every feed and destination hostname must be declared so a
    compromised row cannot turn the application into an open redirect.
    """

    sources: list[RetailerSource] = []
    coupang = CoupangPartnersAdapter()
    if include_disabled or coupang.enabled:
        sources.append(coupang)
    manual_coupang = CoupangPartnerLinksAdapter(os.getenv("COUPANG_PARTNERS_LINKS_JSON", ""))
    if include_disabled or manual_coupang.enabled:
        sources.append(manual_coupang)
    sources.extend(_partner_sources(os.getenv("PARTNER_FEEDS_JSON", "")))
    return sources


def source_status(sources: Iterable[RetailerSource] | None = None) -> list[dict[str, object]]:
    selected = list(sources) if sources is not None else configured_sources(include_disabled=True)
    statuses: list[dict[str, object]] = []
    for source in selected:
        status: dict[str, object] = {
            "source_id": source.source_id,
            "enabled": source.enabled,
        }
        details = getattr(source, "status_details", None)
        if callable(details):
            status.update(details())
        statuses.append(status)
    return statuses


def _partner_sources(raw: str) -> list[PartnerFeedAdapter]:
    if not raw.strip():
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("PARTNER_FEEDS_JSON must contain valid JSON") from exc
    if not isinstance(payload, list):
        raise ValueError("PARTNER_FEEDS_JSON must be a JSON array")
    sources: list[PartnerFeedAdapter] = []
    seen_ids: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Every PARTNER_FEEDS_JSON entry must be an object")
        source_id = _required_text(item, "source_id")
        if source_id in seen_ids:
            raise ValueError(f"Duplicate partner source_id: {source_id}")
        seen_ids.add(source_id)
        config = PartnerFeedConfig(
            source_id=source_id,
            retailer_id=_required_text(item, "retailer_id"),
            retailer_name=_required_text(item, "retailer_name"),
            feed_url=_required_text(item, "feed_url"),
            feed_hosts=_string_tuple(item.get("feed_hosts"), "feed_hosts"),
            destination_hosts=_string_tuple(item.get("destination_hosts"), "destination_hosts"),
            currency=str(item.get("currency") or "KRW").strip().upper(),
            affiliate=bool(item.get("affiliate", True)),
            stale_after_seconds=max(300, int(item.get("stale_after_seconds") or 129_600)),
            bearer_token=_secret_from_env(item.get("bearer_token_env")),
        )
        sources.append(PartnerFeedAdapter(config))
    return sources


def _required_text(item: dict[str, object], key: str) -> str:
    value = str(item.get(key) or "").strip()
    if not value:
        raise ValueError(f"Partner feed entry is missing {key}")
    return value


def _string_tuple(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Partner feed {key} must be a non-empty array")
    values = tuple(str(item).strip().lower().rstrip(".") for item in value if str(item).strip())
    if not values:
        raise ValueError(f"Partner feed {key} must contain a hostname")
    return values


def _secret_from_env(value: object) -> str | None:
    env_name = str(value or "").strip()
    if env_name and not re.fullmatch(r"PARTNER_FEED_[A-Z0-9_]+_TOKEN", env_name):
        raise ValueError("bearer_token_env must use a dedicated PARTNER_FEED_*_TOKEN variable")
    return os.getenv(env_name) if env_name else None
