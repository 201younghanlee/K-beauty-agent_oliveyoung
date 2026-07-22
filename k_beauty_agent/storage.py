from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import session_secret, sqlite_path_from_url

RETENTION_DAYS = 30
OFFER_OBSERVATION_RETENTION_DAYS = 180
INGESTION_RUN_RETENTION_DAYS = 90
AFFILIATE_CONVERSION_RETENTION_DAYS = 180
MAX_NEW_SESSIONS_PER_MINUTE = 120
MAX_ACTIVE_SESSIONS = 100_000
MAX_FEEDBACK_PER_MINUTE = 20
MAX_GLOBAL_FEEDBACK_PER_MINUTE = 600
MAX_FEEDBACK_PER_SESSION = 200
PUBLIC_PROFILE_MINIMIZATION_MIGRATION = "2026-07-controlled-profile-v1"


class SessionWriteLimitError(RuntimeError):
    """Raised when anonymous session creation reaches a storage safety cap."""


class SQLiteStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else sqlite_path_from_url()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def init_db(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS privacy_consents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    policy_version TEXT NOT NULL,
                    granted_at INTEGER NOT NULL,
                    UNIQUE(session_id, policy_version)
                );
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    query TEXT NOT NULL,
                    response_json TEXT,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    recommendation_id INTEGER,
                    target TEXT NOT NULL,
                    product_id TEXT,
                    feedback TEXT NOT NULL,
                    reason_tags TEXT NOT NULL DEFAULT '[]',
                    comment TEXT,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS openai_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    error TEXT,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_hash TEXT,
                    request_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    latency_ms INTEGER,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS selections (
                    session_id TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    list_type TEXT NOT NULL,
                    selected INTEGER NOT NULL DEFAULT 1,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (session_id, product_id, list_type)
                );
                CREATE INDEX IF NOT EXISTS idx_turns_session_created ON conversation_turns(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_feedback_session_created ON feedback(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at);
                CREATE INDEX IF NOT EXISTS idx_recommendations_created ON recommendations(created_at);
                CREATE INDEX IF NOT EXISTS idx_events_created ON app_events(created_at);
                CREATE INDEX IF NOT EXISTS idx_selections_session_type ON selections(session_id, list_type);
                CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at);
                CREATE TABLE IF NOT EXISTS data_migrations (
                    migration_id TEXT PRIMARY KEY,
                    applied_at INTEGER NOT NULL
                );

                -- Commerce v2 keeps the recommendation product master separate
                -- from retailer-specific availability and monetisation data.
                CREATE TABLE IF NOT EXISTS products (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    brand TEXT NOT NULL,
                    category TEXT NOT NULL,
                    catalog_source TEXT NOT NULL,
                    source_product_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS product_variants (
                    id TEXT PRIMARY KEY,
                    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    gtin TEXT,
                    sku TEXT,
                    size_value REAL,
                    size_unit TEXT,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS retailers (
                    id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    allowed_domains_json TEXT NOT NULL DEFAULT '[]',
                    active INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS affiliate_programs (
                    id TEXT PRIMARY KEY,
                    retailer_id TEXT NOT NULL REFERENCES retailers(id) ON DELETE CASCADE,
                    program_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'inactive',
                    disclosure_ko TEXT NOT NULL,
                    disclosure_en TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(retailer_id, program_name)
                );
                CREATE TABLE IF NOT EXISTS offers (
                    id TEXT PRIMARY KEY,
                    variant_id TEXT NOT NULL REFERENCES product_variants(id) ON DELETE CASCADE,
                    retailer_id TEXT NOT NULL REFERENCES retailers(id) ON DELETE CASCADE,
                    affiliate_program_id TEXT REFERENCES affiliate_programs(id) ON DELETE SET NULL,
                    external_product_id TEXT,
                    destination_url TEXT NOT NULL,
                    affiliate_url TEXT,
                    price_amount NUMERIC,
                    list_price_amount NUMERIC,
                    currency TEXT NOT NULL DEFAULT 'KRW',
                    stock_status TEXT NOT NULL DEFAULT 'unknown',
                    availability_text TEXT,
                    checked_at INTEGER,
                    stale_after INTEGER,
                    source_kind TEXT NOT NULL,
                    commission_bps INTEGER,
                    active INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(variant_id, retailer_id, destination_url)
                );
                CREATE TABLE IF NOT EXISTS offer_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    offer_id TEXT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
                    price_amount NUMERIC,
                    list_price_amount NUMERIC,
                    currency TEXT NOT NULL,
                    stock_status TEXT NOT NULL,
                    availability_text TEXT,
                    observed_at INTEGER NOT NULL,
                    source_payload_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS affiliate_clicks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    click_id TEXT NOT NULL UNIQUE,
                    offer_id TEXT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
                    affiliate_program_id TEXT REFERENCES affiliate_programs(id) ON DELETE SET NULL,
                    session_hash TEXT,
                    redirect_token_hash TEXT,
                    destination_domain TEXT NOT NULL,
                    campaign TEXT,
                    clicked_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS affiliate_conversions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    affiliate_program_id TEXT NOT NULL REFERENCES affiliate_programs(id) ON DELETE CASCADE,
                    click_id TEXT,
                    external_conversion_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    order_amount INTEGER,
                    commission_amount INTEGER,
                    currency TEXT NOT NULL DEFAULT 'KRW',
                    occurred_at INTEGER NOT NULL,
                    recorded_at INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(affiliate_program_id, external_conversion_id)
                );
                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at INTEGER NOT NULL,
                    completed_at INTEGER,
                    products_seen INTEGER NOT NULL DEFAULT 0,
                    offers_seen INTEGER NOT NULL DEFAULT 0,
                    observations_written INTEGER NOT NULL DEFAULT 0,
                    error_text TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS data_sources (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    base_url TEXT,
                    license_name TEXT,
                    license_url TEXT,
                    attribution_url TEXT,
                    terms_url TEXT,
                    refresh_interval_seconds INTEGER,
                    active INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS product_identifiers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    source_id TEXT REFERENCES data_sources(id) ON DELETE SET NULL,
                    identifier_type TEXT NOT NULL,
                    identifier_value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    created_at INTEGER NOT NULL,
                    UNIQUE(product_id, identifier_type, identifier_value)
                );
                CREATE TABLE IF NOT EXISTS source_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
                    source_record_id TEXT NOT NULL,
                    product_id TEXT REFERENCES products(id) ON DELETE SET NULL,
                    variant_id TEXT REFERENCES product_variants(id) ON DELETE SET NULL,
                    source_url TEXT,
                    payload_hash TEXT NOT NULL,
                    fetched_at INTEGER NOT NULL,
                    source_updated_at INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(source_id, source_record_id)
                );
                CREATE TABLE IF NOT EXISTS ingredient_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    variant_id TEXT REFERENCES product_variants(id) ON DELETE SET NULL,
                    source_record_id INTEGER REFERENCES source_records(id) ON DELETE SET NULL,
                    ingredients_json TEXT NOT NULL,
                    completeness TEXT NOT NULL DEFAULT 'unknown',
                    observed_at INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS match_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_record_id INTEGER NOT NULL REFERENCES source_records(id) ON DELETE CASCADE,
                    candidate_product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    match_strategy TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewed_at INTEGER,
                    reviewer_note TEXT,
                    created_at INTEGER NOT NULL,
                    UNIQUE(source_record_id, candidate_product_id)
                );
                CREATE TABLE IF NOT EXISTS legacy_product_ids (
                    legacy_id TEXT NOT NULL,
                    namespace TEXT NOT NULL DEFAULT 'v1',
                    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    migrated_at INTEGER NOT NULL,
                    PRIMARY KEY(namespace, legacy_id)
                );
                CREATE INDEX IF NOT EXISTS idx_variants_product ON product_variants(product_id);
                CREATE INDEX IF NOT EXISTS idx_offers_variant_active ON offers(variant_id, active);
                CREATE INDEX IF NOT EXISTS idx_offers_retailer_active ON offers(retailer_id, active);
                CREATE INDEX IF NOT EXISTS idx_offer_observations_offer_time ON offer_observations(offer_id, observed_at DESC);
                CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_offer_time ON affiliate_clicks(offer_id, clicked_at DESC);
                CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_time ON affiliate_clicks(clicked_at DESC);
                CREATE INDEX IF NOT EXISTS idx_affiliate_conversions_time ON affiliate_conversions(recorded_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ingestion_runs_source_time ON ingestion_runs(source_name, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_product_identifiers_lookup ON product_identifiers(identifier_type, identifier_value);
                CREATE INDEX IF NOT EXISTS idx_source_records_product_time ON source_records(product_id, fetched_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ingredient_snapshots_product_time ON ingredient_snapshots(product_id, observed_at DESC);
                CREATE INDEX IF NOT EXISTS idx_match_candidates_status_confidence ON match_candidates(status, confidence DESC);
                CREATE INDEX IF NOT EXISTS idx_legacy_product_ids_product ON legacy_product_ids(product_id);
                """
            )
            click_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(affiliate_clicks)").fetchall()
            }
            if "redirect_token_hash" not in click_columns:
                connection.execute("ALTER TABLE affiliate_clicks ADD COLUMN redirect_token_hash TEXT")
            offer_columns = {row["name"] for row in connection.execute("PRAGMA table_info(offers)").fetchall()}
            if "list_price_amount" not in offer_columns:
                connection.execute("ALTER TABLE offers ADD COLUMN list_price_amount NUMERIC")
            observation_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(offer_observations)").fetchall()
            }
            if "list_price_amount" not in observation_columns:
                connection.execute("ALTER TABLE offer_observations ADD COLUMN list_price_amount NUMERIC")
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_affiliate_clicks_redirect_token
                ON affiliate_clicks(redirect_token_hash)
                WHERE redirect_token_hash IS NOT NULL
                """
            )

    def ensure_session(self, session_id: str) -> dict[str, Any]:
        now = _now()
        expires_at = now + RETENTION_DAYS * 86400
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if row is not None and int(row["expires_at"]) <= now:
                _delete_session_rows(connection, session_id)
                row = None
            if row is None:
                recent_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM sessions WHERE created_at >= ?",
                    (now - 60,),
                ).fetchone()["count"]
                total_count = connection.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()["count"]
                if int(recent_count) >= MAX_NEW_SESSIONS_PER_MINUTE or int(total_count) >= MAX_ACTIVE_SESSIONS:
                    raise SessionWriteLimitError("Anonymous session capacity has been reached")
                connection.execute(
                    "INSERT INTO sessions(session_id, profile_json, created_at, updated_at, expires_at) VALUES (?, '{}', ?, ?, ?)",
                    (session_id, now, now, expires_at),
                )
                return {"session_id": session_id, "profile": {}, "created_at": now, "updated_at": now}
            connection.execute(
                "UPDATE sessions SET updated_at = ?, expires_at = ? WHERE session_id = ?",
                (now, expires_at, session_id),
            )
            return {
                "session_id": row["session_id"],
                "profile": json.loads(row["profile_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": now,
            }

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        now = _now()
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if row is None:
                return None
            if int(row["expires_at"]) <= now:
                _delete_session_rows(connection, session_id)
                return None
            return {
                "session_id": row["session_id"],
                "profile": json.loads(row["profile_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    def has_privacy_consent(self, session_id: str, policy_version: str) -> bool:
        now = _now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM sessions s
                JOIN privacy_consents c ON c.session_id = s.session_id
                WHERE s.session_id = ? AND s.expires_at > ? AND c.policy_version = ?
                """,
                (session_id, now, policy_version),
            ).fetchone()
        return row is not None

    def recommendation_belongs_to_session(self, recommendation_id: int, session_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM recommendations WHERE id = ? AND session_id = ?",
                (recommendation_id, session_id),
            ).fetchone()
        return row is not None

    def recommendation_contains_product(self, recommendation_id: int, session_id: str, product_id: str) -> bool:
        """Return whether a stored recommendation exposed the product to this session."""

        with self.connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM recommendations WHERE id = ? AND session_id = ?",
                (recommendation_id, session_id),
            ).fetchone()
        if row is None:
            return False
        try:
            payload = json.loads(row["result_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            return False
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            return False
        for item in results:
            if not isinstance(item, dict):
                continue
            product = item.get("product")
            if isinstance(product, dict) and product.get("id") == product_id:
                return True
            similar = item.get("similar_products")
            if isinstance(similar, list) and any(
                isinstance(candidate, dict) and candidate.get("id") == product_id
                for candidate in similar
            ):
                return True
        return False

    def record_privacy_consent(self, session_id: str, policy_version: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO privacy_consents(session_id, policy_version, granted_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id, policy_version) DO NOTHING
                """,
                (session_id, policy_version, _now()),
            )

    def save_profile(self, session_id: str, profile: dict[str, Any]) -> None:
        now = _now()
        with self.connect() as connection:
            connection.execute(
                "UPDATE sessions SET profile_json = ?, updated_at = ? WHERE session_id = ?",
                (json.dumps(profile, ensure_ascii=False), now, session_id),
            )

    def recent_queries(self, session_id: str, limit: int = 5) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT query FROM conversation_turns WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [row["query"] for row in reversed(rows)]

    def add_turn(self, session_id: str, role: str, query: str, response: dict[str, Any] | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO conversation_turns(session_id, role, query, response_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, query, json.dumps(response or {}, ensure_ascii=False), _now()),
            )

    def add_recommendation(
        self,
        session_id: str,
        query: str,
        decision: str,
        result: dict[str, Any],
        latency_ms: int,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO recommendations(session_id, query, decision, result_json, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, query, decision, json.dumps(result, ensure_ascii=False), latency_ms, _now()),
            )
            return int(cursor.lastrowid)

    def add_feedback(
        self,
        session_id: str,
        target: str,
        feedback: str,
        recommendation_id: int | None = None,
        product_id: str | None = None,
        reason_tags: list[str] | None = None,
        comment: str | None = None,
    ) -> int:
        now = _now()
        with self.connect() as connection:
            recent_count = connection.execute(
                "SELECT COUNT(*) AS count FROM feedback WHERE session_id = ? AND created_at >= ?",
                (session_id, now - 60),
            ).fetchone()["count"]
            global_recent_count = connection.execute(
                "SELECT COUNT(*) AS count FROM feedback WHERE created_at >= ?",
                (now - 60,),
            ).fetchone()["count"]
            total_count = connection.execute(
                "SELECT COUNT(*) AS count FROM feedback WHERE session_id = ?",
                (session_id,),
            ).fetchone()["count"]
            if (
                int(recent_count) >= MAX_FEEDBACK_PER_MINUTE
                or int(global_recent_count) >= MAX_GLOBAL_FEEDBACK_PER_MINUTE
                or int(total_count) >= MAX_FEEDBACK_PER_SESSION
            ):
                raise SessionWriteLimitError("Anonymous feedback capacity has been reached")
            cursor = connection.execute(
                """
                INSERT INTO feedback(session_id, recommendation_id, target, product_id, feedback, reason_tags, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    recommendation_id,
                    target,
                    product_id,
                    feedback,
                    json.dumps(reason_tags or []),
                    comment,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def feedback_for_session(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM feedback WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_selection(self, session_id: str, product_id: str, list_type: str, selected: bool) -> None:
        now = _now()
        with self.connect() as connection:
            if selected:
                connection.execute(
                    """
                    INSERT INTO selections(session_id, product_id, list_type, selected, updated_at)
                    VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(session_id, product_id, list_type)
                    DO UPDATE SET selected = 1, updated_at = excluded.updated_at
                    """,
                    (session_id, product_id, list_type, now),
                )
            else:
                connection.execute(
                    "DELETE FROM selections WHERE session_id = ? AND product_id = ? AND list_type = ?",
                    (session_id, product_id, list_type),
                )

    def selections_for_session(self, session_id: str) -> dict[str, list[str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT product_id, list_type
                FROM selections
                WHERE session_id = ? AND selected = 1
                ORDER BY updated_at ASC
                """,
                (session_id,),
            ).fetchall()
        selections = {"saved": [], "compare": []}
        for row in rows:
            list_type = row["list_type"]
            if list_type in selections:
                selections[list_type].append(row["product_id"])
        return selections

    def record_openai_call(self, session_id: str | None, model: str, status: str, latency_ms: int, error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO openai_calls(session_id, model, status, latency_ms, error, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, model, status, latency_ms, error, _now()),
            )

    def log_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO app_events(session_hash, request_id, event_type, payload_json, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    hash_session(session_id) if session_id else None,
                    request_id,
                    event_type,
                    json.dumps(payload or {}, ensure_ascii=False),
                    latency_ms,
                    _now(),
                ),
            )

    def delete_session(self, session_id: str) -> None:
        with self.connect() as connection:
            _delete_session_rows(connection, session_id)

    def apply_public_profile_minimization_migration(self) -> int:
        """One-time scrub of legacy free text and health-linked profile fields."""

        with self.connect() as connection:
            applied = connection.execute(
                "SELECT 1 FROM data_migrations WHERE migration_id = ?",
                (PUBLIC_PROFILE_MINIMIZATION_MIGRATION,),
            ).fetchone()
            if applied is not None:
                return 0
            changed = 0
            cursor = connection.execute("UPDATE sessions SET profile_json = '{}'")
            changed += cursor.rowcount
            cursor = connection.execute("DELETE FROM conversation_turns")
            changed += cursor.rowcount
            cursor = connection.execute("DELETE FROM recommendations")
            changed += cursor.rowcount
            cursor = connection.execute(
                "UPDATE feedback SET recommendation_id = NULL, comment = NULL "
                "WHERE recommendation_id IS NOT NULL OR comment IS NOT NULL"
            )
            changed += cursor.rowcount
            connection.execute(
                "INSERT INTO data_migrations(migration_id, applied_at) VALUES (?, ?)",
                (PUBLIC_PROFILE_MINIMIZATION_MIGRATION, _now()),
            )
        return changed

    def cleanup_expired(self, retention_days: int = RETENTION_DAYS) -> int:
        now = _now()
        cutoff = now - retention_days * 86400
        observation_cutoff = now - OFFER_OBSERVATION_RETENTION_DAYS * 86400
        ingestion_cutoff = now - INGESTION_RUN_RETENTION_DAYS * 86400
        conversion_cutoff = now - AFFILIATE_CONVERSION_RETENTION_DAYS * 86400
        deleted = 0
        with self.connect() as connection:
            for table in ("conversation_turns", "recommendations", "feedback", "openai_calls", "app_events"):
                cursor = connection.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,))
                deleted += cursor.rowcount
            cursor = connection.execute("DELETE FROM selections WHERE updated_at < ?", (cutoff,))
            deleted += cursor.rowcount
            cursor = connection.execute("DELETE FROM affiliate_clicks WHERE clicked_at < ?", (cutoff,))
            deleted += cursor.rowcount
            cursor = connection.execute(
                "DELETE FROM affiliate_conversions WHERE recorded_at < ?",
                (conversion_cutoff,),
            )
            deleted += cursor.rowcount
            cursor = connection.execute(
                "DELETE FROM offer_observations WHERE observed_at < ?",
                (observation_cutoff,),
            )
            deleted += cursor.rowcount
            cursor = connection.execute(
                "DELETE FROM ingestion_runs WHERE started_at < ?",
                (ingestion_cutoff,),
            )
            deleted += cursor.rowcount
            cursor = connection.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
            deleted += cursor.rowcount
        return deleted

    def metrics(self) -> dict[str, Any]:
        with self.connect() as connection:
            total_sessions = _count(connection, "sessions")
            total_recommendations = _count(connection, "recommendations")
            fallback = _count_where(connection, "recommendations", "decision = 'fallback'")
            ask_more = _count_where(connection, "recommendations", "decision = 'ask_more'")
            liked = _count_where(connection, "feedback", "feedback = 'liked'")
            disliked = _count_where(connection, "feedback", "feedback = 'disliked'")
            openai_failures = _count_where(connection, "openai_calls", "status != 'ok'")
            latencies = [row["latency_ms"] for row in connection.execute("SELECT latency_ms FROM recommendations").fetchall()]
            recent_errors = [
                dict(row)
                for row in connection.execute(
                    "SELECT event_type, payload_json, created_at FROM app_events WHERE event_type LIKE '%error%' ORDER BY created_at DESC LIMIT 10"
                ).fetchall()
            ]
            top_feedback = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT product_id, feedback, COUNT(*) AS count
                    FROM feedback
                    WHERE product_id IS NOT NULL
                    GROUP BY product_id, feedback
                    ORDER BY count DESC
                    LIMIT 12
                    """
                ).fetchall()
            ]
        return {
            "total_sessions": total_sessions,
            "total_recommendations": total_recommendations,
            "fallback_rate": _rate(fallback, total_recommendations),
            "ask_more_rate": _rate(ask_more, total_recommendations),
            "liked_count": liked,
            "disliked_count": disliked,
            "openai_failure_count": openai_failures,
            "latency_p50_ms": _percentile(latencies, 50),
            "latency_p95_ms": _percentile(latencies, 95),
            "top_feedback": top_feedback,
            "recent_errors": recent_errors,
        }


def hash_session(session_id: str | None) -> str | None:
    if not session_id:
        return None
    return hmac.new(session_secret().encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def _delete_session_rows(connection: sqlite3.Connection, session_id: str) -> None:
    session_hash = hash_session(session_id)
    for table in (
        "conversation_turns",
        "recommendations",
        "feedback",
        "openai_calls",
        "selections",
        "privacy_consents",
    ):
        connection.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
    if session_hash:
        connection.execute("DELETE FROM app_events WHERE session_hash = ?", (session_hash,))
        connection.execute("DELETE FROM affiliate_clicks WHERE session_hash = ?", (session_hash,))
    connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def _now() -> int:
    return int(time.time())


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])


def _count_where(connection: sqlite3.Connection, table: str, where: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {where}").fetchone()["count"])


def _rate(value: int, total: int) -> float:
    return round(value / total, 4) if total else 0.0


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((percentile / 100) * (len(ordered) - 1)))
    return int(ordered[index])
