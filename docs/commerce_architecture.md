# Multi-retailer commerce architecture

The recommendation engine and the commerce layer are deliberately separate.
The engine ranks canonical products from skin fit, ingredient evidence, safety,
and the user's stated constraints. It never reads affiliate commission values.
Only after ranking does the commerce layer attach fresh retailer offers.
For a user-supplied KRW budget, the request-local ranking view replaces catalog
price snapshots with the lowest non-stale KRW offer; if no current KRW offer is
available, the product has unknown price, receives a ranking penalty, and is
shown with an explicit warning instead of claiming to meet that budget. A
known current price outside the requested range remains a hard exclusion.

```text
approved API/feed -> normalize -> identity resolution -> product variant
                                                     -> retailer offer
                                                     -> observation history
recommendation engine -> ranked products -> fresh offer resolver -> client
client -> signed /r token -> click log -> approved affiliate URL -> retailer
```

## Data ownership

- `products` stores the canonical recommendation entity and contains no price,
  stock, retailer, or commission fields.
- `product_variants` reserves separate identities for sizes, shades, markets,
  and formula versions. The current catalog migration creates one default
  variant per product, so ingestion quarantines missing or conflicting package
  sizes rather than mixing them into that default variant.
- `retailers` owns the destination-domain allowlist.
- `offers` stores the latest retailer view of one variant.
- `offer_observations` is append-only price and availability history.
- `affiliate_programs` stores public program metadata. Credentials remain in
  the deployment secret manager.
- `affiliate_clicks` stores an opaque click ID and HMAC session hash, never a
  Toss user key, email, health profile, or raw recommendation query.
- `affiliate_conversions` accepts only allowlisted scalar fields and opaque
  network transaction IDs from a signed callback or approved report import;
  free-form metadata is rejected and rows expire after 180 days.
- `ingestion_runs` makes source failures, record drops, and schema drift visible.

Existing CSV product IDs remain canonical during the migration so saved lists,
feedback, and recommendation history continue to work. The v1 API remains a
compatibility layer; clients should adopt `/api/v2` for retailer comparisons.

## Identity resolution

Automatic matching is conservative:

1. An exact GTIN maps automatically only when it identifies one product and no
   package-size conflict exists.
2. Brand, normalized product name, source variant text, and package size form
   the fallback match. Sources without an explicit category field do not gain
   a category-match signal.
3. High-confidence unique matches may auto-link; ambiguous matches are held for
   review; low-confidence rows become new-product candidates.
4. Different sizes, shades, countries, or formula versions are not merged merely
   because their display names are similar.

The thresholds must be calibrated against a manually labelled match set before
large feeds are enabled.

## Freshness rules

| Source capability | Refresh target | Becomes stale | Public behaviour |
| --- | ---: | ---: | --- |
| Official price API | 1 hour | 2 hours | Hide price/stock and disable the outbound link after expiry |
| Approved daily affiliate feed | 24 hours | 36 hours | Hide price/stock and disable the outbound link after expiry |
| Link-only affiliate program | On link review | Immediately unknown | Show `판매처에서 확인` |
| Open Beauty Facts product master | Daily dump check | Per-record date shown separately | Never provides price or stock |

`fetched_at` records when this service copied data. `source_updated_at` records
when the source says the product changed. They are not interchangeable. A page
or purchase button is never treated as evidence of stock. Missing availability
is always `unknown`.

Search APIs and query-scoped feeds cannot safely treat one missing result as a
deletion. Their short TTL therefore disables stale links automatically; an
explicit successful feed record or source configuration change reactivates or
deactivates the corresponding offer.

## Safe outbound redirects

Clients never receive an arbitrary user-controlled destination. The backend:

1. selects an active offer;
2. signs a short-lived token containing the offer ID, expiry, and target
   fingerprint;
3. verifies the token and the retailer's HTTPS domain allowlist;
4. stores an anonymized click event; and
5. returns a `302` with `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.

Changing an affiliate URL invalidates outstanding tokens. Query parameters
cannot override the destination, preventing open-redirect abuse.

## Approved sources only

`k_beauty_agent/source_adapters` includes:

- a Coupang Partners adapter enabled only by official API credentials; and
- a normalized JSON feed adapter that requires explicit feed and destination
  host allowlists.

Feed requests reject private/non-global literal addresses, validate DNS answers
immediately before connecting, disable redirects, cap response bytes, and use
exact HTTPS host allowlists. DNS can still change between validation and the
network connection, so production should also apply an infrastructure egress
allowlist for the approved partner hosts.

The commerce v2 ingestion path has no generic storefront scraper. The older
experimental `live_keyless` product-source mode still contains source-specific
Olive Young discovery code, but it is disabled in both Render profiles and does
not populate commerce offers. Olive Young Shopping Curator, Hwahae, Musinsa,
StyleKorean, and other link-only programs must remain link-only until the
operator receives a feed/API contract that permits storage and display.

The protected `GET /api/admin/sources` endpoint exposes readiness without
returning credentials. `POST /api/admin/sources/sync` accepts only product
queries, optional configured source IDs, and limits; it never accepts a runtime
feed URL. The read-only `GET /api/admin/source-candidates` exposes unlinked rows
and their suggested matches for an authenticated operator review; corrections
must be made in approved source mappings or canonical identifiers before a new
sync. A daily GitHub Actions
caller is disabled until its Render URL, admin token, and request JSON secrets
are supplied. Missing or ambiguous product matches are retained as review
candidates and cannot become active offers.

Linked rows are also quarantined when prices fall outside conservative currency
bounds, a list price is below the sale price, the currency changes, or a price
moves by more than fivefold from the stored offer. Quarantined values remain in
the review metadata and cannot affect budget ranking or public lowest-price
summaries.

Prices use the source currency's major unit. KRW values are normally integers;
currencies such as USD may retain two decimal places. The public KRW summary
compares only KRW offers and never treats unlike currencies as comparable.

## Production storage

The free Render web-service filesystem is ephemeral. SQLite under `/tmp` is
acceptable only for a demonstration because clicks, sessions, observations,
and conversions disappear after a restart or idle spin-down. Production must
use a durable managed database or a paid service with a persistent disk. Render
free Postgres also expires after 30 days, so it is not a long-term production
database.

The application cleanup retains anonymous sessions and clicks for 30 days,
offer observations for 180 days, and ingestion runs for 90 days. Current source
records are upserted by source SKU rather than appended. Conversion rows are
automatically deleted after 180 days. Production operations must confirm that
period against partner, accounting, and dispute obligations, then monitor disk
usage and test backup restoration before affiliate activation.

- Render persistent-disk documentation: <https://render.com/docs/disks>
- Render free-instance limits: <https://render.com/docs/free>
