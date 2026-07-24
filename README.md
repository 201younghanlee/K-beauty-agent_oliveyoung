# K-Beauty Recommendation Agent

A bilingual skincare recommendation and retailer-comparison app built with FastAPI. It combines deterministic ingredient and skin-fit scoring with optional OpenAI-generated explanations, while preserving rule-based fallback behavior. The runtime catalog combines a curated K-beauty set with a quality-filtered global snapshot; an independent commerce layer can attach fresh offers from explicitly approved retailer APIs and partner feeds.

## Currently deployed baseline

- Web app: https://k-beauty-recommendation-agent-gafd.onrender.com/
- API documentation: https://k-beauty-recommendation-agent-gafd.onrender.com/docs
- Health check: https://k-beauty-recommendation-agent-gafd.onrender.com/health
- GitHub Pages archival preview: https://201younghanlee.github.io/K-beauty-agent_oliveyoung/ (deprecated; it is not a production API client)

These URLs point to the currently deployed baseline, not automatically to the
latest feature branch. The commerce v2 API and UI become public only after this
branch is reviewed and merged into the branch connected to Render. The supported
web client is served from the same Render origin. A separate static host needs
an HTTPS reverse proxy or an explicit runtime API-base implementation in
addition to adding its exact origin to `CORS_ALLOW_ORIGINS`; the shared
`201younghanlee.github.io` origin is intentionally excluded from production
defaults because other projects under the same origin share browser storage.

## Apps in Toss miniapp

The `miniapp/` directory contains a separate React, TypeScript, and Vite client packaged with the stable Apps in Toss WebView SDK 2. It keeps the existing public website intact while reusing the same Render recommendation API.

```bash
cd miniapp
pnpm install --frozen-lockfile
pnpm run dev
pnpm run build
```

The miniapp identifier is `k-beauty-agent`. After uploading a build, QR testing uses `intoss-private://k-beauty-agent?_deploymentId=<deploymentId>`; the production deep link is `intoss://k-beauty-agent`. The build command produces the `.ait` package used by the Apps in Toss console. Before the first console upload:

1. Create a non-game WebView app with the immutable app name `k-beauty-agent` and display name `K뷰티에이전트`.
2. Upload `miniapp/public/app-icon.png` as the 600 x 600 opaque app logo and keep its console image URL in sync with `miniapp/granite.config.ts`.
3. Upload the generated `.ait` package and complete at least one QR test before requesting review.

The client uses the SDK `Storage`, `SafeAreaInsets`, and `openURL` APIs. API calls use an anonymous `X-KBeauty-Session` token instead of depending on third-party cookies, which are blocked by iOS WebViews. The production and QR-test Toss origins are included in the backend CORS allowlist. Retailer choices are loaded from `/api/v2/products/{id}/offers`; the client opens only the backend's short-lived signed `/r/` URL and never constructs a storefront URL itself.

## Product capabilities

- Korean and English beauty quiz with category-specific concern choices
- Ingredient-, concern-, texture-, and budget-aware ranking
- Hundreds of recommendation-eligible records across core skincare, masks, eye and lip care, exfoliation, body care, hair care, and makeup; exact current counts are exposed by `/api/catalog/status` and `data/catalog_manifest.json`
- A multi-brand catalog that combines maintained K-beauty records with a quality-filtered global Open Beauty Facts snapshot; global records are not presented as Korean origin
- Daily catalog refresh workflow with validation gates and a reviewable pull request; refreshed data is never auto-merged
- Follow-up refinement, comparison, saved products, and routine building
- Multi-retailer discovery across exact product pages plus Naver Shopping, Coupang, Musinsa Beauty, and YesStyle product-name searches
- Price freshness, stock state, exact-match labeling, and affiliate disclosure that distinguish verified offers from search fallbacks
- Conservative product/variant identity matching for approved retailer APIs and feeds
- Signed, expiring, exact-domain-allowlisted outbound links with anonymized click logging
- Anonymous session, feedback, and operational metrics storage
- Optional OpenAI explanations with rule-only fallback
- Admin metrics endpoints protected by `X-Admin-Token`
- Per-IP and anonymous-session recommendation rate limiting
- Render Blueprint, health check, secure cookie options, and GitHub Actions tests

## Architecture

```text
Browser
  |
  v
FastAPI web app
  |-- static bilingual UI
  |-- session / feedback API
  |-- rule-first recommendation engine
  |-- canonical product / variant / retailer / offer store
  |-- approved retailer API and partner-feed adapters
  |-- signed outbound redirect and affiliate click/conversion ledger
  |-- curated product and review data
  |-- checked-in, quality-filtered global catalog snapshot
  `-- optional OpenAI explanation layer
          |
          `-- disabled safely when no key or public LLM flag is off

Apps in Toss WebView
  |-- React/TypeScript mobile quiz and recommendations
  |-- fresh retailer comparison bottom sheet
  |-- SDK safe-area, storage, and external-link integration
  `-- HTTPS request to the same FastAPI recommendation API
```

Recommendation ranking and follow-up parsing are calculated from repository data and deterministic rules. The optional LLM only explains already-ranked results from a controlled profile; it does not receive the user's raw query, select unsupported products, or invent product attributes.

Affiliate commission is stored only in the commerce layer and is never read by the recommendation scorer. Prices are shown only while their configured freshness window is valid; stale stock becomes `unknown`. See [the commerce architecture](docs/commerce_architecture.md) and [affiliate launch checklist](docs/affiliate_operations.md).

## Catalog refresh

The generated catalog is built from the official Open Beauty Facts daily JSONL export. The refresh job streams the compressed dump, normalizes five core skincare categories plus explicit mask, eye, lip, exfoliation, body, hair, and makeup product forms, deduplicates by barcode, and publishes new files only after minimum-size, per-category drop-rate, duplicate-rate, malformed-data, product-scope, and ingredient-transcription checks pass.

```bash
python scripts/refresh_catalog.py
python -m pytest -q
```

The committed outputs are `data/catalog_generated.csv` and `data/catalog_manifest.json`. The scheduled GitHub Actions workflow runs daily and opens or updates a pull request when the validated snapshot changes. It does not merge automatically, so a data regression can be reviewed before deployment.

Only records with a stable barcode, valid product name, brand, an explicitly supported beauty product form, product image, plausible reported ingredient list, and a source-record update within the last three years enter the generated recommendation catalog. The five core skincare categories remain the required safety floor for every refresh, while expanded categories are protected by their own previous-count drop checks after first publication. Community-reported ingredient lists are not treated as complete: these products are excluded for frequent sensitivity and avoid-ingredient requests, and records containing known prohibited legacy ingredients are removed. Allergy, pregnancy, and nursing text is rejected before storage until a separate sensitive-data consent flow exists. A recent Open Beauty Facts edit is not proof that a product is currently sold or that its formula is current; the manifest and catalog-status API expose the source-record freshness distribution, and users are told to verify current packaging. A future Korean regulatory-catalog expansion can use an approved MFDS data source after its access and product fields are verified; that integration is not enabled yet.

## Local setup

```bash
git clone https://github.com/201younghanlee/K-beauty-agent_oliveyoung.git
cd K-beauty-agent_oliveyoung
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -c requirements.lock
cp .env.example .env
uvicorn k_beauty_agent.web:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000 in a browser.

The app works without an OpenAI key. To enable LLM explanations locally, set `OPENAI_API_KEY` and keep `PUBLIC_LLM_ENABLED=true` in `.env`.

## API example

```bash
curl -X POST http://127.0.0.1:8000/api/v2/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "query": "지성 피부에 맞는 3만원 이하 제품 추천",
    "limit": 3,
    "use_openai": false,
    "language": "ko",
    "privacy_consent": true
  }'
```

Fetch the current retailer choices for a recommended product separately:

```bash
curl http://127.0.0.1:8000/api/v2/products/PRODUCT_ID/offers
```

V2 product responses intentionally omit raw storefront URLs. Fresh commerce
offers and explicitly link-only retailer destinations expose a relative,
signed `redirect_url`. A stale price/stock feed returns `null`, while an
allowlisted link-only destination can remain available with its price and stock
hidden. Use the supplied value as-is instead of opening catalog source URLs.

When no approved exact product page is available, the service adds clearly
labeled product-name search destinations for Naver Shopping, Coupang, Musinsa
Beauty, and YesStyle. These links do not claim that the exact product is sold
there and never carry a price or stock value. An approved exact page, partner
feed, or affiliate offer for the same retailer automatically replaces its
generic search fallback in the public response.

## Approved retailer offer sync

Retailer price and availability updates run only through sources configured by the operator. Inspect readiness and trigger a protected sync with the same Render `ADMIN_TOKEN`:

```bash
curl https://YOUR-RENDER-SERVICE/api/admin/sources \
  -H "X-Admin-Token: $ADMIN_TOKEN"

curl "https://YOUR-RENDER-SERVICE/api/admin/source-candidates?limit=50" \
  -H "X-Admin-Token: $ADMIN_TOKEN"

curl -X POST https://YOUR-RENDER-SERVICE/api/admin/sources/sync \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -d '{"queries":["serum","cleanser","sunscreen"],"limit":20}'
```

The `retailer-offer-sync.yml` workflow calls the protected retention cleanup
endpoint every day after the first two GitHub Actions secrets are configured.
It also syncs approved offers when the optional request JSON is present:

- `RETAILER_SYNC_BASE_URL`: the HTTPS Render service origin
- `RETAILER_SYNC_ADMIN_TOKEN`: the same protected Render admin token
- `RETAILER_SYNC_REQUEST_JSON`: optional until approved sources are ready; for example `{"queries":["serum","cleanser","toner","moisturizer","sunscreen"],"limit":20}`

Configure `RETAILER_SYNC_BASE_URL` and `RETAILER_SYNC_ADMIN_TOKEN` before a
durable production launch so expiry does not depend only on user or health-check
traffic. The workflow skips safely while those two secrets are absent.
`PARTNER_FEEDS_JSON` and retailer credentials remain Render secrets. Add a source ID to `ACTIVE_AFFILIATE_SOURCE_IDS` only after the affiliate contract and disclosure review are complete. Unmatched or price-anomalous feed rows are available through the protected, read-only `source-candidates` endpoint; they do not automatically enter the recommendation catalog or become purchase offers. The operator must correct the approved source mapping or canonical identifiers and sync again—this build intentionally has no one-click candidate approval mutation.

## Tests

```bash
python -m pytest -q
```

The CI workflow runs the same suite on every pull request and push to `main`.

## Deploy to Render

The repository includes `render.yaml`, so it can be deployed as a Render Blueprint.

[Deploy to Render](https://render.com/deploy?repo=https://github.com/201younghanlee/K-beauty-agent_oliveyoung)

The default Blueprint is intentionally cost-safe. During the first Blueprint
creation, leave the partner-feed, affiliate-source, and Coupang credential
secret prompts empty until approvals exist; `sync: false` prevents later
Blueprint syncs from overwriting values managed in the Render dashboard.

- `YOUTUBE_API_KEY`, `PARTNER_FEEDS_JSON`, `ACTIVE_AFFILIATE_SOURCE_IDS`, and Coupang credentials are operator-managed secrets

- `PRODUCT_SOURCE=catalog_snapshot` for deterministic startup from the curated and checked-in generated catalogs
- `PUBLIC_LLM_ENABLED=false` so public traffic cannot spend OpenAI credits
- generated `ADMIN_TOKEN`, `SESSION_SECRET`, and `AFFILIATE_REDIRECT_SECRET`
- HTTPS-only cookies and `/health` deployment checks
- Python 3.12 pinned for reproducible builds

To enable public LLM explanations, add `OPENAI_API_KEY` in Render and explicitly set `PUBLIC_LLM_ENABLED=true`. Review rate limits and spending limits before enabling it for unrestricted traffic.

The free Render configuration stores SQLite session, offer history, clicks, and conversions under `/tmp`; this data can reset after restarts or deploys. It is suitable for a public demo, not durable commerce operations. `render.production.yaml` is an alternative paid upgrade profile with a 1 GB persistent disk. Because it uses the same service name, applying it can modify the existing service rather than create a separate one; back up first and review Render pricing. This build is SQLite-only and fails fast if a PostgreSQL URL is supplied.

## Repository layout

```text
k_beauty_agent/     production recommendation engine and FastAPI web app
  source_adapters/  approved API/feed adapters for the commerce v2 path
miniapp/             Apps in Toss SDK 2 WebView client and build config
static/             bilingual product UI and admin page
data/               curated products, reviews, and source snapshots
docs/               commerce, affiliate operations, and privacy launch notes
tests/              recommendation, personalization, source, and config tests
render.yaml         Render infrastructure definition
render.production.yaml  optional paid persistent-disk profile
app/ and agent/     compact reference API retained for portfolio examples
```

## Environment variables

| Variable | Purpose | Production default |
| --- | --- | --- |
| `OPENAI_API_KEY` | Optional explanation of already-ranked results | unset |
| `OPENAI_MODEL` | OpenAI model name | `gpt-5.4-mini` |
| `PUBLIC_LLM_ENABLED` | Allows public endpoints to call OpenAI | `false` on Render |
| `YOUTUBE_API_KEY` | Server-only YouTube Data API key for lazy product-review video search | unset; product-specific YouTube search link fallback remains available |
| `YOUTUBE_SEARCH_DAILY_LIMIT` | Maximum unique uncached YouTube searches per Pacific Time quota day, reserved atomically in SQLite | `90` |
| `YOUTUBE_REVIEW_CACHE_TTL_SECONDS` | YouTube result cache lifetime, capped at 24 hours | `86400` |
| `ADMIN_TOKEN` | Protects admin metrics and maintenance APIs | generated |
| `SESSION_SECRET` | HMAC key for anonymized session logging | generated |
| `AFFILIATE_REDIRECT_SECRET` | Separate HMAC key for expiring retailer redirects | generated |
| `AFFILIATE_WEBHOOK_SECRET` | HMAC key for the optional normalized conversion callback | generated |
| `PRODUCT_SOURCE` | `catalog_snapshot`, `curated`, or legacy experimental `live_keyless` data layer | `catalog_snapshot` |
| `DATABASE_URL` | SQLite storage URL | `/tmp` on free Render |
| `COUPANG_PARTNERS_LINKS_JSON` | Portal-created Coupang Partners links mapped to exact catalog product IDs for the pre-API launch phase | `[]` |
| `COUPANG_PARTNERS_ACCESS_KEY` / `COUPANG_PARTNERS_SECRET_KEY` | Enables the official Coupang Partners API adapter after final approval | unset |
| `PARTNER_FEEDS_JSON` | Approved normalized feeds and exact feed/destination host allowlists | `[]` |
| `ACTIVE_AFFILIATE_SOURCE_IDS` | Comma-separated source IDs explicitly approved for activation; use either `coupang_partner_links` for portal links or `coupang_partners` for the API, never both | empty |
| `CORS_ALLOW_ORIGINS` | Comma-separated trusted browser origins | Apps in Toss production and QR-test origins only |
| `RECOMMEND_RATE_LIMIT_REQUESTS` | Recommendation requests allowed per rate-limit window | `30` |
| `RECOMMEND_RATE_LIMIT_WINDOW_SECONDS` | Recommendation rate-limit window | `60` |

See `.env.example` for the complete local configuration.

## Data and safety notes

- Recommendations are cosmetic product-selection guidance, not medical diagnosis or treatment.
- Open Beauty Facts is community-contributed data. Its ingredient lists, images, product names, and modification dates can be incomplete or incorrect; users should verify current packaging.
- The Open Beauty Facts product master does not provide live prices or stock. Approved retailer adapters may provide them, but missing values remain missing and stale values are hidden; users are always directed to confirm sales information with the retailer.
- Affiliate programs remain inactive until partner approval, visible disclosure, and Apps in Toss review are complete. Do not paste API credentials into source code or chat logs.
- Users with allergies or skin conditions should verify current packaging and seek qualified medical advice. The public app does not accept allergy, pregnancy, or nursing information until a separate sensitive-data consent flow is implemented.
- Open Beauty Facts database content is available under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/), and its product images are available under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). Product cards link back to the source record; see `data/README.md` and the manifest for attribution details.
- OpenAI failures fall back to grounded rule-based explanations.
- Product-related videos are fetched only after the user accepts the service terms/privacy notice and taps the YouTube section. They are public YouTube search results, do not affect product ranking or evidence confidence, and fall back to a product-specific YouTube results page when the server key or quota is unavailable. Configure the key only in Render after enabling YouTube Data API v3 and restricting the credential to that API.
