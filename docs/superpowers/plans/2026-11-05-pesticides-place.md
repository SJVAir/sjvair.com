# Pesticides for a Place Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /api/2.0/pesticides/place/` returns monthly and yearly pesticide use (pounds, acres, applications) for a region or monitor, plus the sdk-js wrapper `getPesticidesForPlace`.

**Architecture:** A new endpoint resolves the place with `camp/apps/regions/resolve.py`, maps it to rollup rows (county → `county=`; any other region → the MTRS sections touching it; monitor → its ZIP's sections), and sums `PesticideUseRollup` by year and month in one query. The counting rule depends on how the filters narrow chemicals (below). The answer is cached under the pesticides data version, so a rollup rebuild retires it.

**Tech Stack:** Django 5 / PostGIS, django-resticus, Django forms; Deno 2 + Zod (sdk-js).

**Spec:** `docs/superpowers/specs/2026-11-05-get-data-place-layers-design.md` (Item 1, "How the dashboard names a place", SDK, Deferred).

## Counting rule (settled, verified 2026-11-05 on the local DB)

Rollup rows are keyed by (year, month, county, mtrs, chemical, product, commodity, method). A use record has one product, and every record of a product carries the same ingredient rows. Checked: 0 of 2023's 50,922 multi-ingredient (year, month, county, mtrs, product, commodity, method) groups disagree on `applications` across their chemicals (0 across all years); `acres_treated` differs only by float noise (max 2.3e-13). No record has two products. 36 raw rows (27 rollup rows) have no product.

| Filters | pounds | acres | applications |
|---|---|---|---|
| `chemical` given (with or without others) | `SUM(lbs_chemical)` | `SUM(acres_treated)` | `SUM(applications)` |
| `category` and/or `iarc_group`, no `chemical` | `SUM(lbs_chemical)` over matching rows | per group key `MAX(acres_treated)`, then summed | per group key `MAX(applications)`, then summed |
| none of those three (`commodity`, `aerial_ground`, years only) | `SUM(lbs_chemical)` | `SUM(acres_once)` | `SUM(records)` |

Group key for the middle row: `(year, month, county_id, mtrs_id, product_id, commodity_id, method)`. Rows with no product use the same MAX (they may merge records of different products; at most 27 rows, accepted and noted in a code comment). `pounds` is always pounds of active ingredient.

## Global Constraints

- Addressing exactly as `calheatscore/place/`: `resolve_place(request.GET)`; `PlaceNotFound` → 404, `PlaceError` → 400, body `{"error": "..."}`, errors `Cache-Control: no-cache`.
- Response `{"data": {"place": place_json(place), "months": [...], "years": [...]}}`.
- `months` rows `{year, month, pounds, acres, applications}`, month 1–12 only, only months with a rollup row, ordered year, month.
- `years` rows `{year, pounds, acres, applications, undated: {pounds, acres, applications}}`; a year's totals **include** its undated (month 0) records; `undated` is zeros when none; a year whose only use is undated still has a row; ordered by year.
- Filters: `chemical` (chem code, int), `commodity` (site code), `category` (a `Chemical.Category` value), `iarc_group` (a `Chemical.IARCGroup` value), `aerial_ground` (a `PesticideUse.AerialGround` value), `year__gte`, `year__lte` (int). Blank values are ignored. An invalid value is a 400 `{"errors": form.errors.get_json_data()}` with `no-cache`.
- Region rule: county → `county=region`; any other region → rollup rows whose `mtrs` boundary intersects the region's boundary; monitor → `zips_for(monitor)` (0 or 1 ZIP) then the region rule on that ZIP; no ZIP or no boundary → empty lists, 200.
- Read `PesticideUseRollup` only, never `PesticideUse`.
- `region/<sqid>/summary/` unchanged.
- 200: `Cache-Control: public, max-age=3600`.
- No AI attribution in commits or PRs. Never merge into `develop` or `release/5.0.0` without the user's yes. No beta, tag or publish.

## Review Focus

1. A record with two ingredients that both match `category=carcinogen` → counted once in applications and acres, pounds of both. (Task 2 test.)
2. A retired region code → still answers 200. (Task 3 test.)
3. A monitor outside every ZIP, and a region with no boundary → 200 with empty `months` and `years`. (Task 3 tests.)
4. `year__gte=abc`, `category=nope`, `aerial_ground=X` → 400, not a silent unfiltered answer. (Task 3 test.)
5. A rollup rebuild after a cached answer → the next request reflects the new data. (Task 3 test.)

---

## Setup

Branch `feature/pesticides-place` from `feature/get-data-layers` (it holds the spec and this plan), in `/home/alex/workspace/sjvair/sjvair.com/.worktrees/pesticides-place`. Copy `.env`, `.env.test` and `docker-compose.override.yml` from the main checkout.

Test command (the `TEST` alias in every task below), run from the worktree; give it its own database by using `.env.test`'s `DATABASE_URL` with the database name `sjvair_places` (shared by the place-layers track, items 1–3, which run one after another) (never paste the password into docs or commits):

```bash
podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 \
  -e TWILIO_AUTH_TOKEN=test-token -e DATABASE_URL="$LAYERS1_DB_URL" \
  -v "$PWD":/app:z \
  -v ~/workspace/django-resticus/.worktrees/session-csrf/resticus:/usr/local/lib/python3.14/site-packages/resticus:ro,z \
  -w /app sjvair-com-test:latest pytest <args>
```

Ignore the trailing "not a git repository" line. Take a baseline first: `TEST -n 4 --dist loadscope` on the untouched branch; record the pass/fail counts.

---

### Task 1: Section set for a region

**Files:**
- Create: `camp/apps/pesticides/places.py`
- Test: `camp/apps/pesticides/tests/test_places.py`

**Interfaces:**
- Consumes: `camp.apps.regions.resolve._place_key(prefix, place)`, `_place_geometry(place)`, `CACHE_TIMEOUT`.
- Produces: `section_ids_for(region: Region) -> list[int]`: pks of current MTRS regions whose boundary intersects the region's boundary, sorted; `[]` without a boundary. Cached 24h under `_place_key('pesticide_sections', region)`. Not used for counties.

- [ ] **Step 1: Write the failing tests** (fixture `pesticides-explorer`; `cache.clear()` in `setUp`)

```python
def test_sections_touching_region(self):
    region = Region.objects.create(name='Box', slug='box', type=Region.Type.CITY, external_id='X1')
    Boundary.objects.create(region=region, version='t', geometry=MultiPolygon(Polygon.from_bbox((-119.9, 36.6, -119.7, 36.8))))
    region.refresh_from_db()
    assert section_ids_for(region) == [9101]

def test_no_boundary_is_empty(self):
    region = Region.objects.create(name='Bare', slug='bare', type=Region.Type.CITY, external_id='X2')
    assert section_ids_for(region) == []

def test_cached(self):
    # second call makes no queries
    section_ids_for(region); 
    with self.assertNumQueries(0):
        assert section_ids_for(region) == [9101]
```

(Set `region.boundary` the way the fixture links it: `Region.boundary` FK; create the Boundary, then save it on the region.)

- [ ] **Step 2: Run, expect failure** — `TEST camp/apps/pesticides/tests/test_places.py -v` → ImportError.
- [ ] **Step 3: Implement `section_ids_for`** — `Region.objects.filter(type=Region.Type.MTRS, boundary__geometry__intersects=geometry).order_by('pk').values_list('pk', flat=True)`.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(pesticides): MTRS sections for a region, cached"`

### Task 2: Monthly aggregation with the counting rule

**Files:**
- Modify: `camp/apps/pesticides/places.py`
- Test: `camp/apps/pesticides/tests/test_places.py`

**Interfaces:**
- Consumes: Task 1's `section_ids_for`.
- Produces: `rollup_rows_for(place: Region | Monitor) -> QuerySet[PesticideUseRollup]` (county → `county=`; other region → `mtrs__in=section_ids_for(region)`; monitor → first of `zips_for(monitor)` then the same, or `.none()`); `monthly_use(rows: QuerySet, chemical_scoped: bool, multi_chemical: bool) -> dict` returning `{'months': [...], 'years': [...]}` in the contract shape. Floats as stored; `applications` int.

- [ ] **Step 1: Write the failing tests** (class uses `RollupTestMixin`, fixture `pesticides-explorer`; Fresno = pk 9001)

```python
def test_county_months_and_years(self):
    out = monthly_use(rollup_rows_for(fresno), chemical_scoped=False, multi_chemical=False)
    # 2023 Fresno: uses 1 (Mar,100lb,10ac), 2 (Apr,50,5), 4 (Jun,20,2), 6 (Aug,500,50)
    assert out['months'][:2] == [
        {'year': 2022, 'month': 3, 'pounds': 80.0, 'acres': 8.0, 'applications': 1},
        {'year': 2022, 'month': 8, 'pounds': 400.0, 'acres': 40.0, 'applications': 1},
    ]
    y2023 = next(y for y in out['years'] if y['year'] == 2023)
    assert y2023 == {'year': 2023, 'pounds': 670.0, 'acres': 67.0, 'applications': 4,
                     'undated': {'pounds': 0.0, 'acres': 0.0, 'applications': 0}}

def test_undated_in_year_not_months(self):
    PesticideUse.objects.filter(pk=1).update(application_date=None)
    rollup.rebuild_year(2023)
    out = monthly_use(rollup_rows_for(fresno), False, False)
    assert not any(m['year'] == 2023 and m['month'] == 3 for m in out['months'])
    y = next(y for y in out['years'] if y['year'] == 2023)
    assert y['pounds'] == 670.0 and y['undated'] == {'pounds': 100.0, 'acres': 10.0, 'applications': 1}

def test_multi_ingredient_counted_once(self):
    # Product 1 gets a second ingredient, chlorpyrifos marked carcinogen: use 1 becomes two rows.
    Chemical.objects.filter(pk=2).update(categories=['carcinogen'])
    ProductChemical.objects.create(product_id=1, chemical_id=2, pct_active=5)
    PesticideUse.objects.create(year=2023, use_no=1, county_id=9001, mtrs_id=9101, product_id=1,
        chemical_id=2, commodity_id=1, lbs_chemical=7, lbs_product=250, amount_treated=10,
        unit_treated='A', application_date=date(2023, 3, 1), aerial_ground='G')
    rollup.rebuild_year(2023)
    rows = rollup_rows_for(fresno).filter(chemical__categories__contains=['carcinogen'], year=2023, month=3)
    out = monthly_use(rows, chemical_scoped=False, multi_chemical=True)
    assert out['months'] == [{'year': 2023, 'month': 3, 'pounds': 107.0, 'acres': 10.0, 'applications': 1}]
    # Unfiltered, the record also counts once (records / acres_once).
    out = monthly_use(rollup_rows_for(fresno).filter(year=2023, month=3), False, False)
    assert out['months'][0]['applications'] == 1 and out['months'][0]['acres'] == 10.0

def test_chemical_scoped_uses_ingredient_rows(self):
    rows = rollup_rows_for(fresno).filter(chemical__chem_code=253)
    out = monthly_use(rows, chemical_scoped=True, multi_chemical=False)
    assert out['months'] == [{'year': 2023, 'month': 6, 'pounds': 20.0, 'acres': 2.0, 'applications': 1}]

def test_region_via_sections_and_monitor_via_zip(self):
    # A city boundary around section 9101 → the same numbers as Fresno's 9101 rows.
    # A monitor: patch camp.apps.pesticides.places.zips_for to return [that city-like ZIP];
    # and to return [] → rows.none().
```

(Write the last test fully: create a ZIP region with a boundary covering 9101, assert its 2023 total is 670 lb; a monitor with `zips_for` patched to `[]` gives empty lists.)

- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.** One query for the plain cases: `.values('year', 'month').annotate(pounds=Sum('lbs_chemical'), acres=Sum(<col>), applications=Sum(<col>))`; years are summed in Python from the month rows (month 0 rows feed `undated` and the year totals, never `months`). For `multi_chemical`, first group by the key with `Max('acres_treated')`, `Max('applications')`, `Sum('lbs_chemical')`, then sum those per (year, month) — a subquery or `connection.cursor()` SQL, one round trip. Comment the null-product caveat.
- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** — `feat(pesticides): monthly use for a place with once-per-record counting`

### Task 3: The endpoint

**Files:**
- Modify: `camp/api/v2/pesticides/endpoints.py` (add `PesticidePlace`, `PesticidePlaceForm`), `camp/api/v2/pesticides/urls.py` (`path('place/', endpoints.PesticidePlace.as_view(), name='pesticide-place')`, before `region/...`)
- Test: `camp/api/v2/pesticides/tests.py` (new class `PesticidePlaceTests(RollupTestMixin, TestCase)`, fixture `pesticides-explorer`)

**Interfaces:**
- Consumes: `resolve_place`, `place_json`, `PlaceError`, `PlaceNotFound`; Task 2's `rollup_rows_for`, `monthly_use`; `stats.cached`, `stats.all_years_key`.
- Produces: URL name `api:v2:pesticides:pesticide-place`.

Filter → queryset: `chemical` → `chemical__chem_code`; `commodity` → `commodity__site_code`; `category` → `chemical__categories__contains=[v]`; `iarc_group` → `chemical__iarc_group`; `aerial_ground` → `method`; years → `year__gte` / `year__lte`. `chemical_scoped = bool(chemical)`; `multi_chemical = not chemical_scoped and bool(category or iarc_group)`.

Cache: `stats.cached(stats.all_years_key('place', _place_key('pesticides', place), <sorted cleaned filters>), build, ttl=CACHE_TIMEOUT)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_county(self):
    r = self.client.get(URL, {'region_type': 'county', 'region': '06019'})
    assert r.status_code == 200 and r['Cache-Control'] == 'public, max-age=3600'
    data = r.json()['data']
    assert data['place'] == {'region': {'type': 'county', 'external_id': '06019', 'name': 'Fresno County'}}
    assert {'year': 2023, 'month': 8, 'pounds': 500.0, 'acres': 50.0, 'applications': 1} in data['months']

def test_filters(self):
    d = self.client.get(URL, {'region_type': 'county', 'region': '06019', 'chemical': 253, 'year__gte': 2023}).json()['data']
    assert [y['year'] for y in d['years']] == [2023] and d['years'][0]['pounds'] == 20.0
    d = self.client.get(URL, {'region_type': 'county', 'region': '06029', 'aerial_ground': 'A', 'year__lte': 2022}).json()['data']
    assert d['years'] == [{'year': 2022, 'pounds': 60.0, 'acres': 6.0, 'applications': 1,
                           'undated': {'pounds': 0.0, 'acres': 0.0, 'applications': 0}}]

def test_bad_filter_values_are_400(self):
    for bad in ({'year__gte': 'abc'}, {'category': 'nope'}, {'aerial_ground': 'X'}, {'iarc_group': '9'}, {'chemical': 'x'}):
        r = self.client.get(URL, {'region_type': 'county', 'region': '06019', **bad})
        assert r.status_code == 400 and r['Cache-Control'] == 'no-cache'

def test_blank_filters_ignored(self): ...   # chemical='' equals no filter
def test_place_errors(self): ...            # land_use 400, unknown 404, nothing 400, monitor+region 400
def test_retired_region_answers(self): ...  # set retired_at on Fresno, still 200
def test_monitor_without_zip_is_empty(self): ...  # patch zips_for → [], months == years == []
def test_rebuild_retires_cache(self):
    first = self.client.get(URL, {'region_type': 'county', 'region': '06019'}).json()['data']
    PesticideUse.objects.filter(pk=6).delete(); rollup.rebuild_year(2023)
    second = self.client.get(URL, {'region_type': 'county', 'region': '06019'}).json()['data']
    assert next(y for y in second['years'] if y['year'] == 2023)['pounds'] == 170.0
```

Write the `...` tests out in full with the values shown in the comments.

- [ ] **Step 2: Run, expect failure** (404 on the URL).
- [ ] **Step 3: Implement** `PesticidePlace(generics.Endpoint)` mirroring `CalHeatScorePlace`; `PesticidePlaceForm(forms.Form)` with `IntegerField`/`ChoiceField(required=False)`; a docstring naming the params.
- [ ] **Step 4: Run the class, then the whole pesticides API file** — `TEST camp/api/v2/pesticides/tests.py -v` → all pass.
- [ ] **Step 5: Commit** — `feat(api): pesticides/place/ monthly use for a region or monitor`

### Task 4: Measure, document, full suite

**Files:**
- Modify: `CLAUDE.md` ("Metadata Endpoints", the **Place endpoints** bullet)

- [ ] **Step 1: Measure locally.** Message `data-dashboard-b7` before swapping the shared web container to serve this worktree (brief's "Serving a worktree" recipe), and again after restoring the main checkout. Read-only requests with `curl -w '%{time_total}'`. Time cold and warm requests for `?region_type=city&region=0627000` (Fresno) and `?region_type=ab617&region=SCFR` (South Central Fresno), unfiltered and with `category=carcinogen`, and `county 06019`. Record the times in the PR description. If a cold request exceeds ~2 s, stop and report before optimizing.
- [ ] **Step 2: Add to CLAUDE.md** after the place endpoints sentence: `pesticides/place/` (same addressing) returns `months` and `years` from `PesticideUseRollup`: counties by `county=`, other regions by the MTRS sections they touch, monitors by their ZIP; month 0 only in `years[].undated` (included in the year totals); acres/applications count each record once (per-ingredient columns with `chemical`, per-product MAX with `category`/`iarc_group`, `records`/`acres_once` otherwise); cached under the pesticides data version.
- [ ] **Step 3: Full suite** — `TEST -n 4 --dist loadscope`; compare to the baseline: no new failures.
- [ ] **Step 4: Commit** — `docs: pesticides/place/ in CLAUDE.md`
- [ ] **Step 5: Push and open the PR into `develop`** (`gh pr create --base develop`), no AI attribution. Tell `data-dashboard-b7` and `data-dashboard-13` the PR number and the final shape. Do not merge.

---

## SDK (sdk-js) — after the server PR is open

Worktree: `git -C /home/alex/workspace/sjvair/sdk-js worktree add .worktrees/pesticides-place -b feature/pesticides-place origin/release/5.0.0`. Follow sdk-js `CLAUDE.md`. PR into `release/5.0.0`. No beta, tag or publish.

### Task 5: `getPesticidesForPlace`

**Files:**
- Create: `lib/pesticides/get_pesticides_for_place.ts`, `lib/pesticides/schemas/pesticides_for_place.ts`, `lib/pesticides/fixtures/pesticides_for_place.json` (a real response from the local server running the branch, trimmed to a few months)
- Modify: `lib/pesticides/schemas/mod.ts`, `lib/pesticides/types.ts`, `lib/pesticides/mod.ts`, `lib/pesticides/mod_test.ts`, `deno.json` (export `./pesticides/get_pesticides_for_place`), `CHANGELOG.md` (5.0.0 "Added"), `api-urls.md` (`[x] /api/2.0/pesticides/place/`)

**Interfaces:**
- Consumes: `PlaceRef`, `placeSearchParams` from `lib/meta/place.ts`; `jsonCall`; existing `AerialGround`, `IARCGroup` types.
- Produces: `getPesticidesForPlace(place: PlaceRef, filters?: PesticidesForPlaceFilters, options?: RequestOptions): Promise<PesticidesForPlace>`; `PesticidesForPlaceFilters { chemical?: number; commodity?: string; category?: string; iarc_group?: IARCGroup; aerial_ground?: AerialGround; year__gte?: number; year__lte?: number }`; `pesticidesForPlaceSchema` (`place`, `months: {year, month, pounds, acres, applications}[]`, `years: {year, pounds, acres, applications, undated: {pounds, acres, applications}}[]`).

- [ ] **Step 1: Failing tests** in `mod_test.ts`, a `Module: pesticides for a place` test: fixture matches the schema (`getSimpleValidationTest`); with `stubFetch`, `getPesticidesForPlace({ region: { type: "county", external_id: "06019" } }, { chemical: 253, year__gte: 2022 })` calls `/api/2.0/pesticides/place/` with `region_type=county`, `region=06019`, `chemical=253`, `year__gte=2022` and no other params; a live step against the local API validates the response or skips when unavailable (as the heat test does).
- [ ] **Step 2: Run** `deno test --allow-net --allow-env --allow-read --env-file=.env lib/pesticides/mod_test.ts` → fails.
- [ ] **Step 3: Implement** the wrapper (JSDoc with an `@example`, like `getHeatForPlace`) and schema (JSDoc per field: undated is included in year totals; months has only months with use).
- [ ] **Step 4: Verify** `deno fmt --check && deno lint && deno check mod.ts && deno test --allow-net --allow-env --allow-read --env-file=.env` (skip the account tests). Pass.
- [ ] **Step 5: Commit, push, PR into `release/5.0.0`**; tell the coordinator. Ask the user before any beta.

---

## Docs (data-dashboard) — with the server PR

### Task 6: DEFERRED entry

- [ ] **Step 1:** In the docs worktree (`git -C /home/alex/workspace/sjvair/data-dashboard worktree add .worktrees/docs-explorer-layers origin/main` if missing; else `git fetch && git rebase origin/main`), re-read `DEFERRED.md`, then add an entry: **Pesticide use within a distance of a place** — Get data counts a place's pesticide use by region membership (a monitor or school by its ZIP); a buffer (e.g. sections within 1/3/5 miles, the `shapes.BUFFERS` choices) would answer "use near this school". Why deferred: region membership is the rule for every Get data layer today. Revisit when the dashboard wants a distance option or users ask about nearby use.
- [ ] **Step 2:** `../../node_modules/.bin/prettier --write DEFERRED.md`; rebase on `origin/main`; commit `docs: defer distance-based pesticide use for a place`; push straight to `main`.
