# Pesticides explorer: count each application once

Date: 2026-09-29. Branch: `feature/pesticides-explorer` (draft PR #275). Approved by Derek.

## Problem

`PesticideUse` has one row per (use record, active ingredient); a record is identified by `(year, use_no)`
(unique per year statewide). The rollup counts `applications = COUNT(*)` and sums `lbs_product` over those
rows, so any sum spanning more than one chemical counts a multi-ingredient record once per ingredient:

- 2023 valley: 1,612,181 "applications" shown vs 1,494,329 records (~8% high); Fresno 377,816 vs 348,990.
- Two-ingredient products: exactly 2×. TELONE C-35 7 → 14 applications; PIC-CLOR 60 product pounds
  84,758 → 169,516.
- Chemical pages are correct: a record has one row per chemical.

## Rule

A sum over rows is correct as-is only when the rows are restricted to **one chemical**. Every other sum
(product, commodity, place, section, county, valley, the map) must count each record once.

## Design

### Data

- `PesticideUseRollup`, `PesticideUseTotal`, `PesticideSectionTotal` gain `records` (IntegerField, default 0)
  and `lbs_product_once` (FloatField, default 0). The section-total covering index includes them.
- `REBUILD_SQL`: mark one **designated row** per record with
  `row_number() OVER (PARTITION BY year, use_no ORDER BY chemical_id NULLS LAST, id) = 1`; then
  `records = SUM(designated::int)` and `lbs_product_once = SUM(CASE WHEN designated THEN lbs_product ELSE 0 END)`.
  Records with no `use_no` (if any) are each their own record.
- `TOTALS_SQL` / `SECTION_TOTALS_SQL` sum the two new columns like the others. The product/commodity totals
  and section totals are then correct; chemical totals rows carry per-chemical `applications` (correct per
  chemical) and `records` (correct when summed across chemicals).

### Readers

- Stats functions that report applications take `apps_field` (default `'records'`); output keys stay
  `applications`. Chemical-scoped callers pass `'applications'`: `ChemicalDetail` (the whole detail mixin
  when `use_field == 'chemical'`), any list/API query filtered to one chemical.
- `lbs_product` is used as-is only when chemical-scoped; otherwise `lbs_product_once`: `ProductDetail`, the
  product list (unless `?chemical=`), every "top products" card outside chemical pages (landing, place,
  section, commodity page, section API), `narrowed_lbs` for products, product sparklines.
- Sections/townships API: `TOTALS` serves `applications` from `records` and `lbs_product` from
  `lbs_product_once` unless the request is filtered to one chemical (`?chemical=`), keeping the property
  names (no JS change). `SectionTotal` path always uses the once columns.
- Records browser: pagination keeps counting rows (it pages ingredient rows); the displayed count
  ("N applications") is distinct records unless filtered to one chemical.
- `by_fume_method` (raw rows): per-chemical scope counts rows; otherwise distinct records, product pounds
  once per record.
- `PesticideRegionSummary` API (grouped by chemical) is unchanged.

### Copy

About: "An application is one use report; a product with two active ingredients counts once." Chemical
pages keep counting the applications that included that chemical.

## Deploy

migrate → `rebuild_pesticide_rollup --all` (full: the rollup gains columns; `--totals-only` is not enough)
→ cache flush.

## Testing

A two-ingredient record (same `use_no`, two chemicals, one product) must show: product page 1 application and
the record's product pounds once; commodity/place/section/landing/county/map counts 1; each chemical's page
1 application and its own pounds; records browser displays 1 application (2 rows paged). Existing
fixture numbers stay (fixture records are single-ingredient) except where tests build rollup rows by hand
(they set `records`/`lbs_product_once` too).
