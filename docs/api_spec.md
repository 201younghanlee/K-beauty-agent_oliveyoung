# API Spec: compatibility API and commerce v2

The public API uses the checked-in multi-source catalog by default. The current snapshot combines verified curated records with quality-filtered Open Beauty Facts records. The `/api/*` routes below are the v1 compatibility surface; new clients should use `/api/v2/recommend`, `/api/v2/follow-up`, `/api/v2/products`, `/api/v2/products/{id}/offers`, and `/api/v2/catalog/status`. Price and stock are commerce-offer fields, not Open Beauty Facts catalog fields. Counts change with reviewed catalog refreshes, so the abbreviated examples below intentionally omit volatile numeric totals; query the deployed endpoints for current values.

## GET `/health`

Checks whether the API is running.

### Response

```json
{
  "ok": true,
  "product_source": "catalog_snapshot",
  "product_source_status": {
    "source_used": "generated_snapshot"
  },
  "public_llm_enabled": false
}
```

## GET `/api/catalog/status`

Returns catalog size, source counts, recommendation tiers, ingredient-data status, snapshot update time, and the number of products with a checked price.

```json
{
  "product_source": "catalog_snapshot",
  "source_used": "generated_snapshot",
  "catalog_updated_at": "2026-07-20T00:17:46Z",
  "record_freshness": {
    "as_of": "2026-07-20T00:17:46Z",
    "newest_source_updated_at": "2025-06-08T12:07:37Z",
    "median_age_days": 1813
  },
  "message": "Using the checked-in multi-source catalog snapshot; prices and stock are not live."
}
```

The actual response also includes numeric total, source, recommendation-tier, ingredient-status, checked-price, and full freshness-distribution counts.

## GET `/api/products`

Browses the catalog without loading every product in one response.

| Query parameter | Meaning |
| --- | --- |
| `q` | Product, brand, ingredient, or claim text, maximum 120 characters |
| `category` | One normalized category, such as `serum` or `sunscreen` |
| `source` | Source identifier, such as `curated` or `open_beauty_facts` |
| `limit` | Page size from 1 to 100; default 50 |
| `cursor` | Zero-based offset for the next page |

Illustrative filtered result:

```json
{
  "products": [
    {
      "id": "open-beauty-facts-1234567890123",
      "name": "Example Serum",
      "brand": "Example Brand",
      "category": "serum",
      "catalog_source": "open_beauty_facts",
      "source_product_id": "1234567890123",
      "source_url": "https://world.openbeautyfacts.org/product/1234567890123",
      "source_updated_at": "2026-07-19T10:00:00Z",
      "ingredient_status": "reported",
      "recommendation_tier": "eligible",
      "price_krw": null,
      "price_checked_at": null,
      "data_license": "ODbL-1.0 (database); CC-BY-SA-3.0 (product images)"
    }
  ],
  "total": 1,
  "next_cursor": null
}
```

## POST `/api/recommend`

Returns personalized skincare recommendations from the current multi-source catalog.

### Request Body

```json
{
  "query": "지성 피부용 산뜻한 선크림을 추천해줘",
  "limit": 3,
  "use_openai": false,
  "language": "en",
  "privacy_consent": true,
  "privacy_policy_version": "2026-07-22",
  "profile": {
    "skin_type": "oily",
    "concerns": ["oil_control"],
    "desired_categories": ["sunscreen"],
    "avoid_ingredients": ["fragrance"],
    "max_price_krw": 30000,
    "texture_preference": "lightweight"
  }
}
```

### Fields

- `query`: Required request text, maximum 1,200 characters. The server rejects known health-condition, allergy, pregnancy, and nursing text; it never persists this raw value. Only a controlled profile summary is saved.
- `limit`: Number of products to return, from 1 to 8.
- `use_openai`: Requests an optional grounded explanation. Render keeps the public LLM disabled by default.
- `language`: `en` or `ko`.
- `profile`: Optional structured quiz values. `skin_type` and at least one `desired_categories` item are required when this object is present.
- `profile.avoid_ingredients`: Up to 12 inputs, reduced to supported canonical cosmetic ingredient names. Community-reported catalog rows are not considered when a supported exclusion is present.
- `profile.max_price_krw`: Uses only fresh KRW commerce prices for the budget comparison. Products without a fresh price receive a missing-price warning and penalty but can remain when otherwise suitable.
- `privacy_consent`: `true` stores the controlled profile, result, and selections for the anonymous session for up to 30 days. With `false`, recommendation is stateless and `recommendation_id` is `null`.

### Response Body

```json
{
  "recommendation_id": 42,
  "decision": "recommend",
  "query": "{\"controlled_profile\":{\"concerns\":[\"oil_control\"],\"desired_categories\":[\"sunscreen\"]}}",
  "results": [
    {
      "score": 7.3,
      "product": {
        "id": "isntree-hyaluronic-acid-watery-sun-gel",
        "name": "Hyaluronic Acid Watery Sun Gel",
        "brand": "Isntree",
        "category": "sunscreen",
        "price_krw": 25900,
        "catalog_source": "curated",
        "ingredient_status": "complete",
        "recommendation_tier": "verified"
      },
      "display_reasons": ["지성 피부 적합 신호가 있습니다."],
      "display_cautions": [],
      "personalized_reason": "선택한 조건과 성분 근거를 기준으로 추천했어요."
    }
  ],
  "grounded_explanation": "Recommended options ...",
  "openai_status": "not_used",
  "product_source_status": {
    "source_used": "generated_snapshot"
  }
}
```

## POST `/api/follow-up`

Uses the same request and response shape as `/api/recommend`, while merging
controlled fields with the anonymous session's stored profile. It requires
`privacy_consent: true` and the same cookie or `X-KBeauty-Session` header used
for the original recommendation. Free text is not retained or sent to the
LLM. Follow-up constraints are parsed locally into the same controlled fields.

## Selection endpoints

- `GET /api/selections` returns saved and compare lists with current product metadata and requires a consented anonymous session.
- `POST /api/selections` accepts `product_id`, `list_type` (`saved` or `compare`), and `selected`; it requires the same consented session.
- Saved-list totals sum only fresh KRW commerce offers and return `missing_price_ids` separately.

## Commerce v2 offer contract

- `GET /api/v2/products/{product_id}/offers` returns retailer offers, freshness,
  stock, affiliate disclosure, and an expiring relative `redirect_url`.
- Stale price/stock feed offers hide price and stock and return
  `redirect_url: null`; explicitly link-only offers retain an operator-approved,
  allowlisted destination while price and stock stay hidden.
- Clients must open only the returned relative redirect and must not construct a
  retailer URL. The redirect rechecks activity, exact destination-domain
  allowlisting, target fingerprint, token expiry, and either offer freshness or
  the explicit link-only source policy.
- `GET /api/v2/catalog/status` exposes public product/variant/retailer/offer and
  freshness counts without click, conversion, program, or ingestion-error data.

## Product-related YouTube videos

- `GET /api/v2/products/{product_id}/video-reviews?limit=3` performs a lazy,
  server-side search using the canonical product brand and name. It does not
  accept a public search query and never changes recommendation ranking or
  evidence confidence.
- The request must include `X-YouTube-Policy-Accepted: 2026-07-22`. Missing or
  stale acceptance returns `428`; request bursts return `429` with
  `Retry-After`. The miniapp sends this header only after the required service
  terms and privacy-policy checkbox is accepted.
- When `YOUTUBE_API_KEY` is configured, the response contains up to three
  canonical public `youtube.com/watch` links with the API-provided title,
  channel, publication date, duration, and positive paid-product-placement
  disclosure when YouTube reports it.
- `status` is one of `ready`, `search_only`, `no_results`,
  `temporarily_unavailable`, or `quota_limited`. Every response includes a
  product-specific `search_url`, YouTube Terms link, Google Privacy link, and a
  customer disclaimer. The search link is the fallback when the key, quota, or
  upstream API is unavailable.
- Cached results are served for no more than 24 hours and expired entries are
  purged on subsequent cache activity. The daily circuit breaker uses YouTube's
  Pacific Time quota day and an atomic SQLite ledger. Video metadata is not included
  in the recommendation response, stored in user profiles, or used as review
  rating evidence.

The compact reference API under `app/` has a separate `/api/compare` endpoint and legacy request shape. It is retained for portfolio examples but is not the Render production entry point.
