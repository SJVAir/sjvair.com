# Pesticides explorer: fumigants that include re-registered products, and application method

Date: 2026-09-29. Branch: `feature/pesticides-explorer` (draft PR #275).

## Why

Two findings from the 2014–2023 PUR data (local, 16.1 M use records):

1. **The Fumigants scope misses the valley's biggest fumigant from 2021 on.** It filters on CDPR's
   product-table flag (`PRODUCT.FUMIGANT_SW`, "the product is a soil fumigant", `X`), which CDPR sets per
   product registration. Telone was re-registered in 2021 under EPA company 95290 (TELONE II `95290-1-AA`,
   C-35 `-2`, EC `-3`, TECHNICAL `-4`, INLINE `-5`) and none of the new registrations carry the flag, while
   26 of the 30 older Telone registrations do. TELONE II alone is 2,945 records / 14.79 M lbs of
   1,3-dichloropropene, 2021–2023, every one applied by fumigation. The flagged share of fumigation-method
   pounds fell from ~100% (2014–2020) to 68% / 60% / 70% (2021 / 2022 / 2023), so the Fumigants trend shows
   a ~34% drop 2020→2021 (19.2 M → 12.7 M lbs) where fumigation itself fell ~6%.
2. **Application method is recorded but never summarised.** `PesticideUse.aerial_ground` (CDPR's
   `AER_GND_IND`) is only a records-browser filter. Readers ask how much is sprayed by air.

What the fields are (CDPR *PUR User Guide and Documentation*, `pur_archives/Information_Data_Structure_Definitions/`):

- `FUMIGANT_SW` is product-level; `CHEMICAL.txt` carries no fumigant or hazard field.
- `AER_GND_IND` is per use record. The July 2002 guide lists only `A` aerial, `G` ground, `O` other
  ("paint, ear tag, dip, injection, chemigation, etc."); the `readme_excel.xlsx` shipped inside recent PUR
  archives (read from `pur2023.zip`) adds **"F: Field fumigation (starting 2008/2009)"** (2023: 2,783
  records, 12.0 M lbs, 14% of pounds). Blank (2023: 132,899 records claiming 395 M "acres") is not
  documented for this field; the readme says non-production-agriculture summary records (record ids 2, C,
  G) carry no location fields, and the blank-method records look like those (sites, implausible acreage),
  but we don't import `record_id`, so that stays an inference and the copy says "mostly".
- The same readme documents `fume_cd` (the field-fumigation technique, joined to `FUMIGATION_METHODS.txt`,
  required since 2008 in the five VOC non-attainment areas including the San Joaquin Valley). Not imported
  today; out of scope here, noted for later.
- SprayDays notices carry the *intended* method, `ApplicationMethod` ∈ {Ground, Aircraft, Fumigation}.

Overlap of CDPR's product flag and method `F`, 2014–2023: both 165.5 M lbs (86%), product only 12.3 M
(6%, 79% of it with a blank method — structural and storage fumigation: sulfuryl fluoride, propylene
oxide, methyl bromide, phosphides — plus field fumigants coded ground), method only 14.9 M (8%, 99.4%
TELONE II). So the product flag is the broader concept (field + structural + storage), method `F` is
field soil fumigation and even that incompletely; the flag's one large hole is the Telone
re-registration.

## Decisions (Derek, 2026-09-28/29)

- A product is a fumigant if CDPR flags it **or** it contains a fumigant active ingredient; an active
  ingredient is a fumigant when the data says so, not by a hand-kept list.
- A fumigant active ingredient: **≥ 100 lbs** reported across every loaded year, **≥ 90%** of which came
  from CDPR-flagged products or method-`F` applications. Classified over **all loaded years**, never per
  year, so nothing flips between years; the set has been unchanged since 2016 as each year was added. No
  exclusions: dichlobenil qualifies (99.5%) because CDPR itself flags some dichlobenil products — we
  propagate CDPR's own call, and a one-entry exclusion can be added later if wanted.
- CDPR's flag is kept as published; ours is stored beside it.
- Application method surfaces as a **breakdown** on pages and one **Narrow-to** option, **"Applied by air"**.
  Fumigation stays covered by the (fixed) Fumigants scope — no second "fumigant" option. No aerial map
  metric: with "Applied by air" in the scope bar the map already shades aerial pounds, and a metric on an
  unnarrowed page would change what the map shows outside the scope bar.
- Scope changes only through the scope bar (standing rule).

## Part 1 — Fumigants

### Data

- `Chemical.categories` gains `Category.FUMIGANT` (the choice exists already, unused: 0 chemicals) for
  every classified fumigant ingredient, the way `CALIFORNIA_RESTRICTED` is set by
  `import_restricted_materials`. Classification adds and removes only `fumigant`; other categories are
  untouched.
- `Product.is_fumigant` (new stored `BooleanField`, indexed): `fumigant OR` any of its
  `product_chemicals` has the `fumigant` category. `Product.fumigant` stays CDPR's flag (verbose name
  "CDPR fumigant flag"). Migration adds the field; a data step isn't needed (the rebuild sets it).
- Classification lives in `camp/apps/pesticides/fumigants.py`:
  `classify_fumigants() -> dict` — one group-by over `PesticideUse` by chemical
  (`SUM(lbs_chemical)`, and the sum filtered to `product.fumigant OR aerial_ground = 'F'`), sets the
  category on qualifying chemicals and clears it elsewhere, then recomputes `Product.is_fumigant` in one
  UPDATE. Constants `FUMIGANT_MIN_LBS = 100`, `FUMIGANT_MIN_SHARE = 0.9`. Returns counts for the command
  output (chemicals, products, products newly fumigant vs CDPR).
- Runs at the end of `rollup.rebuild_all()` / `import_pur` and in `rebuild_pesticide_rollup`; the command
  gains `--fumigants-only`. `--totals-only` does not run it (it reads PUR, not the rollup).

### Everywhere the explorer means "fumigant"

Every reader of `product__fumigant` / `product.fumigant` that means "is a fumigant" switches to
`is_fumigant` (~40 references): `stats.narrow_rows` / `narrow_notices`, the landing stat row's fumigant
product count, product list filter (`forms.py`), product badges (`includes/product-badges.html`),
`notes.py` (the fumigant health note), product list/detail templates, admin list filter, and the API
(`filters.py` `fumigant` filter and `serializers.py` `fumigant` field read `is_fumigant`; the serializer
adds `cdpr_fumigant` for the raw flag). Cached aggregates that depend on the narrowing (LANDING_KEY and
friends) get a version bump so no stale fumigant numbers survive the deploy.

### Pages

- Product badge "Fumigant" for `is_fumigant`. When CDPR doesn't flag it, a tooltip: "Not flagged as a
  fumigant by CDPR; its active ingredient is almost always applied as a fumigant."
- About `#methodology`: how the explorer decides what's a fumigant, that CDPR's flag misses the 2021
  Telone re-registration, and that the earlier Fumigants numbers for 2021 on were ~30–40% low.

### SprayDays

Six local fumigation notices list 1,3-D but link no product: `_product_pks_from_raw` matches
`EPARegNo` exactly against `Product.reg_number` (`show_regno`, e.g. `95290-1-AA`). Inspect a raw
`get_applications` payload for one of them (application ids 2093917, 2095139) to see the format, and
normalise both sides (e.g. compare on company-product, ignoring the distributor suffix) so they link.
Notices narrow on `products__is_fumigant`.

## Part 2 — Application method

### Data

- `PesticideUseRollup.method` — `CharField(max_length=1, blank=True, default='')`, CDPR's
  `aer_gnd_ind` verbatim (`A`/`G`/`F`/`O`/''). Added to the rollup grain: `REBUILD_SQL` selects and groups
  by `aerial_ground`, the unique constraint `pesticides_rollup_key` gains `method`. Measured cost: +0.7%
  rows (2023: 804,174 → 809,716). `PesticideUseTotal` and `PesticideSectionTotal` are unchanged: they sum
  across methods (their GROUP BYs don't name it), so list pages and the unnarrowed map don't move.
- One label set, `stats.METHOD_LABELS`: `G` Ground, `A` Air, `F` Field fumigation, `O` Other, `''` Not reported;
  SprayDays `Ground`/`Aircraft`/`Fumigation` map onto Ground/Air/Field fumigation. Order for display:
  Ground, Air, Field fumigation, Other, Not reported.

### "How it was applied" breakdown

- `stats.by_method(rows, year, lbs_field, all_years)` → rows of `{method, label, lbs, share,
  applications}` in display order, zero rows omitted; rows are the page's rollup rows already scoped
  (county, narrowing).
- Shown on chemical, product, commodity, place and section pages for the scope year: a thin stacked bar
  (the explorer's palette, one tone per method, accessible labels) over a five-row table (lbs, share of
  lbs, applications). A note under it: "Not reported is mostly structural, landscape and right-of-way
  use, which is reported in monthly summaries without a method." Placed in the "Confirmed applications" section near
  the by-year table. Hidden when the page has no use in the scope year. Placeholder-chemical pages hide
  pounds as elsewhere.
- All-years aggregation goes through the page's existing `cached_stat` so `?year=all` stays fast.

### "Applied by air" narrowing

- `NARROW_AERIAL = 'aerial'`, label "Applied by air", added to `NARROW_CHOICES` after Fumigants.
- `narrow_rows`: `rows.filter(method='A')` for rollup rows. Totals rows have no method, so every place a
  narrowed page reads the totals tables must take the rollup path the existing narrowings already take
  (the "has to give way to the rollup" paths — `stats` concern helpers, `lbs_subquery`, the commodity
  concern cache, list pages, landing, county figure, section map endpoints). The implementation plan
  lists each and how it branches today.
- `narrow_notices`: `application_method='Aircraft'`.
- The section map's grid endpoints already accept the narrowing as a param; under `narrow=aerial` they
  read the rollup filtered to `method='A'` (as for the other narrowings), so the map shades aerial pounds.
- Scope bar, banner and About `#concern`-style copy get the new option; the scope-picker already renders
  `NARROW_CHOICES`.

### Records browser

Its method filter keeps working on `PesticideUse.aerial_ground`; its labels switch to `METHOD_LABELS`
(so "Fumigation" and "Not reported" read the same everywhere).

## Deploy

1. `migrate` (the `Product.is_fumigant` field, the rollup `method` column and constraint).
2. `rebuild_pesticide_rollup --all` — a **full** rebuild (the rollup grain changed; `--totals-only` is not
   enough). It also classifies fumigants.
3. Flush the explorer caches (or rely on the version bumps).

## Out of scope

The unified pesticides API (next project) — this only keeps the current API's `fumigant` meaning
consistent. An aerial map metric. Per-year fumigant classification. Ground as a narrowing.

## Testing

- `fumigants.py`: an ingredient over the thresholds gets the category and its unflagged product becomes
  `is_fumigant`; one under 90% or under 100 lbs doesn't; re-running is idempotent and clears a category
  that no longer qualifies; CDPR-flagged products stay fumigant regardless. Fixture additions rather than
  a new fixture file.
- Rollup: method in the grain (two records differing only by method make two rows; totals still sum
  both); `rebuild_totals_year` unchanged results.
- Narrowing: `narrow=aerial` on entity, list, place, landing and section pages and the sections API only
  counts `A` rows; notices narrow to Aircraft; `narrow=fumigant` now includes an unflagged product with a
  fumigant ingredient.
- Breakdown: shares sum to 100%, labels/ordering, scope applied, hidden when empty.
- SprayDays: the reg-number normalisation links a `95290-1`-style number.
- Full suite; browser pass on :8002 (Fumigants trend 2020→2023 on the landing page, a Telone II product
  page badge and tooltip, the breakdown on a chemical page, "Applied by air" across pages and the map).
