# Metadata Enablers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the new dashboard server metadata it can build on: a dataset catalog with an available-pollutants gate, permanent official codes for regions and locations (lookups, retirement instead of deletion), a cheap coverage endpoint, and sdk-js wrappers plus a time-zone fix.

**Architecture:** A new `camp/api/v2/meta/` API package holds the catalog and coverage endpoints. Region and location permanence is model-level (`retired_at`, `replaced_by`, a filtered `objects` manager and an unfiltered default `all_objects` manager), so existing listings hide retired rows without per-file edits. sdk-js gains thin typed wrappers and a Pacific-aware date module.

**Tech Stack:** Django 5 / PostGIS, django-resticus, django-filter, pytest + `django.test.TestCase`; sdk-js on Deno 2 with Zod.

**Spec:** `docs/superpowers/specs/2026-10-22-metadata-enablers-design.md` (approved 2026-10-22). Read it first; this plan argues from it.

## Global Constraints

- sjvair.com work happens in the worktree `/home/alex/workspace/sjvair/sjvair.com/.worktrees/metadata-enablers` on `feature/metadata-enablers`; PR into `develop`.
- sdk-js work happens on a new branch `feature/metadata-enablers` in `~/workspace/sjvair/sdk-js` (check `git status` is clean first); PR into `main`.
- This developer uses podman. Run sjvair.com tests **from the worktree** with: `podman-compose -p sjvaircom --profile test run --rm test pytest <path> -v` (the `-p sjvaircom` reuses the running db/redis/memcached; `.env` and `.env.test` are already copied into the worktree and are git-ignored). Tee long runs to a log in the scratchpad before filtering.
- **No AI attribution anywhere**: no `Co-Authored-By` trailers, no "Generated with" lines in commits or PR bodies.
- Commit message style: `feat(api): …`, `fix(regions): …`, `docs: …` (conventional, scope = app or area).
- **Never release**: no sdk-js version bump, JSR publish, tag, or GitHub release without the user's explicit approval for that specific release.
- Tests use `django.test.TestCase`, pytest-style `assert`, fixtures from `/fixtures/*.yaml` (`regions.yaml`, `default-calibrations.yaml`, `purple-air.yaml`, …), and `RequestFactory` + `camp.utils.test.get_response_data` like `camp/api/v2/regions/tests.py`.
- Dataset ids, entry-type ids, and region/location codes are a **permanent public contract**: never reused, a rename changes only the label.
- Land-use regions (`type=land_use`) are **excluded** from code lookup and the permanence promise.
- Dates in coverage are **Pacific calendar dates** (`settings.DEFAULT_TIMEZONE`). sdk-js day snapping is in `America/Los_Angeles`.
- Weigh performance on every query: no table-wide `MIN`/`MAX` on entry tables (BRIN-only on `timestamp`); per-monitor queries must use the `(monitor, timestamp, …)` unique index.

## Review Focus

1. **Messy code lists** (`external_id= 06019, ,06019`): whitespace and empty items are ignored, duplicates return one row, more than 100 codes is a 400. Tests in Task 5 and Task 8.
2. **A child-care site whose licenses split** across two new sites: only one site keeps the old code; the other gets its own lowest number, with no unique-constraint error. Test in Task 7.
3. **A retired location reappears** in the next file: it is un-retired in place, not duplicated. Test in Task 7.
4. **Coverage on a place with no data / an unknown place**: no data → `first`/`last` are `null` with 200; unknown monitor or region code → 404; a retired region still answers. Tests in Task 9.
5. **Day snapping near DST and far-off zones** (device in `Pacific/Auckland` or `UTC`, a range across 2026-11-01): ranges snap to Pacific midnight and 23:59:59.999 Pacific, sent as UTC `Z`. Tests in Task 11.

---

## sjvair.com

### Task 1: Available pollutants

**Files:**
- Modify: `camp/apps/calibrations/models.py` (`DefaultCalibrationManager`)
- Modify: `camp/api/v2/monitors/endpoints.py` (`MonitorMetaEndpoint.get`)
- Test: `camp/apps/calibrations/tests.py` (or the existing calibrations test module), `camp/api/v2/monitors/tests/test_endpoints.py`

**Interfaces:**
- Produces: `DefaultCalibration.objects.available_pollutants() -> list[str]`: sorted entry-type keys published by at least one **enabled** monitor type (`Monitor.get_enabled_subclasses()`). `monitors/meta/` response gains `data.available_pollutants: list[str]`.

- [ ] **Step 1: Write failing tests**

```python
class AvailablePollutantsTests(TestCase):
    fixtures = ['default-calibrations.yaml']

    def test_fixture_publishes_pm25_and_o3(self):
        assert DefaultCalibration.objects.available_pollutants() == ['o3', 'pm25']

    def test_adding_a_row_makes_it_available(self):
        DefaultCalibration.objects.create(monitor_type='airnow', entry_type='no2', calibration='')
        assert 'no2' in DefaultCalibration.objects.available_pollutants()

    def test_monitor_meta_lists_available_pollutants(self):
        data = get_response_data(monitor_meta(RequestFactory().get('/')))
        assert data['data']['available_pollutants'] == ['o3', 'pm25']
```

- [ ] **Step 2: Run them, expect FAIL** (`AttributeError: available_pollutants`).
- [ ] **Step 3: Implement** `available_pollutants()` on `DefaultCalibrationManager` (one `values_list` query filtered to enabled monitor types, `distinct`, sorted) and add `'available_pollutants'` to `MonitorMetaEndpoint.get`'s payload. Reuse the same `published` set computation; don't duplicate it.
- [ ] **Step 4: Run, expect PASS.** Also run `camp/api/v2/monitors/tests/` to catch shape assertions that list exact keys.
- [ ] **Step 5: Commit** `feat(calibrations): Derive available pollutants from DefaultCalibration`.

### Task 2: Dataset catalog `GET /api/2.0/meta/datasets/`

**Files:**
- Create: `camp/api/v2/meta/__init__.py`, `camp/api/v2/meta/urls.py`, `camp/api/v2/meta/catalog.py`, `camp/api/v2/meta/endpoints.py`, `camp/api/v2/meta/tests/__init__.py`, `camp/api/v2/meta/tests/test_catalog.py`
- Modify: `camp/api/v2/urls.py` (add `path('meta/', include('camp.api.v2.meta.urls', namespace='meta'))`)

**Interfaces:**
- Consumes: `DefaultCalibration.objects.available_pollutants()` (Task 1); `Monitor.get_enabled_subclasses()`; each entry model's `entry_type`, `label`, `units`, `summarize`; `BaseSummary.Resolution`.
- Produces: `catalog.get_catalog() -> dict` = `{'datasets': [...], 'summary_rules': {...}}`; `catalog.DATASET_IDS: tuple[str, ...]`; `catalog.dataset_entry_types(dataset_id: str) -> list[str]` (used by Task 9). URL name `api:v2:meta:datasets`.

Catalog content (pinned; these ids become permanent at merge, so correct a name only if the domain's endpoint shows it's wrong, and note the change in the PR):

| id | entry types (`id`: kind, units, resolutions) | geographies | meta_url |
|---|---|---|---|
| `air-quality` | derived (below) | `monitor`, `region` | `monitors/meta/` |
| `weather` | derived from `CIMIS.ENTRY_CONFIG` | `monitor` | `monitors/meta/` |
| `hms-smoke` | `smoke-density`: other, `""`, `[day]` | `polygon` | `""` |
| `hms-fire` | `fire-frp`: other, `MW`, `[raw]` | `point` | `""` |
| `pesticide-use` | `pounds-applied`: other, `lbs`, `[month, year]`; `acres-treated`: other, `acres`, `[month, year]` | `region` | `""` |
| `pesticide-notices` | `spray-notice`: other, `""`, `[day]` | `point` | `""` |
| `forecasts` | `aqi-forecast`: other, `AQI`, `[day]` | `zone` | `""` |
| `calheatscore` | `heat-score`: other, `""`, `[day]` | `zip` | `""` |
| `calenviroscreen` | `ces-score`: other, `percentile`, `[]` | `tract` | `""` |
| `emissions` | `facility-emissions`: other, `tons/yr`, `[year]` | `point` | `""` |
| `tempo` | one per `tempo` product choice (`no2`, `o3tot`, `hcho`, `cldo4`): pollutant/other per product, product units, `[hour]` | `point`, `region` | `""` |

- **Derived monitor entry types:** for `air-quality`, the union of entry models across all enabled monitor types except CIMIS; for `weather`, CIMIS's. `kind`: `meteorological` if the entry model is defined in `camp.apps.entries.models.meteorological`, `other` for `particulates`, otherwise `pollutant`. `resolutions`: `['raw', 'hour', 'day', 'month', 'quarter', 'season', 'year']` if `entry_model.summarize`, else `['raw']` (resolution list from `BaseSummary.Resolution` values, not a literal). `available` only on air-quality `pollutant` types: `entry_type in available_pollutants()`.
- `meta_url` is a path from `reverse(...)` (e.g. `/api/2.0/monitors/meta/`), or `""`.
- Every dataset and entry type carries `retired: None`.
- `summary_rules = {'complete_after_period_end': ['month', 'quarter', 'season', 'year']}`.
- `source`, `license`, `label`, `description`: short plain strings per dataset (builder writes the copy; name the real upstream sources: SJVAir sensors/AirNow/AQview/AQLite; CIMIS; NOAA HMS; CDPR PUR; SprayDays; SJVAPCD; OEHHA CalHeatScore; OEHHA CalEnviroScreen; CARB/EPA emissions; NASA TEMPO).

- [ ] **Step 1: Write failing tests** in `test_catalog.py`:

```python
class DatasetCatalogTests(TestCase):
    fixtures = ['default-calibrations.yaml']

    def get(self):
        return get_response_data(datasets_view(RequestFactory().get(reverse('api:v2:meta:datasets'))))['data']

    def entry(self, dataset, entry_type):
        ds = next(d for d in self.get()['datasets'] if d['id'] == dataset)
        return next(e for e in ds['entry_types'] if e['id'] == entry_type)

    def test_lists_every_domain(self):
        assert [d['id'] for d in self.get()['datasets']] == list(catalog.DATASET_IDS)
        assert len(catalog.DATASET_IDS) == 11

    def test_no_dataset_level_resolutions(self):
        assert all('resolutions' not in d for d in self.get()['datasets'])

    def test_pm25_is_summarized_and_pm10_is_raw_only(self):
        assert self.entry('air-quality', 'pm25')['resolutions'] == ['raw', 'hour', 'day', 'month', 'quarter', 'season', 'year']
        assert self.entry('air-quality', 'pm10')['resolutions'] == ['raw']

    def test_available_follows_default_calibration(self):
        assert self.entry('air-quality', 'pm25')['available'] is True
        assert self.entry('air-quality', 'no2')['available'] is False
        DefaultCalibration.objects.create(monitor_type='airnow', entry_type='no2', calibration='')
        assert self.entry('air-quality', 'no2')['available'] is True

    def test_temperature_kind(self):
        assert self.entry('weather', 'temperature')['kind'] == 'meteorological'

    def test_retired_present_and_null(self):
        for d in self.get()['datasets']:
            assert d['retired'] is None
            assert all(e['retired'] is None for e in d['entry_types'])

    def test_summary_rules(self):
        assert self.get()['summary_rules'] == {'complete_after_period_end': ['month', 'quarter', 'season', 'year']}
```

- [ ] **Step 2: Run, expect FAIL** (`NoReverseMatch` for `api:v2:meta:datasets`).
- [ ] **Step 3: Implement** `catalog.py` (static dataset definitions as data + the derived monitor entry types), `DatasetCatalogEndpoint(generics.Endpoint)` in `endpoints.py` returning `{'data': get_catalog()}`, docstring stating the never-reuse rule, response header `Cache-Control: public, max-age=300` (computed per request; the only DB work is Task 1's one query, so no server cache that could hide an admin change).
- [ ] **Step 4: Run, expect PASS.** Check `/api/2.0/docs/` still renders (OpenAPI view imports every endpoint).
- [ ] **Step 5: Commit** `feat(api): Add meta/datasets/ dataset catalog`.

### Task 3: Region retirement model and managers

**Files:**
- Modify: `camp/apps/regions/models.py` (`Region`, `Region.Meta`), `camp/apps/regions/managers.py` (`RegionManager`, `import_or_update`)
- Create: migration `camp/apps/regions/migrations/00xx_region_retirement.py`
- Test: `camp/apps/regions/tests/test_retirement.py`

**Interfaces:**
- Produces:
  - `Region.retired_at = DateField(null=True, blank=True, db_index=True)`, `Region.replaced_by = ForeignKey('self', null=True, blank=True, on_delete=SET_NULL, related_name='replaces')`.
  - `Region.all_objects`: unfiltered manager, declared **first**; `Meta.default_manager_name = 'all_objects'` and `Meta.base_manager_name = 'all_objects'` (admin, serialization, related access see every row).
  - `Region.objects`: same `RegionManager` class with `get_queryset()` excluding `retired_at__isnull=False`. Implement as `RegionManager(include_retired=False)` or a `CurrentRegionManager` subclass; both managers keep every `RegionQuerySet` method.
  - `Region.retire(since: date, replaced_by: Region | None = None) -> None`, `Region.unretire() -> None`, property `Region.is_retired -> bool`.
  - `RegionManager.import_or_update` reads and writes through `Region.all_objects` (a retired row is updated, never duplicated, and never un-retired by an import).

- [ ] **Step 1: Write failing tests**:

```python
class RegionRetirementTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.region = Region.objects.filter(type='county').first()

    def test_retired_hidden_from_objects_but_in_all_objects(self):
        self.region.retire(date(2026, 10, 1))
        assert not Region.objects.filter(pk=self.region.pk).exists()
        assert Region.all_objects.filter(pk=self.region.pk).exists()

    def test_default_and_base_managers_include_retired(self):
        self.region.retire(date(2026, 10, 1))
        assert Region._default_manager.filter(pk=self.region.pk).exists()
        assert Region._base_manager.filter(pk=self.region.pk).exists()

    def test_unretire(self):
        self.region.retire(date(2026, 10, 1))
        self.region.unretire()
        assert Region.objects.filter(pk=self.region.pk).exists()
        assert self.region.replaced_by is None

    def test_import_updates_a_retired_row_without_duplicating(self):
        self.region.retire(date(2026, 10, 1))
        region, created = Region.objects.import_or_update(
            name='Renamed', slug='renamed', type=self.region.type, external_id=self.region.external_id,
            geometry=self.region.boundary.geometry, version=self.region.boundary.version)
        assert not created and region.pk == self.region.pk
        assert region.retired_at == date(2026, 10, 1)

    def test_import_never_changes_a_code(self):
        before = set(Region.all_objects.values_list('type', 'external_id'))
        r = self.region
        Region.objects.import_or_update(name=r.name, slug=r.slug, type=r.type, external_id=r.external_id,
            geometry=r.boundary.geometry, version=r.boundary.version)
        assert set(Region.all_objects.values_list('type', 'external_id')) == before
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** fields, managers, `Meta` names, `retire`/`unretire`, and switch `import_or_update`'s `Region.objects` uses to `Region.all_objects`. `makemigrations regions` via `podman-compose -p sjvaircom run --rm web python manage.py makemigrations regions` (from the worktree) and check the migration contains only the two fields, the index, and the manager options.
- [ ] **Step 4: Run, expect PASS**, then run all of `camp/apps/regions/` and `camp/api/v2/regions/`.
- [ ] **Step 5: Commit** `feat(regions): Retire regions instead of deleting them`.

### Task 4: Retired-row audit of existing region call sites

Every place that names a specific region must find it retired or not; every listing and search must skip it.

**Files (audit all; change where the rule says so):** the ~70 files from `grep -rln --include='*.py' "Region.objects" camp | grep -v "/tests\|/migrations"`. Known changes:
- `camp/api/v2/regions/endpoints.py`: `RegionDetail` queryset → `Region.all_objects` (sqid detail keeps working); `RegionList` `within=` parent lookup → `all_objects`.
- `camp/api/v2/{ces,hms,pesticides}/filters.py`, `camp/api/v2/pesticides/{endpoints,sections}.py`, `camp/api/v2/summaries/{forms,endpoints}.py`, `camp/api/v2/tempo/endpoints.py`, `camp/api/v2/emissions/{places,geojson}.py`: where a region is resolved from a request-supplied id → `all_objects`.
- `camp/apps/regions/management/commands/import_*.py` and `management/base.py`: any direct `Region.objects` read/write → `all_objects`.
- `camp/apps/regions/admin.py`: `RegionAdmin` already uses the default manager (now `all_objects`); add `'retired_at'` to `list_filter` (as a "retired" yes/no `SimpleListFilter`) and `retired_at`/`replaced_by` as editable fields, plus actions "Retire today" and "Un-retire". `RegionAdmin` uses `ReadOnlyAdminMixin`: make only these two fields editable.
- `camp/apps/regions/shapes.py`: bump `SHAPES_KEY` version (feature properties change in Task 5).
- Listings (`search_regions`, `resolve_place`, `counties()`, summaries tasks, map config, explorers) keep `Region.objects` (current only). No change needed, but confirm each.

**Interfaces:**
- Consumes: Task 3 managers.
- Produces: the rule above, enforced by tests; an audit list in the commit body (file → "all_objects" or "current only, OK").

- [ ] **Step 1: Write failing tests** (`camp/apps/regions/tests/test_retirement.py`, plus API tests in `camp/api/v2/regions/tests.py`):

```python
def test_detail_by_sqid_finds_retired_region(self):  # API
    region.retire(date(2026, 10, 1))
    response = region_detail(self.factory.get('/'), region_id=region.sqid)
    assert response.status_code == 200

def test_list_and_search_skip_retired(self):  # API
    region.retire(date(2026, 10, 1))
    ids = [r['id'] for r in get_response_data(region_list(self.factory.get('/', {'type': region.type})))['data']]
    assert region.sqid not in ids
    assert region not in Region.objects.search_regions(region.name, type=region.type)

def test_summaries_filter_accepts_retired_region_id(self): ...   # one per filter module named above
def test_admin_changelist_shows_retired(self): ...               # logged-in staff client, 200 and row present
```

- [ ] **Step 2: Run, expect FAIL** for detail/filter tests.
- [ ] **Step 3: Apply the audit.** Review every call site; don't assume.
- [ ] **Step 4: Full suite**: `podman-compose -p sjvaircom --profile test run --rm test pytest -n 4 --dist loadscope 2>&1 | tee <scratchpad>/task4-suite.log | tail -20`. Expect all pass.
- [ ] **Step 5: Commit** `refactor(regions): Resolve named regions through all_objects` with the audit list in the body.

### Task 5: Region codes in responses, lookup by code

**Files:**
- Modify: `camp/api/v2/regions/serializers.py`, `camp/api/v2/regions/filters.py`, `camp/api/v2/regions/endpoints.py` (`RegionList.get`/`get_queryset`), `camp/apps/regions/shapes.py` (`region_feature`)
- Test: `camp/api/v2/regions/tests.py`

**Interfaces:**
- Consumes: Task 3 (`is_retired`, `replaced_by`).
- Produces:
  - `serializers.retired_json(obj) -> dict | None` = `{'since': 'YYYY-MM-DD', 'replaced_by': {'type': …, 'external_id': …} | None}` or `None` (Task 8 reuses it for locations with `{'source', 'external_id'}` for the replacement).
  - `external_id` and `retired` on `RegionSerializer`, `RegionListSerializer`, GeoJSON feature properties, `places/search/`, `places/lookup/`.
  - `GET regions/?type=<type>&external_id=<a,b,…>`: requires `type` (400 `"The type parameter is required with external_id."`), refuses `type=land_use` (400 `"Land-use regions can't be looked up by code yet."`), max 100 codes (400). Searches `Region.all_objects`, so retired rows are returned flagged; unknown codes are absent. Without `external_id`, the list stays current-only.
  - `LOOKUP_MAX_CODES = 100` in `camp/api/v2/regions/filters.py` (Task 8 imports it); a `parse_codes(value: str) -> list[str]` helper beside it (split on commas, strip, drop empties, de-duplicate keeping order).

- [ ] **Step 1: Write failing tests**:

```python
def test_list_fields_include_code_and_retired(self):
    assert set(data['data'][0].keys()) == {'id', 'name', 'slug', 'type', 'boundary', 'external_id', 'retired'}
    # update the existing test_list_fields expectation the same way

def test_lookup_by_several_codes(self):
    counties = list(Region.objects.filter(type='county')[:2])
    codes = ','.join(c.external_id for c in counties)
    data = get(region_list, {'type': 'county', 'external_id': codes})
    assert {r['external_id'] for r in data['data']} == {c.external_id for c in counties}

def test_lookup_cleans_the_list(self):
    c = Region.objects.filter(type='county').first()
    data = get(region_list, {'type': 'county', 'external_id': f' {c.external_id}, ,{c.external_id}'})
    assert [r['external_id'] for r in data['data']] == [c.external_id]

def test_lookup_returns_retired_flagged_and_skips_unknown(self):
    c.retire(date(2026, 10, 1))
    data = get(region_list, {'type': 'county', 'external_id': f'{c.external_id},99999'})
    assert len(data['data']) == 1
    assert data['data'][0]['retired'] == {'since': '2026-10-01', 'replaced_by': None}

def test_lookup_requires_type(self): ...          # 400
def test_lookup_refuses_land_use(self): ...       # 400, message above
def test_lookup_caps_codes(self): ...             # 101 codes → 400
def test_geojson_properties_include_code(self): ...
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** The lookup branch lives in `RegionList.get_queryset`/`get` (it needs `all_objects` and early 400s, which a django-filter method can't return); declare `external_id` on `RegionFilter` as a no-op like `within`, for the OpenAPI schema.
- [ ] **Step 4: Run, expect PASS**, plus `camp/apps/regions/tests/test_shapes.py`.
- [ ] **Step 5: Commit** `feat(api): Expose region codes and look regions up by code`.

### Task 6: CDP that becomes a city

**Files:**
- Modify: `camp/apps/regions/management/commands/import_cities.py`
- Test: `camp/apps/regions/tests/test_regions.py` (or a new `test_import_cities.py`)

**Interfaces:**
- Consumes: `Region.retire(since, replaced_by)`.
- Produces: after a city row is imported, any **current** `cdp` row with the same `external_id` (GEOID) is retired as of the import date with `replaced_by` = that city. Exactly one match → retire; none → nothing. (The `(external_id, type)` uniqueness allows at most one CDP per GEOID.)

- [ ] **Step 1: Write failing test**: create a `cdp` region with GEOID `0612345`, run the import loop's per-row handling with a `C1` row of that GEOID (factor the per-row body into `import_place_row(row) -> Region` so it's testable without CKAN), and assert the CDP `retired_at == today` (Pacific) and `replaced_by == city`. Second test: re-running doesn't change `retired_at`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(regions): Retire a CDP when it incorporates as a city`.

### Task 7: Location permanence (retire, sticky child-care codes, stable grouping)

**Files:**
- Modify: `camp/apps/regions/models.py` (`Location`, `Location.Meta`), `camp/apps/regions/querysets.py` (`LocationQuerySet.one_per_place`, `_same_place`), `camp/apps/regions/locations.py` (`import_source`)
- Modify: `camp/apps/emissions/schools.py` (`CACHE_VERSION = 4`, with the reason in the comment)
- Create: migration `camp/apps/regions/migrations/00xx_location_retirement.py`
- Test: `camp/apps/regions/tests/test_import_locations.py`, `camp/apps/regions/tests/test_locations.py`

**Interfaces:**
- Consumes: the manager pattern from Task 3 (same shape: `all_objects` first and default/base; filtered `objects` keeps `LocationQuerySet` methods).
- Produces:
  - `Location.retired_at`, `Location.replaced_by` (self-FK), `retire()`, `unretire()`, `is_retired`, `Location.all_objects`.
  - `import_source` counts gain `'retired'` and `'unretired'`; `'removed'` stays in the dict at 0 (callers print it).
  - `Location.facility_numbers -> list[str]` property: `metadata.get('facility_numbers') or []`.
  - `one_per_place()` chooses the lowest `external_id` per group (facility numbers are fixed-width digit strings, so string order is numeric order; assert that in a test).

**Import algorithm (pinned):**
1. `existing = Location.all_objects.filter(source=source)`; build `by_code = {row.external_id: row}` and `by_license = {n: row for row in existing for n in row.facility_numbers}`.
2. For each parsed row (in file order, sorted by its own lowest number for determinism): candidates = rows found by its `external_id` in `by_code` or any of `metadata['facility_numbers']` in `by_license`/`by_code`. Drop candidates already claimed this run. If one remains, prefer the candidate whose code is among the row's numbers, else the lowest code; set the parsed row's `external_id` to that candidate's code and mark it claimed. Otherwise keep the parsed code (a new row; if that code is already claimed, which can only happen on a split, use the parsed row's next-lowest unclaimed number).
3. Upsert as today, via `all_objects`. A row that was retired and is now seen: `unretire()`, count `unretired`.
4. Instead of `stale.delete()`: rows of this source not seen and not retired → `retire(today_pacific)`, count `retired`. Keep the "empty parse changes nothing" guard.

- [ ] **Step 1: Write failing tests**:

```python
def test_missing_rows_are_retired_not_deleted(self): ...       # replaces test_rows_missing_from_the_source_are_removed
def test_a_retired_row_that_reappears_is_unretired_in_place(self):
    # import with X, import without X (retired), import with X again → same pk, retired_at None, counts['unretired'] == 1
def test_child_care_keeps_its_code_when_the_lowest_license_closes(self):
    # file 1: licenses 105 + 210 at one site → code '105'
    # file 2: only 210 → still one row, pk unchanged, external_id '105', facility_numbers == ['210']
def test_a_split_site_keeps_one_code_and_the_other_gets_its_own(self):
    # file 1: 105 + 210 (one site); file 2: 105 at old address, 210 at a new address (two sites)
    # → the 105 site keeps '105'; the 210 site is a new row '210'; no IntegrityError
def test_one_per_place_picks_lowest_code_not_pk(self):
    # create two same-name child-care rows within SAME_PLACE_DEGREES, the higher code first (lower pk)
    # → one_per_place() returns the row with the lower code
def test_retired_locations_are_hidden_from_objects(self): ...
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** fields, managers, migration, `one_per_place` (`external_id__lt=OuterRef('external_id')` in place of `pk__lt`), the import algorithm, and the `CACHE_VERSION` bump. Then grep the ~12 Location call sites (`grep -rln --include='*.py' "Location.objects\|\.locations()\|_locations\b\|location_q" camp`): listings stay current-only; anything resolving a location from a request id moves to `all_objects`. Reverse relations like `region.county_locations` use the base manager (all rows), so check `camp/apps/pesticides/places.py`, `camp/apps/emissions/schools.py`, and `camp/apps/emissions/wells.py` for reverse-relation listings and add `retired_at__isnull=True` where they list.
- [ ] **Step 4: Run** `camp/apps/regions/`, `camp/apps/pesticides/`, `camp/apps/emissions/`, `camp/api/v2/pesticides/`, `camp/api/v2/emissions/`. Expect PASS.
- [ ] **Step 5: Commit** `feat(regions): Retire closed locations and keep child-care codes stable`.

### Task 8: Location lookup by code `GET /api/2.0/regions/locations/`

**Files:**
- Modify: `camp/api/v2/regions/urls.py` (add `path('locations/', …, name='location-list')` **before** `<entry_type>/summaries/` and `<region_id>/`), `camp/api/v2/regions/endpoints.py`, `camp/api/v2/regions/serializers.py`
- Test: `camp/api/v2/regions/tests.py`

**Interfaces:**
- Consumes: `parse_codes`, `LOOKUP_MAX_CODES`, `retired_json` (Task 5); `Location.all_objects`, `facility_numbers` (Task 7).
- Produces: `GET regions/locations/?source=<source>&external_id=<a,b,…>` → `{'data': [LocationSerializer…]}`. Both params required (400 otherwise); `source` must be a key of `camp.apps.regions.locations.SOURCES` (400). A code matches a row's `external_id` **or** any of its `facility_numbers` (JSON containment, one `Q` per code). `LocationSerializer` fields: `id` (sqid), `source`, `external_id`, `aliases` (the row's facility numbers other than its code; `[]` for schools), `type`, `name`, `address`, `city_name`, `zip`, `point` (`{'lat', 'lng'}`), `regions` (`{'county'|'city'|'zipcode'|'school_district': {'type', 'external_id'} | None}`), `retired`.

- [ ] **Step 1: Write failing tests**: lookup by code; lookup by a non-key license number returns the site (with `aliases` containing it); retired row returned flagged; unknown absent; missing params 400; unknown source 400; >100 codes 400; `regions/locations/` isn't swallowed by `<region_id>/` (status 200, not 404).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** `select_related('county', 'city', 'zipcode', 'school_district')`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(api): Look up schools and child-care sites by code`.

### Task 9: Coverage `GET /api/2.0/meta/coverage/`

**Files:**
- Create: `camp/api/v2/meta/coverage.py`, `camp/api/v2/meta/tests/test_coverage.py`
- Modify: `camp/api/v2/meta/endpoints.py`, `camp/api/v2/meta/urls.py`

**Interfaces:**
- Consumes: `catalog.DATASET_IDS`, `catalog.dataset_entry_types()` (Task 2); `available_pollutants()` (Task 1); `Region.all_objects` (Task 3).
- Produces:
  - `coverage.Span = TypedDict('Span', {'first': date | None, 'last': date | None})`.
  - `coverage.dataset_span(dataset_id: str, entry_type: str | None) -> Span`.
  - `coverage.monitor_span(monitor: Monitor, entry_type: str) -> Span`.
  - `coverage.region_span(region: Region, entry_type: str) -> Span`.
  - Endpoint response: `{'data': {'dataset', 'entry_type', 'monitor' | 'region': {'type','external_id'} (when given), 'first': 'YYYY-MM-DD' | None, 'last': … }}`; `Cache-Control: public, max-age=900`; server-side `CachedEndpointMixin` with `cache_timeout = 900`.

Rules (pinned):
- Timestamps → Pacific date via `timezone.localtime(ts, settings.DEFAULT_TIMEZONE).date()`.
- **Monitor span:** entry model from `entry_type`. If `(monitor.monitor_type, entry_type)` is published, filter to the `DefaultCalibration` processor; else any stage/processor. `first` = `MIN(timestamp)` over `entry_model.objects.filter(monitor=monitor, …)`; `last` = matching `LatestEntry.timestamp` (fallback: `MAX` with the same filter).
- **Region span:** `RegionSummary` `resolution='hour'`, `region`, `entry_type`: `MIN`/`MAX(timestamp)`. Entry types with `summarize = False` → 400 (regions have no raw data).
- **Dataset span:** `air-quality`: `MonitorSummary` `resolution='hour'` with `entry_type` = the given one, or `__in=available_pollutants()` if omitted; `MIN`/`MAX`. An unsummarized `entry_type` at dataset level → 400 `"pm10 has no dataset-level coverage; ask for a monitor."`. `weather`: `MIN` per CIMIS monitor (index-backed loop over CIMIS monitors) and `MAX` from `LatestEntry` for CIMIS monitors. Other datasets: `MIN`/`MAX` of the domain's date field **only if** it is indexed or the table is small (< 100k rows); otherwise the domain's rollup/years table (e.g. pesticide rollups, `emissions` years). Check each with `EXPLAIN` and list the choice per dataset in the commit body. `calenviroscreen` (static) returns nulls.
- **Request validation:** unknown `dataset` → 400; `monitor` and `region` both given → 400; a place without `entry_type` → 400; a place with a non-monitor dataset → 400 (not supported this round); unknown monitor id → 404; `region_type` + `region` (code) resolved through `Region.all_objects` (retired regions answer), `land_use` → 400, unknown → 404.

- [ ] **Step 1: Write failing tests** (fixtures: `purple-air.yaml`, `regions.yaml`, `default-calibrations.yaml`; create entries and summaries in the test):

```python
def test_monitor_span_uses_published_processor_and_pacific_dates(self):
    # raw entry at 2026-01-01 08:00 UTC, calibrated (published processor) at 2026-01-02 07:30 UTC
    span = coverage.monitor_span(monitor, 'pm25')
    assert span == {'first': date(2026, 1, 1), 'last': date(2026, 1, 1)}  # 07:30 UTC = Jan 1 Pacific

def test_monitor_with_no_data_returns_nulls(self): ...          # endpoint 200, nulls
def test_unknown_monitor_404(self): ...
def test_region_by_code_including_retired(self): ...
def test_region_unknown_code_404(self): ...
def test_dataset_span_defaults_to_available_pollutants(self): ...
def test_dataset_level_pm10_is_400(self): ...
def test_monitor_span_query_count(self):
    with self.assertNumQueries(2):   # MIN + LatestEntry
        coverage.monitor_span(monitor, 'pm25')
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.** Then on the local dev database (realistic size), `EXPLAIN` the monitor `MIN` query for a busy PurpleAir monitor and the dataset `MonitorSummary` query; both must show an index scan, not a seq scan. Paste the plans in the commit body.
- [ ] **Step 5: Commit** `feat(api): Add meta/coverage/ endpoint`.

### Task 10: Server accepts zone-aware timestamps (sdk-js time-zone fix, server side)

**Files:**
- Test: `camp/api/v2/monitors/tests/test_endpoints.py` (or the filters test module)

**Interfaces:**
- Produces: tests proving `timestamp__gte`/`timestamp__lte` (via `TimezoneDateTimeFilter`) and `at/`'s `timestamp` (`MonitorAtForm`) accept `2026-10-22T07:00:00Z` and `2026-10-22T00:00:00-07:00` (URL-encoded) and treat them as that instant. If either fails, fix the parsing in `camp/api/v2/filters.py` / `camp/api/v2/monitors/forms.py` (Python 3.14 `fromisoformat` handles both forms, so expect only tests).

- [ ] **Step 1: Write the tests** (entries at 06:59Z and 07:01Z; `timestamp__gte=2026-10-22T07:00:00Z` returns only the second; the offset form gives the same result; a zone-less `2026-10-22 00:00:00` is still read as Pacific).
- [ ] **Step 2: Run.** Expect PASS; if FAIL, fix the parser and rerun.
- [ ] **Step 3: Commit** `test(api): Pin zone-aware timestamp filters`.

### Task 11 (sjvair.com wrap-up): docs, full suite, PR

- [ ] **Step 1:** Add a "Region and location codes" section to `CLAUDE.md` (the never-reuse rule, `all_objects` vs `objects`, land use excluded, imports retire instead of delete) and a short "Metadata endpoints" note (`meta/datasets/`, `meta/coverage/`, available pollutants come from `DefaultCalibration`).
- [ ] **Step 2: Full suite**: `podman-compose -p sjvaircom --profile test run --rm test pytest -n 4 --dist loadscope 2>&1 | tee <scratchpad>/final-suite.log | tail -30`. All pass.
- [ ] **Step 3:** Commit `docs: Document region codes and metadata endpoints`; push; open a PR into `develop` (`gh pr create --base develop`). PR body: summary, and **deploy steps**: (1) migrate; (2) on production, `python manage.py import_forecast_zones` (the 3 `custom` zones are missing there). No AI attribution.

## sdk-js

All sdk-js tasks run on `feature/metadata-enablers` in `~/workspace/sjvair/sdk-js`. Integration tests need the local server from the sjvair.com branch: run `podman-compose -p sjvaircom --profile web up -d` **from the sjvair.com worktree** so the web container serves this branch, and migrate. Follow the module layout in sdk-js `CLAUDE.md` (`mod.ts`, `types.ts`, `schemas/`, `mod_test.ts`, JSDoc `@example` on every export, `RequestOptions` as the last parameter, `deno.json` `exports` entries for new files).

### Task 12: Pacific-aware date bounds (sdk-js time-zone fix)

**Files:**
- Create: `lib/datetime/pacific.ts`, `lib/datetime/to_api_timestamp.ts`
- Modify: `lib/datetime/get_valid_date_range.ts`, `lib/datetime/mod.ts`, `lib/datetime/api_date_format.ts` (JSDoc: mark `@deprecated`, kept unchanged for existing callers), `lib/monitors/get_monitor_entries.ts`, `lib/monitors/get_monitor_entries_csv.ts`, `lib/monitors/get_monitors.ts`, `deno.json` exports
- Test: `lib/datetime/mod_test.ts`

**Interfaces:**
- Produces:
  - `toApiTimestamp(date: Date | number | string): string`: UTC ISO 8601 with `Z`, millisecond precision (`date.toISOString()` after validation; throws on an invalid date with the existing message).
  - `startOfPacificDay(date: Date): Date`, `endOfPacificDay(date: Date): Date` (23:59:59.999 Pacific), `addPacificDays(date: Date, days: number): Date`. Use `Intl.DateTimeFormat('en-US', { timeZone: 'America/Los_Angeles', … })` to read Pacific wall-clock parts and compute the offset; no new dependency. Must be DST-correct.
  - `getValidDateRange` keeps its signature and defaults (last 3 days to end of today) but snaps with the Pacific helpers, and **no longer throws for a bound later than now**.
  - Callers send `toApiTimestamp(...)` for `timestamp__gte`, `timestamp__lte`, and `at/`'s `timestamp`.

- [ ] **Step 1: Write failing tests** run under several zones:

```ts
Deno.test("endOfPacificDay is 23:59:59.999 Pacific in any device zone", () => {
  assertEquals(endOfPacificDay(new Date("2026-10-22T12:00:00Z")).toISOString(), "2026-10-23T06:59:59.999Z");
});
Deno.test("startOfPacificDay across DST end (2026-11-01)", () => {
  assertEquals(startOfPacificDay(new Date("2026-11-01T20:00:00Z")).toISOString(), "2026-11-01T07:00:00.000Z");
  assertEquals(startOfPacificDay(new Date("2026-11-02T20:00:00Z")).toISOString(), "2026-11-02T08:00:00.000Z");
});
Deno.test("toApiTimestamp sends UTC with Z", () => {
  assertEquals(toApiTimestamp(new Date("2026-10-22T07:00:00Z")), "2026-10-22T07:00:00.000Z");
});
Deno.test("getValidDateRange accepts an end later than now", () => {
  const end = new Date(Date.now() + 6 * 3600_000);
  assertEquals(getValidDateRange(undefined, end).lte.getTime() >= end.getTime() - 1, true);
});
```

- [ ] **Step 2: Run** `TZ=Pacific/Auckland deno test lib/datetime/mod_test.ts`, `TZ=UTC …`, and `TZ=America/Los_Angeles …`. Expect FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all three zones**, expect PASS; then `deno test --allow-net --allow-env lib/monitors/mod_test.ts` against the local server (entries and `at/` still return data).
- [ ] **Step 5: Commit** `fix(datetime): Send zone-aware bounds and snap days in Pacific time`.

### Task 13: Catalog and available pollutants wrappers

**Files:**
- Create: `lib/meta/mod.ts`, `lib/meta/get_dataset_catalog.ts`, `lib/meta/schemas/dataset_catalog.ts`, `lib/meta/types.ts`, `lib/meta/mod_test.ts`
- Modify: `lib/monitors/schemas/` (monitors meta schema gains `available_pollutants: z.array(z.string())`), `mod.ts`, `deno.json` exports (`./meta`, `./meta/get_dataset_catalog`, `./meta/types`)

**Interfaces:**
- Consumes: Task 2 response shape.
- Produces: `getDatasetCatalog(options?: RequestOptions): Promise<DatasetCatalog>`; types `DatasetCatalog`, `DatasetCatalogEntry`, `DatasetEntryType`, `Retired`, `Resolution`, `Geography`. Fields keep the server's snake_case names, matching existing SDK types.

- [ ] **Step 1: Failing integration test**: `validate(datasetCatalogSchema)` on the response; `air-quality` → `pm25.available === true`; `pm10.resolutions` deep-equals `["raw"]`; `getMonitorsMeta()` has `available_pollutants` including `"pm25"`.
- [ ] **Step 2: Run, expect FAIL.** **Step 3: Implement.** **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(meta): Add getDatasetCatalog and available pollutants`.

### Task 14: Region and location codes

**Files:**
- Modify: `lib/regions/schemas/region.ts` (both schemas gain `external_id: z.nullable(z.string())`, `retired: z.nullable(retiredRegionSchema)`), `lib/regions/get_regions_list.ts`, `lib/regions/mod.ts`, `lib/regions/types.ts`
- Create: `lib/regions/get_regions_by_code.ts`, `lib/regions/get_locations_by_code.ts`, `lib/regions/schemas/location.ts`
- Modify: `deno.json` exports, `api-urls.md`

**Interfaces:**
- Consumes: Tasks 5 and 8 response shapes.
- Produces: `getRegionsByCode(type: RegionType, codes: string[], options?: RequestOptions): Promise<RegionListItem[]>` (throws before calling if `codes.length > 100` or `type === "land_use"`); `getLocationsByCode(source: LocationSource, codes: string[], options?: RequestOptions): Promise<Location[]>`; types `Location`, `LocationSource` (`"cde-public" | "cde-private" | "cdss-ccl"`), `RegionRetired`, `LocationRetired`.

- [ ] **Step 1: Failing integration tests**: a county from `getRegionsList({type:"county"})` round-trips through `getRegionsByCode("county", [c.external_id!])`; an unknown code returns `[]`; `land_use` throws; locations: a `cdss-ccl` row round-trips (skip with a note if the local DB has none, per the repo's existing skip pattern).
- [ ] **Step 2: Run, expect FAIL.** **Step 3: Implement**; update `api-urls.md` for `regions/?external_id=`, `regions/locations/`, `meta/datasets/`, `meta/coverage/`. **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(regions): Look up regions and locations by official code`.

### Task 15: Coverage wrapper, then PR

**Files:**
- Create: `lib/meta/get_coverage.ts`, `lib/meta/schemas/coverage.ts`
- Modify: `lib/meta/mod.ts`, `lib/meta/types.ts`, `deno.json`

**Interfaces:**
- Consumes: Task 9 response shape.
- Produces: `getCoverage(query: CoverageQuery, options?: RequestOptions): Promise<Coverage>` where `CoverageQuery = { dataset: string; entry_type?: string; monitor?: string; region?: { type: RegionType; external_id: string } }` and `Coverage = { dataset: string; entry_type: string | null; first: string | null; last: string | null; … }` (dates as `YYYY-MM-DD` strings; the SDK doesn't turn them into `Date`, since they're Pacific calendar dates).

- [ ] **Step 1: Failing integration test**: dataset-level `air-quality` returns `first <= last` or nulls; a `TEST_MONITOR_ID` + `pm25` query validates; passing both `monitor` and `region` throws before the request.
- [ ] **Step 2: Run, expect FAIL.** **Step 3: Implement.** **Step 4: Run** the whole SDK suite: `deno test --allow-net --allow-env` and `deno lint`, `deno fmt --check`. All pass.
- [ ] **Step 5: Commit** `feat(meta): Add getCoverage`; push; open a PR into sdk-js `main`. **Do not bump the version or publish**; tell the user the release is the next step and wait for their explicit approval.
