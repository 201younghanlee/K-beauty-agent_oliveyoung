# Catalog data, attribution, and reuse

The source-code license in the repository does not replace the licenses attached to third-party catalog data and images.

## Curated catalog

`products_verified.csv` and `review_summaries.csv` contain the maintained, evidence-linked catalog used before the global expansion. Their source and verification URLs remain attached to each record.

## Open Beauty Facts snapshot

`catalog_generated.csv` is a transformed snapshot of the official Open Beauty Facts JSONL export. It covers core facial skincare and explicitly classified mask, eye, lip, exfoliation, body, hair, and makeup forms. `catalog_manifest.json` records the source URL, source timestamp, category counts, processing counts, quality thresholds, output hash, attribution, and applicable licenses.

The manifest also reports the distribution of `source_updated_at` ages. Generated rows are limited to source records edited within the configured three-year window, but that edit timestamp is not a launch date, current-sale check, or formula verification. A newly downloaded daily dump does not imply that every community-contributed product record was recently edited.

- Database content: Open Beauty Facts, [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/)
- Product images: Open Beauty Facts contributors, [Creative Commons Attribution-ShareAlike 3.0](https://creativecommons.org/licenses/by-sa/3.0/)
- Source and attribution page: [Open Beauty Facts data](https://world.openbeautyfacts.org/data)

Every generated row carries its Open Beauty Facts product URL, source product identifier, source modification timestamp, attribution URL, and license label. UI product cards link to the source record.

Open Beauty Facts is community-contributed and does not guarantee completeness or accuracy. Generated ingredient lists are labeled `reported`, not `complete`. They can be recommended only for general matching; the recommendation engine excludes them for sensitive skin, allergies, and explicit avoid-ingredient requests. Users must verify the current package before purchase or use.

The Open Beauty Facts snapshot does not contain live retailer price or stock. Those fields remain empty. A product-source update timestamp must not be presented as a price or inventory check.

Open Beauty Facts `countries` tags describe markets where a product was reported, not a reliable country of manufacture. Generated records therefore keep `country=Unknown` instead of presenting a sale market as product origin or labeling global records as K-beauty.

Run `python scripts/refresh_catalog.py` to rebuild the snapshot. The scheduled workflow validates changes and opens a pull request rather than merging data automatically.
