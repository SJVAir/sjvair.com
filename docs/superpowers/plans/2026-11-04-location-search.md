# Location Name Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A name search for schools and child-care sites (`regions/locations/search/`) for the dashboard's "Pick my school", plus region names on location rows, location type labels in `regions/meta/`, and sdk-js wrappers for the search and `pesticides/locations/`.

**Architecture:** The matching and ordering live in `LocationQuerySet.search(q)` (one SQL query: trigram word similarity plus escaped `ILIKE` patterns, tried for the whole query and for name + town splits). A resticus endpoint beside `LocationList` validates params, applies type and region filters, caps and stretches the result, and sets `Cache-Control`. sdk-js gains `searchLocations` (via `apiCall`, to keep `more`) and `getPesticideLocations`.

**Tech Stack:** Django 5 / PostGIS / `pg_trgm` (already installed), django-resticus; Deno + zod for sdk-js.

**Spec:** `docs/superpowers/specs/2026-11-04-location-search-design.md` (read it first; this plan argues from it).

## Global Constraints

- sjvair.com: branch `feature/location-search` (worktree `.worktrees/location-search`), PR into `develop`. Never merge without the user's yes.
- sdk-js: branch from `origin/release/4.8.0`, worktree `/home/alex/workspace/sjvair/sdk-js/.worktrees/location-search`, PR into `release/4.8.0`. Never push a `v*` tag, publish, or cut a beta without the user's explicit yes.
- No Claude or AI attribution in commits, PRs, or docs.
- Searches use `Location.objects` (current only); by-code lookups keep `Location.all_objects`.
- No hardcoded labels in clients: type labels come from `regions/meta/` `location_types`.
- Names are shown as stored (no case tidying).
- `q`: stripped; under 2 characters → `{"data": [], "more": false}` 200; over 100 → 400.
- Result size: 10, stretched to at most 15 on a name tie at the 10th row; `more` when any match is left out.
- `Cache-Control: public, max-age=3600` on 200s; `no-cache` on errors. No server-side cache.
- Tests: `django.test.TestCase`, pytest-style `assert`. Test command (from the worktree, which has `.env` and `.env.test` copied in):
  `podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token -v $PWD:/app:z -v ~/workspace/django-resticus/.worktrees/session-csrf/resticus:/usr/local/lib/python3.14/site-packages/resticus:ro,z -w /app sjvair-com-test:latest pytest <target>` (call this `$PYTEST` below; ignore the trailing "not a git repository" line).

## Review Focus

1. **Wildcard characters in `q`** (`%`, `_`, `\`): must match literally, never as patterns. Pinned in Task 2 (`test_wildcards_match_literally`).
2. **Extra whitespace** (`"  lincoln   visalia "`): must behave like the single-spaced query. Pinned in Task 2 (`test_extra_spaces_are_ignored`).
3. **A town word that also appears in names** ("fresno high" → the Fresno High school, and "fresno" alone matches names, not just towns). Pinned in Task 2 (`test_town_word_still_matches_names`).
4. **A location with no city link and an empty `city_name`**: it must still be returned and sort without error. Pinned in Task 2 (`test_location_without_city`).
5. **Repeated or blank `type` values** (`type=public_school,,public_school`): must not 400. Pinned in Task 3 (`test_type_list_tolerates_blanks_and_repeats`).

---

### Task 1: Region names on location rows, and `location_types` in `regions/meta/`

**Files:**
- Modify: `camp/api/v2/regions/serializers.py:78-79` (`_region_ref`)
- Modify: `camp/api/v2/regions/endpoints.py:282-312` (`RegionMetaEndpoint`)
- Test: `camp/api/v2/regions/tests.py` (`LocationLookupTests`, `RegionMetaTests`)

**Interfaces:**
- Produces: location rows whose `regions.<field>` is `{"type", "external_id", "name"}` or `null`; `regions/meta/` `data.location_types` = `{type: {"type", "label", "source"}}`.

- [ ] **Step 1: Write the failing tests**

In `LocationLookupTests.test_lookup_by_code`, change the county assertion to:
```python
assert item['regions']['county'] == {'type': 'county', 'external_id': self.county.external_id, 'name': self.county.name}
```
In `RegionMetaTests`, add:
```python
def test_location_types(self):
    data = get_response_data(region_meta(self.factory.get('/')))['data']
    assert data['location_types'] == {
        'public_school': {'type': 'public_school', 'label': 'Public school', 'source': 'cde-public'},
        'private_school': {'type': 'private_school', 'label': 'Private school', 'source': 'cde-private'},
        'child_care': {'type': 'child_care', 'label': 'Child care', 'source': 'cdss-ccl'},
    }
```
(Use whatever view/factory names `RegionMetaTests` already uses.)

- [ ] **Step 2: Run to verify they fail**

Run: `$PYTEST camp/api/v2/regions/tests.py -k "test_lookup_by_code or test_location_types" -v`
Expected: 2 FAIL (missing `name`; missing `location_types`).

- [ ] **Step 3: Implement**

`_region_ref` adds `'name': region.name`. `RegionMetaEndpoint.get` adds `'location_types'` built from `Location.Type` in declared order, labels from `str(Location.SHORT_TYPES[t])`, and `source` from the type → source mapping the importer uses in `camp/apps/regions/locations.py` (import the constant if one exists; otherwise add a `Location.TYPE_SOURCES` dict on the model and have both use it).

- [ ] **Step 4: Run the regions API tests**

Run: `$PYTEST camp/api/v2/regions/tests.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/api/v2/regions camp/apps/regions/models.py
git commit -m "Add region names to location rows and location types to regions meta"
```

---

### Task 2: `LocationQuerySet.search(q)`

**Files:**
- Modify: `camp/apps/regions/querysets.py` (`LocationQuerySet`)
- Test: create `camp/apps/regions/tests/test_location_search.py`

**Interfaces:**
- Produces: `LocationQuerySet.search(self, q: str) -> LocationQuerySet` — filtered to matches, `one_per_place()` applied, ordered per the spec, with annotations `search_rank` (int) and `search_similarity` (float). Callers chain `.filter(...)` for type/region before slicing. Does **not** validate length (the endpoint does); a blank `q` returns `self.none()`.

**Algorithm (the part the tests don't fully determine):**

1. Normalize: `text = ' '.join(q.split())`; `words = text.lower().split(' ')`.
2. Splits: `(text, None)`, plus for `k` in `1..min(3, len(words) - 1)`: name = first `n-k` words, town = last `k` words; and name = last `n-k` words, town = first `k` words. (Town part capped at 3 words.)
3. `city_key = Lower(Coalesce(NullIf('city__name', ''), 'city_name'))`, annotated once.
4. For each split `i` with name text `t`:
   - `tier_i = Case(When(name__istartswith=t, then 3), When(Q(name__icontains=' '+t) | Q(name__icontains='/'+t) | Q(name__icontains='-'+t) | Q(name__icontains='('+t), then 2), When(Q(name__icontains=t) | Q(sim_i__gte=0.3), then 1), default 0)` where `sim_i = TrigramWordSimilarity(t, 'name')`. Django's `i*` lookups escape `%`, `_` and `\`.
   - `match_i = tier_i > 0` and, for a town split, `city_key__startswith=town`.
   - `rank_i = Case(When(match_i, then (4 if town else 0) + tier_i), default 0)`.
5. `search_rank = Greatest(rank_0 … rank_n)`; filter `search_rank > 0`.
6. `search_similarity = Greatest(Case(When(rank_i == search_rank, then sim_i), default 0.0) …)`.
7. Apply `one_per_place()` **before** the rank annotations (it's a filter on the base rows, so the representative is the lowest code regardless of the query).
8. `order_by('-search_rank', '-search_similarity', 'city_key', Lower('name'), 'source', 'external_id')`.

With one split (single word) use the plain expressions, not `Greatest` of one item.

- [ ] **Step 1: Write the failing tests**

`LocationSearchTests(TestCase)` with `fixtures = ['regions.yaml']`; in `setUp` create `Location.objects` rows via a helper `make(name, city_name, type=PUBLIC_SCHOOL, source='cde-public', external_id=<unique>, point=<distinct per row>, city=None, **kw)`. Create at least: "Lincoln Elementary" in Visalia, Fresno, Bakersfield, dinuba (lowercase city_name); "Abraham Lincoln Jr. High" (Bakersfield); "Roosevelt Elementary" (Fresno); "Fresno High" (Fresno); "FRESNO EOC HEAD START" (child care, CARUTHERS); the wildcard rows named in `test_wildcards_match_literally`. Each test asserts on `[(l.name, l.city_name) for l in Location.objects.search(q)]` or its prefix.

Tests (names and assertions):
- `test_prefix_beats_word_start_beats_substring`: `search('linc')` → all "Lincoln Elementary" rows before "Abraham Lincoln Jr. High".
- `test_same_name_orders_by_city_ignoring_case`: `search('lincoln elementary')` first four cities == `['Bakersfield', 'dinuba', 'Fresno', 'Visalia']`.
- `test_typo_matches`: `search('Linclon')` includes every Lincoln row; `search('Rosevelt')` first row is Roosevelt Elementary.
- `test_town_suffix_ranks_first`: `search('lincoln visalia')[0]` is (Lincoln Elementary, Visalia).
- `test_town_prefix_ranks_first`: `search('visalia lincoln')[0]` is the Visalia Lincoln.
- `test_partial_town`: `search('lincoln vis')[0]` is the Visalia Lincoln.
- `test_town_alone_does_not_match`: `search('roosevelt visalia')` contains no Visalia Lincoln (town matched, name not).
- `test_single_word_never_splits`: `search('visalia')` returns no rows (no name contains it) even though a row's city is Visalia.
- `test_town_word_still_matches_names`: `search('fresno high')[0]` is Fresno High; `search('fresno')` includes "FRESNO EOC HEAD START".
- `test_retired_excluded`: retire the Visalia Lincoln; `search('lincoln')` excludes it.
- `test_child_care_licenses_are_one_row`: two child-care rows, same name, ~50 m apart, codes `153400002` and `153400001` → one result with `external_id == '153400001'`.
- `test_wildcards_match_literally`: with rows "100% Kids Club", "1000 Oaks Preschool", "Kids_Club" and "KidsZClub": `search('100%')[0]` is "100% Kids Club" with `search_rank == 3`, and "1000 Oaks Preschool", if returned at all (trigram may), has `search_rank < 3`; in `search('s_c')`, "Kids_Club" has `search_rank >= 1` via substring and "KidsZClub" is not given a substring tier (its `search_rank`, if present, comes only from similarity, and is below "Kids_Club"'s position).
- `test_extra_spaces_are_ignored`: `search('  lincoln   visalia ')` equals `search('lincoln visalia')`.
- `test_location_without_city`: a row with `city=None, city_name=''` named "Lincoln Annex" is returned by `search('lincoln')`.
- `test_blank_query_returns_nothing`: `search('   ')` is empty.

- [ ] **Step 2: Run to verify they fail**

Run: `$PYTEST camp/apps/regions/tests/test_location_search.py -v`
Expected: FAIL (`'LocationQuerySet' object has no attribute 'search'`).

- [ ] **Step 3: Implement `search` per the algorithm above**

- [ ] **Step 4: Run to verify they pass**

Run: `$PYTEST camp/apps/regions/tests/test_location_search.py camp/apps/regions/tests/test_location_places.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/regions/querysets.py camp/apps/regions/tests/test_location_search.py
git commit -m "Add a name search to locations, with typo tolerance and town matching"
```

---

### Task 3: `GET /api/2.0/regions/locations/search/`

**Files:**
- Modify: `camp/api/v2/regions/endpoints.py` (new `LocationSearch` after `LocationList`)
- Modify: `camp/api/v2/regions/urls.py` (add `path('locations/search/', endpoints.LocationSearch.as_view(), name='location-search')` **before** `<region_id>/`)
- Modify: `CLAUDE.md` → "Metadata Endpoints" (one bullet: the endpoint, its params, the 10→15 stretch, `more`, the cache header, and `location_types`)
- Test: `camp/api/v2/regions/tests.py` (new `LocationSearchEndpointTests`)

**Interfaces:**
- Consumes: `Location.objects.search(q)` (Task 2); `LocationSerializer` (Task 1).
- Produces: JSON `{"data": [LocationRow…], "more": bool}`; constants `SEARCH_MIN_CHARS = 2`, `SEARCH_MAX_CHARS = 100`, `SEARCH_LIMIT = 10`, `SEARCH_TIE_LIMIT = 15`; filterable region types `SEARCH_REGION_FIELDS = {'county': 'county', 'city': 'city', 'cdp': 'city', 'zipcode': 'zipcode', 'school_district': 'school_district'}`.

Behavior:
- `q` stripped; `< 2` → 200 empty; `> 100` → 400 `{"error": "q must be at most 100 characters."}`.
- `type`: comma list, blanks dropped, duplicates ignored; unknown → 400 naming them (same wording style as `pesticides/locations/`).
- `region_type` + `region`: both or neither (400 otherwise); type not in `SEARCH_REGION_FIELDS` → 400; region resolved with `Region.all_objects.filter(type=…, external_id=…)`; none → 404; filter `**{field: region}`.
- Fetch `SEARCH_TIE_LIMIT + 1` rows with `select_related('county', 'city', 'zipcode', 'school_district', 'replaced_by')`. Keep the first 10; then keep following rows while their `name.strip().lower()` equals the 10th's, up to 15. `more = len(fetched) > len(kept)`.
- 200 → `Cache-Control: public, max-age=3600`; 400/404 → `Cache-Control: no-cache`.

- [ ] **Step 1: Write the failing tests**

`LocationSearchEndpointTests(TestCase)`, `fixtures = ['regions.yaml']`, using `RequestFactory` and `get_response_data` like `LocationLookupTests`. Tests:
- `test_returns_rows_and_more_false`: `q=lincoln` with 3 matches → 3 rows, each with the Task 1 shape (`regions.county.name` present), `more is False`, header `public, max-age=3600`.
- `test_short_query_is_empty`: `q=l` → 200, `{"data": [], "more": False}`.
- `test_long_query_is_400`: `q='x'*101` → 400, `no-cache`.
- `test_caps_at_ten`: 12 distinct names matching `academy` → 10 rows, `more is True`.
- `test_stretches_on_name_tie`: 9 other "Academy …" names ranking first (prefix) plus 4 rows named "Academy Zeta" in different cities, so the 10th row is an "Academy Zeta" → 13 rows, `more is False`.
- `test_stretch_stops_at_fifteen`: as above with 8 "Academy Zeta" rows → 15 rows, `more is True`.
- `test_type_filter`: `type=child_care` → only child care; `type=public_school,private_school` → no child care.
- `test_type_list_tolerates_blanks_and_repeats`: `type=public_school,,public_school` → 200.
- `test_unknown_type_is_400`: `type=college` → 400, error names `college`.
- `test_region_filter_each_linked_type`: for county, city, zipcode, school_district (and `cdp` against a CDP-linked row) the filter keeps only rows linked to that region.
- `test_region_filter_retired_region_still_filters`.
- `test_region_half_pair_is_400`, `test_region_unlinked_type_is_400` (`region_type=census_tract`), `test_region_unknown_code_is_404` (`no-cache`).
- `test_url_resolves`: `reverse('api:v2:regions:location-search')` (use the namespace the other region tests use) resolves to `LocationSearch`, not `RegionDetail`.

- [ ] **Step 2: Run to verify they fail**

Run: `$PYTEST camp/api/v2/regions/tests.py -k LocationSearchEndpointTests -v`
Expected: FAIL (`LocationSearch` not importable).

- [ ] **Step 3: Implement `LocationSearch(generics.Endpoint)` and the URL**

- [ ] **Step 4: Run the regions tests**

Run: `$PYTEST camp/api/v2/regions/tests.py camp/apps/regions/tests -v`
Expected: all PASS.

- [ ] **Step 5: Check speed on the real local database**

Run in the shared web container (read-only; the web container serves `develop`, so pass the worktree's queryset by running the check in a throwaway container instead):
`podman run --rm --network sjvaircom_sjvair-net --env-file .env -v $PWD:/app:z -w /app sjvair-com-test:latest python manage.py shell -c "<script>"`
The script runs `EXPLAIN ANALYZE` (via `str(qs.query)` + cursor, or `qs.explain(analyze=True)`) and times 5 runs each for: `linc`, `lincoln elementary`, `lincoln visalia`, `visalia lincoln elem`, `rosevelt`, `el`, `academy`, `x`*100 (not rejected at queryset level), each also with `type=child_care` and with a county filter, slicing `[:16]`.
Expected: warm median under 30 ms for every query. If any exceeds it, add a migration with a `GinIndex(OpClass(Lower('name'), 'gin_trgm_ops'))`-style trigram index on `name`, re-measure, and record before/after numbers in the PR description either way.

- [ ] **Step 6: Update `CLAUDE.md` and commit**

```bash
git add camp/api/v2/regions CLAUDE.md
git commit -m "Add the regions/locations/search endpoint"
```

---

### Task 4: sdk-js schemas and `searchLocations`

**Files (in `/home/alex/workspace/sjvair/sdk-js/.worktrees/location-search`, branch `feature/location-search` from `origin/release/4.8.0`):**
- Modify: `lib/regions/schemas/location.ts` (region ref gains `name: z.string()`; add exported `locationTypeSchema = z.enum(["public_school", "private_school", "child_care"])`, used for `type`)
- Modify: `lib/regions/schemas/regions_meta.ts` (`location_types: z.record(locationTypeSchema, z.object({ type: locationTypeSchema, label: z.string(), source: locationSourceSchema }))`)
- Modify: `lib/regions/schemas/mod.ts`, `lib/regions/types.ts` (export `LocationType`, `LocationTypeMeta`, `LocationSearchResult`)
- Create: `lib/regions/search_locations.ts`; export from `lib/regions/mod.ts`
- Modify: fixtures `lib/regions/fixtures/locations_cde_public.json`, `locations_cdss_ccl.json` (add region `name`s), and the regions-meta fixture if one exists; create `lib/regions/fixtures/locations_search.json`
- Test: create `lib/regions/search_locations_test.ts`
- Modify: `api-urls.md` (add and tick `/api/2.0/regions/locations/search/`)

**Interfaces:**
- Consumes: the server response from Task 3.
- Produces:
```ts
export type LocationSearchParams = {
  q: string;
  type?: LocationType | Array<LocationType>;
  region?: { type: RegionType; external_id: string };
} & RequestOptions;
export type LocationSearchResult = { results: Array<Location>; more: boolean };
export async function searchLocations(params: LocationSearchParams): Promise<LocationSearchResult>;
```
`q` trimmed; under 2 characters returns `{ results: [], more: false }` with no request. Sends `q`, `type` (comma-joined), `region_type`/`region`. Uses `apiCall<{ data: Array<Location>; more: boolean }>` and maps `data` → `results`. Splits request options off the params the way `getMonitorsList` does.

- [ ] **Step 0: Search first**

Run: `git grep -n -i "locations/search\|searchLocations\|location.*search" -- lib api-urls.md`
Expected: no existing wrapper. If one exists, extend it instead and adjust this task.

- [ ] **Step 1: Capture fixtures** from the Task 3 branch's code (serve the worktree per the brief's "Serving a worktree" recipe after messaging the data-dashboard sessions, or capture through a throwaway container with Django's test client against `regions.yaml` + created rows, as the existing location fixtures were). `locations_search.json` holds a `q=lincoln` answer with `more`.

- [ ] **Step 2: Write the failing tests** (stubbed fetch, as `lookup_by_code_test.ts`):
- `"search fixture matches the schema"`: each row validates against `locationSchema`; `regions.county.name` is a string.
- `"searchLocations sends q, type and region"`: stub asserts the URL path `regions/locations/search` and params `q=lincoln visalia`, `type=public_school,child_care`, `region_type=county`, `region=06107`.
- `"searchLocations returns results and more"`: stubbed `{data:[…], more:true}` → `{ results: [...], more: true }`.
- `"searchLocations skips the request under 2 characters"`: stub that throws if called; `searchLocations({ q: " l " })` → `{ results: [], more: false }`.
- `"searchLocations passes the abort signal"`: aborted signal → rejects.
- `"regions meta lists location types"`: meta fixture validates; `location_types.child_care.source === "cdss-ccl"`.

- [ ] **Step 3: Run to verify they fail**

Run: `deno test --allow-net --allow-env --allow-read --env-file=.env lib/regions/search_locations_test.ts`
Expected: FAIL (module not found).

- [ ] **Step 4: Implement the schemas and `searchLocations`**

- [ ] **Step 5: Run the SDK checks**

Run: `deno fmt --check && deno lint && deno check mod.ts && deno test --allow-net --allow-env --allow-read --env-file=.env lib/regions`
Expected: PASS (live-API steps need the Task 3 branch served; skip-guarded ones may skip).

- [ ] **Step 6: Commit**

```bash
git add lib/regions api-urls.md
git commit -m "feat(regions): add searchLocations and location type metadata"
```

---

### Task 5: sdk-js `getPesticideLocations`

**Files:**
- Create: `lib/pesticides/get_pesticide_locations.ts`; export from `lib/pesticides/mod.ts`
- Create: `lib/pesticides/schemas/pesticide_locations.ts` (FeatureCollection of Point features; properties `id`, `name`, `type` (`locationTypeSchema`), `type_label`, `address`, `city` (nullable), `school_district` (nullable), `school_district_id` (nullable), `school_district_url` (nullable), `grade_span` (nullable), `enrollment` (nullable number), `capacity` (nullable number))
- Modify: `lib/pesticides/types.ts`, `api-urls.md` (tick `/api/2.0/pesticides/locations/`)
- Test: `lib/pesticides/get_pesticide_locations_test.ts` plus a captured fixture

**Interfaces:**
```ts
export type PesticideLocationsArea =
  | { bbox: [west: number, south: number, east: number, north: number] }
  | { region: string; buffer?: 0 | 1 | 3 | 5 }   // region sqid
  | { lat: number; lng: number; radius?: number }; // miles, up to 10
export type PesticideLocationsParams = PesticideLocationsArea & {
  type?: LocationType | Array<LocationType>;
  county?: string; // county slug
} & RequestOptions;
export async function getPesticideLocations(params: PesticideLocationsParams): Promise<PesticideLocationCollection>;
```
The endpoint returns a bare FeatureCollection (no `data` wrapper): use `apiCall`. The doc comment says the `lat`/`lng` form puts coordinates in the URL, so it is for public points (a school), never a person's own location.

- [ ] **Step 0: Search first**: `git grep -n -i "pesticides/locations\|PesticideLocation" -- lib api-urls.md` → none expected.
- [ ] **Step 1: Capture a fixture** (`bbox` around Fresno, from the local API).
- [ ] **Step 2: Write the failing tests**: fixture validates; bbox is sent as `bbox=w,s,e,n`; region form sends `region` and `buffer`; point form sends `lat`, `lng`, `radius`; `type` array is comma-joined; `county` passes through.
- [ ] **Step 3: Run to verify they fail**: `deno test … lib/pesticides/get_pesticide_locations_test.ts` → FAIL.
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Run the full SDK check** (the command in Task 4 Step 5, over the whole repo, minus the account tests).
- [ ] **Step 6: Commit**: `git commit -m "feat(pesticides): add getPesticideLocations"`.

---

### Task 6: Verify, open PRs, update the dashboard docs

- [ ] **Step 1: Full sjvair.com suite**: `$PYTEST -n 4 --dist loadscope 2>&1 | tee /tmp/claude-…/scratchpad/location-search-tests.log`. Expected: about 4189 + new tests passed, 0 failed.
- [ ] **Step 2: Hand check on the served branch** (message `data-dashboard-2c` and `data-dashboard-0d` before swapping the web container, and again after restoring): `curl` `regions/locations/search/?q=lincoln%20visalia`, `?q=lincoln%20elementary` (13 rows, `more:false`), `?q=linclon`, `?q=lincoln&type=child_care`, `?q=lincoln&region_type=county&region=06019`, and check the `Cache-Control` header.
- [ ] **Step 3: Push and open PRs** (sjvair.com into `develop`, sdk-js into `release/4.8.0`); PR bodies list the speed numbers from Task 3 Step 5. No AI attribution.
- [ ] **Step 4: Tell `data-dashboard-2c` and `data-dashboard-0d`** the PRs are open, with the endpoint shape and the SDK function names. Say no beta exists yet; a beta waits for the user's yes.
- [ ] **Step 5: Dashboard docs** (own worktree `git -C /home/alex/workspace/sjvair/data-dashboard worktree add .worktrees/docs-location-search origin/main`; re-read each file before editing; prettier; push straight to `main`): TODO.md step 3 location item and this track's row; ARCHITECTURE.md → "Schools and child care are places" (what was built: endpoint, town matching, 10→15, `location_types`, region names, SDK names); DEFERRED.md entry "Tidy child-care names" (why: rule-based casing gets acronyms and names wrong; revisit if parents or partners find the capitals confusing in the picker).
