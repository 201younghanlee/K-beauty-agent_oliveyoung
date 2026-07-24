from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from urllib.parse import quote, urlparse

from .catalog_links import CatalogLink, retailer_links
from .identity_resolution import normalize_gtin
from .models import Product
from .source_adapters.security import require_https_url
from .storage import SQLiteStore, hash_session

DEFAULT_OFFER_TTL_SECONDS = 24 * 60 * 60
DEFAULT_REDIRECT_TTL_SECONDS = 15 * 60
MAX_REDIRECT_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_LOGGED_CLICKS_PER_MINUTE = 120
MAX_LOGGED_CLICKS_PER_OFFER_PER_MINUTE = 30
MAX_WEBHOOK_AGE_SECONDS = 5 * 60
MAX_MINOR_UNIT_AMOUNT = 9_000_000_000_000
CONVERSION_PAYLOAD_FIELDS = frozenset(
    {
        "affiliate_program_id",
        "external_conversion_id",
        "status",
        "occurred_at",
        "click_id",
        "order_amount",
        "commission_amount",
        "currency",
    }
)
DISCLOSURE_KO = "이 링크를 통해 구매가 발생하면 판매처로부터 수수료를 받을 수 있어요."
DISCLOSURE_EN = "We may receive a commission when a purchase is made through this link."
RANKING_POLICY_KO = "추천 점수와 제품 순위에는 제휴 수수료를 사용하지 않습니다."
RANKING_POLICY_EN = "Affiliate commission is not used in recommendation scores or product ranking."
MANUAL_COUPANG_LINK_SOURCE_KIND = "approved_source:coupang_partner_links"


class RedirectTokenError(ValueError):
    """Raised when an outbound redirect token cannot be trusted."""


@dataclass(frozen=True)
class RedirectTarget:
    offer_id: str
    url: str
    domain: str
    affiliate_program_id: str | None
    campaign: str | None
    token_hash: str


@dataclass(frozen=True)
class IngestionResult:
    record_id: str
    created: bool
    observation_written: bool = False


class CommerceService:
    """SQLite-backed product/retailer offer layer.

    The recommendation engine remains the authority for product ranking. This
    service only enriches an already-ranked product with retailer offers.
    """

    def __init__(self, store: SQLiteStore, signing_secret: str):
        if not signing_secret:
            raise ValueError("A redirect signing secret is required")
        self.store = store
        self._signing_secret = signing_secret.encode("utf-8")

    def sync_legacy_catalog(self, products: Iterable[Product]) -> dict[str, int]:
        """Idempotently backfill the current in-memory catalog and its legacy offer.

        Legacy prices are deliberately timestamped from the catalog evidence.
        Public serialization hides them once their freshness window has elapsed.
        """

        product_list = list(products)
        started_at = _now()
        products_seen = 0
        offers_seen = 0
        observations_written = 0
        try:
            with self.store.connect() as connection:
                run = connection.execute(
                    "INSERT INTO ingestion_runs(source_name, status, started_at, metadata_json) VALUES (?, 'running', ?, ?)",
                    ("legacy_catalog", started_at, json.dumps({"mode": "backfill"})),
                )
                run_id = int(run.lastrowid)
                connection.execute("UPDATE offers SET active = 0 WHERE source_kind = 'legacy_catalog'")

                for product in product_list:
                    products_seen += 1
                    self._upsert_product(connection, product, started_at)
                    for link in retailer_links(product):
                        destination_url = link.url
                        try:
                            domain = _validated_domain(destination_url)
                        except ValueError:
                            continue

                        retailer_id = self._upsert_retailer(
                            connection,
                            display_name=link.provider,
                            domain=domain,
                            now=started_at,
                        )
                        variant_id = _variant_id(product.id)
                        offer_id = _offer_id(product.id, retailer_id, destination_url)
                        price_amount, checked_at = _legacy_price_evidence(product, link)
                        stale_after = checked_at + DEFAULT_OFFER_TTL_SECONDS if checked_at else None
                        previous = connection.execute(
                            "SELECT price_amount, stock_status, checked_at, destination_url FROM offers WHERE id = ?",
                            (offer_id,),
                        ).fetchone()
                        connection.execute(
                            """
                            INSERT INTO offers(
                                id, variant_id, retailer_id, external_product_id, destination_url,
                                price_amount, currency, stock_status, checked_at, stale_after,
                                source_kind, active, metadata_json, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, 'KRW', 'unknown', ?, ?, 'legacy_catalog', 1, ?, ?, ?)
                            ON CONFLICT(id) DO UPDATE SET
                                variant_id = excluded.variant_id,
                                retailer_id = excluded.retailer_id,
                                external_product_id = excluded.external_product_id,
                                destination_url = excluded.destination_url,
                                price_amount = excluded.price_amount,
                                currency = excluded.currency,
                                stock_status = excluded.stock_status,
                                checked_at = excluded.checked_at,
                                stale_after = excluded.stale_after,
                                source_kind = excluded.source_kind,
                                active = 1,
                                metadata_json = excluded.metadata_json,
                                updated_at = excluded.updated_at
                            """,
                            (
                                offer_id,
                                variant_id,
                                retailer_id,
                                product.source_product_id,
                                destination_url,
                                price_amount,
                                checked_at,
                                stale_after,
                                json.dumps(
                                    {
                                        "backfilled_from": "Product",
                                        "catalog_link_source": link.source_field,
                                    },
                                    ensure_ascii=False,
                                ),
                                started_at,
                                started_at,
                            ),
                        )
                        offers_seen += 1
                        observation = (price_amount, "unknown", checked_at, destination_url)
                        prior_observation = (
                            previous["price_amount"],
                            previous["stock_status"],
                            previous["checked_at"],
                            previous["destination_url"],
                        ) if previous is not None else None
                        if prior_observation != observation:
                            connection.execute(
                                """
                                INSERT INTO offer_observations(
                                    offer_id, price_amount, currency, stock_status, observed_at, source_payload_json
                                ) VALUES (?, ?, 'KRW', 'unknown', ?, ?)
                                """,
                                (
                                    offer_id,
                                    price_amount,
                                    checked_at or started_at,
                                    json.dumps(
                                        {"backfilled": True, "catalog_link_source": link.source_field}
                                    ),
                                ),
                            )
                            observations_written += 1

                connection.execute(
                    """
                    UPDATE ingestion_runs
                    SET status = 'completed', completed_at = ?, products_seen = ?, offers_seen = ?, observations_written = ?
                    WHERE id = ?
                    """,
                    (_now(), products_seen, offers_seen, observations_written, run_id),
                )
        except Exception as exc:
            with self.store.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO ingestion_runs(
                        source_name, status, started_at, completed_at, products_seen,
                        offers_seen, observations_written, error_text, metadata_json
                    ) VALUES (?, 'failed', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "legacy_catalog",
                        started_at,
                        _now(),
                        products_seen,
                        offers_seen,
                        observations_written,
                        str(exc)[:1000],
                        json.dumps({"mode": "backfill"}),
                    ),
                )
            raise

        return {
            "products_seen": products_seen,
            "offers_seen": offers_seen,
            "observations_written": observations_written,
        }

    def _upsert_product(self, connection: sqlite3.Connection, product: Product, now: int) -> None:
        connection.execute(
            """
            INSERT INTO products(
                id, name, brand, category, catalog_source, source_product_id,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                brand = excluded.brand,
                category = excluded.category,
                catalog_source = excluded.catalog_source,
                source_product_id = excluded.source_product_id,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                product.id,
                product.name,
                product.brand,
                product.category,
                product.catalog_source,
                product.source_product_id,
                json.dumps(
                    {
                        "country": product.country,
                        "image_url": product.image_url,
                        "ingredient_status": product.ingredient_status,
                        "recommendation_tier": product.recommendation_tier,
                    },
                    ensure_ascii=False,
                ),
                now,
                now,
            ),
        )
        variant_id = _variant_id(product.id)
        connection.execute(
            """
            INSERT INTO product_variants(
                id, product_id, name, is_default, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, 1, '{}', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                product_id = excluded.product_id,
                name = excluded.name,
                is_default = 1,
                updated_at = excluded.updated_at
            """,
            (variant_id, product.id, product.name, now, now),
        )
        connection.execute(
            """
            INSERT INTO legacy_product_ids(legacy_id, namespace, product_id, migrated_at)
            VALUES (?, 'v1', ?, ?)
            ON CONFLICT(namespace, legacy_id) DO UPDATE SET
                product_id = excluded.product_id,
                migrated_at = excluded.migrated_at
            """,
            (product.id, product.id, now),
        )
        gtin = normalize_gtin(product.source_product_id) if product.catalog_source == "open_beauty_facts" else None
        if gtin:
            connection.execute(
                """
                INSERT INTO product_identifiers(
                    product_id, source_id, identifier_type,
                    identifier_value, confidence, created_at
                ) VALUES (?, NULL, 'gtin', ?, 1.0, ?)
                ON CONFLICT(product_id, identifier_type, identifier_value) DO UPDATE SET
                    confidence = MAX(product_identifiers.confidence, excluded.confidence)
                """,
                (product.id, gtin, now),
            )

    def _upsert_retailer(
        self,
        connection: sqlite3.Connection,
        *,
        display_name: str,
        domain: str,
        now: int,
    ) -> str:
        slug = _slug(display_name)
        retailer_id = f"retailer-{slug}"
        existing = connection.execute(
            "SELECT allowed_domains_json FROM retailers WHERE id = ?",
            (retailer_id,),
        ).fetchone()
        domains = _json_list(existing["allowed_domains_json"]) if existing is not None else []
        if domain not in domains:
            domains.append(domain)
        connection.execute(
            """
            INSERT INTO retailers(
                id, slug, display_name, base_url, allowed_domains_json,
                active, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, '{}', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                display_name = excluded.display_name,
                base_url = excluded.base_url,
                allowed_domains_json = excluded.allowed_domains_json,
                active = 1,
                updated_at = excluded.updated_at
            """,
            (retailer_id, slug, display_name, f"https://{domain}", json.dumps(sorted(domains)), now, now),
        )
        return retailer_id

    def upsert_retailer(
        self,
        *,
        display_name: str,
        base_url: str,
        allowed_domains: Iterable[str] = (),
        retailer_id: str | None = None,
        active: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> IngestionResult:
        """Register an explicitly approved retailer and exact domain allowlist."""

        base_domain = _validated_domain(base_url)
        domains = {_normalize_allowlisted_domain(domain) for domain in allowed_domains}
        domains.add(base_domain)
        slug = _slug(display_name)
        resolved_id = retailer_id or f"retailer-{slug}"
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", resolved_id):
            raise ValueError("retailer_id must be a 1-120 character safe identifier")
        now = _now()
        with self.store.connect() as connection:
            existed = connection.execute("SELECT 1 FROM retailers WHERE id = ?", (resolved_id,)).fetchone() is not None
            connection.execute(
                """
                INSERT INTO retailers(
                    id, slug, display_name, base_url, allowed_domains_json,
                    active, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name = excluded.display_name,
                    base_url = excluded.base_url,
                    allowed_domains_json = excluded.allowed_domains_json,
                    active = excluded.active,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    resolved_id,
                    slug,
                    display_name.strip(),
                    base_url,
                    json.dumps(sorted(domains)),
                    int(active),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return IngestionResult(record_id=resolved_id, created=not existed)

    def upsert_affiliate_program(
        self,
        *,
        program_id: str,
        retailer_id: str,
        program_name: str,
        status: str = "inactive",
        disclosure_ko: str = DISCLOSURE_KO,
        disclosure_en: str = DISCLOSURE_EN,
        metadata: dict[str, Any] | None = None,
    ) -> IngestionResult:
        if status not in {"inactive", "pending", "active", "suspended"}:
            raise ValueError("Unsupported affiliate program status")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", program_id):
            raise ValueError("program_id must be a 1-120 character safe identifier")
        now = _now()
        with self.store.connect() as connection:
            if connection.execute("SELECT 1 FROM retailers WHERE id = ?", (retailer_id,)).fetchone() is None:
                raise ValueError("Unknown retailer_id")
            existed = (
                connection.execute("SELECT 1 FROM affiliate_programs WHERE id = ?", (program_id,)).fetchone()
                is not None
            )
            connection.execute(
                """
                INSERT INTO affiliate_programs(
                    id, retailer_id, program_name, status, disclosure_ko,
                    disclosure_en, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    retailer_id = excluded.retailer_id,
                    program_name = excluded.program_name,
                    status = excluded.status,
                    disclosure_ko = excluded.disclosure_ko,
                    disclosure_en = excluded.disclosure_en,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    program_id,
                    retailer_id,
                    program_name,
                    status,
                    disclosure_ko,
                    disclosure_en,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return IngestionResult(record_id=program_id, created=not existed)

    def upsert_offer(
        self,
        *,
        product_id: str,
        retailer_id: str,
        destination_url: str,
        source_kind: str,
        offer_id: str | None = None,
        variant_id: str | None = None,
        external_product_id: str | None = None,
        price_amount: int | float | None = None,
        list_price_amount: int | float | None = None,
        currency: str = "KRW",
        stock_status: str = "unknown",
        availability_text: str | None = None,
        checked_at: str | int | float | None = None,
        ttl_seconds: int = DEFAULT_OFFER_TTL_SECONDS,
        affiliate_program_id: str | None = None,
        affiliate_url: str | None = None,
        commission_bps: int | None = None,
        active: bool = True,
        metadata: dict[str, Any] | None = None,
        source_payload: dict[str, Any] | None = None,
    ) -> IngestionResult:
        """Idempotently persist a normalized offer from an approved adapter."""

        if stock_status not in {"in_stock", "out_of_stock", "preorder", "unknown"}:
            raise ValueError("Unsupported stock_status")
        normalized_currency = currency.upper()
        if not re.fullmatch(r"[A-Z]{3}", normalized_currency):
            raise ValueError("currency must be a three-letter ISO-style code")
        _validate_money_amount(price_amount, "price_amount")
        _validate_money_amount(list_price_amount, "list_price_amount")
        if ttl_seconds < 60 or ttl_seconds > 30 * 24 * 60 * 60:
            raise ValueError("ttl_seconds must be between 60 seconds and 30 days")
        observed_at = _parse_timestamp(checked_at) or _now()
        resolved_variant_id = variant_id or _variant_id(product_id)
        now = _now()
        with self.store.connect() as connection:
            variant = connection.execute(
                "SELECT id FROM product_variants WHERE id = ? AND product_id = ?",
                (resolved_variant_id, product_id),
            ).fetchone()
            if variant is None:
                raise ValueError("Unknown product variant")
            retailer = connection.execute(
                "SELECT allowed_domains_json FROM retailers WHERE id = ? AND active = 1",
                (retailer_id,),
            ).fetchone()
            if retailer is None:
                raise ValueError("Unknown or inactive retailer")
            _validate_target_for_retailer(destination_url, retailer["allowed_domains_json"])
            if affiliate_url:
                _validate_target_for_retailer(affiliate_url, retailer["allowed_domains_json"])
            if affiliate_program_id:
                program = connection.execute(
                    "SELECT retailer_id FROM affiliate_programs WHERE id = ?",
                    (affiliate_program_id,),
                ).fetchone()
                if program is None or program["retailer_id"] != retailer_id:
                    raise ValueError("Affiliate program does not belong to retailer")

            resolved_offer_id = offer_id or _offer_id(product_id, retailer_id, destination_url)
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", resolved_offer_id):
                raise ValueError("offer_id must be a 1-160 character safe identifier")
            previous = connection.execute(
                """
                SELECT price_amount, list_price_amount, currency, stock_status, availability_text
                FROM offers WHERE id = ?
                """,
                (resolved_offer_id,),
            ).fetchone()
            current_observation = (
                price_amount,
                list_price_amount,
                normalized_currency,
                stock_status,
                availability_text,
            )
            previous_observation = (
                (
                    previous["price_amount"],
                    previous["list_price_amount"],
                    previous["currency"],
                    previous["stock_status"],
                    previous["availability_text"],
                )
                if previous is not None
                else None
            )
            connection.execute(
                """
                INSERT INTO offers(
                    id, variant_id, retailer_id, affiliate_program_id,
                    external_product_id, destination_url, affiliate_url,
                    price_amount, list_price_amount, currency, stock_status, availability_text,
                    checked_at, stale_after, source_kind, commission_bps, active,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    variant_id = excluded.variant_id,
                    retailer_id = excluded.retailer_id,
                    affiliate_program_id = excluded.affiliate_program_id,
                    external_product_id = excluded.external_product_id,
                    destination_url = excluded.destination_url,
                    affiliate_url = excluded.affiliate_url,
                    price_amount = excluded.price_amount,
                    list_price_amount = excluded.list_price_amount,
                    currency = excluded.currency,
                    stock_status = excluded.stock_status,
                    availability_text = excluded.availability_text,
                    checked_at = excluded.checked_at,
                    stale_after = excluded.stale_after,
                    source_kind = excluded.source_kind,
                    commission_bps = excluded.commission_bps,
                    active = excluded.active,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    resolved_offer_id,
                    resolved_variant_id,
                    retailer_id,
                    affiliate_program_id,
                    external_product_id,
                    destination_url,
                    affiliate_url,
                    price_amount,
                    list_price_amount,
                    normalized_currency,
                    stock_status,
                    availability_text,
                    observed_at,
                    observed_at + ttl_seconds,
                    source_kind,
                    commission_bps,
                    int(active),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            observation_written = previous_observation != current_observation
            if observation_written:
                connection.execute(
                    """
                    INSERT INTO offer_observations(
                        offer_id, price_amount, list_price_amount, currency, stock_status,
                        availability_text, observed_at, source_payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resolved_offer_id,
                        price_amount,
                        list_price_amount,
                        normalized_currency,
                        stock_status,
                        availability_text,
                        observed_at,
                        json.dumps(source_payload or {}, ensure_ascii=False),
                    ),
                )
        return IngestionResult(
            record_id=resolved_offer_id,
            created=previous is None,
            observation_written=observation_written,
        )

    def record_signed_conversion(
        self,
        *,
        raw_payload: bytes,
        signature: str,
        signed_at: int,
        webhook_secret: str,
        now: int | None = None,
    ) -> IngestionResult:
        """Verify a timestamped HMAC and record only the signed JSON bytes."""

        if not webhook_secret:
            raise ValueError("webhook_secret is required")
        current_time = _now() if now is None else int(now)
        try:
            timestamp = int(signed_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("A valid webhook signed_at timestamp is required") from exc
        if abs(current_time - timestamp) > MAX_WEBHOOK_AGE_SECONDS:
            raise ValueError("Conversion signature timestamp is outside the replay window")
        supplied = signature.removeprefix("sha256=").strip().lower()
        signed_content = f"{timestamp}.".encode("ascii") + raw_payload
        expected = hmac.new(webhook_secret.encode("utf-8"), signed_content, hashlib.sha256).hexdigest()
        if not re.fullmatch(r"[a-f0-9]{64}", supplied) or not hmac.compare_digest(expected, supplied):
            raise ValueError("Invalid conversion signature")
        try:
            payload = json.loads(raw_payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Signed conversion payload must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Signed conversion payload must be a JSON object")
        return self._record_conversion(payload, verification="hmac-sha256")

    def record_admin_conversion(self, payload: dict[str, Any]) -> IngestionResult:
        """Record a manually reconciled conversion after admin authentication."""

        return self._record_conversion(payload, verification="admin")

    def _record_conversion(self, payload: dict[str, Any], *, verification: str) -> IngestionResult:
        unexpected_fields = sorted(str(key) for key in payload if key not in CONVERSION_PAYLOAD_FIELDS)
        if unexpected_fields:
            raise ValueError(f"Unsupported conversion fields: {', '.join(unexpected_fields)}")
        program_id = str(payload.get("affiliate_program_id") or "")
        external_id = str(payload.get("external_conversion_id") or "")
        status = str(payload.get("status") or "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", program_id):
            raise ValueError("affiliate_program_id must be a safe configured identifier")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,240}", external_id):
            raise ValueError("affiliate_program_id and external_conversion_id are required")
        if status not in {"pending", "approved", "rejected", "reversed"}:
            raise ValueError("Unsupported conversion status")
        occurred_at = _parse_timestamp(payload.get("occurred_at"))
        if occurred_at is None:
            raise ValueError("A valid occurred_at timestamp is required")
        currency = str(payload.get("currency") or "KRW").upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("currency must be a three-letter ISO-style code")
        click_id = str(payload["click_id"]) if payload.get("click_id") else None
        if click_id and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", click_id):
            raise ValueError("click_id must be a safe opaque identifier")
        now = _now()
        with self.store.connect() as connection:
            if connection.execute("SELECT 1 FROM affiliate_programs WHERE id = ?", (program_id,)).fetchone() is None:
                raise ValueError("Unknown affiliate program")
            if click_id:
                click = connection.execute(
                    "SELECT affiliate_program_id FROM affiliate_clicks WHERE click_id = ?",
                    (click_id,),
                ).fetchone()
                if click is None or click["affiliate_program_id"] != program_id:
                    raise ValueError("click_id does not belong to affiliate program")
            previous = connection.execute(
                """
                SELECT id, status FROM affiliate_conversions
                WHERE affiliate_program_id = ? AND external_conversion_id = ?
                """,
                (program_id, external_id),
            ).fetchone()
            if previous is not None and verification == "hmac-sha256":
                allowed_transitions = {
                    "pending": {"pending", "approved", "rejected"},
                    "approved": {"approved", "reversed"},
                    "rejected": {"rejected"},
                    "reversed": {"reversed"},
                }
                if status not in allowed_transitions.get(str(previous["status"]), set()):
                    raise ValueError("Signed conversion status transition is not allowed")
            metadata = {"verification": verification}
            connection.execute(
                """
                INSERT INTO affiliate_conversions(
                    affiliate_program_id, click_id, external_conversion_id,
                    status, order_amount, commission_amount, currency,
                    occurred_at, recorded_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(affiliate_program_id, external_conversion_id) DO UPDATE SET
                    click_id = COALESCE(excluded.click_id, affiliate_conversions.click_id),
                    status = excluded.status,
                    order_amount = excluded.order_amount,
                    commission_amount = excluded.commission_amount,
                    currency = excluded.currency,
                    occurred_at = excluded.occurred_at,
                    recorded_at = excluded.recorded_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    program_id,
                    click_id,
                    external_id,
                    status,
                    _optional_int(payload.get("order_amount"), "order_amount"),
                    _optional_int(payload.get("commission_amount"), "commission_amount"),
                    currency,
                    occurred_at,
                    now,
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            row = connection.execute(
                """
                SELECT id FROM affiliate_conversions
                WHERE affiliate_program_id = ? AND external_conversion_id = ?
                """,
                (program_id, external_id),
            ).fetchone()
        return IngestionResult(record_id=str(row["id"]), created=previous is None)

    def offers_for_product(self, product_id: str, *, now: int | None = None) -> dict[str, Any]:
        current_time = _now() if now is None else now
        with self.store.connect() as connection:
            rows = connection.execute(_OFFERS_FOR_PRODUCT_SQL, (product_id,)).fetchall()
        offers = [self._public_offer(dict(row), current_time) for row in rows]
        offers.sort(key=_public_offer_sort_key)
        return {
            "product_id": product_id,
            "offers": offers,
            "summary": _offer_summary(product_id, offers),
            "affiliate_disclosure": disclosure_metadata(any(offer["affiliate"]["active"] for offer in offers)),
        }

    def product_summary(self, product_id: str, *, now: int | None = None) -> dict[str, Any]:
        return self.product_summaries([product_id], now=now)[product_id]

    def product_summaries(self, product_ids: Iterable[str], *, now: int | None = None) -> dict[str, dict[str, Any]]:
        ids = list(dict.fromkeys(product_ids))
        if not ids:
            return {}
        current_time = _now() if now is None else now
        rows: list[sqlite3.Row] = []
        with self.store.connect() as connection:
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows.extend(
                    connection.execute(
                        f"""
                        SELECT
                            p.id AS product_id, o.price_amount, o.currency, o.checked_at,
                            o.stale_after, o.stock_status, r.id AS retailer_id,
                            r.display_name AS retailer_name, o.affiliate_url,
                            ap.status AS affiliate_status
                        FROM products p
                        JOIN product_variants v ON v.product_id = p.id
                        JOIN offers o ON o.variant_id = v.id AND o.active = 1
                        JOIN retailers r ON r.id = o.retailer_id AND r.active = 1
                        LEFT JOIN affiliate_programs ap ON ap.id = o.affiliate_program_id
                        WHERE p.id IN ({placeholders})
                        """,
                        chunk,
                    ).fetchall()
                )
        grouped: dict[str, list[sqlite3.Row]] = {product_id: [] for product_id in ids}
        for row in rows:
            grouped[row["product_id"]].append(row)
        return {
            product_id: _summary_from_rows(product_id, product_rows, current_time)
            for product_id, product_rows in grouped.items()
        }

    def _public_offer(self, row: dict[str, Any], now: int) -> dict[str, Any]:
        freshness = _freshness(row.get("checked_at"), row.get("stale_after"), now)
        stored_stock = row.get("stock_status") or "unknown"
        public_stock = stored_stock if freshness == "fresh" else "unknown"
        price_amount = row.get("price_amount") if freshness == "fresh" else None
        list_price_amount = row.get("list_price_amount") if freshness == "fresh" else None
        price_status = "current" if price_amount is not None else freshness
        if freshness == "fresh" and price_amount is None:
            price_status = "unknown"
        affiliate_active = row.get("affiliate_status") == "active" and bool(row.get("affiliate_url"))
        affiliate_link_allowed = not row.get("affiliate_program_id") or affiliate_active
        # Explicitly marked link-only rows carry no live price or stock claim.
        # They may remain navigable after their observation timestamp ages out;
        # live feed offers keep the stricter stale-link block.
        link_only = _is_link_only_offer(row)
        token = (
            self.create_redirect_token(row["id"], now=now)
            if affiliate_link_allowed and (freshness != "stale" or _allows_stale_redirect(row))
            else None
        )
        return {
            "id": row["id"],
            "variant_id": row["variant_id"],
            "retailer": {
                "id": row["retailer_id"],
                "name": row["retailer_name"],
                "domain": urlparse(row["base_url"]).hostname,
            },
            "price": {
                "amount": price_amount,
                "currency": row["currency"],
                "status": price_status,
            },
            "list_price": {
                "amount": list_price_amount,
                "currency": row["currency"],
                "status": "current" if list_price_amount is not None else price_status,
            },
            "stock_status": public_stock,
            "availability_text": row.get("availability_text") if freshness == "fresh" else None,
            "freshness": {
                "status": freshness,
                "checked_at": _iso_timestamp(row.get("checked_at")),
                "stale_after": _iso_timestamp(row.get("stale_after")),
            },
            "redirect_url": f"/r/{token}" if token else None,
            "link_only": link_only,
            "affiliate": {
                "active": affiliate_active,
                "enabled": affiliate_active,
                "is_affiliate": affiliate_active,
                "program": row.get("program_name") if affiliate_active else None,
                "label": "광고·제휴" if affiliate_active else None,
                "disclosure_ko": (row.get("disclosure_ko") or DISCLOSURE_KO) if affiliate_active else None,
                "disclosure_en": (row.get("disclosure_en") or DISCLOSURE_EN) if affiliate_active else None,
                "disclosure": (row.get("disclosure_ko") or DISCLOSURE_KO) if affiliate_active else None,
            },
            "source_kind": row["source_kind"],
        }

    def create_redirect_token(
        self,
        offer_id: str,
        *,
        ttl_seconds: int = DEFAULT_REDIRECT_TTL_SECONDS,
        campaign: str = "product-offer",
        now: int | None = None,
    ) -> str:
        current_time = _now() if now is None else now
        ttl = max(60, min(int(ttl_seconds), MAX_REDIRECT_TTL_SECONDS))
        row = self._redirect_offer(offer_id, now=current_time)
        target_url = _target_url(row)
        _validate_target_for_retailer(target_url, row["allowed_domains_json"])
        payload = {
            "v": 1,
            "o": offer_id,
            "e": current_time + ttl,
            "u": _url_fingerprint(target_url),
            "c": _clean_campaign(campaign),
            "j": secrets.token_urlsafe(12),
        }
        encoded = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        signature = hmac.new(self._signing_secret, encoded.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded}.{_b64encode(signature)}"

    def resolve_redirect_token(self, token: str, *, now: int | None = None) -> RedirectTarget:
        current_time = _now() if now is None else now
        if len(token) > 2048 or token.count(".") != 1:
            raise RedirectTokenError("Invalid redirect token")
        encoded, supplied_signature = token.split(".", 1)
        try:
            encoded_bytes = encoded.encode("ascii")
        except UnicodeEncodeError as exc:
            raise RedirectTokenError("Invalid redirect token") from exc
        expected = hmac.new(self._signing_secret, encoded_bytes, hashlib.sha256).digest()
        try:
            actual = _b64decode(supplied_signature)
        except ValueError as exc:
            raise RedirectTokenError("Invalid redirect token") from exc
        if not hmac.compare_digest(expected, actual):
            raise RedirectTokenError("Invalid redirect token")
        try:
            payload = json.loads(_b64decode(encoded))
            version = int(payload["v"])
            offer_id = str(payload["o"])
            expires_at = int(payload["e"])
            fingerprint = str(payload["u"])
            campaign = _clean_campaign(str(payload.get("c") or "")) or None
            nonce = str(payload["j"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RedirectTokenError("Invalid redirect token") from exc
        if version != 1 or expires_at < current_time:
            raise RedirectTokenError("Redirect token has expired")
        if not re.fullmatch(r"[A-Za-z0-9_-]{12,40}", nonce):
            raise RedirectTokenError("Invalid redirect token nonce")
        if expires_at > current_time + MAX_REDIRECT_TTL_SECONDS:
            raise RedirectTokenError("Invalid redirect token expiry")

        row = self._redirect_offer(offer_id, now=current_time)
        target_url = _target_url(row)
        if not hmac.compare_digest(_url_fingerprint(target_url), fingerprint):
            raise RedirectTokenError("Redirect target changed")
        domain = _validate_target_for_retailer(target_url, row["allowed_domains_json"])
        return RedirectTarget(
            offer_id=offer_id,
            url=target_url,
            domain=domain,
            affiliate_program_id=row["affiliate_program_id"] if row["affiliate_status"] == "active" else None,
            campaign=campaign,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        )

    def _redirect_offer(self, offer_id: str, *, now: int) -> sqlite3.Row:
        with self.store.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    o.id, o.destination_url, o.affiliate_url, o.affiliate_program_id,
                    o.checked_at, o.stale_after, o.source_kind, o.metadata_json,
                    r.allowed_domains_json, ap.status AS affiliate_status
                FROM offers o
                JOIN retailers r ON r.id = o.retailer_id
                LEFT JOIN affiliate_programs ap ON ap.id = o.affiliate_program_id
                WHERE o.id = ? AND o.active = 1 AND r.active = 1
                """,
                (offer_id,),
            ).fetchone()
        if row is None:
            raise RedirectTokenError("Offer is unavailable")
        if row["affiliate_program_id"] and (
            row["affiliate_status"] != "active" or not row["affiliate_url"]
        ):
            raise RedirectTokenError("Affiliate offer is inactive")
        if (
            _freshness(row["checked_at"], row["stale_after"], now) == "stale"
            and not _allows_stale_redirect(row)
        ):
            raise RedirectTokenError("Offer data is stale")
        return row

    def log_click(self, target: RedirectTarget, *, session_id: str | None = None) -> str | None:
        click_id = secrets.token_urlsafe(16)
        now = _now()
        with self.store.connect() as connection:
            existing = connection.execute(
                "SELECT click_id FROM affiliate_clicks WHERE redirect_token_hash = ?",
                (target.token_hash,),
            ).fetchone()
            if existing is not None:
                return str(existing["click_id"])
            global_count = connection.execute(
                "SELECT COUNT(*) AS count FROM affiliate_clicks WHERE clicked_at >= ?",
                (now - 60,),
            ).fetchone()["count"]
            offer_count = connection.execute(
                "SELECT COUNT(*) AS count FROM affiliate_clicks WHERE offer_id = ? AND clicked_at >= ?",
                (target.offer_id, now - 60),
            ).fetchone()["count"]
            if (
                int(global_count) >= MAX_LOGGED_CLICKS_PER_MINUTE
                or int(offer_count) >= MAX_LOGGED_CLICKS_PER_OFFER_PER_MINUTE
            ):
                return None
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO affiliate_clicks(
                    click_id, offer_id, affiliate_program_id, session_hash, redirect_token_hash,
                    destination_domain, campaign, clicked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    click_id,
                    target.offer_id,
                    target.affiliate_program_id,
                    hash_session(session_id),
                    target.token_hash,
                    target.domain,
                    target.campaign,
                    now,
                ),
            )
            if inserted.rowcount == 0:
                existing = connection.execute(
                    "SELECT click_id FROM affiliate_clicks WHERE redirect_token_hash = ?",
                    (target.token_hash,),
                ).fetchone()
                return str(existing["click_id"]) if existing is not None else None
        return click_id

    def reconcile_source_activation(
        self,
        *,
        configured_source_ids: Iterable[str],
        approved_affiliate_source_ids: Iterable[str],
    ) -> dict[str, int]:
        """Fail closed when a configured source or affiliate approval disappears.

        Reconciliation only deactivates. A later successful source sync is
        required to reactivate offers, so restoring an environment variable
        alone cannot revive stale or contractually unapproved links.
        """

        configured = {str(value).strip() for value in configured_source_ids if str(value).strip()}
        approved = {str(value).strip() for value in approved_affiliate_source_ids if str(value).strip()}
        for source_id in configured | approved:
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", source_id):
                raise ValueError("Source activation sets contain an invalid source ID")
        effective_affiliate = configured & approved
        programs_changed = 0
        offers_deactivated = 0
        now = _now()
        with self.store.connect() as connection:
            programs = connection.execute(
                "SELECT id, status, metadata_json FROM affiliate_programs"
            ).fetchall()
            for program in programs:
                source_id = str(_json_object(program["metadata_json"]).get("source_id") or "")
                if not source_id or source_id in effective_affiliate:
                    continue
                if program["status"] == "active":
                    connection.execute(
                        "UPDATE affiliate_programs SET status = 'pending', updated_at = ? WHERE id = ?",
                        (now, program["id"]),
                    )
                    programs_changed += 1
                cursor = connection.execute(
                    "UPDATE offers SET active = 0, updated_at = ? WHERE affiliate_program_id = ? AND active = 1",
                    (now, program["id"]),
                )
                offers_deactivated += max(0, int(cursor.rowcount))

            source_offers = connection.execute(
                "SELECT id, source_kind FROM offers WHERE active = 1 AND source_kind LIKE 'approved_source:%'"
            ).fetchall()
            unavailable_offer_ids = [
                str(row["id"])
                for row in source_offers
                if str(row["source_kind"]).removeprefix("approved_source:") not in configured
            ]
            if unavailable_offer_ids:
                placeholders = ",".join("?" for _ in unavailable_offer_ids)
                cursor = connection.execute(
                    f"UPDATE offers SET active = 0, updated_at = ? WHERE id IN ({placeholders}) AND active = 1",
                    (now, *unavailable_offer_ids),
                )
                offers_deactivated += max(0, int(cursor.rowcount))
        return {
            "programs_changed": programs_changed,
            "offers_deactivated": offers_deactivated,
        }

    def source_review_candidates(
        self,
        *,
        source_id: str | None = None,
        limit: int = 50,
        cursor: int = 0,
    ) -> dict[str, Any]:
        """List unlinked source records for an authenticated operator review."""

        if source_id is not None and not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", source_id):
            raise ValueError("source_id must be a safe 1-120 character identifier")
        safe_limit = max(1, min(int(limit), 100))
        safe_cursor = max(0, int(cursor))
        where = "sr.product_id IS NULL"
        parameters: list[Any] = []
        if source_id is not None:
            where += " AND sr.source_id = ?"
            parameters.append(source_id)

        with self.store.connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM source_records sr WHERE {where}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT
                    sr.id, sr.source_id, sr.source_record_id, sr.source_url,
                    sr.fetched_at, sr.source_updated_at, sr.metadata_json
                FROM source_records sr
                WHERE {where}
                ORDER BY sr.fetched_at DESC, sr.id DESC
                LIMIT ? OFFSET ?
                """,
                (*parameters, safe_limit, safe_cursor),
            ).fetchall()
            record_ids = [int(row["id"]) for row in rows]
            candidate_rows: list[sqlite3.Row] = []
            if record_ids:
                placeholders = ",".join("?" for _ in record_ids)
                candidate_rows = connection.execute(
                    f"""
                    SELECT
                        mc.source_record_id, mc.candidate_product_id,
                        mc.match_strategy, mc.confidence, mc.status,
                        mc.reviewed_at, mc.reviewer_note,
                        p.name AS candidate_name, p.brand AS candidate_brand,
                        p.category AS candidate_category
                    FROM match_candidates mc
                    JOIN products p ON p.id = mc.candidate_product_id
                    WHERE mc.source_record_id IN ({placeholders})
                    ORDER BY mc.confidence DESC, mc.candidate_product_id
                    """,
                    record_ids,
                ).fetchall()

        candidates_by_record: dict[int, list[dict[str, Any]]] = {record_id: [] for record_id in record_ids}
        for candidate in candidate_rows:
            candidates_by_record[int(candidate["source_record_id"])].append(
                {
                    "product_id": candidate["candidate_product_id"],
                    "name": candidate["candidate_name"],
                    "brand": candidate["candidate_brand"],
                    "category": candidate["candidate_category"],
                    "strategy": candidate["match_strategy"],
                    "confidence": candidate["confidence"],
                    "status": candidate["status"],
                    "reviewed_at": _iso_timestamp(candidate["reviewed_at"]),
                    "reviewer_note": candidate["reviewer_note"],
                }
            )

        items: list[dict[str, Any]] = []
        public_metadata_keys = (
            "title",
            "brand",
            "variant",
            "gtin",
            "price",
            "list_price",
            "currency",
            "availability",
            "image_url",
            "match_status",
            "match_reason",
            "match_confidence",
            "affiliate",
        )
        for row in rows:
            metadata = _json_object(row["metadata_json"])
            items.append(
                {
                    "record_id": int(row["id"]),
                    "source_id": row["source_id"],
                    "source_record_id": row["source_record_id"],
                    "source_url": row["source_url"],
                    "fetched_at": _iso_timestamp(row["fetched_at"]),
                    "source_updated_at": _iso_timestamp(row["source_updated_at"]),
                    "source_product": {
                        key: metadata.get(key)
                        for key in public_metadata_keys
                        if metadata.get(key) is not None
                    },
                    "candidate_products": candidates_by_record[int(row["id"])],
                }
            )
        next_cursor = safe_cursor + len(items) if safe_cursor + len(items) < total else None
        return {
            "items": items,
            "total": total,
            "next_cursor": next_cursor,
            "policy": "manual_review_required",
        }

    def catalog_status(self, *, now: int | None = None) -> dict[str, Any]:
        current_time = _now() if now is None else now
        with self.store.connect() as connection:
            counts = {
                "products": _count(connection, "products"),
                "variants": _count(connection, "product_variants"),
                "retailers": _count_where(connection, "retailers", "active = 1"),
                "offers": _count_where(connection, "offers", "active = 1"),
                "active_affiliate_programs": _count_where(connection, "affiliate_programs", "status = 'active'"),
                "clicks": _count(connection, "affiliate_clicks"),
                "conversions": _count(connection, "affiliate_conversions"),
            }
            freshness = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN checked_at IS NULL OR stale_after IS NULL THEN 1 ELSE 0 END) AS unknown_count,
                    SUM(CASE WHEN checked_at IS NOT NULL AND stale_after >= ? THEN 1 ELSE 0 END) AS fresh_count,
                    SUM(CASE WHEN stale_after IS NOT NULL AND stale_after < ? THEN 1 ELSE 0 END) AS stale_count
                FROM offers WHERE active = 1
                """,
                (current_time, current_time),
            ).fetchone()
            last_run = connection.execute(
                """
                SELECT source_name, status, started_at, completed_at, products_seen,
                       offers_seen, observations_written, error_text
                FROM ingestion_runs ORDER BY started_at DESC, id DESC LIMIT 1
                """
            ).fetchone()
        return {
            "schema_version": 2,
            **counts,
            "offer_freshness": {
                "fresh": int(freshness["fresh_count"] or 0),
                "stale": int(freshness["stale_count"] or 0),
                "unknown": int(freshness["unknown_count"] or 0),
            },
            "last_ingestion_run": _run_to_dict(last_run),
            "rules": {
                "stale_prices_hidden": True,
                "stale_stock_becomes_unknown": True,
                "recommendation_ranking_uses_commission": False,
            },
            "affiliate_disclosure": disclosure_metadata(counts["active_affiliate_programs"] > 0),
        }

    def public_catalog_status(self, *, now: int | None = None) -> dict[str, Any]:
        """Return operationally safe catalog health without business metrics or errors."""

        status = self.catalog_status(now=now)
        return {
            "schema_version": status["schema_version"],
            "products": status["products"],
            "variants": status["variants"],
            "retailers": status["retailers"],
            "offers": status["offers"],
            "offer_freshness": status["offer_freshness"],
            "rules": status["rules"],
            "affiliate_disclosure": status["affiliate_disclosure"],
        }


def disclosure_metadata(required: bool) -> dict[str, Any]:
    return {
        "required": required,
        "label": "광고·제휴" if required else None,
        "text_ko": DISCLOSURE_KO if required else None,
        "text_en": DISCLOSURE_EN if required else None,
        "ranking_policy_ko": RANKING_POLICY_KO,
        "ranking_policy_en": RANKING_POLICY_EN,
    }


def _legacy_price_evidence(product: Product, link: CatalogLink) -> tuple[int | None, int | None]:
    """Attach a catalog price only to its explicitly configured purchase link.

    A retailer URL found in an official/review/source field proves that the
    product page exists; it does not prove that an old KRW snapshot belongs to
    that retailer. Those additional destinations therefore stay link-only.
    """

    if link.source_field not in {"purchase_url", "oliveyoung_url"}:
        return None, None
    price_amount = product.price_krw
    if price_amount is None:
        price_amount = product.oliveyoung_price_krw
    checked_at = _parse_timestamp(
        product.price_checked_at or product.oliveyoung_verified_at or product.verified_at
    )
    return price_amount, checked_at


_OFFERS_FOR_PRODUCT_SQL = """
    SELECT
        o.*, r.display_name AS retailer_name, r.base_url, r.allowed_domains_json,
        ap.program_name, ap.status AS affiliate_status, ap.disclosure_ko, ap.disclosure_en
    FROM products p
    JOIN product_variants v ON v.product_id = p.id
    JOIN offers o ON o.variant_id = v.id
    JOIN retailers r ON r.id = o.retailer_id
    LEFT JOIN affiliate_programs ap ON ap.id = o.affiliate_program_id
    WHERE p.id = ? AND o.active = 1 AND r.active = 1
"""


def _offer_summary(product_id: str, offers: list[dict[str, Any]]) -> dict[str, Any]:
    fresh = [offer for offer in offers if offer["freshness"]["status"] == "fresh"]
    priced = [
        offer
        for offer in fresh
        if (
            offer["price"]["amount"] is not None
            and offer["price"]["currency"] == "KRW"
            and offer["stock_status"] != "out_of_stock"
        )
    ]
    best = min(priced, key=lambda offer: offer["price"]["amount"]) if priced else None
    best_price = best["price"]["amount"] if best else None
    return {
        "offer_count": len(offers),
        "retailer_count": len({offer["retailer"]["id"] for offer in offers}),
        "fresh_offer_count": len(fresh),
        "stale_offer_count": sum(offer["freshness"]["status"] == "stale" for offer in offers),
        "unknown_offer_count": sum(offer["freshness"]["status"] == "unknown" for offer in offers),
        "best_current_price": (
            {
                "amount": best["price"]["amount"],
                "currency": best["price"]["currency"],
                "retailer_name": best["retailer"]["name"],
            }
            if best
            else None
        ),
        "lowest_fresh_price_krw": best_price,
        "has_affiliate_offers": any(offer["affiliate"]["active"] for offer in offers),
        "offers_url": f"/api/v2/products/{quote(product_id, safe='')}/offers",
    }


def _summary_from_rows(product_id: str, rows: list[sqlite3.Row], now: int) -> dict[str, Any]:
    freshness = [_freshness(row["checked_at"], row["stale_after"], now) for row in rows]
    priced = [
        row
        for row, status in zip(rows, freshness)
        if (
            status == "fresh"
            and row["price_amount"] is not None
            and row["currency"] == "KRW"
            and row["stock_status"] != "out_of_stock"
        )
    ]
    best = min(priced, key=lambda row: row["price_amount"]) if priced else None
    best_price = best["price_amount"] if best else None
    return {
        "offer_count": len(rows),
        "retailer_count": len({row["retailer_id"] for row in rows}),
        "fresh_offer_count": freshness.count("fresh"),
        "stale_offer_count": freshness.count("stale"),
        "unknown_offer_count": freshness.count("unknown"),
        "best_current_price": (
            {
                "amount": best["price_amount"],
                "currency": best["currency"],
                "retailer_name": best["retailer_name"],
            }
            if best
            else None
        ),
        "lowest_fresh_price_krw": best_price,
        "has_affiliate_offers": any(
            row["affiliate_status"] == "active" and bool(row["affiliate_url"])
            for row in rows
        ),
        "offers_url": f"/api/v2/products/{quote(product_id, safe='')}/offers",
    }


def _public_offer_sort_key(offer: dict[str, Any]) -> tuple[int, int, int, str]:
    freshness_rank = {"fresh": 0, "unknown": 1, "stale": 2}.get(offer["freshness"]["status"], 3)
    stock_rank = {"in_stock": 0, "preorder": 1, "unknown": 2, "out_of_stock": 3}.get(
        offer["stock_status"], 2
    )
    price = (
        offer["price"]["amount"]
        if offer["price"]["amount"] is not None and offer["price"]["currency"] == "KRW"
        else 2**63 - 1
    )
    return freshness_rank, stock_rank, price, offer["retailer"]["name"].casefold()


def _freshness(checked_at: int | None, stale_after: int | None, now: int) -> str:
    if checked_at is None or stale_after is None:
        return "unknown"
    return "fresh" if stale_after >= now else "stale"


def _is_link_only_offer(row: Any) -> bool:
    if row["source_kind"] == "legacy_catalog":
        return True
    if row["source_kind"] != MANUAL_COUPANG_LINK_SOURCE_KIND:
        return False
    return _json_object(row["metadata_json"]).get("link_only") is True


def _allows_stale_redirect(row: Any) -> bool:
    if row["source_kind"] == "legacy_catalog":
        return True
    if not _is_link_only_offer(row):
        return False
    return _json_object(row["metadata_json"]).get("stale_redirect_allowed") is True


def _target_url(row: sqlite3.Row) -> str:
    if row["affiliate_status"] == "active" and row["affiliate_url"]:
        return str(row["affiliate_url"])
    return str(row["destination_url"])


def _validate_target_for_retailer(url: str, allowed_domains_json: str) -> str:
    try:
        domain = _validated_domain(url)
    except ValueError as exc:
        raise RedirectTokenError("Redirect URL is invalid") from exc
    allowed_domains = _json_list(allowed_domains_json)
    if domain not in allowed_domains:
        raise RedirectTokenError("Redirect domain is not allowlisted")
    return domain


def _validated_domain(url: str) -> str:
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


def _normalize_allowlisted_domain(value: str) -> str:
    domain = value.strip().rstrip(".").lower()
    if not domain or "/" in domain or ":" in domain or domain.startswith("."):
        raise ValueError("Allowed domains must be exact hostnames without scheme, path, port, or wildcard")
    try:
        normalized = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Invalid allowed domain") from exc
    if not re.fullmatch(r"[a-z0-9.-]+", normalized) or ".." in normalized:
        raise ValueError("Invalid allowed domain")
    require_https_url(f"https://{normalized}")
    return normalized


def _url_fingerprint(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if slug:
        return slug[:80]
    return f"retailer-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"


def _variant_id(product_id: str) -> str:
    return f"variant-{hashlib.sha256(product_id.encode('utf-8')).hexdigest()[:24]}"


def _offer_id(product_id: str, retailer_id: str, destination_url: str) -> str:
    value = "\x1f".join((product_id, retailer_id, destination_url))
    return f"offer-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _parse_timestamp(value: str | int | float | None) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    try:
        return int(float(text))
    except ValueError:
        pass
    if text.endswith(" KST"):
        text = text[:-4]
        parsed = datetime.fromisoformat(text).replace(tzinfo=timezone(timedelta(hours=9)))
        return int(parsed.timestamp())
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _iso_timestamp(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def _json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).rstrip(".").lower() for item in parsed if str(item).strip()]


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_campaign(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "", value)[:80]


def _optional_int(value: Any, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer minor-unit amount")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer minor-unit amount") from exc
    if (
        not amount.is_finite()
        or amount != amount.to_integral_value()
        or amount < 0
        or amount > MAX_MINOR_UNIT_AMOUNT
    ):
        raise ValueError(f"{field_name} must be a non-negative integer minor-unit amount")
    return int(amount)


def _validate_money_amount(value: int | float | None, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    if not value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None or len(value) % 4 == 1:
        raise ValueError("Invalid base64")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError, TypeError) as exc:
        raise ValueError("Invalid base64") from exc
    if not hmac.compare_digest(_b64encode(decoded), value):
        raise ValueError("Invalid base64")
    return decoded


def _run_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "source_name": row["source_name"],
        "status": row["status"],
        "started_at": _iso_timestamp(row["started_at"]),
        "completed_at": _iso_timestamp(row["completed_at"]),
        "products_seen": row["products_seen"],
        "offers_seen": row["offers_seen"],
        "observations_written": row["observations_written"],
        "error": row["error_text"],
    }


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])


def _count_where(connection: sqlite3.Connection, table: str, where: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {where}").fetchone()["count"])


def _now() -> int:
    return int(time.time())
