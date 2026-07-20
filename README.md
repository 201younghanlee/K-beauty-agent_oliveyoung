# K-Beauty Recommendation Agent

A bilingual skincare recommendation web app built with FastAPI. It combines deterministic ingredient and skin-fit scoring with optional OpenAI-generated explanations, while preserving rule-based fallback behavior. The runtime catalog combines a curated K-beauty set with a quality-filtered global snapshot.

## Live product

- Web app: https://k-beauty-recommendation-agent-gafd.onrender.com/
- API documentation: https://k-beauty-recommendation-agent-gafd.onrender.com/docs
- Health check: https://k-beauty-recommendation-agent-gafd.onrender.com/health
- GitHub Pages client: https://201younghanlee.github.io/K-beauty-agent_oliveyoung/

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

The client uses the SDK `Storage`, `SafeAreaInsets`, and `openURL` APIs. API calls use an anonymous `X-KBeauty-Session` token instead of depending on third-party cookies, which are blocked by iOS WebViews. The production and QR-test Toss origins are included in the backend CORS allowlist.

## Product capabilities

- Korean and English skin quiz
- Ingredient-, concern-, texture-, and budget-aware ranking
- Hundreds of recommendation-eligible records across cleanser, toner, serum, moisturizer, and sunscreen categories; exact current counts are exposed by `/api/catalog/status` and `data/catalog_manifest.json`
- A multi-brand catalog that combines maintained K-beauty records with a quality-filtered Open Beauty Facts facial-skincare snapshot
- Daily catalog refresh workflow with validation gates and a reviewable pull request; refreshed data is never auto-merged
- Follow-up refinement, comparison, saved products, and routine building
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
  |-- curated product and review data
  |-- checked-in, quality-filtered global catalog snapshot
  `-- optional OpenAI explanation layer
          |
          `-- disabled safely when no key or public LLM flag is off

Apps in Toss WebView
  |-- React/TypeScript mobile quiz and recommendations
  |-- SDK safe-area, storage, and external-link integration
  `-- HTTPS request to the same FastAPI recommendation API
```

Recommendation ranking is calculated from repository data and deterministic rules. The LLM is limited to parsing optional follow-up constraints and explaining already-ranked results; it does not select unsupported products or invent product attributes.

## Catalog refresh

The generated catalog is built from the official Open Beauty Facts daily JSONL export. The refresh job streams the compressed dump, normalizes the five supported skincare categories, deduplicates by barcode, and publishes new files only after minimum-size, per-category drop-rate, duplicate-rate, malformed-data, facial-scope, and ingredient-transcription checks pass.

```bash
python scripts/refresh_catalog.py
python -m pytest -q
```

The committed outputs are `data/catalog_generated.csv` and `data/catalog_manifest.json`. The scheduled GitHub Actions workflow runs daily and opens or updates a pull request when the validated snapshot changes. It does not merge automatically, so a data regression can be reviewed before deployment.

Only records with a stable barcode, product name, brand, supported facial category, product image, and plausible reported ingredient list enter the generated recommendation catalog. Community-reported ingredient lists are not treated as complete: these products are excluded when the user selects sensitive skin, an allergy, or an ingredient to avoid. The workflow checks the newest dump every day, but an individual community record may still be years old; the manifest and catalog-status API expose that record-freshness distribution. A future Korean regulatory-catalog expansion can use the MFDS functional-cosmetics API after a `MFDS_SERVICE_KEY` is issued; that integration is not enabled yet.

## Local setup

```bash
git clone https://github.com/201younghanlee/K-beauty-agent_oliveyoung.git
cd K-beauty-agent_oliveyoung
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn k_beauty_agent.web:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000 in a browser.

The app works without an OpenAI key. To enable LLM explanations locally, set `OPENAI_API_KEY` and keep `PUBLIC_LLM_ENABLED=true` in `.env`.

## API example

```bash
curl -X POST http://127.0.0.1:8000/api/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "query": "지성 피부에 맞는 3만원 이하 제품 추천",
    "limit": 3,
    "use_openai": false,
    "language": "ko"
  }'
```

## Tests

```bash
python -m pytest -q
```

The CI workflow runs the same suite on every pull request and push to `main`.

## Deploy to Render

The repository includes `render.yaml`, so it can be deployed as a Render Blueprint.

[Deploy to Render](https://render.com/deploy?repo=https://github.com/201younghanlee/K-beauty-agent_oliveyoung)

The default Blueprint is intentionally cost-safe:

- `PRODUCT_SOURCE=catalog_snapshot` for deterministic startup from the curated and checked-in generated catalogs
- `PUBLIC_LLM_ENABLED=false` so public traffic cannot spend OpenAI credits
- generated `ADMIN_TOKEN` and `SESSION_SECRET`
- HTTPS-only cookies and `/health` deployment checks
- Python 3.12 pinned for reproducible builds

To enable public LLM explanations, add `OPENAI_API_KEY` in Render and explicitly set `PUBLIC_LLM_ENABLED=true`. Review rate limits and spending limits before enabling it for unrestricted traffic.

The free Render configuration stores SQLite session and feedback data under `/tmp`; this data can reset after restarts or deploys. Use a persistent disk or a managed database before treating session history as durable production data.

## Repository layout

```text
k_beauty_agent/     production recommendation engine and FastAPI web app
miniapp/             Apps in Toss SDK 2 WebView client and build config
static/             bilingual product UI and admin page
data/               curated products, reviews, and source snapshots
tests/              recommendation, personalization, source, and config tests
render.yaml         Render infrastructure definition
app/ and agent/     compact reference API retained for portfolio examples
```

## Environment variables

| Variable | Purpose | Production default |
| --- | --- | --- |
| `OPENAI_API_KEY` | Optional explanation and follow-up parsing | unset |
| `OPENAI_MODEL` | OpenAI model name | `gpt-5.4-mini` |
| `PUBLIC_LLM_ENABLED` | Allows public endpoints to call OpenAI | `false` on Render |
| `ADMIN_TOKEN` | Protects admin metrics and maintenance APIs | generated |
| `SESSION_SECRET` | HMAC key for anonymized session logging | generated |
| `PRODUCT_SOURCE` | `catalog_snapshot`, `curated`, or experimental `live_keyless` data layer | `catalog_snapshot` |
| `DATABASE_URL` | SQLite storage URL | `/tmp` on free Render |
| `CORS_ALLOW_ORIGINS` | Comma-separated trusted browser origins | repository Pages and Apps in Toss origins |
| `RECOMMEND_RATE_LIMIT_REQUESTS` | Recommendation requests allowed per rate-limit window | `30` |
| `RECOMMEND_RATE_LIMIT_WINDOW_SECONDS` | Recommendation rate-limit window | `60` |

See `.env.example` for the complete local configuration.

## Data and safety notes

- Recommendations are cosmetic product-selection guidance, not medical diagnosis or treatment.
- Open Beauty Facts is community-contributed data. Its ingredient lists, images, product names, and modification dates can be incomplete or incorrect; users should verify current packaging.
- The expanded source does not provide live prices or stock. Missing values remain missing, and the UI directs users to confirm current sales information with a retailer.
- Users with allergies or skin conditions should verify current packaging and seek qualified medical advice when appropriate. Community-reported rows are not used for sensitive-skin, allergy, or avoid-ingredient recommendations.
- Open Beauty Facts database content is available under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/), and its product images are available under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). Product cards link back to the source record; see `data/README.md` and the manifest for attribution details.
- OpenAI failures fall back to grounded rule-based explanations.
