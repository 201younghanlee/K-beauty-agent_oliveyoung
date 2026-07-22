from __future__ import annotations

import pytest

from k_beauty_agent.config import (
    active_affiliate_source_ids,
    cors_allow_origins,
    public_llm_enabled,
    sqlite_path_from_url,
    validate_runtime_secrets,
)


def test_public_llm_is_disabled_by_default_in_production(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("PUBLIC_LLM_ENABLED", raising=False)

    assert public_llm_enabled() is False


def test_public_llm_can_be_explicitly_enabled(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("PUBLIC_LLM_ENABLED", "true")

    assert public_llm_enabled() is True


def test_default_cors_origins_cover_only_apps_in_toss(monkeypatch) -> None:
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)

    assert cors_allow_origins() == [
        "https://k-beauty-agent.apps.tossmini.com",
        "https://k-beauty-agent.private-apps.tossmini.com",
    ]


def test_production_cors_origins_require_exact_https_origins(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    for invalid in (
        "http://web.kbeauty.example",
        "https://*.kbeauty.example",
        "https://web.kbeauty.example/path",
    ):
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", invalid)
        with pytest.raises(ValueError, match="CORS_ALLOW_ORIGINS"):
            cors_allow_origins()


def test_unsupported_managed_database_urls_fail_fast() -> None:
    with pytest.raises(ValueError, match="Only SQLite"):
        sqlite_path_from_url("postgresql://db.example/app")


def test_affiliate_sources_require_explicit_safe_ids(monkeypatch) -> None:
    monkeypatch.setenv("ACTIVE_AFFILIATE_SOURCE_IDS", "coupang_partners, approved.feed")
    assert active_affiliate_source_ids() == {"coupang_partners", "approved.feed"}
    monkeypatch.setenv("ACTIVE_AFFILIATE_SOURCE_IDS", "coupang_partners,not allowed")
    with pytest.raises(ValueError, match="invalid source ID"):
        active_affiliate_source_ids()


def test_production_secrets_must_be_strong_and_distinct(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_TOKEN", "A" * 32)
    monkeypatch.setenv("SESSION_SECRET", "B" * 32)
    monkeypatch.setenv("AFFILIATE_REDIRECT_SECRET", "C" * 32)
    monkeypatch.setenv("AFFILIATE_WEBHOOK_SECRET", "D" * 32)
    validate_runtime_secrets()

    monkeypatch.setenv("SESSION_SECRET", "dev-session-secret-change-me")
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        validate_runtime_secrets()

    monkeypatch.setenv("SESSION_SECRET", "A" * 32)
    with pytest.raises(RuntimeError, match="distinct"):
        validate_runtime_secrets()


def test_retailer_sync_workflow_fails_when_api_reports_failed_runs() -> None:
    from pathlib import Path

    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/retailer-offer-sync.yml").read_text()
    assert "jq -e '.ok == true'" in workflow


def test_catalog_refresh_detects_manifest_only_changes() -> None:
    from pathlib import Path

    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/catalog-refresh.yml").read_text()
    assert workflow.count("data/catalog_generated.csv data/catalog_manifest.json") >= 2


def test_render_blueprints_preserve_operator_managed_partner_secrets() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for filename in ("render.yaml", "render.production.yaml"):
        blueprint = (root / filename).read_text()
        assert "pip install -r requirements.txt -c requirements.lock" in blueprint
        for key in (
            "PARTNER_FEEDS_JSON",
            "ACTIVE_AFFILIATE_SOURCE_IDS",
            "COUPANG_PARTNERS_ACCESS_KEY",
            "COUPANG_PARTNERS_SECRET_KEY",
        ):
            section = blueprint.split(f"- key: {key}", 1)[1].split("- key:", 1)[0]
            assert "sync: false" in section
