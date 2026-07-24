from __future__ import annotations

from dataclasses import replace

import httpx
from fastapi.testclient import TestClient
import pytest

from k_beauty_agent import web
from k_beauty_agent.models import Product
from k_beauty_agent.storage import SQLiteStore
from k_beauty_agent.video_reviews import (
    YouTubeReviewService,
    _is_product_related,
    _review_query,
)


CHANNEL_ID = "UCabcdefghijklmnopqrstuv"
OTHER_CHANNEL_ID = "UCbbbbbbbbbbbbbbbbbbbbbb"


def _product() -> Product:
    return Product(
        id="round-lab-1025-dokdo-cleanser",
        name="Round Lab 1025 Dokdo Cleanser",
        display_name_ko="라운드랩 1025 독도 클렌저",
        brand="Round Lab",
        category="cleanser",
        country="Korea",
        ingredients=("Glycerin",),
    )


def test_without_api_key_returns_safe_product_specific_youtube_search() -> None:
    service = YouTubeReviewService(None)

    result = service.reviews_for_product(_product())

    assert result["status"] == "search_only"
    assert result["videos"] == []
    assert "API" not in result["message_ko"]
    assert "연동 키" not in result["message_ko"]
    assert result["search_url"].startswith("https://www.youtube.com/results?search_query=")
    assert "%EB%9D%BC%EC%9A%B4%EB%93%9C%EB%9E%A9" in result["search_url"]
    assert result["terms_url"] == "https://www.youtube.com/t/terms"
    assert result["privacy_url"] == "https://policies.google.com/privacy"
    service.close()


def test_review_query_uses_bilingual_alternatives_without_repeating_brand() -> None:
    query = _review_query(_product())

    assert query == (
        "라운드랩 1025 독도 클렌저 후기|"
        "Round Lab 1025 Dokdo Cleanser review"
    )
    assert query.count("Round Lab") == 1
    assert len(query) <= 240


def test_relevance_filter_requires_product_identity_and_review_intent() -> None:
    product = Product(
        id="cosrx-low-ph-good-morning-gel-cleanser",
        name="COSRX Low pH Good Morning Gel Cleanser",
        display_name_ko="COSRX 약산성 굿모닝 젤 클렌저",
        brand="COSRX",
        category="cleanser",
        country="Korea",
        ingredients=("Glycerin",),
    )

    def related(title: str, description: str = "") -> bool:
        return _is_product_related(
            product,
            {"title": title, "channelTitle": "Creator"},
            {"title": title, "description": description, "channelTitle": "Creator"},
        )

    assert related("COSRX Low pH Good Morning Gel Cleanser honest review")
    assert related("코스알엑스 약산성 굿모닝 젤 클렌저 솔직 사용 후기")
    assert related("Low pH Good Morning Gel Cleanser 30-day review")
    assert related("COSRX Low pH Good Morning Gel Cleanser 스킨케어 솔직 후기")

    # These are representative production false positives: brand-wide videos,
    # a generic low-pH cleanser from another brand, and a different COSRX line.
    assert not related("i tried everything from COSRX | honest review")
    assert not related("[COSRX] Best Sellers review")
    assert not related("빈스캐빈 약산성 클렌저 솔직 후기")
    assert not related("COSRX Low pH Cleanser review")
    assert not related("COSRX Snail Mucin Essence review")
    assert not related(
        "2026 skincare haul honest review",
        "COSRX Low pH Good Morning Gel Cleanser 약산성 굿모닝 클렌저",
    )
    assert not related("COSRX Low pH Good Morning Gel Cleanser official commercial")


def test_relevance_filter_rejects_same_family_wrong_category() -> None:
    assert _is_product_related(
        _product(),
        {"title": "Round Lab 1025 Dokdo Cleanser honest review"},
        {"title": "Round Lab 1025 Dokdo Cleanser honest review"},
    )
    assert not _is_product_related(
        _product(),
        {"title": "Round Lab 1025 Dokdo Toner honest review"},
        {"title": "Round Lab 1025 Dokdo Toner honest review"},
    )
    assert not _is_product_related(
        _product(),
        {"title": "Round Lab Birch Juice Sunscreen honest review"},
        {"title": "Round Lab Birch Juice Sunscreen honest review"},
    )
    brand_only_product = Product(
        id="embryolisse",
        name="Embryolisse",
        display_name_ko=None,
        brand="Embryolisse",
        category="moisturizer",
        country="France",
        ingredients=(),
    )
    assert not _is_product_related(
        brand_only_product,
        {"title": "Everything from Embryolisse honest review"},
        {"title": "Everything from Embryolisse honest review"},
    )


@pytest.mark.parametrize(
    ("category", "product_form", "competing_form"),
    [
        ("face_mask", "Repair Mask", "Hair Repair Mask"),
        ("moisturizer", "Repair Cream", "Eye Repair Cream"),
        ("moisturizer", "Repair Cream", "Body Repair Cream"),
        ("exfoliator", "Sugar Scrub", "Body Sugar Scrub"),
        ("cleanser", "Gentle Wash", "Body Gentle Wash"),
        ("serum", "Repair Serum", "Eye Repair Serum"),
    ],
)
def test_relevance_filter_prioritizes_scoped_competing_forms(
    category: str,
    product_form: str,
    competing_form: str,
) -> None:
    product = Product(
        id=f"example-{category}",
        name=f"Example {product_form}",
        display_name_ko=None,
        brand="Example",
        category=category,
        country="Unknown",
        ingredients=("Glycerin",),
    )
    title = f"Example {competing_form} honest review"

    assert not _is_product_related(
        product,
        {"title": title},
        {"title": title, "description": ""},
    )


@pytest.mark.parametrize(
    ("category", "form"),
    [
        ("eye_care", "Eye Cream"),
        ("body_moisturizer", "Body Lotion"),
        ("body_cleanser", "Body Wash"),
        ("hair_treatment", "Hair Mask"),
        ("lip_care", "Lip Mask"),
        ("exfoliator", "Exfoliating Toner"),
        ("eye_care", "Eye Mask"),
        ("eye_care", "아이세럼"),
        ("lip_care", "Lip Moisturizer"),
        ("base_makeup", "Tinted Moisturizer"),
        ("body_cleanser", "Bath Wash"),
        ("body_moisturizer", "풋크림"),
        ("body_exfoliator", "Body Exfoliator"),
    ],
)
def test_relevance_filter_accepts_multiword_category_forms(
    category: str,
    form: str,
) -> None:
    product = Product(
        id=f"example-{category}",
        name=f"Example Aurora {form}",
        display_name_ko=None,
        brand="Example",
        category=category,
        country="Unknown",
        ingredients=("Glycerin",),
    )
    title = f"Example Aurora {form} honest review"

    assert _is_product_related(
        product,
        {"title": title},
        {"title": title, "description": ""},
    )


def test_relevance_filter_preserves_youtube_search_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/videos")
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "partial0001",
                        "snippet": {
                            "title": "Round Lab Dokdo Cleanser review",
                            "channelTitle": "Creator",
                        },
                        "status": {
                            "privacyStatus": "public",
                            "embeddable": True,
                            "madeForKids": False,
                        },
                    },
                    {
                        "id": "exactfull01",
                        "snippet": {
                            "title": "Round Lab 1025 Dokdo Cleanser honest review",
                            "channelTitle": "Creator",
                        },
                        "status": {
                            "privacyStatus": "public",
                            "embeddable": True,
                            "madeForKids": False,
                        },
                    },
                    {
                        "id": "madeforkid1",
                        "snippet": {
                            "title": "Round Lab 1025 Dokdo Cleanser honest review",
                            "channelTitle": "Kids Creator",
                        },
                        "status": {
                            "privacyStatus": "public",
                            "embeddable": True,
                            "madeForKids": True,
                        },
                    },
                    {
                        "id": "unknownmfk1",
                        "snippet": {
                            "title": "Round Lab 1025 Dokdo Cleanser honest review",
                            "channelTitle": "Unknown Creator",
                        },
                        "status": {
                            "privacyStatus": "public",
                            "embeddable": True,
                        },
                    },
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = YouTubeReviewService("key", client=client)
    videos = service._video_details(
        [
            {"id": {"videoId": "partial0001"}, "snippet": {}},
            {"id": {"videoId": "exactfull01"}, "snippet": {}},
            {"id": {"videoId": "madeforkid1"}, "snippet": {}},
            {"id": {"videoId": "unknownmfk1"}, "snippet": {}},
        ],
        _product(),
    )

    assert [video["video_id"] for video in videos] == ["partial0001", "exactfull01"]
    client.close()


def test_api_results_are_verified_enriched_and_cached() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["x-goog-api-key"] == "server-secret-key"
        assert "server-secret-key" not in str(request.url)
        if request.url.path.endswith("/search"):
            assert request.url.params["type"] == "video"
            assert request.url.params["videoEmbeddable"] == "true"
            assert request.url.params["videoSyndicated"] == "true"
            assert request.url.params["safeSearch"] == "strict"
            assert "Round Lab" in request.url.params["q"]
            assert request.url.params["maxResults"] == "10"
            assert "channelId" in request.url.params["fields"]
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": {"videoId": "abcDEF_123-"}, "snippet": {}},
                        {"id": {"videoId": "noembed_123"}, "snippet": {}},
                        {"id": {"videoId": "wrongprod01"}, "snippet": {}},
                        {"id": {"videoId": "private1234"}, "snippet": {}},
                    ]
                },
            )
        if request.url.path.endswith("/videos"):
            assert "statistics" in request.url.params["part"]
            assert "channelId" in request.url.params["fields"]
            assert "viewCount" in request.url.params["fields"]
            assert "madeForKids" in request.url.params["fields"]
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "abcDEF_123-",
                            "snippet": {
                                "title": "I used Round Lab 1025 Dokdo Cleanser &amp; here is my review",
                                "channelId": CHANNEL_ID,
                                "channelTitle": "Skin Creator",
                                "publishedAt": "2026-07-01T01:02:03Z",
                                "thumbnails": {
                                    "medium": {
                                        "url": "https://i.ytimg.com/vi/abcDEF_123-/mqdefault.jpg"
                                    }
                                },
                            },
                            "status": {
                                "privacyStatus": "public",
                                "embeddable": True,
                                "madeForKids": False,
                            },
                            "contentDetails": {"duration": "PT8M12S"},
                            "paidProductPlacementDetails": {"hasPaidProductPlacement": True},
                            "statistics": {"viewCount": "50752", "likeCount": "1882"},
                        },
                        {
                            "id": "noembed_123",
                            "snippet": {
                                "title": "Round Lab Dokdo Cleanser review that cannot be embedded",
                                "channelId": CHANNEL_ID,
                                "channelTitle": "Skin Creator",
                            },
                            "status": {
                                "privacyStatus": "public",
                                "embeddable": False,
                                "madeForKids": False,
                            },
                        },
                        {
                            "id": "wrongprod01",
                            "snippet": {
                                "title": "Round Lab Birch Juice Sunscreen honest review",
                                "channelId": OTHER_CHANNEL_ID,
                                "channelTitle": "Skin Creator",
                            },
                            "status": {
                                "privacyStatus": "public",
                                "embeddable": True,
                                "madeForKids": False,
                            },
                        },
                        {
                            "id": "private1234",
                            "snippet": {"title": "Private", "channelTitle": "Hidden"},
                            "status": {
                                "privacyStatus": "private",
                                "embeddable": True,
                                "madeForKids": False,
                            },
                        },
                    ]
                },
            )
        assert request.url.path.endswith("/channels")
        assert request.url.params["part"] == "snippet,statistics"
        assert request.url.params["id"] == CHANNEL_ID
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": CHANNEL_ID,
                        "snippet": {
                            "thumbnails": {
                                "default": {
                                    "url": "https://yt3.googleusercontent.com/channel-avatar"
                                }
                            }
                        },
                        "statistics": {
                            "subscriberCount": "41900",
                            "hiddenSubscriberCount": False,
                        },
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = YouTubeReviewService("server-secret-key", client=client)

    first = service.reviews_for_product(_product(), limit=3)
    second = service.reviews_for_product(_product(), limit=3)

    assert first == second
    assert "server-secret-key" not in str(first)
    assert len(calls) == 3
    assert first["status"] == "ready"
    assert first["videos"] == [
        {
            "video_id": "abcDEF_123-",
            "title": "I used Round Lab 1025 Dokdo Cleanser & here is my review",
            "channel_title": "Skin Creator",
            "published_at": "2026-07-01T01:02:03Z",
            "duration": "PT8M12S",
            "thumbnail_url": "https://i.ytimg.com/vi/abcDEF_123-/mqdefault.jpg",
            "url": "https://www.youtube.com/watch?v=abcDEF_123-",
            "has_paid_product_placement": True,
            "channel_id": CHANNEL_ID,
            "channel_url": f"https://www.youtube.com/channel/{CHANNEL_ID}",
            "view_count": 50752,
            "like_count": 1882,
            "channel_thumbnail_url": "https://yt3.googleusercontent.com/channel-avatar",
            "subscriber_count_hidden": False,
            "subscriber_count": 41900,
        }
    ]
    client.close()


def test_malformed_thumbnail_and_upstream_failure_fail_closed() -> None:
    def malformed_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"items": [{"id": {"videoId": "abcDEF_123-"}}]})
        if request.url.path.endswith("/videos"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "abcDEF_123-",
                            "snippet": {
                                "title": "Round Lab Dokdo Cleanser Review",
                                "channelId": CHANNEL_ID,
                                "channelTitle": "Creator",
                                "thumbnails": {
                                    "medium": {
                                        "url": "https://i.ytimg.com.attacker.example/x.jpg"
                                    }
                                },
                            },
                            "statistics": {
                                "viewCount": "-1",
                                "likeCount": "9" * 5_000,
                            },
                            "status": {
                                "privacyStatus": "public",
                                "embeddable": True,
                                "madeForKids": False,
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": CHANNEL_ID,
                        "snippet": {
                            "thumbnails": {
                                "default": {
                                    "url": "https://yt3.googleusercontent.com.attacker.example/avatar"
                                }
                            }
                        },
                        "statistics": {
                            "subscriberCount": "99999",
                            "hiddenSubscriberCount": True,
                        },
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(malformed_handler))
    result = YouTubeReviewService("key", client=client).reviews_for_product(_product())
    video = result["videos"][0]
    assert video["thumbnail_url"] is None
    assert "view_count" not in video
    assert "like_count" not in video
    assert "channel_thumbnail_url" not in video
    assert video["subscriber_count_hidden"] is True
    assert "subscriber_count" not in video
    client.close()

    failing_client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(503, json={"error": "quota"}))
    )
    fallback = YouTubeReviewService("key", client=failing_client).reviews_for_product(_product())
    assert fallback["status"] == "temporarily_unavailable"
    assert fallback["videos"] == []
    assert fallback["search_url"].startswith("https://www.youtube.com/results?")
    failing_client.close()


def test_channel_lookup_failure_preserves_verified_video_and_statistics() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"items": [{"id": {"videoId": "abcDEF_123-"}}]})
        if request.url.path.endswith("/videos"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "abcDEF_123-",
                            "snippet": {
                                "title": "Round Lab Dokdo Cleanser Review",
                                "channelId": CHANNEL_ID,
                                "channelTitle": "Creator",
                            },
                            "statistics": {"viewCount": "12", "likeCount": "3"},
                            "status": {
                                "privacyStatus": "public",
                                "embeddable": True,
                                "madeForKids": False,
                            },
                        }
                    ]
                },
            )
        return httpx.Response(503, json={"error": "channel service unavailable"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = YouTubeReviewService("key", client=client).reviews_for_product(_product())

    assert calls == ["/youtube/v3/search", "/youtube/v3/videos", "/youtube/v3/channels"]
    assert result["status"] == "ready"
    assert result["videos"] == [
        {
            "video_id": "abcDEF_123-",
            "title": "Round Lab Dokdo Cleanser Review",
            "channel_title": "Creator",
            "published_at": None,
            "duration": None,
            "thumbnail_url": None,
            "url": "https://www.youtube.com/watch?v=abcDEF_123-",
            "has_paid_product_placement": False,
            "channel_id": CHANNEL_ID,
            "channel_url": f"https://www.youtube.com/channel/{CHANNEL_ID}",
            "view_count": 12,
            "like_count": 3,
        }
    ]
    client.close()


def test_invalid_channel_id_is_not_requested_or_exposed() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"items": [{"id": {"videoId": "abcDEF_123-"}}]})
        if request.url.path.endswith("/videos"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "abcDEF_123-",
                            "snippet": {
                                "title": "Round Lab Dokdo Cleanser Review",
                                "channelId": "UC-invalid/../../../attacker",
                                "channelTitle": "Creator",
                            },
                            "status": {
                                "privacyStatus": "public",
                                "embeddable": True,
                                "madeForKids": False,
                            },
                        }
                    ]
                },
            )
        raise AssertionError("invalid channel ID must not trigger channels.list")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = YouTubeReviewService("key", client=client).reviews_for_product(_product())

    assert calls == ["/youtube/v3/search", "/youtube/v3/videos"]
    assert result["status"] == "ready"
    assert "channel_id" not in result["videos"][0]
    assert "channel_url" not in result["videos"][0]
    client.close()


def test_video_review_endpoint_validates_product_and_never_changes_recommendation_data(monkeypatch) -> None:
    class StubService:
        def reviews_for_product(self, product: Product, *, limit: int = 3):
            return {"status": "ready", "product_id": product.id, "limit": limit, "videos": []}

    monkeypatch.setattr(web, "youtube_reviews", StubService())
    client = TestClient(web.app)
    existing_product = web.agent.database.products[0]

    headers = {"X-YouTube-Policy-Accepted": web.YOUTUBE_POLICY_ACCEPTANCE_VERSION}
    response = client.get(
        f"/api/v2/products/{existing_product.id}/video-reviews?limit=2",
        headers=headers,
    )
    missing = client.get("/api/v2/products/not-a-product/video-reviews", headers=headers)
    no_acceptance = client.get(f"/api/v2/products/{existing_product.id}/video-reviews")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "product_id": existing_product.id,
        "limit": 2,
        "videos": [],
    }
    assert missing.status_code == 404
    assert no_acceptance.status_code == 428


def test_daily_quota_uses_provider_day_and_persists_across_service_instances(tmp_path) -> None:
    quota_day = ["2026-07-21"]
    store = SQLiteStore(tmp_path / "quota.sqlite3")
    first = YouTubeReviewService(
        "key",
        daily_search_limit=1,
        quota_store=store,
        quota_day_provider=lambda: quota_day[0],
    )
    second = YouTubeReviewService(
        "key",
        daily_search_limit=1,
        quota_store=store,
        quota_day_provider=lambda: quota_day[0],
    )

    assert first._reserve_search() is True
    assert second._reserve_search() is False
    quota_day[0] = "2026-07-22"
    assert second._reserve_search() is True
    first.close()
    second.close()


def test_upstream_quota_error_opens_daily_circuit_breaker() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            403,
            json={"error": {"errors": [{"reason": "quotaExceeded"}]}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = YouTubeReviewService("key", daily_search_limit=3, client=client)

    first = service.reviews_for_product(_product())
    second = service.reviews_for_product(replace(_product(), id="another-round-lab-product"))

    assert first["status"] == "quota_limited"
    assert second["status"] == "quota_limited"
    assert calls == 1
    client.close()


def test_upstream_concurrency_guard_returns_fallback_without_calling_google() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(AssertionError("unexpected call")))
    )
    service = YouTubeReviewService("key", client=client, max_concurrent_searches=1)
    assert service._upstream_slots.acquire(blocking=False)
    try:
        result = service.reviews_for_product(_product())
    finally:
        service._upstream_slots.release()

    assert result["status"] == "temporarily_unavailable"
    client.close()


def test_video_review_endpoint_rate_limits_bursts(monkeypatch) -> None:
    class StubService:
        def reviews_for_product(self, product: Product, *, limit: int = 3):
            return {"status": "ready", "product_id": product.id, "videos": []}

    monkeypatch.setattr(web, "youtube_reviews", StubService())
    monkeypatch.setattr(web, "VIDEO_REVIEW_GLOBAL_RATE_LIMIT_REQUESTS", 2)
    web._rate_limit_buckets.clear()
    client = TestClient(web.app)
    product = web.agent.database.products[0]
    headers = {"X-YouTube-Policy-Accepted": web.YOUTUBE_POLICY_ACCEPTANCE_VERSION}
    try:
        first = client.get(f"/api/v2/products/{product.id}/video-reviews", headers=headers)
        second = client.get(f"/api/v2/products/{product.id}/video-reviews", headers=headers)
        limited = client.get(f"/api/v2/products/{product.id}/video-reviews", headers=headers)
    finally:
        web._rate_limit_buckets.clear()

    assert first.status_code == 200
    assert second.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == str(web.VIDEO_REVIEW_RATE_LIMIT_WINDOW_SECONDS)
