# API Spec

The public API uses the checked-in multi-source catalog by default. The current snapshot combines verified curated records with quality-filtered Open Beauty Facts records. Price and stock are not live catalog fields. Counts change with reviewed catalog refreshes, so the abbreviated examples below intentionally omit volatile numeric totals; query the live endpoints for current values.

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

- `query`: Required natural-language request, maximum 1,200 characters.
- `limit`: Number of products to return, from 1 to 8.
- `use_openai`: Requests an optional grounded explanation. Render keeps the public LLM disabled by default.
- `language`: `en` or `ko`.
- `profile`: Optional structured quiz values. `skin_type` and at least one `desired_categories` item are required when this object is present.
- `profile.avoid_ingredients`: Up to 12 explicit ingredient exclusions. Community-reported catalog rows are not considered when this list is present.
- `profile.max_price_krw`: Uses only products with a checked price; products without one are excluded from a budget-constrained result.

### Response Body

```json
{
  "recommendation_id": 42,
  "decision": "recommend",
  "query": "지성 피부용 산뜻한 선크림을 추천해줘",
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

Uses the same request and response shape as `/api/recommend`, while merging the new request with the anonymous session's stored profile.

## Selection endpoints

- `GET /api/selections` returns saved and compare lists with current product metadata.
- `POST /api/selections` accepts `product_id`, `list_type` (`saved` or `compare`), and `selected`.
- Saved-list totals sum only checked `price_krw` values and return `missing_price_ids` separately.

The compact reference API under `app/` has a separate `/api/compare` endpoint and legacy request shape. It is retained for portfolio examples but is not the Render production entry point.
