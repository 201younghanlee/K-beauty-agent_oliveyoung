from __future__ import annotations

from http.cookies import SimpleCookie
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from k_beauty_agent import web
from k_beauty_agent.storage import SQLiteStore


def test_profile_avoid_ingredient_items_have_a_length_limit() -> None:
    client = TestClient(web.app)
    response = client.post(
        "/api/v2/recommend",
        json={
            "query": "serum",
            "use_openai": False,
            "profile": {
                "skin_type": "dry",
                "desired_categories": ["serum"],
                "avoid_ingredients": ["a" * 81],
            },
        },
    )
    assert response.status_code == 422


def test_public_request_body_limit_rejects_declared_and_streamed_oversize_bodies() -> None:
    client = TestClient(web.app)
    declared = client.post(
        "/api/v2/recommend",
        content=b"{}",
        headers={"Content-Length": str(web.MAX_PUBLIC_REQUEST_BODY_BYTES + 1)},
    )
    assert declared.status_code == 413

    def oversized_chunks():
        yield b"x" * (web.MAX_PUBLIC_REQUEST_BODY_BYTES // 2 + 1)
        yield b"y" * (web.MAX_PUBLIC_REQUEST_BODY_BYTES // 2 + 1)

    streamed = client.post(
        "/api/v2/recommend",
        content=oversized_chunks(),
        headers={"Transfer-Encoding": "chunked"},
    )
    assert streamed.status_code == 413


def test_invalid_session_cookie_is_replaced_with_a_safe_random_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web, "store", SQLiteStore(tmp_path / "request-cookie.sqlite3"))
    client = TestClient(web.app)
    response = client.get(
        "/api/session",
        headers={"Cookie": f"{web.SESSION_COOKIE}=x"},
    )
    assert response.status_code == 200
    parsed = SimpleCookie()
    parsed.load(response.headers["set-cookie"])
    replacement = parsed[web.SESSION_COOKIE].value
    assert replacement != "x"
    assert web.SESSION_ID_PATTERN.fullmatch(replacement)
