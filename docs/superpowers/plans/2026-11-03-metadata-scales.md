# Metadata Scales (Step 3 Spec 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve every data scale (AQ, AQI, heat, smoke, fire, burn status) in one shape with a 0–4 `tier`, plus region hierarchy, display hints, stage/processor labels, place-aware heat and forecast endpoints, and the sdk-js wrappers for all of it.

**Architecture:** A small `camp/utils/scales.py` defines the shared `Scale`/`ScaleLevel` and its JSON. `entries/levels.py` gains tiers and EPA descriptions and converts each `LevelSet` to a `Scale`; each domain adds a `…/meta/` endpoint that returns its scales keyed by catalog entry-type id. A `camp/apps/regions/resolve.py` module resolves "a place" (region by code, or monitor) and answers "which ZIPs" and "which forecast zone" with caching; new `calheatscore/place/` and `forecasts/place/` endpoints use it. sdk-js mirrors each endpoint with zod schemas and wrappers.

**Tech Stack:** Django 4 + PostGIS + django-resticus (sjvair.com); Deno 2 + zod (sdk-js).

**Spec:** `docs/superpowers/specs/2026-11-03-metadata-scales-design.md` (this worktree). Read it first; this plan argues from it.

## Global Constraints

- sjvair.com: work in `/home/alex/workspace/sjvair/sjvair.com/.worktrees/metadata-scales`, branch `feature/metadata-scales` (from `origin/develop`); PR into `develop`; never merge without the user's yes.
- sdk-js: worktree `/home/alex/workspace/sjvair/sdk-js/.worktrees/metadata-scales`, branch `feature/metadata-scales` from `origin/release/4.8.0`; PR into `release/4.8.0`. **Never push a `v*` tag, publish, or bump the beta without the user's explicit yes for that release.** Don't build on `@sjvair/sdk/documents`.
- No Claude/AI attribution in commits, PRs, or docs. Commit messages: plain imperative sentence.
- Tests: `django.test.TestCase`, pytest-style `assert`, fixtures from `/fixtures/*.yaml` (`regions.yaml`, `calheatscore.yaml` exist).
- Test command (`$TEST` below), run from the worktree (copy `.env` and `.env.test` from the main checkout first):
  `podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token -v $PWD:/app:z -w /app sjvair-com-test:latest pytest`
  (a "not a git repository" line from a worktree is harmless). One suite at a time.
- **No breaking change** to `monitors/meta/`'s existing `levels` dict (uppercase keys, `name`, `label`, `color`, `range` with "next minus 0.1", `guidance`): only add `tier`.
- Ids are permanent: scale ids = catalog entry-type ids; level `key`s are permanent.
- Range levels are half-open: `min <= value < max`; the top level's `max` is `null`.
- `guidance` is empty (`""`) for AQ Good and heat Low.
- Region lookups by code use `Region.all_objects` (retired regions still answer); `type=land_use` is refused with `"Land-use regions can't be looked up by code yet."`.
- Never run an unscoped management command against the local DB; this plan needs none.
- Docs-only commits need no PR: push to the branch being worked on, or data-dashboard `main` for its docs.

## Review Focus

1. **A value exactly on a breakpoint, or above the top level** → the half-open rule puts 9.1 µg/m³ PM2.5 in Moderate, and 600 in Hazardous (top `max` null). Test in Task 1.
2. **A retired region's code** given to `calheatscore/place/` or `forecasts/place/` → still answers. Test in Task 7.
3. **A ZIP or area with no heat rows, or a place outside every forecast zone** → `200` with empty `data` (`zone: null`), never 500. Tests in Tasks 8 and 9.
4. **A monitor with no position** given to a place endpoint → `400` "Monitor has no location.", not 500. Test in Task 7.
5. **A burn status the feed sends that isn't in the scale** → stored, served as-is, logged once per value per run. Test in Task 5.

---

## Server (sjvair.com)

### Task 0: Worktree setup and baseline

**Files:** none committed.

- [ ] **Step 1:** `cp /home/alex/workspace/sjvair/sjvair.com/.env /home/alex/workspace/sjvair/sjvair.com/.env.test .` in the worktree.
- [ ] **Step 2:** Run `$TEST -n 4 --dist loadscope`. Expected: all pass (record the count; later runs must not drop below it).

### Task 1: Shared scale shape and AQ tiers

**Files:**
- Create: `camp/utils/scales.py`
- Modify: `camp/apps/entries/levels.py` (`Level`, `AQLevelMeta._levels`, `LevelSet`)
- Test: `camp/apps/entries/tests/test_scales.py`

**Interfaces:**
- Produces:
  - `ScaleLevel` frozen dataclass: `key: str, label: str, color: str | None, tier: int | None, description: str = '', guidance: str = '', min: float | None = None, max: float | None = None, value: str | int | None = None, opacity: float | None = None`.
  - `Scale` frozen dataclass: `id: str, label: str, units: str, kind: Literal['range', 'category'], levels: tuple[ScaleLevel, ...], source: dict | None = None` (`{'name': str, 'url': str}`), method `to_json() -> dict`.
  - JSON: `{id, label, units, kind, source, levels: [{key, label, color, opacity, tier, description, guidance, min, max, value}]}`. Every level carries every key; unused ones are `null` (`description`/`guidance` are `""` when empty).
  - `LevelSet.to_scale(id: str, label: str, units: str) -> Scale` (range scale, source `EPA_SOURCE`).
  - `levels.EPA_SOURCE = {'name': 'US EPA AirNow, AQI Basics', 'url': 'https://www.airnow.gov/aqi/aqi-basics/'}`.
  - `Level` gains `tier: int | None = None` and `description: str = ''`; `LevelSet.as_dict()` adds `'tier'` to each entry and changes nothing else.

- [ ] **Step 1: Write the failing tests** in `test_scales.py`:
  - `test_as_dict_keeps_shape_and_adds_tier`: `levels.PM25.as_dict()['MODERATE']` equals `{'name': 'moderate', 'label': 'Moderate', 'color': '#ffff00', 'range': (9.1, 35.4), 'guidance': <existing text>, 'tier': 1}`.
  - `test_aq_tiers`: tiers by key across all of `PM25, PM100, CO, NO2, O3, SO2, AQI`: good 0, moderate 1, unhealthy_sensitive 2, unhealthy 3, very_unhealthy 4, hazardous 4, very_hazardous 4.
  - `test_to_scale_half_open`: `s = levels.PM25.to_scale('pm25', 'PM2.5', 'µg/m³')`; `s.kind == 'range'`; level `good` has `min 0.0, max 9.1`; `hazardous` has `min 225.5, max None`; a helper `level_for(s, 9.1).key == 'moderate'`, `level_for(s, 9.0999).key == 'good'`, `level_for(s, 600).key == 'hazardous'` (helper lives in the test: first level with `min <= v` and (`max is None` or `v < max`)).
  - `test_scale_and_dict_agree`: for every LevelSet above, each `as_dict()` entry's `range[0]`, `color`, `label`, `tier` equal the matching `to_scale()` level's `min`, `color`, `label`, `tier`.
  - `test_epa_descriptions`: `good.description == "Air quality is satisfactory, and air pollution poses little or no risk."` and `good.guidance == ""`; `very_hazardous.description == hazardous.description`.
  - `test_to_json_keys`: `set(s.to_json()['levels'][0]) == {'key','label','color','opacity','tier','description','guidance','min','max','value'}`; `s.to_json()['source'] == levels.EPA_SOURCE`.
- [ ] **Step 2:** `$TEST camp/apps/entries/tests/test_scales.py -v` → FAIL (no module / no attribute).
- [ ] **Step 3: Implement.** In `AQLevelMeta._levels` add `tier` and `description` per level; the generated `Level` carries both. EPA descriptions, verbatim:
  - good: `Air quality is satisfactory, and air pollution poses little or no risk.`
  - moderate: `Air quality is acceptable. However, there may be a risk for some people, particularly those who are unusually sensitive to air pollution.`
  - unhealthy_sensitive: `Members of sensitive groups may experience health effects. The general public is less likely to be affected.`
  - unhealthy: `Some members of the general public may experience health effects; members of sensitive groups may experience more serious health effects.`
  - very_unhealthy: `Health alert: The risk of health effects is increased for everyone.`
  - hazardous and very_hazardous: `Health warning of emergency conditions: everyone is more likely to be affected.`
  Set Good's `guidance` to `''` (today `None`; `as_dict` must still emit `None` for Good to stay byte-compatible, so normalize only in `to_scale`). `to_scale` sorts by `value`, sets `max` to the next level's `value`.
- [ ] **Step 4:** Re-run → PASS. Also `$TEST camp/apps/entries camp/api/v2/monitors -q` → PASS.
- [ ] **Step 5:** Commit: `Add the shared scale shape and AQ tiers`.

### Task 2: `monitors/meta/` serves `scale` per entry type

**Files:**
- Modify: `camp/api/v2/monitors/endpoints.py` (`MonitorMetaEndpoint.get_entries`)
- Test: `camp/api/v2/monitors/tests/test_meta_scales.py`

**Interfaces:**
- Consumes: `LevelSet.to_scale` (Task 1).
- Produces: `entries[<entry_type>].scale` = `Scale.to_json()` with `id = entry_type`, `label = entry_model.label`, `units = entry_model.units or ''`; `null` when `entry_model.Levels` is `None`. `levels` unchanged plus `tier`.

- [ ] **Step 1: Failing tests:** `test_pm25_scale_present` (`data.entries.pm25.scale.id == 'pm25'`, 6 levels, first `tier == 0`); `test_levels_dict_unchanged` (`data.entries.pm25.levels.GOOD` keys == `{'name','label','color','range','guidance','tier'}`); `test_scale_null_without_levels` (`data.entries.humidity.scale is None`).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Add `'scale'` next to `'levels'` in `get_entries`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `Serve the shared scale for each entry type in monitors/meta`.

### Task 3: Stage and processor labels (approval gate)

**Files:**
- Modify: `camp/apps/entries/stages.py` (add `STAGE_DESCRIPTIONS: dict[str, str]`)
- Modify: `camp/apps/calibrations/core/processors/base.py` (`BaseProcessor.label: str = ''`, `BaseProcessor.description: str = ''`)
- Modify: every concrete processor under `camp/apps/calibrations/core/processors/` (set `label`, `description`)
- Modify: `camp/api/v2/monitors/endpoints.py` (`MonitorMetaEndpoint.get`)
- Test: `camp/api/v2/monitors/tests/test_meta_labels.py`

**Interfaces:**
- Produces in `monitors/meta/` `data`: `stages: {<stage>: {key, label, description}}` for all four stages; `processors: {<name>: {key, label, description}}` for every processor named in any enabled monitor type's `ENTRY_CONFIG` (`label` falls back to `name` when empty).

- [ ] **Step 1: Failing tests:** `test_stages_listed` (keys == `{'raw','corrected','cleaned','calibrated'}`, each `label` non-empty); `test_processors_listed` (`'PM25_EPA_Oct2021' in data.processors`; every processor in any `monitors.*.entries.*.processors` list is a key); `test_every_processor_has_label` (no `label` equals its `key`, i.e. all are written).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Draft the texts.** Read each processor's code and docstring and write a short plain-language `label` (≤ 40 chars, e.g. "EPA correction (Oct 2021)") and one-sentence `description` of what it does to the data; same for the four stages. Put them in the code.
- [ ] **Step 4: STOP for the user's approval.** Show the user a table of every stage and processor `key → label — description`. Apply their edits. Do not commit before they approve.
- [ ] **Step 5:** Implement the meta fields; run → PASS.
- [ ] **Step 6:** Commit: `Label stages and processors in monitors/meta`.

### Task 4: `calheatscore/meta/` and `hms/meta/`

**Files:**
- Create: `camp/apps/calheatscore/scales.py`, `camp/apps/hms/scales.py`
- Modify: `camp/api/v2/calheatscore/{endpoints,urls}.py`, `camp/api/v2/hms/{endpoints,urls}.py`
- Test: `camp/api/v2/calheatscore/tests.py`, `camp/api/v2/hms/tests.py` (extend)

**Interfaces:**
- Consumes: `Scale`, `ScaleLevel` (Task 1).
- Produces: `GET calheatscore/meta/` → `{data: {scales: {'heat-score': Scale}}}`, URL name `calheatscore-meta`; `GET hms/meta/` → `{data: {scales: {'smoke-density': Scale, 'fire-frp': Scale}}}`, URL name `hms-meta`. Both `Cache-Control: public, max-age=3600`. Routes go **before** `<str:zipcode>/` / `<smoke_id>/`.

  Heat (`kind: category`, `value` = score int, source `{'name': 'CalHeatScore (CalEPA / OEHHA)', 'url': 'https://calheatscore.calepa.ca.gov/'}`): keys `low, mild, moderate, high, severe`; labels from `CalHeatScore.Score`; tiers 0–4; colors `#dedede, #fae0c8, #ea8753, #c23a00, #700006`; descriptions verbatim:
  - 0: `Little to no heat-related health impacts are expected.`
  - 1: `Warm day. A minor increase in heat-related health impacts is expected among those sensitive to heat.`
  - 2: `Very warm day. A moderate increase in heat-related health impacts is expected among those sensitive to heat.`
  - 3: `Hot day. An increase in heat-related health impacts is expected for everyone, especially those without access to adequate cooling and hydration or those engaged in strenuous physical activity outdoors. This level of heat can pose a significant risk to health.`
  - 4: `Extreme heat day. A major increase in heat-related health impacts is expected for everyone, especially those without access to adequate cooling and hydration or those engaged in strenuous physical activity outdoors. This level of heat can pose a very serious risk to health.`
  Guidance: the spec's approved table (0 empty).

  Smoke (`kind: category`, `value` = `Smoke.Density` value, source `{'name': 'NOAA Hazard Mapping System', 'url': 'https://www.ospo.noaa.gov/products/land/hms.html'}`): `light` (`#bfc8c3`, opacity 0.2, tier 1), `medium` (`#757b78`, 0.3, tier 2), `heavy` (`#333634`, 0.4, tier 3); descriptions and guidance empty.
  Fire (`kind: range`, units `MW`, same source): `sm` [0,10) `#FFD700`, `md` [10,50) `#FF8C00`, `lg` [50,150) `#FF4500`, `xl` [150,350) `#DC143C`, `xxl` [350,null) `#8B0000`; labels `<10`, `10–49`, `50–149`, `150–349`, `≥350`; `tier: null`; opacity null.

- [ ] **Step 1: Failing tests:** `test_heat_meta` (5 levels, tiers 0..4, level 3 color `#c23a00`, level 0 guidance `""`, level 4 guidance starts `"Everyone should stay somewhere cool"`); `test_hms_meta_smoke_opacity` (heavy opacity 0.4, tier 3); `test_hms_meta_fire_tierless` (all tiers `None`, last `max is None`); `test_meta_routes_not_shadowed` (`calheatscore/meta/` returns the scale, not ZIP "meta").
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `Add calheatscore and hms meta endpoints with their scales`.

### Task 5: `forecasts/meta/` and unknown burn statuses

**Files:**
- Create: `camp/apps/forecasts/scales.py`
- Modify: `camp/api/v2/forecasts/{endpoints,urls}.py`, `camp/apps/forecasts/tasks.py`
- Test: `camp/api/v2/forecasts/tests.py`, `camp/apps/forecasts/tests.py` (extend)

**Interfaces:**
- Consumes: `levels.AQI.to_scale` (Task 1), `ZONE_TO_REGION` (tasks.py).
- Produces: `GET forecasts/meta/` (URL name `forecast-meta`, before `<forecast_id>/`) → `{data: {scales: {'aqi-forecast': Scale, 'burn-status': Scale}, zones: [{name, region: {id, type, external_id, name}}]}}` (`region` null when that zone's Region isn't imported). `BURN_STATUS_VALUES: set[str]` in `forecasts/scales.py`.

  AQI: `levels.AQI.to_scale('aqi-forecast', 'AQI Forecast', 'AQI')`.
  Burn status (`kind: category`, `tier: null`, source `{'name': 'San Joaquin Valley APCD, Check Before You Burn', 'url': 'https://ww2.valleyair.org/'}`), `value` = the feed's `status` attribute as stored in `Forecast.burn_status`:
  - `discouraged`: value `Discouraged`, label `Burning Discouraged`, `#ffff00`
  - `registered`: value `Registered`, label `No Burning Unless Registered`, `#ff7e00`
  - `no_burning`: label `No Burning For All`, `#ff0000`, value **to confirm**: find the feed's `status` attribute for this case (Valley Air docs or an archived feed). If it can't be confirmed, leave this level out, rely on the fallback below, and say so in the PR.
  Descriptions and guidance empty.

- [ ] **Step 1: Failing tests:** `test_forecast_meta_scales` (AQI 6 levels, `hazardous.max is None`; burn status tiers all `None`); `test_forecast_meta_zones` (9 zones listed with `fixtures = ['regions.yaml']`; a missing custom zone has `region: None`); `test_unknown_burn_status_stored_and_logged` (feed a sample with `status="Prohibited"`: the Forecast row stores `Prohibited`, and `assertLogs('camp.apps.forecasts.tasks', 'WARNING')` captures one message naming it).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (warn in the ingest loop when `burn_status` isn't in `BURN_STATUS_VALUES`, once per value per run). **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `Add forecasts meta with the AQI and burn status scales`.

### Task 6: Catalog: burn-status, display hints, meta URLs

**Files:**
- Modify: `camp/api/v2/meta/catalog.py`
- Test: `camp/api/v2/meta/tests/test_catalog.py` (extend)

**Interfaces:**
- Consumes: URL names from Tasks 4–5 (`api:v2:calheatscore:calheatscore-meta`, `api:v2:hms:hms-meta`, `api:v2:forecasts:forecast-meta`).
- Produces:
  - `forecasts` dataset entry types: `aqi-forecast` (existing) and new `_other('burn-status', 'Burn Status', '', ['day'])`.
  - Every entry type gains `display: {precision: int | None, chart: 'line' | 'bar' | None, y_min: float | None}` (`y_min: 0` = start at zero; `null` = auto).
  - `meta_url`: `hms-smoke` and `hms-fire` → `hms/meta/`; `forecasts` → `forecasts/meta/`; `calheatscore` → `calheatscore/meta/`.

  Display hints (`_my call_` values):

  | Entry types | precision | chart | y_min |
  | --- | --- | --- | --- |
  | monitor `kind: pollutant` | 1 | line | 0 |
  | monitor `kind: meteorological` | 1 | line | null |
  | `particulates` | 0 | line | 0 |
  | `heat-score`, `aqi-forecast`, `pounds-applied`, `acres-treated`, `spray-notice` | 0 | bar | 0 |
  | `fire-frp`, `ces-score`, `facility-*` | 1 | bar | 0 |
  | `methane-emission-rate` | 1 | line | 0 |
  | `smoke-density`, `burn-status` (categories) | null | null | null |
  | TEMPO products | null | line | null |

- [ ] **Step 1: Failing tests:** `test_burn_status_listed`; `test_every_entry_type_has_display` (keys `{'precision','chart','y_min'}`); `test_display_values` (pm25 `{1,'line',0}`, temperature `{1,'line',None}`, heat-score `{0,'bar',0}`, smoke-density all `None`); `test_meta_urls` (the four datasets' `meta_url` equal the reversed URLs); `dataset_entry_types('forecasts') == ['aqi-forecast', 'burn-status']`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (one `display_for(entry_id, kind)` helper; no per-call DB work). **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `Add burn status, display hints, and domain meta URLs to the catalog`.

### Task 7: Place resolution, ZIP overlap, and forecast zones

**Files:**
- Create: `camp/apps/regions/resolve.py`
- Modify: `camp/apps/regions/querysets.py` (add `overlapping`)
- Test: `camp/apps/regions/tests/test_resolve.py`

**Interfaces:**
- Produces:
  - `RegionQuerySet.overlapping(geometry: GEOSGeometry, min_fraction: float = 0.01)`: regions with at least `min_fraction` of **their own** area inside `geometry` (mirror `contained_within`).
  - `class PlaceError(Exception)` (message is the 400 text) and `class PlaceNotFound(PlaceError)` (message is the 404 text).
  - `resolve_place(params: Mapping[str, str]) -> Region | Monitor`: reads `region_type` + `region` or `monitor`; errors (exact text): both given `"Give either monitor or region, not both."`; one of the region pair `"region_type and region go together."`; neither `"Give a region (region_type and region) or a monitor."`; land use as in Global Constraints; unknown region → `PlaceNotFound("No such region: <type> <code>.")` (404); unknown monitor → `PlaceNotFound("No such monitor: <id>.")`; monitor with no `position` → `PlaceError("Monitor has no location.")`. Uses `Region.all_objects`.
  - `zips_for(place: Region | Monitor) -> list[Region]`: a ZIP region → `[itself]`; a monitor → the ZIP containing its position (0 or 1); any other region → current ZIPs `overlapping` its boundary at 0.01; no boundary → `[]`. Cache the id list 24 h, key includes the region pk and boundary version (or monitor pk and position).
  - `forecast_zone_for(place: Region | Monitor) -> tuple[Region | None, str | None]`: rules, in order, returning `(zone, rule)`: a zone region → `'zone'`; a county named in `ZONE_TO_REGION` → its zone, `'county'`; zone containing the point-on-surface (monitor: its position) → `'center'`; zone with the largest overlap area → `'overlap'`; else `(None, None)`. "Zones" = the Regions named by `ZONE_TO_REGION` that exist. Cache 24 h like `zips_for`.

- [ ] **Step 1: Failing tests** (`fixtures = ['regions.yaml']`; build small square regions in `setUp` where the fixture lacks a case):
  - `test_overlapping_threshold`: a ZIP 0.5% inside a county is excluded, 5% inside is included.
  - `test_resolve_retired_region`: a region with `retired_at` set resolves by code.
  - `test_resolve_errors`: each error text above; land use refused.
  - `test_resolve_monitor_without_position`: raises `PlaceError("Monitor has no location.")`.
  - `test_zips_for_zip_is_itself`, `test_zips_for_county`, `test_zips_for_no_boundary_is_empty`.
  - `test_zone_rules`: Fresno County → (Fresno County, `'county'`); a city inside Fresno → (Fresno County, `'center'`); a region outside all zones → `(None, None)`; a zone region → `'zone'`.
  - `test_zips_for_cached`: second call runs 0 queries (`assertNumQueries(0)` after warming), locmem cache from test settings.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `Resolve places to their ZIPs and forecast zone`.

### Task 8: `calheatscore/place/`

**Files:**
- Modify: `camp/api/v2/calheatscore/{endpoints,urls}.py` (route before `<str:zipcode>/`)
- Test: `camp/api/v2/calheatscore/tests.py`

**Interfaces:**
- Consumes: `resolve_place`, `zips_for`, `PlaceError`, `PlaceNotFound` (Task 7).
- Produces: `GET calheatscore/place/?region_type=&region=` or `?monitor=`, optional `date`, `date__gte`, `date__lte` (default `date >= today` Pacific) →
  `{data: {place: {region: {type, external_id, name}} | {monitor: <id>}, zip_count: int, days: [{date, score, score_display, zipcode}]}}`: per date the highest score among `zips_for(place)`; `zipcode` is the ZIP that set it (ties → lowest code). URL name `calheatscore-place`. `Cache-Control: public, max-age=900`. 400/404 from `PlaceError`/`PlaceNotFound`.

- [ ] **Step 1: Failing tests** (`fixtures = ['regions', 'calheatscore']`): `test_county_takes_highest_zip` (two ZIPs scoring 1 and 3 on a date → score 3, its ZIP code); `test_tie_lowest_zip`; `test_zip_target_is_itself`; `test_no_rows_is_empty` (`days == []`, 200); `test_errors_pass_through` (land use 400, unknown region 404); `test_query_count_bounded` (`assertNumQueries` ≤ 4 cold, independent of ZIP count).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (one aggregate query: `values('date').annotate(Max('score'))` plus one to pick the ZIP per date, or a window function). **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `Answer heat for any place with the highest ZIP score`.

### Task 9: Forecast rows drop boundaries; `forecasts/place/`

**Files:**
- Modify: `camp/api/v2/forecasts/{endpoints,serializers,urls}.py`
- Test: `camp/api/v2/forecasts/tests.py`

**Interfaces:**
- Consumes: `resolve_place`, `forecast_zone_for` (Task 7).
- Produces:
  - `ForecastSerializer.region` → `{id, type, external_id, name}` (no `boundary`); drop `region__boundary` from `select_related`.
  - `GET forecasts/place/?region_type=&region=` or `?monitor=`, optional `forecast_date` filters (default `>= today`) → `{data: {place: …as Task 8…, zone: {id, type, external_id, name} | null, rule: 'zone'|'county'|'center'|'overlap'|null, forecasts: [ForecastSerializer rows]}}`. URL name `forecast-place`, before `<forecast_id>/`. `Cache-Control: public, max-age=900`.

- [ ] **Step 1: Failing tests:** `test_list_has_no_boundary` (`'boundary' not in row['region']`); `test_place_county_rule`; `test_place_city_center_rule`; `test_place_outside_valley` (`zone is None`, `forecasts == []`, 200).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `Slim forecast rows and answer forecasts for any place`.

### Task 10: Region hierarchy meta and overlap browsing

**Files:**
- Modify: `camp/apps/regions/models.py` (add `Region.TYPE_PARENTS: dict[str, list[str]]`), `camp/api/v2/regions/{endpoints,filters,serializers}.py`
- Test: `camp/api/v2/regions/tests.py`

**Interfaces:**
- Consumes: `RegionQuerySet.overlapping` (Task 7).
- Produces:
  - `regions/meta/` `types[t]` gains `count` (current regions of that type; one grouped query, cached 1 h), `parents` (from `TYPE_PARENTS`), `referenceable` (`t != 'land_use'`).
  - `TYPE_PARENTS`: `county` parent for `city, cdp, zipcode, tract, school_district, urban_area, ab617`; every other type `[]`.
  - `regions/?within=<sqid>&within_mode=overlaps` (also on `regions/geojson/`): regions overlapping the parent(s) by ≥ 1% of their own area, instead of the 99% containment; `within_mode` values `contained` (default) and `overlaps`, anything else → 400 `"within_mode must be contained or overlaps."`. In overlaps mode each list item gains `also_in: [{type, external_id, name}]`: other regions of the parent's type (excluding the requested parents) the item overlaps ≥ 1%. Query count must not grow with the number of results.

- [ ] **Step 1: Failing tests:** `test_meta_counts_parents_referenceable` (zipcode `parents == ['county']`, `land_use.referenceable is False`, `county.count` equals current county rows; a retired county isn't counted); `test_within_default_unchanged` (a straddling ZIP is absent without `within_mode`); `test_overlaps_includes_straddler_with_also_in`; `test_bad_within_mode_400`; `test_overlaps_query_count` (same `assertNumQueries` for 2 and 6 results).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `Add region hierarchy metadata and overlap browsing`.

### Task 11: Server docs, full suite, PR

**Files:** Modify `CLAUDE.md` ("Metadata Endpoints": the scale shape, the domain `…/meta/` endpoints, `calheatscore/place/`, `forecasts/place/`, `within_mode=overlaps`, the `levels` compatibility rule).

- [ ] **Step 1:** Update `CLAUDE.md`; commit `Document the scale and place endpoints`.
- [ ] **Step 2:** `$TEST -n 4 --dist loadscope` → all pass, count ≥ Task 0's.
- [ ] **Step 3:** Push; open a PR into `develop` (no merge). Body: summary, endpoints added, compatibility note, burn-status third-value outcome, deploy steps ("none beyond deploy").

## sdk-js

Serve the server branch locally for integration tests: copy `docker-compose.override.yml`, `.env`, `.env.test` into the sjvair.com worktree; `podman stop sjvaircom_web_1 && podman rm sjvaircom_web_1`; from the worktree `podman-compose -p sjvaircom --profile web up -d --no-deps web`. Restore the same way from the main checkout when done.

Each sdk-js task: schemas in `schemas/`, types via `zinfer`, wrapper file with JSDoc `@example Usage` and `@module`, export from the module's `mod.ts`, add `deno.json` `exports` entries, unit tests on saved fixtures (`lib/<domain>/fixtures/*.json`, captured from the local server) plus a round-trip in `mod_test.ts`, and every fetch takes a trailing `options?: RequestOptions`. Run `deno fmt --check && deno lint && deno check mod.ts && deno test --allow-net --allow-env` before each commit.

### Task 12: Scale types; monitors meta and catalog additions

**Files:**
- Create: `lib/meta/schemas/scale.ts`
- Modify: `lib/meta/schemas/{mod,dataset_catalog}.ts`, `lib/meta/types.ts`, `lib/monitors/schemas/monitors_meta.ts`, `lib/monitors/types.ts`, `lib/monitors/get_monitors_meta.ts`, `lib/monitors/fixtures/monitors_meta.json`, `lib/meta/fixtures/dataset_catalog.json`
- Test: `lib/meta/mod_test.ts`, `lib/monitors/mod_test.ts`

**Interfaces:**
- Produces: `scaleLevelSchema`, `scaleSchema`, `scaleSourceSchema`; types `Scale`, `ScaleLevel`, `ScaleSource` (exported from `@sjvair/sdk/meta/types`); `choiceSchema` / `Choice` (`{key, label, description}`).
  - Monitors: level meta gains `tier: number | null` (optional); entry meta gains `scale: Scale | null` (optional); `MonitorsMeta` gains `stages` and `processors` getters (records of `Choice`) with `.asIter`.
  - Catalog: entry type gains optional `display: {precision: number | null; chart: "line" | "bar" | null; y_min: number | null}`.
  - All new fields optional so older servers still parse.
- [ ] **Step 1:** Failing tests: fixture parse of the new fields; `meta.entryType("pm25").scale.levels[0].tier === 0`; a fixture *without* the new fields still parses.
- [ ] **Step 2–4:** Run → FAIL; implement; run → PASS.
- [ ] **Step 5:** Commit: `Add the shared Scale types and the new monitors meta and catalog fields`.

### Task 13: Domain meta wrappers

**Files:** Create `lib/calheatscore/{mod,get_calheatscore_meta,types}.ts` + `schemas/`, `lib/forecasts/{mod,get_forecasts_meta,types}.ts` + `schemas/`, `lib/hms/get_hms_meta.ts`; modify `lib/hms/mod.ts`, `deno.json`, `mod.ts` (root re-exports if the root re-exports modules).

**Interfaces:**
- Produces: `getCalHeatScoreMeta(options?) -> Promise<{ scales: Record<string, Scale> }>`; `getHmsMeta(options?)` (same shape); `getForecastsMeta(options?) -> Promise<{ scales: Record<string, Scale>; zones: Array<ForecastZone> }>`, `ForecastZone = { name: string; region: RegionRef | null }`, `RegionRef = { id: string; type: RegionType; external_id: string; name: string }` (defined in `lib/regions/schemas/region_ref.ts`, reused below).
- [ ] **Steps:** failing tests (heat level 3 color `#c23a00`; smoke heavy opacity 0.4; forecast zones length 9) → implement → pass → commit `Add calheatscore, hms, and forecasts meta wrappers`.

### Task 14: Heat and forecast data wrappers

**Files:** Create `lib/calheatscore/{get_calheatscores,get_heat_for_place}.ts`, `lib/forecasts/{get_forecasts,get_forecast_for_place}.ts`, `lib/meta/place.ts` (or alongside `RegionRef`).

**Interfaces:**
- Produces:
  - `PlaceRef = { region: { type: RegionType; external_id: string } } | { monitor: string }`; land use throws `"Land-use regions can't be looked up by code"` before fetching (as `getCoverage`).
  - `getCalHeatScores(filters?: { date?: string; zipcode?: string | string[] }, options?) -> Promise<CalHeatScore[]>` (`zipcode__in` for arrays); `CalHeatScore = { zipcode: string; date: string; score: number; score_display: string }`.
  - `getHeatForPlace(place: PlaceRef, dates?: { date?: string; gte?: string; lte?: string }, options?) -> Promise<HeatForPlace>`, `HeatForPlace = { place; zip_count: number; days: Array<{ date; score; score_display; zipcode }> }`.
  - `getForecasts(filters?: { region_id?: string; forecast_date?: string; gte?: string; lte?: string }, options?) -> Promise<Forecast[]>` (row `region` is `RegionRef`).
  - `getForecastForPlace(place: PlaceRef, dates?, options?) -> Promise<ForecastForPlace>`, `{ place; zone: RegionRef | null; rule: "zone" | "county" | "center" | "overlap" | null; forecasts: Forecast[] }`.
- [ ] **Steps:** failing tests (Fresno County heat `zip_count > 0`; forecast for Fresno County has `rule === "county"`; land-use throws without a request; paginated list endpoints use `paginatedApiCall`) → implement → pass → commit `Add heat and forecast wrappers, including by place`.

### Task 15: Region meta fields, overlap browsing, `getRegionsGeoJSON`

**Files:** Modify `lib/regions/schemas/regions_meta.ts`, `lib/regions/schemas/region.ts` (list item `also_in`), `lib/regions/get_regions_list.ts`; create `lib/regions/get_regions_geojson.ts`, `lib/regions/schemas/region_geojson.ts`.

**Interfaces:**
- Produces: region type meta gains optional `count: number`, `parents: RegionType[]`, `referenceable: boolean`; `RegionsListFilters` gains `within_mode?: "contained" | "overlaps"`; list item gains optional `also_in: RegionRef-without-id[]` (`{type, external_id, name}`).
  - `getRegionsGeoJSON(query: { type: RegionType; external_id?: string | string[]; within?: string | string[]; within_mode?: "contained" | "overlaps"; slug?: string; name?: string; simplify?: boolean }, options?) -> Promise<RegionFeatureCollection>`; arrays joined with commas for `external_id` (the server's format), `simplify` sent as `1`; land use + `external_id` throws as above. Feature `properties` schema matches `shapes.region_feature` (read it).
- [ ] **Steps:** failing tests (zipcode `parents` include `"county"`; overlaps returns more ZIPs for Fresno County than contained; geojson by two county codes returns 2 features) → implement → pass → commit `Add region hierarchy fields, overlap browsing, and getRegionsGeoJSON`.

### Task 16: sdk-js docs and PR

- [ ] **Step 1:** `api-urls.md`: add and mark `calheatscore/meta/`, `calheatscore/place/`, `forecasts/`, `forecasts/meta/`, `forecasts/place/`, `hms/meta/`, `regions/geojson/`; fix stale entries touched. `CHANGELOG` (if the repo keeps one): the new functions and types. Commit `Document the new endpoints`.
- [ ] **Step 2:** Full check (`deno fmt --check && deno lint && deno check mod.ts && deno test --allow-net --allow-env`) against the served branch → pass.
- [ ] **Step 3:** Push; open a PR into `release/4.8.0` (no merge, no tag, no beta). Restore the stack to the main checkout.

## Wrap-up

### Task 17: Dashboard docs and handoffs

- [ ] **Step 1:** In `/home/alex/workspace/sjvair/data-dashboard/.worktrees/docs-step3` (`git fetch && git switch --detach origin/main`, then a local branch), re-read and update: `ARCHITECTURE.md` → "Metadata as source of truth" (the scale shape and JSON keys, `opacity`, scales keyed by entry-type id, `display` hints, `calheatscore/place/` and `forecasts/place/` and their rules, `within_mode=overlaps` and `also_in`, region meta fields); `TODO.md` step 3 (spec 1 items ✅ with the PR links, "waiting on a beta"); `ROADMAP.md` item 3 if wording changes. Commit and push straight to data-dashboard `main` (docs only).
- [ ] **Step 2:** Tell the user both PRs are open and ask whether to cut a 4.8.0 beta (never without their yes). After a beta they approve is out, message `data-dashboard-26` (pin bump) and `map-sdk-e7` (Scale types, `opacity`, `getRegionsGeoJSON`).
