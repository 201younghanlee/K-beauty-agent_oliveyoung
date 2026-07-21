from __future__ import annotations

from pathlib import Path

import pytest

from k_beauty_agent import storage
from k_beauty_agent.storage import SQLiteStore, SessionWriteLimitError


def test_feedback_writes_are_bounded_per_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SQLiteStore(tmp_path / "feedback-limit.sqlite3")
    session_id = "S" * 24
    store.ensure_session(session_id)
    monkeypatch.setattr(storage, "MAX_FEEDBACK_PER_MINUTE", 1)

    store.add_feedback(session_id, "result", "liked")
    with pytest.raises(SessionWriteLimitError, match="feedback capacity"):
        store.add_feedback(session_id, "result", "liked")


def test_feedback_writes_have_a_global_minute_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SQLiteStore(tmp_path / "feedback-global-limit.sqlite3")
    monkeypatch.setattr(storage, "MAX_GLOBAL_FEEDBACK_PER_MINUTE", 1)
    first_session = "A" * 24
    second_session = "B" * 24
    store.ensure_session(first_session)
    store.ensure_session(second_session)

    store.add_feedback(first_session, "result", "liked")
    with pytest.raises(SessionWriteLimitError, match="feedback capacity"):
        store.add_feedback(second_session, "result", "liked")


def test_public_profile_migration_scrubs_legacy_free_text_once(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "legacy-profile.sqlite3")
    session_id = "L" * 24
    store.ensure_session(session_id)
    with store.connect() as connection:
        connection.execute(
            "UPDATE sessions SET profile_json = ? WHERE session_id = ?",
            ('{"allergies":["snail"],"pregnant_or_nursing":true}', session_id),
        )
        connection.execute(
            "INSERT INTO conversation_turns(session_id, role, query, created_at) "
            "VALUES (?, 'user', 'legacy health text', 1)",
            (session_id,),
        )
        connection.execute(
            """
            INSERT INTO recommendations(session_id, query, decision, result_json, latency_ms, created_at)
            VALUES (?, 'legacy health text', 'recommend', '{}', 1, 1)
            """,
            (session_id,),
        )
        connection.execute(
            """
            INSERT INTO feedback(session_id, recommendation_id, target, feedback, comment, created_at)
            VALUES (?, 1, 'result', 'liked', 'legacy free text', 1)
            """,
            (session_id,),
        )

    assert store.apply_public_profile_minimization_migration() == 4
    assert store.apply_public_profile_minimization_migration() == 0
    with store.connect() as connection:
        assert connection.execute("SELECT profile_json FROM sessions").fetchone()[0] == "{}"
        assert connection.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0] == 0
        feedback = connection.execute("SELECT recommendation_id, comment FROM feedback").fetchone()
    assert feedback["recommendation_id"] is None
    assert feedback["comment"] is None


def test_session_delete_removes_linked_hash_logs_and_clicks(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "delete-session.sqlite3")
    session_id = "D" * 24
    store.ensure_session(session_id)
    store.log_event("test", {"ok": True}, session_id=session_id)
    session_hash = storage.hash_session(session_id)

    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO products(id, name, brand, category, catalog_source, metadata_json, created_at, updated_at)
            VALUES ('p', 'P', 'B', 'serum', 'test', '{}', 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO product_variants(id, product_id, name, is_default, metadata_json, created_at, updated_at)
            VALUES ('v', 'p', 'default', 1, '{}', 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO retailers(id, slug, display_name, base_url, allowed_domains_json, metadata_json, created_at, updated_at)
            VALUES ('r', 'r', 'R', 'https://shop.example.com', '["shop.example.com"]', '{}', 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO affiliate_programs(
                id, retailer_id, program_name, status, disclosure_ko,
                disclosure_en, metadata_json, created_at, updated_at
            ) VALUES ('program', 'r', 'Program', 'active', '고지', 'Disclosure', '{}', 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO offers(id, variant_id, retailer_id, destination_url, currency, stock_status, source_kind, metadata_json, created_at, updated_at)
            VALUES ('o', 'v', 'r', 'https://shop.example.com/p', 'KRW', 'unknown', 'test', '{}', 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO affiliate_clicks(click_id, offer_id, session_hash, destination_domain, clicked_at)
            VALUES ('c', 'o', ?, 'shop.example.com', 1)
            """,
            (session_hash,),
        )

    store.delete_session(session_id)
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM app_events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM affiliate_clicks").fetchone()[0] == 0


def test_cleanup_bounds_offer_observation_and_ingestion_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SQLiteStore(tmp_path / "commerce-retention.sqlite3")
    now = 1_800_000_000
    monkeypatch.setattr(storage, "_now", lambda: now)
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO products(id, name, brand, category, catalog_source, metadata_json, created_at, updated_at)
            VALUES ('p', 'P', 'B', 'serum', 'test', '{}', 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO product_variants(id, product_id, name, is_default, metadata_json, created_at, updated_at)
            VALUES ('v', 'p', 'default', 1, '{}', 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO retailers(id, slug, display_name, base_url, allowed_domains_json, metadata_json, created_at, updated_at)
            VALUES ('r', 'r', 'R', 'https://shop.example.com', '["shop.example.com"]', '{}', 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO affiliate_programs(
                id, retailer_id, program_name, status, disclosure_ko,
                disclosure_en, metadata_json, created_at, updated_at
            ) VALUES ('program', 'r', 'Program', 'active', '고지', 'Disclosure', '{}', 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO offers(id, variant_id, retailer_id, destination_url, currency, stock_status, source_kind, metadata_json, created_at, updated_at)
            VALUES ('o', 'v', 'r', 'https://shop.example.com/p', 'KRW', 'unknown', 'test', '{}', 1, 1)
            """
        )
        for observed_at in (now - 181 * 86400, now - 179 * 86400):
            connection.execute(
                """
                INSERT INTO offer_observations(
                    offer_id, currency, stock_status, observed_at, source_payload_json
                ) VALUES ('o', 'KRW', 'unknown', ?, '{}')
                """,
                (observed_at,),
            )
        for started_at in (now - 91 * 86400, now - 89 * 86400):
            connection.execute(
                """
                INSERT INTO ingestion_runs(source_name, status, started_at, metadata_json)
                VALUES ('source', 'completed', ?, '{}')
                """,
                (started_at,),
            )
        for external_id, recorded_at in (
            ("old-conversion", now - 181 * 86400),
            ("recent-conversion", now - 179 * 86400),
        ):
            connection.execute(
                """
                INSERT INTO affiliate_conversions(
                    affiliate_program_id, external_conversion_id, status,
                    currency, occurred_at, recorded_at, metadata_json
                ) VALUES ('program', ?, 'approved', 'KRW', ?, ?, '{}')
                """,
                (external_id, recorded_at, recorded_at),
            )

    store.cleanup_expired()

    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM offer_observations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM affiliate_conversions").fetchone()[0] == 1
