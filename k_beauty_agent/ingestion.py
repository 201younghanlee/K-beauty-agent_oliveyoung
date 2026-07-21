from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Collection, Iterable, Literal
from urllib.parse import urlparse

from .commerce import DISCLOSURE_EN, DISCLOSURE_KO, CommerceService
from .identity_resolution import MatchDecision, normalize_gtin, resolve_offer
from .models import Product
from .source_adapters.base import RetailerSource, SourceOffer, SourceSyncResult
from .source_adapters.registry import configured_sources
from .source_adapters.security import require_https_url


MAX_SOURCE_LIMIT = 100
MAX_PRICE_CHANGE_RATIO = 5.0
_SYNC_LOCK = threading.RLock()
_SAFE_RECORD_ID = re.compile(r"[A-Za-z0-9_.-]{1,120}")


@dataclass(frozen=True)
class SourceIngestionReport:
    source_id: str
    run_id: int
    status: Literal["completed", "failed"]
    fetched_at: int | None
    offers_received: int
    offers_persisted: int
    observations_written: int
    linked_product_ids: tuple[str, ...]
    review_candidates: int
    skipped_offers: int
    affiliate_active: bool
    warnings: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class _PreparedOffer:
    offer: SourceOffer
    decision: MatchDecision
    product_id: str | None
    variant_id: str | None
    retailer_id: str
    destination_host: str
    offer_id: str | None
    payload_hash: str

    @property
    def persists(self) -> bool:
        return self.product_id is not None and (
            self.decision.auto_link or self.decision.status == "explicit_link"
        )


@dataclass
class _MutationJournal:
    retailers: dict[str, dict[str, Any] | None]
    programs: dict[str, dict[str, Any] | None]
    offers: dict[str, dict[str, Any] | None]
    observation_max_ids: dict[str, int]


def sync_retailer_sources(
    commerce: CommerceService,
    products: Iterable[Product],
    *,
    query: str,
    sources: Iterable[RetailerSource] | None = None,
    explicit_product_id: str | None = None,
    identifiers: dict[str, set[str]] | None = None,
    active_affiliate_source_ids: Collection[str] = (),
    limit: int = 20,
) -> tuple[SourceIngestionReport, ...]:
    """Fetch and persist offers from configured, approved retailer adapters.

    The function never accepts a URL and never performs HTTP itself. In normal
    operation adapters come only from :func:`configured_sources`; ``sources``
    exists for dependency injection and tests. Adapter configuration remains
    responsible for feed and destination host approval.

    An offer is linked only when the caller explicitly supplies a canonical
    ``product_id`` or the identity resolver returns its conservative
    ``auto_link`` decision. Affiliate-only offers remain inactive until their
    source ID is present in ``active_affiliate_source_ids`` on every sync.
    """

    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("A non-empty product query is required")
    safe_limit = max(1, min(int(limit), MAX_SOURCE_LIMIT))
    product_list = list(products)
    product_ids = {product.id for product in product_list}
    if explicit_product_id is not None and explicit_product_id not in product_ids:
        raise ValueError("explicit_product_id is not present in the canonical catalog")

    owns_sources = sources is None
    selected_sources = list(configured_sources() if owns_sources else sources)
    try:
        source_ids = [str(source.source_id).strip() for source in selected_sources]
        if any(not source_id for source_id in source_ids):
            raise ValueError("Every retailer source must have a non-empty source_id")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Retailer source IDs must be unique within a sync")

        approved_affiliate_sources = {str(source_id).strip() for source_id in active_affiliate_source_ids}
        identifier_map = _identifier_map(commerce, identifiers)
        reports: list[SourceIngestionReport] = []
        with _SYNC_LOCK:
            for source in selected_sources:
                reports.append(
                    _sync_one_source(
                        commerce,
                        product_list,
                        source,
                        query=normalized_query,
                        limit=safe_limit,
                        explicit_product_id=explicit_product_id,
                        identifiers=identifier_map,
                        affiliate_approved=str(source.source_id).strip() in approved_affiliate_sources,
                    )
                )
        return tuple(reports)
    finally:
        if owns_sources:
            for source in selected_sources:
                close = getattr(getattr(source, "client", None), "close", None)
                if callable(close):
                    close()


def _sync_one_source(
    commerce: CommerceService,
    products: list[Product],
    source: RetailerSource,
    *,
    query: str,
    limit: int,
    explicit_product_id: str | None,
    identifiers: dict[str, set[str]],
    affiliate_approved: bool,
) -> SourceIngestionReport:
    source_id = str(source.source_id).strip()
    run_id = _start_run(commerce, source_id, query=query, explicit_product_id=explicit_product_id)
    fetched_at: int | None = None
    offers_received = 0
    persisted = 0
    observations = 0
    linked_product_ids: set[str] = set()
    review_candidates = 0
    warnings: list[str] = []
    journal: _MutationJournal | None = None

    try:
        if not source.enabled:
            raise RuntimeError("Retailer source is not enabled by its approved configuration")
        result = source.fetch(query, limit=limit)
        _validate_result_identity(source_id, result)
        fetched_at = _valid_timestamp(result.fetched_at, "source fetched_at")
        offers_received = len(result.offers)
        warnings.extend(str(warning)[:500] for warning in result.warnings[:100])
        if offers_received > limit:
            warnings.append(f"Adapter returned {offers_received} offers; only the configured limit of {limit} was processed")
            result = SourceSyncResult(result.source_id, result.offers[:limit], result.fetched_at, result.warnings)
        prepared = _prepare_offers(
            commerce,
            result,
            products,
            explicit_product_id=explicit_product_id,
            identifiers=identifiers,
        )
        review_candidates = sum(not item.persists for item in prepared)
        warnings.extend(
            f"Quarantined {item.offer.merchant_sku}: {item.decision.reason}"
            for item in prepared
            if item.decision.reason.startswith("price_anomaly:")
        )

        linked = [item for item in prepared if item.persists]
        retailer_specs = _retailer_specs(commerce, source_id, linked)
        program_specs = _affiliate_program_specs(commerce, source_id, linked)
        program_statuses = {
            program_id: (
                "suspended"
                if spec.get("current_status") == "suspended"
                else "active"
                if affiliate_approved
                else "pending"
            )
            for program_id, spec in program_specs.items()
        }
        inactive_programs = {
            program_id: spec
            for program_id, spec in program_specs.items()
            if program_statuses[program_id] != "active"
        }
        deactivate_offer_ids = _affiliate_offer_ids(commerce, inactive_programs)
        retired_domain_offer_ids = _retired_domain_offer_ids(commerce, retailer_specs)
        offers_to_deactivate = deactivate_offer_ids | retired_domain_offer_ids
        affiliate_program_active = any(status == "active" for status in program_statuses.values())
        journal = _snapshot_mutations(
            commerce,
            retailer_specs,
            program_specs,
            linked,
            extra_offer_ids=offers_to_deactivate,
        )

        for retailer_id, spec in retailer_specs.items():
            commerce.upsert_retailer(
                retailer_id=retailer_id,
                display_name=spec["display_name"],
                base_url=spec["base_url"],
                allowed_domains=spec["allowed_domains"],
                metadata=spec["metadata"],
            )

        for program_id, spec in program_specs.items():
            program_metadata = dict(spec.get("metadata") or {})
            program_metadata.update(
                {
                    "source_id": source_id,
                    "activation_policy": "explicit_source_approval",
                }
            )
            commerce.upsert_affiliate_program(
                program_id=program_id,
                retailer_id=spec["retailer_id"],
                program_name=spec["program_name"],
                status=program_statuses[program_id],
                disclosure_ko=spec.get("disclosure_ko") or DISCLOSURE_KO,
                disclosure_en=spec.get("disclosure_en") or DISCLOSURE_EN,
                metadata=program_metadata,
            )

        if offers_to_deactivate:
            with commerce.store.connect() as connection:
                placeholders = ",".join("?" for _ in offers_to_deactivate)
                connection.execute(
                    f"UPDATE offers SET active = 0, updated_at = ? WHERE id IN ({placeholders})",
                    (int(time.time()), *sorted(offers_to_deactivate)),
                )

        for item in linked:
            offer = item.offer
            program_id = _program_id(source_id, item.retailer_id) if offer.affiliate else None
            is_active = not offer.affiliate or (
                program_id is not None and program_statuses.get(program_id) == "active"
            )
            result_row = commerce.upsert_offer(
                product_id=str(item.product_id),
                variant_id=item.variant_id,
                retailer_id=item.retailer_id,
                destination_url=offer.landing_url,
                affiliate_url=offer.landing_url if offer.affiliate else None,
                affiliate_program_id=program_id,
                source_kind=f"approved_source:{source_id}",
                offer_id=item.offer_id,
                external_product_id=offer.merchant_sku,
                price_amount=offer.price,
                list_price_amount=offer.list_price,
                currency=offer.currency,
                stock_status="unknown" if offer.availability == "backorder" else offer.availability,
                availability_text="backorder" if offer.availability == "backorder" else None,
                checked_at=offer.observed_at or fetched_at,
                ttl_seconds=offer.stale_after_seconds,
                active=is_active,
                metadata={
                    "source_id": source_id,
                    "match_status": item.decision.status,
                    "match_reason": item.decision.reason,
                    "match_confidence": item.decision.confidence,
                    "affiliate_requires_explicit_activation": bool(offer.affiliate),
                },
                source_payload={
                    "source_id": source_id,
                    "merchant_sku": offer.merchant_sku,
                    "payload_hash": item.payload_hash,
                },
            )
            persisted += 1
            observations += int(result_row.observation_written)
            linked_product_ids.add(str(item.product_id))

        _write_provenance_and_complete(
            commerce,
            run_id,
            source_id,
            prepared,
            fetched_at=fetched_at,
            offers_received=offers_received,
            offers_persisted=persisted,
            observations_written=observations,
            linked_product_ids=linked_product_ids,
            review_candidates=review_candidates,
            warnings=warnings,
            affiliate_approved=affiliate_approved,
        )
        return SourceIngestionReport(
            source_id=source_id,
            run_id=run_id,
            status="completed",
            fetched_at=fetched_at,
            offers_received=offers_received,
            offers_persisted=persisted,
            observations_written=observations,
            linked_product_ids=tuple(sorted(linked_product_ids)),
            review_candidates=review_candidates,
            skipped_offers=offers_received - persisted,
            affiliate_active=affiliate_program_active,
            warnings=tuple(warnings),
        )
    except Exception as exc:
        rollback_error: Exception | None = None
        if journal is not None:
            try:
                _restore_mutations(commerce, journal)
            except Exception as restore_exc:  # pragma: no cover - catastrophic storage failure
                rollback_error = restore_exc
        error = f"{type(exc).__name__}: {exc}"[:1000]
        if rollback_error is not None:
            error = f"{error}; rollback failed: {rollback_error}"[:1000]
        _fail_run(
            commerce,
            run_id,
            error=error,
            offers_received=offers_received,
            offers_persisted=persisted,
            observations_written=observations,
            warnings=warnings,
        )
        return SourceIngestionReport(
            source_id=source_id,
            run_id=run_id,
            status="failed",
            fetched_at=fetched_at,
            offers_received=offers_received,
            offers_persisted=0,
            observations_written=0,
            linked_product_ids=(),
            review_candidates=review_candidates,
            skipped_offers=offers_received,
            affiliate_active=False,
            warnings=tuple(warnings),
            error=error,
        )


def _prepare_offers(
    commerce: CommerceService,
    result: SourceSyncResult,
    products: list[Product],
    *,
    explicit_product_id: str | None,
    identifiers: dict[str, set[str]],
) -> list[_PreparedOffer]:
    prepared: list[_PreparedOffer] = []
    variants = _default_variants(commerce, {product.id for product in products})
    for offer in result.offers:
        if offer.source_id != result.source_id:
            raise ValueError("SourceOffer source_id does not match its SourceSyncResult")
        if not offer.merchant_sku.strip() or len(offer.merchant_sku) > 240:
            raise ValueError("merchant_sku must contain 1-240 characters")
        if not _SAFE_RECORD_ID.fullmatch(offer.retailer_id):
            raise ValueError("retailer_id must be a safe 1-120 character identifier")
        host = _exact_https_host(offer.landing_url)
        currency = offer.currency.upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("currency must be a three-letter ISO-style code")
        for field_name, amount in (("price", offer.price), ("list_price", offer.list_price)):
            if amount is not None and (isinstance(amount, bool) or not math.isfinite(float(amount))):
                raise ValueError(f"{field_name} must be a finite number")
        if offer.stale_after_seconds < 60 or offer.stale_after_seconds > 30 * 24 * 60 * 60:
            raise ValueError("stale_after_seconds is outside the supported range")
        if offer.observed_at is not None:
            _valid_timestamp(offer.observed_at, "offer observed_at")

        if explicit_product_id is not None:
            decision = MatchDecision(explicit_product_id, 1.0, "explicit_link", "explicit_product_id")
            product_id: str | None = explicit_product_id
        else:
            decision = resolve_offer(offer, products, identifiers=identifiers)
            product_id = decision.product_id if decision.auto_link else None
        variant_id = variants.get(product_id) if product_id else None
        if product_id and not variant_id:
            raise ValueError(f"Canonical product has no default variant: {product_id}")
        payload_hash = _payload_hash(offer)
        offer_id = None
        if product_id and variant_id:
            offer_id = _existing_offer_id(
                commerce,
                variant_id=variant_id,
                retailer_id=offer.retailer_id,
                destination_url=offer.landing_url,
            ) or _stable_id("offer", result.source_id, offer.retailer_id, offer.merchant_sku, product_id)
            anomaly = _price_anomaly_reason(commerce, offer, offer_id=offer_id)
            if anomaly:
                decision = MatchDecision(
                    product_id,
                    decision.confidence,
                    "review",
                    f"price_anomaly:{anomaly}",
                )
                product_id = None
                variant_id = None
                offer_id = None
        prepared.append(
            _PreparedOffer(
                offer=offer,
                decision=decision,
                product_id=product_id,
                variant_id=variant_id,
                retailer_id=offer.retailer_id,
                destination_host=host,
                offer_id=offer_id,
                payload_hash=payload_hash,
            )
        )
    return prepared


def _price_anomaly_reason(
    commerce: CommerceService,
    offer: SourceOffer,
    *,
    offer_id: str,
) -> str | None:
    """Quarantine implausible money values before they affect ranking or display."""

    price = float(offer.price) if offer.price is not None else None
    list_price = float(offer.list_price) if offer.list_price is not None else None
    currency = offer.currency.upper()
    minimum, maximum = _currency_price_bounds(currency)
    if price is not None and (price < minimum or price > maximum):
        return f"price_outside_{currency}_bounds"
    if list_price is not None and (list_price < minimum or list_price > maximum):
        return f"list_price_outside_{currency}_bounds"
    if price is not None and list_price is not None and list_price < price:
        return "list_price_below_sale_price"
    if price is None:
        return None

    with commerce.store.connect() as connection:
        previous = connection.execute(
            "SELECT price_amount, currency FROM offers WHERE id = ?",
            (offer_id,),
        ).fetchone()
    if previous is None or previous["price_amount"] is None:
        return None
    if str(previous["currency"]).upper() != currency:
        return "currency_changed"
    previous_price = float(previous["price_amount"])
    if previous_price <= 0:
        return "invalid_previous_price"
    ratio = price / previous_price
    if ratio > MAX_PRICE_CHANGE_RATIO or ratio < 1 / MAX_PRICE_CHANGE_RATIO:
        return "price_changed_more_than_5x"
    return None


def _currency_price_bounds(currency: str) -> tuple[float, float]:
    if currency == "KRW":
        return 100.0, 10_000_000.0
    if currency == "JPY":
        return 1.0, 10_000_000.0
    return 0.01, 1_000_000.0


def _retailer_specs(
    commerce: CommerceService,
    source_id: str,
    linked: list[_PreparedOffer],
) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    with commerce.store.connect() as connection:
        for item in linked:
            current = specs.get(item.retailer_id)
            if current and current["display_name"] != item.offer.retailer_name:
                raise ValueError("One retailer_id cannot have multiple display names in a source result")
            if current is None:
                row = connection.execute(
                    "SELECT allowed_domains_json, metadata_json FROM retailers WHERE id = ?",
                    (item.retailer_id,),
                ).fetchone()
                # Treat the current approved source result as authoritative.
                # Retired hosts must not remain allowlisted indefinitely.
                allowed_domains: set[str] = set()
                metadata = _json_object(row["metadata_json"]) if row else {}
                source_ids = set(str(value) for value in metadata.get("approved_source_ids", []))
                source_ids.add(source_id)
                metadata.update(
                    {
                        "approved_source_ids": sorted(source_ids),
                        "allowlist_policy": "current_sync_exact_https_hosts",
                    }
                )
                current = {
                    "display_name": item.offer.retailer_name.strip() or item.retailer_id,
                    "base_url": f"https://{item.destination_host}",
                    "allowed_domains": allowed_domains,
                    "metadata": metadata,
                }
                specs[item.retailer_id] = current
            current["allowed_domains"].add(item.destination_host)
    for spec in specs.values():
        spec["allowed_domains"] = tuple(sorted(spec["allowed_domains"]))
    return specs


def _affiliate_program_specs(
    commerce: CommerceService,
    source_id: str,
    linked: list[_PreparedOffer],
) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    with commerce.store.connect() as connection:
        existing = connection.execute(
            """
            SELECT id, retailer_id, program_name, status, disclosure_ko,
                   disclosure_en, metadata_json
            FROM affiliate_programs
            """
        ).fetchall()
    for row in existing:
        metadata = _json_object(row["metadata_json"])
        if metadata.get("source_id") == source_id:
            specs[str(row["id"])] = {
                "retailer_id": str(row["retailer_id"]),
                "program_name": str(row["program_name"]),
                "current_status": str(row["status"]),
                "disclosure_ko": str(row["disclosure_ko"]),
                "disclosure_en": str(row["disclosure_en"]),
                "metadata": metadata,
            }
    for item in linked:
        if not item.offer.affiliate:
            continue
        program_id = _program_id(source_id, item.retailer_id)
        current = specs.get(program_id)
        if current is not None and current["retailer_id"] != item.retailer_id:
            raise ValueError("Affiliate program retailer identity changed unexpectedly")
        if current is None:
            specs[program_id] = {
                "retailer_id": item.retailer_id,
                "program_name": f"{item.offer.retailer_name} partner ({source_id})"[:200],
                "metadata": {},
            }
    return specs


def _affiliate_offer_ids(
    commerce: CommerceService,
    program_specs: dict[str, dict[str, Any]],
) -> set[str]:
    if not program_specs:
        return set()
    placeholders = ",".join("?" for _ in program_specs)
    with commerce.store.connect() as connection:
        rows = connection.execute(
            f"SELECT id FROM offers WHERE affiliate_program_id IN ({placeholders})",
            tuple(sorted(program_specs)),
        ).fetchall()
    return {str(row["id"]) for row in rows}


def _retired_domain_offer_ids(
    commerce: CommerceService,
    retailer_specs: dict[str, dict[str, Any]],
) -> set[str]:
    retired: set[str] = set()
    with commerce.store.connect() as connection:
        for retailer_id, spec in retailer_specs.items():
            allowed = set(spec["allowed_domains"])
            rows = connection.execute(
                """
                SELECT id, destination_url, affiliate_url
                FROM offers WHERE retailer_id = ? AND active = 1
                """,
                (retailer_id,),
            ).fetchall()
            for row in rows:
                targets = [row["destination_url"], row["affiliate_url"]]
                if any(
                    value and _exact_https_host(str(value)) not in allowed
                    for value in targets
                ):
                    retired.add(str(row["id"]))
    return retired


def _snapshot_mutations(
    commerce: CommerceService,
    retailer_specs: dict[str, dict[str, Any]],
    program_specs: dict[str, dict[str, Any]],
    linked: list[_PreparedOffer],
    *,
    extra_offer_ids: Collection[str] = (),
) -> _MutationJournal:
    offer_ids = sorted({str(item.offer_id) for item in linked} | set(extra_offer_ids))
    with commerce.store.connect() as connection:
        retailers = {record_id: _row(connection, "retailers", record_id) for record_id in retailer_specs}
        programs = {record_id: _row(connection, "affiliate_programs", record_id) for record_id in program_specs}
        offers = {record_id: _row(connection, "offers", record_id) for record_id in offer_ids}
        observation_max_ids = {
            offer_id: int(
                connection.execute(
                    "SELECT COALESCE(MAX(id), 0) FROM offer_observations WHERE offer_id = ?",
                    (offer_id,),
                ).fetchone()[0]
            )
            for offer_id in offer_ids
        }
    return _MutationJournal(retailers, programs, offers, observation_max_ids)


def _restore_mutations(commerce: CommerceService, journal: _MutationJournal) -> None:
    """Compensate commits made by public upsert methods after a failed sync."""

    with commerce.store.connect() as connection:
        for offer_id, previous in journal.offers.items():
            if previous is None:
                connection.execute("DELETE FROM offers WHERE id = ?", (offer_id,))
            else:
                connection.execute(
                    "DELETE FROM offer_observations WHERE offer_id = ? AND id > ?",
                    (offer_id, journal.observation_max_ids[offer_id]),
                )
                _restore_row(connection, "offers", "id", offer_id, previous)
        for program_id, previous in journal.programs.items():
            if previous is None:
                connection.execute("DELETE FROM affiliate_programs WHERE id = ?", (program_id,))
            else:
                _restore_row(connection, "affiliate_programs", "id", program_id, previous)
        for retailer_id, previous in journal.retailers.items():
            if previous is None:
                connection.execute("DELETE FROM retailers WHERE id = ?", (retailer_id,))
            else:
                _restore_row(connection, "retailers", "id", retailer_id, previous)


def _write_provenance_and_complete(
    commerce: CommerceService,
    run_id: int,
    source_id: str,
    prepared: list[_PreparedOffer],
    *,
    fetched_at: int,
    offers_received: int,
    offers_persisted: int,
    observations_written: int,
    linked_product_ids: set[str],
    review_candidates: int,
    warnings: list[str],
    affiliate_approved: bool,
) -> None:
    completed_at = int(time.time())
    with commerce.store.connect() as connection:
        for item in prepared:
            product_id = item.product_id if item.persists else None
            variant_id = item.variant_id if item.persists else None
            metadata = {
                "title": item.offer.title,
                "brand": item.offer.brand,
                "variant": item.offer.variant,
                "gtin": normalize_gtin(item.offer.gtin),
                "price": item.offer.price,
                "list_price": item.offer.list_price,
                "currency": item.offer.currency,
                "availability": item.offer.availability,
                "image_url": item.offer.image_url,
                "match_status": item.decision.status,
                "match_reason": item.decision.reason,
                "match_confidence": item.decision.confidence,
                "affiliate": item.offer.affiliate,
            }
            connection.execute(
                """
                INSERT INTO source_records(
                    source_id, source_record_id, product_id, variant_id,
                    source_url, payload_hash, fetched_at, source_updated_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, source_record_id) DO UPDATE SET
                    product_id = excluded.product_id,
                    variant_id = excluded.variant_id,
                    source_url = excluded.source_url,
                    payload_hash = excluded.payload_hash,
                    fetched_at = excluded.fetched_at,
                    source_updated_at = excluded.source_updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    source_id,
                    item.offer.merchant_sku,
                    product_id,
                    variant_id,
                    item.offer.landing_url,
                    item.payload_hash,
                    item.offer.observed_at or fetched_at,
                    item.offer.observed_at,
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            source_record = connection.execute(
                "SELECT id FROM source_records WHERE source_id = ? AND source_record_id = ?",
                (source_id, item.offer.merchant_sku),
            ).fetchone()
            candidate_product_id = item.decision.product_id
            if candidate_product_id:
                candidate_status = "linked" if item.persists else "pending"
                connection.execute(
                    """
                    INSERT INTO match_candidates(
                        source_record_id, candidate_product_id, match_strategy,
                        confidence, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_record_id, candidate_product_id) DO UPDATE SET
                        match_strategy = excluded.match_strategy,
                        confidence = excluded.confidence,
                        status = excluded.status
                    """,
                    (
                        int(source_record["id"]),
                        candidate_product_id,
                        item.decision.reason,
                        item.decision.confidence,
                        candidate_status,
                        completed_at,
                    ),
                )
            normalized_gtin = normalize_gtin(item.offer.gtin)
            if item.persists and normalized_gtin:
                connection.execute(
                    """
                    INSERT INTO product_identifiers(
                        product_id, source_id, identifier_type,
                        identifier_value, confidence, created_at
                    ) VALUES (?, ?, 'gtin', ?, ?, ?)
                    ON CONFLICT(product_id, identifier_type, identifier_value) DO UPDATE SET
                        source_id = excluded.source_id,
                        confidence = MAX(product_identifiers.confidence, excluded.confidence)
                    """,
                    (
                        item.product_id,
                        source_id,
                        normalized_gtin,
                        item.decision.confidence,
                        completed_at,
                    ),
                )

        current_run = connection.execute(
            "SELECT metadata_json FROM ingestion_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        run_metadata = _json_object(current_run["metadata_json"] if current_run else None)
        run_metadata.update({
            "offers_received": offers_received,
            "offers_skipped": offers_received - offers_persisted,
            "review_candidates": review_candidates,
            "affiliate_approved": affiliate_approved,
            "warnings": warnings,
        })
        connection.execute(
            """
            UPDATE ingestion_runs
            SET status = 'completed', completed_at = ?, products_seen = ?,
                offers_seen = ?, observations_written = ?, metadata_json = ?
            WHERE id = ?
            """,
            (
                completed_at,
                len(linked_product_ids),
                offers_persisted,
                observations_written,
                json.dumps(run_metadata, ensure_ascii=False),
                run_id,
            ),
        )


def _start_run(
    commerce: CommerceService,
    source_id: str,
    *,
    query: str,
    explicit_product_id: str | None,
) -> int:
    now = int(time.time())
    metadata = {
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "explicit_product_id": explicit_product_id,
        "fetch_policy": "configured_adapter_only",
    }
    with commerce.store.connect() as connection:
        source_row = connection.execute(
            "SELECT metadata_json FROM data_sources WHERE id = ?",
            (source_id,),
        ).fetchone()
        source_metadata = _json_object(source_row["metadata_json"] if source_row else None)
        source_metadata["configured"] = True
        connection.execute(
            """
            INSERT INTO data_sources(
                id, name, source_type, active, metadata_json, created_at, updated_at
            ) VALUES (?, ?, 'approved_retailer_adapter', 1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                source_type = excluded.source_type,
                active = 1,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (source_id, source_id, json.dumps(source_metadata, ensure_ascii=False), now, now),
        )
        cursor = connection.execute(
            """
            INSERT INTO ingestion_runs(source_name, status, started_at, metadata_json)
            VALUES (?, 'running', ?, ?)
            """,
            (source_id, now, json.dumps(metadata, ensure_ascii=False)),
        )
        return int(cursor.lastrowid)


def _fail_run(
    commerce: CommerceService,
    run_id: int,
    *,
    error: str,
    offers_received: int,
    offers_persisted: int,
    observations_written: int,
    warnings: list[str],
) -> None:
    with commerce.store.connect() as connection:
        current_run = connection.execute(
            "SELECT metadata_json FROM ingestion_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        metadata = _json_object(current_run["metadata_json"] if current_run else None)
        metadata.update(
            {
                "offers_received": offers_received,
                "rolled_back_offers": offers_persisted,
                "rolled_back_observations": observations_written,
                "warnings": warnings,
            }
        )
        connection.execute(
            """
            UPDATE ingestion_runs
            SET status = 'failed', completed_at = ?, offers_seen = 0,
                observations_written = 0, error_text = ?, metadata_json = ?
            WHERE id = ?
            """,
            (
                int(time.time()),
                error,
                json.dumps(metadata, ensure_ascii=False),
                run_id,
            ),
        )


def _identifier_map(
    commerce: CommerceService,
    supplied: dict[str, set[str]] | None,
) -> dict[str, set[str]]:
    identifiers: dict[str, set[str]] = {}
    for key, values in (supplied or {}).items():
        normalized = normalize_gtin(str(key))
        if normalized:
            identifiers.setdefault(normalized, set()).update(str(value) for value in values)
    with commerce.store.connect() as connection:
        rows = connection.execute(
            "SELECT product_id, identifier_value FROM product_identifiers WHERE identifier_type = 'gtin'"
        ).fetchall()
    for row in rows:
        normalized = normalize_gtin(str(row["identifier_value"]))
        if normalized:
            identifiers.setdefault(normalized, set()).add(str(row["product_id"]))
    return identifiers


def _default_variants(commerce: CommerceService, product_ids: set[str]) -> dict[str, str]:
    if not product_ids:
        return {}
    placeholders = ",".join("?" for _ in product_ids)
    with commerce.store.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT product_id, id, is_default
            FROM product_variants
            WHERE product_id IN ({placeholders})
            ORDER BY product_id, is_default DESC, id
            """,
            tuple(sorted(product_ids)),
        ).fetchall()
    variants: dict[str, str] = {}
    for row in rows:
        variants.setdefault(str(row["product_id"]), str(row["id"]))
    return variants


def _existing_offer_id(
    commerce: CommerceService,
    *,
    variant_id: str,
    retailer_id: str,
    destination_url: str,
) -> str | None:
    with commerce.store.connect() as connection:
        row = connection.execute(
            """
            SELECT id FROM offers
            WHERE variant_id = ? AND retailer_id = ? AND destination_url = ?
            """,
            (variant_id, retailer_id, destination_url),
        ).fetchone()
    return str(row["id"]) if row is not None else None


def _validate_result_identity(expected_source_id: str, result: SourceSyncResult) -> None:
    if result.source_id != expected_source_id:
        raise ValueError("SourceSyncResult source_id does not match the configured adapter")


def _exact_https_host(url: str) -> str:
    require_https_url(url)
    if any(ord(character) <= 32 for character in url) or "\\" in url:
        raise ValueError("Invalid characters in retailer URL")
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid retailer URL port") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or "%" in parsed.netloc
        or (port is not None and port != 443)
    ):
        raise ValueError("Only credential-free HTTPS retailer URLs are allowed")
    try:
        return parsed.hostname.rstrip(".").lower().encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Invalid retailer domain") from exc


def _valid_timestamp(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a Unix timestamp")
    try:
        normalized = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a Unix timestamp") from exc
    if normalized <= 0:
        raise ValueError(f"{field} must be a positive Unix timestamp")
    return normalized


def _payload_hash(offer: SourceOffer) -> str:
    payload = {
        "source_id": offer.source_id,
        "retailer_id": offer.retailer_id,
        "merchant_sku": offer.merchant_sku,
        "title": offer.title,
        "brand": offer.brand,
        "landing_url": offer.landing_url,
        "currency": offer.currency,
        "price": offer.price,
        "list_price": offer.list_price,
        "availability": offer.availability,
        "image_url": offer.image_url,
        "gtin": offer.gtin,
        "variant": offer.variant,
        "affiliate": offer.affiliate,
        "observed_at": offer.observed_at,
        "raw": offer.raw,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _program_id(source_id: str, retailer_id: str) -> str:
    return _stable_id("affiliate", source_id, retailer_id)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}-{digest}"


def _row(connection: sqlite3.Connection, table: str, record_id: str) -> dict[str, Any] | None:
    if table not in {"retailers", "affiliate_programs", "offers"}:
        raise ValueError("Unsupported journal table")
    row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
    return dict(row) if row is not None else None


def _restore_row(
    connection: sqlite3.Connection,
    table: str,
    key_column: str,
    key_value: str,
    previous: dict[str, Any],
) -> None:
    if table not in {"retailers", "affiliate_programs", "offers"} or key_column != "id":
        raise ValueError("Unsupported journal restore target")
    columns = [column for column in previous if column != key_column]
    assignments = ", ".join(f"{column} = ?" for column in columns)
    connection.execute(
        f"UPDATE {table} SET {assignments} WHERE {key_column} = ?",
        tuple(previous[column] for column in columns) + (key_value,),
    )


def _json_object(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}
