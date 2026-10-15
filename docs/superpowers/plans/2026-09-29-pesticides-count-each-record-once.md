# Count each application once — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Application counts and product pounds count each use record once everywhere a sum spans more than one chemical; chemical pages keep their per-chemical figures.

**Architecture:** The rollup designates one row per use record (window function) and carries `records` and `lbs_product_once`; the totals tables sum them. Stats readers default to the once-per-record measures via a new `apps_field` (and `lbs_product_once` for product pounds); chemical-scoped callers ask for the per-row measures. Output keys and API property names stay the same.

**Tech Stack:** Django 5 / PostGIS, raw-SQL rollup (`camp/apps/pesticides/rollup.py`), templates unchanged except About copy.

**Spec:** `docs/superpowers/specs/2026-09-29-pesticides-count-each-record-once-design.md`

## Global Constraints

- Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer`. Do not commit/stage/stash/push. Don't migrate or rebuild the shared dev DB (the controller does).
- Rule: per-row `applications` / `lbs_product` only when the rows are restricted to ONE chemical; otherwise `records` / `lbs_product_once`.
- Designated row: `row_number() OVER (PARTITION BY year, use_no ORDER BY chemical_id NULLS LAST, id) = 1`.
- Output dict keys stay `applications` / `lbs`; API GeoJSON property names stay `applications` / `lbs_product` (no JS change).
- `PesticideRegionSummary` API unchanged. Records-browser pagination keeps counting rows.
- About copy (verbatim sentence): "An application is one use report; a product with two active ingredients counts once."
- Tests: Django TestCase, plain assert; build multi-ingredient data inside tests; don't edit `fixtures/pesticides-explorer.yaml` (its records are single-ingredient). Harness: `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_records -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer:/app test pytest <paths> -q -p no:cacheprovider --create-db` (`-n 4 --dist loadscope` for packages; full suite `camp` at the end). makemigrations: same flags with `python manage.py makemigrations pesticides` (ignore the pre-existing `ceidars` drift).
- No AI attribution; match surrounding style; no aligned `=`; `_()` first positional arg for verbose names.

## Review Focus

1. A two-ingredient record: every surface except the chemical pages shows 1 application and its product pounds once — product page, product list, commodity page, place, section, landing, county table/map, sections/townships API, records-browser displayed count.
2. Each of that record's chemical pages still shows 1 application and its own chemical pounds (not 0 — the non-designated chemical must not lose its count).
3. A record whose designated row has a NULL chemical is still counted in chemical-totals sums (the designation orders NULL chemicals last).
4. `?chemical=` filtered lists and map requests keep the per-row measures (correct and matching the chemical page).
5. Hand-built rollup rows in tests that set only `applications` now read as 0 applications on non-chemical surfaces — tests must set `records` too, not paper over it.

---

## Reader inventory (from a read-only sweep; verify line numbers)

**Rollup/SQL:** `rollup.py` REBUILD_SQL (:19-46), TOTALS_SQL (:49-64, per chemical/product/commodity dimension), SECTION_TOTALS_SQL (:76-90); models `PesticideUseRollup` (~:549), `PesticideSectionTotal` (~:611, covering index `pesticides_section_total_cov` INCLUDEs measures ~:628), `PesticideUseTotal` (~:655).

**Always chemical-scoped (keep per-row measures):** `ChemicalDetail` (everything from `ExplorerDetailMixin` when `use_field == 'chemical'`: year_totals, by_year, by_county, by_method, by_month, by_year_month, movers, top_related, by_fume_method); `ProductList` with `?chemical=` (rollup product+chemical); sections/townships API with `?chemical=`; records browser with `?chemical=`; `PesticideRegionSummary`.

**Never chemical-scoped (switch to `records` / `lbs_product_once`):**
- `stats.py`: `_totals` (:380) and every caller path not chemical-scoped — `by_year`, `by_county`, `by_month`, `by_year_month`, `by_method` (:316), `year_totals` (:714), `block_totals` (:662, schools), `by_township` (:681), `county_totals` (:1010), `valley_by_year` (:396), `_build_landing_stats` (:1207-1290: `Sum('applications')`, top products `lbs_product`, `with_series(..., 'lbs_product')`), `narrowed_lbs` product (`NARROWED_LBS_FIELDS['product']` :1074), `yearly_series`/`monthly_series`/`with_series` for product boards, `top_related(..., 'product', 'lbs_product')` everywhere outside chemical pages, `top_movers` with lbs_product (ProductDetail).
- `views.py`: `ProductDetail` (`lbs_field = 'lbs_product'` :1062 → `lbs_product_once`; its apps → records), `CommodityDetail` (apps → records; `top_related('product','lbs_product')` :1140), `lbs_subquery` (:132; ProductList unrelated uses Total product rows `Sum('lbs_product')` → once; with `?commodity=` or a narrowing → once; with `?chemical=` → per-row), `ProductList.annotate_queryset` (:716), `section_summary` (:1711-1750, top products lbs_product), `SectionDetail`, `Home` (landing applications), `MapPage`/`RecordsBrowser` county tables (via county_totals), `RecordsBrowser.get_totals` (:1590; displayed count → distinct `(year, use_no)` unless `?chemical=`; keep a row count for the paginator :1547), `get_summary_sentence` truthiness (:916) follows year_totals.
- `places.py`: `_place_stats` (:485-560: year_totals, by_month, by_method, top_products lbs_product), `build_by_year` (:598), `Area.total_rows` (Total chemical rows — sum `records`), `schools_nearby`/`_school_entry` (:313-364, block_totals applications).
- `maps.py`: `metric_value` reads `row['applications']` — correct once by_county supplies records.
- API `sections.py`: `TOTALS`/`ZERO` (:29-35) used on SectionTotal and rollup; `section_totals` (:102), `SectionListBase.get` (:285-301 rollup path via `apply_filters`), `SectionDetailBase.get` (:361 years, :382 months, :365-390 top incl. products lbs_product), `TownshipListBase.get` (:495-555, `by_township`; `if not t['applications']` :536).
- `by_fume_method` (:350-377, raw rows): chemical-scoped → `Count('pk')`; otherwise distinct records and product pounds once per record.

**Tests that will move** (numbers only where multi-ingredient data or hand-built rows are involved): `test_rollup.py` (rebuild sums — add new-column asserts), `test_stats.py`, `test_views.py` (product list/detail lbs_product), `test_places.py` (`make_section` hand-built rollup rows; block totals), `test_narrowed_lists.py` (`expected()` sums lbs_product for products → lbs_product_once), `test_fume_method.py` (applications count test; product pounds), `test_aerial.py` (placeholder breakdown sets `row.applications`), API `tests.py` (`SectionTotalsTableTests` path equality incl. new columns; section/township totals).

---

### Task 1: Rollup carries `records` and `lbs_product_once`

**Files:** `camp/apps/pesticides/models.py`, new migration, `camp/apps/pesticides/rollup.py`, `camp/apps/pesticides/tests/test_rollup.py`.

**Produces:** `records` (IntegerField default 0) and `lbs_product_once` (FloatField default 0) on `PesticideUseRollup`, `PesticideUseTotal`, `PesticideSectionTotal`; section-total covering index includes them.

- [ ] **Step 1: Failing tests** in `test_rollup.py`: build a two-ingredient record (two `PesticideUse` rows, same `year`, same `use_no`, two chemicals, one product, `lbs_product` 100 on each row) plus a single-ingredient record; `rollup.rebuild_year(year)`; assert: rollup `SUM(records)` == 2 and `SUM(applications)` == 3; `SUM(lbs_product_once)` for the product == 100 while `SUM(lbs_product)` == 200; per chemical, `applications` == 1 each; product totals row `records == 1`, `lbs_product_once == 100`; section totals `records` == records in the section; the designated row is the lower `chemical_id`; a record with a NULL-chemical row and a chemical row designates the chemical row.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement.** Model fields (verbose names `_('Records')`, `_('Pounds of Product, once per record')`; a comment on the rollup fields explaining per-row vs once). Migration (pesticides only; the covering index change is a remove+add of the index — acceptable; note it in the report). REBUILD_SQL as a CTE or subquery:
  ```sql
  WITH uses AS (
      SELECT *, row_number() OVER (
          PARTITION BY year, use_no ORDER BY chemical_id NULLS LAST, id
      ) = 1 AS designated
      FROM pesticides_pesticideuse
      WHERE year = %s
  )
  INSERT INTO pesticides_pesticideuserollup (..., records, lbs_product_once)
  SELECT ..., SUM(CASE WHEN designated THEN 1 ELSE 0 END),
         COALESCE(SUM(CASE WHEN designated THEN lbs_product ELSE 0 END), 0)
  FROM uses GROUP BY ...
  ```
  (Postgres needs `INSERT ... WITH` ordering: `WITH ... INSERT INTO ... SELECT` is valid; keep the existing alias comment about GROUP BY.) If `use_no` can be NULL, partition by `COALESCE(use_no, -id)` so each such row is its own record — check the field. TOTALS_SQL and SECTION_TOTALS_SQL add `COALESCE(SUM(records), 0), COALESCE(SUM(lbs_product_once), 0)`.
- [ ] **Step 4: Run** `test_rollup.py` then `camp/apps/pesticides/tests -n 4 --dist loadscope` (other tests shouldn't move yet — readers unchanged).
- [ ] **Step 5: Leave uncommitted.**

### Task 2: Readers use the once-per-record measures

**Files:** `stats.py`, `views.py`, `places.py`, `camp/api/v2/pesticides/sections.py`, `about.html`, tests listed in the inventory.

**Consumes:** Task 1's columns.

- [ ] **Step 1: Failing tests** (new `camp/apps/pesticides/tests/test_count_once.py`, RollupTestMixin + fixture, then add a two-ingredient record: product P with chemicals C1, C2 in one section/county/commodity, `lbs_product` 100 on each row, `lbs_chemical` 30/20; rebuild the year): product page totals `applications == 1`, `lbs == 100`; product list P lbs 100 (and with `?chemical=C1` still the per-row 100); commodity page, place page (county), section page, landing: applications include the record once; county_totals row applications once; sections API `applications` for the section once (and with `?chemical=C1` 1); townships API likewise; records browser displayed count 1 with `?product=P` (paginator still has 2 rows); C1's and C2's chemical pages each `applications == 1` with lbs 30 / 20; product fume breakdown (make the record `aerial_ground='F'` with a fume method) counts 1 and pounds 100.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement.**
  - `stats._totals(lbs_field, apps_field='records')` → `applications=Sum(apps_field)`; thread `apps_field='records'` through `by_year`, `by_county`, `by_month`, `by_year_month`, `by_section`, `by_method`, `year_totals`, `block_totals`, `by_township`, and the landing aggregates. A helper `stats.product_lbs(chemical_scoped)` → `'lbs_product' if chemical_scoped else 'lbs_product_once'` and `stats.apps(chemical_scoped)` → `'applications' if chemical_scoped else 'records'` keeps call sites readable.
  - `ExplorerDetailMixin`: `chemical_scoped = self.use_field == 'chemical'`; pass `apps_field` to every stats call; `ProductDetail.lbs_field = 'lbs_product_once'`; `top_related` for products on non-chemical pages uses `'lbs_product_once'`; `CommodityDetail` products card `'lbs_product_once'`.
  - Lists: `ProductList` pounds → `lbs_product_once` unless `?chemical=` (then `lbs_product`); `lbs_subquery` / `narrowed_lbs` pick accordingly (`NARROWED_LBS_FIELDS['product'] = 'lbs_product_once'`).
  - Landing, places, section_summary, SectionDetail, schools: once measures; top products `lbs_product_once`; product sparklines `lbs_product_once`.
  - API `sections.py`: build TOTALS per request: `applications=Sum('applications' if chemical-filtered else 'records')`, `lbs_product=Sum('lbs_product' if chemical-filtered else 'lbs_product_once')` (SectionTotal path is never chemical-filtered); same in section detail, townships (`by_township`), top products.
  - Records browser: `get_totals()` adds `records` = distinct `(year, use_no)` over the filtered queryset (or equal to rows when `?chemical=`); the summary/count shown uses `records`; the paginator keeps `applications` (rows). Cache key unchanged in shape (totals dict grows).
  - `by_fume_method(uses, lbs_field, chemical_scoped)`: chemical-scoped → rows; else distinct records and product pounds once per record (aggregate per `(year, use_no, fume_method)` with `Max(lbs_product)` then sum).
  - About: add the verbatim sentence where "applications" are defined (methodology).
  - Update existing tests per the inventory; hand-built rollup rows set `records` alongside `applications` (and `lbs_product_once` alongside `lbs_product`).
- [ ] **Step 4: Run** `test_count_once.py`, then `camp/apps/pesticides/tests camp/api/v2/pesticides -n 4 --dist loadscope`, then the full suite.
- [ ] **Step 5: Leave uncommitted.**

## Deploy (for the PR)
migrate → `rebuild_pesticide_rollup --all` (full) → cache flush.
