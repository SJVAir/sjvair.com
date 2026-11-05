# Smoke Over a Place, Per Day — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /api/2.0/hms/smoke/place/` returns, for a region or monitor and a Pacific date range, one row per day with the heaviest HMS smoke density over the place and the share of its area under at least light, medium and heavy smoke; plus an sdk-js wrapper `getSmokeForPlace`.

**Architecture:** One raw-SQL query per request (`camp/apps/hms/place.py`) unions each day's outlines at or above each density level, intersects them with the place in California Albers (EPSG:3310), and returns areas; Python fills every day of the range and divides by the place's area. The endpoint reuses `resolve_place` / `place_json` like `calheatscore/place/`. A day is settled one hour after the next day's 21:00 UTC final pass; fully settled ranges are cached long (client and server side), others short.

**Tech Stack:** Django 5 + PostGIS (raw SQL via `connection.cursor()`), django-resticus, pytest in the podman test image; Deno + Zod for sdk-js.

**Spec:** `docs/superpowers/specs/2026-11-05-get-data-place-layers-design.md` — "How the dashboard names a place", "Item 3", "SDK", "Deferred".

## Global Constraints

- Addressing: `?region_type=&region=` (a region code; retired regions answer; land use is a 400) or `?monitor=` (hidden monitors 404; a monitor without a position is a 400), via `camp.apps.regions.resolve.resolve_place`. Errors `{error}` body, 400/404, `Cache-Control: no-cache`.
- Response `{data: {place, days}}`, `place` from `place_json()`. Each day `{date, density, coverage: {light, medium, heavy}}`.
- One row per day in the range, no holes, ascending. `density` is a `smoke-density` level key (`light`, `medium`, `heavy`) or `null` for no smoke. A day with no outlines reads as no smoke.
- Coverage: share of the place's area under at least that level, 0–1; correct when outlines of different densities overlap. For a monitor (a point) each value is 0 or 1.
- Dates: only `date__gte` / `date__lte` (Pacific `YYYY-MM-DD`). No range = the last 30 days through today. At most 366 days. `date__gte` after `date__lte` is a 400; a longer range is a 400.
- Area math in EPSG:3310 or geography, never degrees. Computed on request; no stored table, no backfill, no migration.
- `hms/smoke/` and `hms/smoke/<smoke_id>/` stay unchanged.
- SDK: branch from `origin/release/5.0.0`, PR into it. No beta, tag or publish without the user's yes for that release. No fallbacks for older server responses.
- No Claude/AI attribution in commits, PRs or docs. Never merge into `develop` or `release/5.0.0` without the user's yes. Nothing touches production.

## Review Focus

1. **Only one bound given.** `date__gte` alone runs through today (Pacific); `date__lte` alone runs the 30 days ending on it. Blank values (`date__gte=`) count as absent, like heat. → tests in Task 2.
2. **Overlapping outlines of the same density** (HMS often sends several light plumes that overlap): coverage must not exceed 1.0 or double-count. → test in Task 1.
3. **A monitor exactly on a plume's edge** counts as under it (`ST_Intersects`, as `zips_for` does for edges). → test in Task 1.
4. **A region with no boundary** (`boundary_id` null): every day `density: null`, coverage zeros, 200 — not a 500. → test in Task 2.
5. **Future days and today**: allowed, filled with null rows; a range touching today or later is never cached long. → tests in Tasks 1 and 2.

---

## Setup (once, before Task 1)

Work in this worktree (`/home/alex/workspace/sjvair/sjvair.com/.worktrees/get-data-layers`), on a new branch from it:

```bash
git fetch && git switch -c feature/smoke-place   # from feature/get-data-layers (carries the spec)
cp ../../.env ../../.env.test ../../docker-compose.override.yml .
```

Test command used below (`$T`), with its own database so parallel sessions don't collide. Take `DATABASE_URL` from `.env.test` and change only the database name to `sjvair_smoke_place`:

```bash
T="podman run --rm --network sjvaircom_sjvair-net --env-file .env.test \
  -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token \
  -e DATABASE_URL=<.env.test URL with db name sjvair_smoke_place> \
  -v $PWD:/app:z \
  -v $HOME/workspace/django-resticus/.worktrees/session-csrf/resticus:/usr/local/lib/python3.14/site-packages/resticus:ro,z \
  -w /app sjvair-com-test:latest"
```

Baseline before any change: `$T pytest camp/api/v2/hms/ -q` → all pass (ignore the trailing "not a git repository" line). Record the count.

---

### Task 1: Per-day smoke query and settle rule

**Files:**
- Create: `camp/apps/hms/place.py`
- Test: `camp/apps/hms/test_place.py` (new file beside the existing `camp/apps/hms/tests.py`; pytest collects both, as with `camp/apps/summaries/test_*.py`)

**Interfaces:**
- Produces:
  - `LEVELS: tuple[str, ...] = ('light', 'medium', 'heavy')` — order is rank (index 0 lightest). Must equal `[c.value for c in Smoke.Density]` (asserted in a test).
  - `smoke_days(geometry: GEOSGeometry | None, start: date, end: date) -> list[dict]` — one dict per day `start..end` inclusive, ascending: `{'date': 'YYYY-MM-DD', 'density': str | None, 'coverage': {'light': float, 'medium': float, 'heavy': float}}`. `geometry` is SRID 4326: a (Multi)Polygon for regions, a Point for monitors, `None` → all-null rows.
  - `FINAL_PASS_UTC: time = time(21, 0)`, `SETTLE_MARGIN: timedelta = timedelta(hours=1)`
  - `is_day_settled(day: date, now: datetime | None = None) -> bool` — True once `now >= datetime.combine(day + 1 day, FINAL_PASS_UTC, UTC) + SETTLE_MARGIN`.

- [ ] **Step 1: Write the failing tests** (`django.test.TestCase`, pytest asserts; reuse the WKT helpers style from `camp/api/v2/hms/tests.py`: build `Smoke` rows with `MultiPolygon(GEOSGeometry(wkt, srid=4326))`)

```python
# Squares in degrees near Fresno; PLACE is 0.2° x 0.2°.
PLACE = 'POLYGON((-119.9 36.7, -119.7 36.7, -119.7 36.9, -119.9 36.9, -119.9 36.7))'
LEFT_HALF = 'POLYGON((-120.0 36.6, -119.8 36.6, -119.8 37.0, -120.0 37.0, -120.0 36.6))'
WHOLE = 'POLYGON((-120.0 36.6, -119.6 36.6, -119.6 37.0, -120.0 37.0, -120.0 36.6))'
FAR = 'POLYGON((-118.5 36.5, -118.0 36.5, -118.0 37.0, -118.5 37.0, -118.5 36.5))'
D = date(2026, 10, 27)

def test_levels_match_model(self):
    assert list(LEVELS) == [c.value for c in Smoke.Density]

def test_one_row_per_day_no_holes(self):
    rows = smoke_days(GEOSGeometry(PLACE, srid=4326), D, D + timedelta(days=2))
    assert [r['date'] for r in rows] == ['2026-10-27', '2026-10-28', '2026-10-29']
    assert rows[0] == {'date': '2026-10-27', 'density': None,
                       'coverage': {'light': 0.0, 'medium': 0.0, 'heavy': 0.0}}

def test_heaviest_density_and_cumulative_coverage(self):
    smoke(D, 'light', WHOLE); smoke(D, 'heavy', LEFT_HALF)
    row = smoke_days(GEOSGeometry(PLACE, srid=4326), D, D)[0]
    assert row['density'] == 'heavy'
    assert row['coverage']['light'] == pytest.approx(1.0, abs=0.01)
    assert row['coverage']['medium'] == pytest.approx(0.5, abs=0.01)   # heavy counts as at least medium
    assert row['coverage']['heavy'] == pytest.approx(0.5, abs=0.01)

def test_overlapping_same_density_not_double_counted(self):   # Review Focus 2
    smoke(D, 'light', WHOLE); smoke(D, 'light', LEFT_HALF); smoke(D, 'light', WHOLE)
    row = smoke_days(GEOSGeometry(PLACE, srid=4326), D, D)[0]
    assert row['coverage']['light'] == pytest.approx(1.0, abs=0.01)

def test_outline_elsewhere_is_no_smoke(self):
    smoke(D, 'heavy', FAR)
    assert smoke_days(GEOSGeometry(PLACE, srid=4326), D, D)[0]['density'] is None

def test_other_days_outlines_ignored(self):
    smoke(D + timedelta(days=1), 'heavy', WHOLE)
    assert smoke_days(GEOSGeometry(PLACE, srid=4326), D, D)[0]['density'] is None

def test_point_coverage_is_zero_or_one(self):
    smoke(D, 'medium', LEFT_HALF)
    inside = smoke_days(Point(-119.85, 36.8, srid=4326), D, D)[0]
    outside = smoke_days(Point(-119.75, 36.8, srid=4326), D, D)[0]
    assert inside == {'date': '2026-10-27', 'density': 'medium',
                      'coverage': {'light': 1.0, 'medium': 1.0, 'heavy': 0.0}}
    assert outside['density'] is None and outside['coverage']['light'] == 0.0

def test_point_on_edge_counts(self):   # Review Focus 3
    smoke(D, 'light', LEFT_HALF)
    assert smoke_days(Point(-119.8, 36.8, srid=4326), D, D)[0]['density'] == 'light'

def test_no_geometry_all_null(self):   # Review Focus 4 (helper side)
    smoke(D, 'heavy', WHOLE)
    assert smoke_days(None, D, D)[0]['density'] is None

def test_settle_rule(self):
    utc = dt_timezone.utc
    assert not is_day_settled(D, datetime(2026, 10, 28, 21, 59, tzinfo=utc))
    assert is_day_settled(D, datetime(2026, 10, 28, 22, 0, tzinfo=utc))

def test_final_pass_constant_matches_schedule(self):
    from camp.apps.hms.tasks import fetch_smoke_final
    at = datetime.combine(D, FINAL_PASS_UTC)          # naive UTC, as Huey validates
    assert fetch_smoke_final.task_class().validate_datetime(at)
    assert not fetch_smoke_final.task_class().validate_datetime(at - timedelta(hours=1))
```

(`smoke(date, density, wkt)` is a small module-level test helper that creates and saves a `Smoke` row. If `task_class().validate_datetime` isn't how this Huey version exposes it, use the equivalent on the `TaskWrapper` — the assertion is that 21:00 UTC matches and 20:00 doesn't.)

- [ ] **Step 2: Run to verify they fail**

Run: `$T pytest camp/apps/hms/ -k "place or settle or levels or final_pass" -v`
Expected: FAIL — `ModuleNotFoundError: camp.apps.hms.place`.

- [ ] **Step 3: Implement `camp/apps/hms/place.py`**

`smoke_days` runs **one** query and fills the days in Python. For a polygon place:

```sql
WITH place AS (SELECT ST_Transform(%(geom)s::geometry, 3310) AS g),
smoke AS (
  SELECT s.date,
         array_position(%(levels)s::text[], s.density) AS rank,   -- 1 light, 2 medium, 3 heavy
         ST_Transform(s.geometry, 3310) AS g
  FROM <Smoke._meta.db_table> s
  WHERE s.date BETWEEN %(start)s AND %(end)s
    AND ST_Intersects(s.geometry, %(geom)s::geometry)              -- 4326, uses the GiST index
)
SELECT sm.date, lvl.rank,
       ST_Area(ST_Intersection(ST_Union(sm.g), (SELECT g FROM place))) AS area
FROM smoke sm
JOIN generate_series(1, 3) AS lvl(rank) ON sm.rank >= lvl.rank
GROUP BY sm.date, lvl.rank
```

Pass `geom` as EWKB/EWKT (`geometry.ewkt`) and `levels` as `list(LEVELS)`. Divide each area by the place's own area (`ST_Area(ST_Transform(geom, 3310))`, one extra column or a scalar subquery in the same statement — keep it to one round trip), clamp to `[0, 1]`, round to 4 places. `density` = the highest level whose area > 0 (`LEVELS[rank-1]`), else `None`.

For a Point: same CTE without the area — select `sm.date, lvl.rank` grouped, where `ST_Intersects` already holds; each present `(date, rank)` is coverage 1.0.

An unknown `density` string (`array_position` null) is ignored by the join. `None` geometry returns the filled rows without querying.

`is_day_settled`: as in Interfaces; `now` defaults to `timezone.now()`.

- [ ] **Step 4: Run to verify they pass**

Run: `$T pytest camp/apps/hms/ -k "place or settle or levels or final_pass" -v`
Expected: PASS (all 11).

- [ ] **Step 5: Commit**

```bash
git add camp/apps/hms/place.py camp/apps/hms/test_place.py
git commit -m "feat(hms): per-day smoke density and coverage over a geometry"
```

---

### Task 2: `hms/smoke/place/` endpoint

**Files:**
- Create: `camp/api/v2/hms/forms.py`
- Modify: `camp/api/v2/hms/endpoints.py` (add `SmokePlace`), `camp/api/v2/hms/urls.py` (route **before** `smoke/<smoke_id>/`)
- Test: `camp/api/v2/hms/tests.py` (new `SmokePlaceTests`)

**Interfaces:**
- Consumes: `smoke_days`, `is_day_settled` (Task 1); `resolve_place`, `place_json`, `PlaceError`, `PlaceNotFound`, `_place_key`, `_place_geometry`, `CACHE_TIMEOUT` from `camp.apps.regions.resolve` (`_place_key`/`_place_geometry` are module-private today; import them anyway, or rename them public in `resolve.py` with their two existing callers updated — implementer's choice, same commit).
- Produces:
  - URL name `api:v2:hms:smoke-place` → `/api/2.0/hms/smoke/place/`
  - `SmokePlaceForm(forms.Form)` with `date__gte`, `date__lte` (`forms.DateField(required=False)`); `clean()` returns `(start, end)` via `cleaned_data['range']`, applying: blank = absent; both absent → `(today-29, today)`; only `gte` → `(gte, today)`; only `lte` → `(lte-29, lte)`; `start > end` → error `"date__gte must be on or before date__lte."`; `(end - start).days + 1 > 366` → error `"At most 366 days per request."`. `today` = Pacific date.
  - Constants in `endpoints.py`: `SMOKE_PLACE_SETTLED_MAX_AGE = 86400`, `SMOKE_PLACE_MAX_AGE = 900`.

- [ ] **Step 1: Write the failing tests** (`SmokePlaceTests(TestCase)`, `fixtures = ['regions']` like `CalHeatScorePlaceTests`; Fresno County is `county` / `06019`. Patch `camp.api.v2.hms.endpoints.smoke_days` only where noted; most tests use real `Smoke` rows over a test region built with the existing `create_region` helper and a `zipcode`/`city` type)

```python
def test_route_not_shadowed_by_detail(self):
    assert reverse('api:v2:hms:smoke-place') == '/api/2.0/hms/smoke/place/'
    assert self.client.get('/api/2.0/hms/smoke/place/', {'region_type': 'county', 'region': '06019'}).status_code == 200

def test_region_days_shape_and_place(self):
    # region from create_region(REGION_COVERS_SMOKE) with type city / external_id 9001; light smoke on D
    body = get(region, date__gte=D, date__lte=D + 1 day).json()['data']
    assert body['place'] == {'region': {'type': 'city', 'external_id': '9001', 'name': 'Test Region'}}
    assert [d['date'] for d in body['days']] == [D, D+1]          # as ISO strings
    assert body['days'][0]['density'] == 'light'
    assert set(body['days'][0]['coverage']) == {'light', 'medium', 'heavy'}

def test_monitor_place(self):
    # a PurpleAir (or any) monitor positioned inside SJV_POLYGON, smoke 'medium' on D
    body = self.client.get(url, {'monitor': monitor.pk, 'date__gte': D, 'date__lte': D}).json()['data']
    assert body['place'] == {'monitor': str(monitor.pk)}
    assert body['days'][0]['coverage'] == {'light': 1.0, 'medium': 1.0, 'heavy': 0.0}

def test_default_range_is_last_30_days(self):        # freeze timezone.now at 2026-07-12 10:00 Pacific
    days = get(region).json()['data']['days']
    assert len(days) == 30 and days[0]['date'] == '2026-06-13' and days[-1]['date'] == '2026-07-12'

def test_blank_dates_are_absent(self):                # Review Focus 1
    days = get(region, date__gte='', date__lte='').json()['data']['days']
    assert len(days) == 30

def test_only_gte_runs_through_today(self):           # Review Focus 1 (frozen now 2026-07-12)
    days = get(region, date__gte='2026-07-10').json()['data']['days']
    assert [d['date'] for d in days] == ['2026-07-10', '2026-07-11', '2026-07-12']

def test_only_lte_is_30_days_ending_there(self):      # Review Focus 1
    days = get(region, date__lte='2026-03-31').json()['data']['days']
    assert days[0]['date'] == '2026-03-02' and days[-1]['date'] == '2026-03-31'

def test_bad_ranges_are_400_no_cache(self):
    for params in ({'date__gte': '2026-07-02', 'date__lte': '2026-07-01'},
                   {'date__gte': '2025-01-01', 'date__lte': '2026-01-02'},   # 367 days
                   {'date__gte': 'nope'}):
        response = get(region, **params)
        assert response.status_code == 400
        assert 'error' in response.json() or 'errors' in response.json()
        assert 'no-cache' in response['Cache-Control']

def test_366_days_allowed(self):
    assert get(region, date__gte='2025-01-01', date__lte='2026-01-01').status_code == 200

def test_place_errors_pass_through(self):
    assert self.client.get(url, {'region_type': 'land_use', 'region': '1'}).status_code == 400
    assert self.client.get(url, {'region_type': 'county', 'region': 'nope'}).status_code == 404
    assert self.client.get(url).status_code == 400
    # hidden monitor → 404 (set is_hidden=True on a monitor)

def test_region_without_boundary_is_all_null(self):   # Review Focus 4
    region = create_region(slug='no-boundary', external_id='9003')     # no geometry
    days = get(region, date__gte=D, date__lte=D).json()['data']['days']
    assert days == [{'date': D_iso, 'density': None, 'coverage': {'light': 0.0, 'medium': 0.0, 'heavy': 0.0}}]

def test_settled_range_cached_long(self):             # frozen now well after D+1 22:00 UTC
    response = get(region, date__gte=D, date__lte=D)
    assert response['Cache-Control'] == 'public, max-age=86400'

def test_range_touching_today_cached_short(self):     # Review Focus 5
    response = get(region)                              # default range ends today
    assert response['Cache-Control'] == 'public, max-age=900'

def test_future_days_filled_with_null(self):          # Review Focus 5 (frozen now 2026-07-12)
    days = get(region, date__gte='2026-07-12', date__lte='2026-07-14').json()['data']['days']
    assert len(days) == 3 and days[-1]['density'] is None

def test_settled_answer_cached_server_side(self):
    with patch('camp.api.v2.hms.endpoints.smoke_days', wraps=smoke_days) as spy:
        get(region, date__gte=D, date__lte=D); get(region, date__gte=D, date__lte=D)
    assert spy.call_count == 1

def test_unsettled_answer_not_cached_server_side(self):
    with patch('camp.api.v2.hms.endpoints.smoke_days', wraps=smoke_days) as spy:
        get(region); get(region)
    assert spy.call_count == 2

def test_retired_region_still_answers(self):
    region.retired_at = timezone.now(); region.save()
    assert get(region, date__gte=D, date__lte=D).status_code == 200

def test_existing_smoke_detail_still_routes(self):
    smoke = create_smoke()
    assert self.client.get(reverse('api:v2:hms:smoke-detail', args=[smoke.pk])).status_code == 200
```

(`get(region, **params)` is a test helper: `self.client.get(url, {'region_type': region.type, 'region': region.external_id, **params})`. Freeze time with `patch.object(timezone, 'now', ...)` as `CalHeatScorePlaceTests` does. Pick `D` in the past, e.g. `date(2026, 6, 1)`, so "settled" tests don't depend on today. Make each test's region type one `resolve_place` accepts.)

- [ ] **Step 2: Run to verify they fail**

Run: `$T pytest camp/api/v2/hms/tests.py -k SmokePlace -v`
Expected: FAIL — `NoReverseMatch: 'smoke-place'`.

- [ ] **Step 3: Implement `SmokePlaceForm` in `camp/api/v2/hms/forms.py`** per its Interfaces entry. Strip values first; treat `''` as absent.

- [ ] **Step 4: Implement `SmokePlace(generics.Endpoint)` in `camp/api/v2/hms/endpoints.py`** and route `path('smoke/place/', endpoints.SmokePlace.as_view(), name='smoke-place')` **above** `smoke/<smoke_id>/` in `urls.py`.

`get()`: `resolve_place(request.GET)` (`PlaceNotFound` → 404, `PlaceError` → 400, `{error}`); form invalid → 400 `{errors: form.errors.get_json_data()}`; `settled = is_day_settled(end)`. When settled, look up / store the `days` list in the Django cache under `f"{_place_key('smoke_days', place)}:{start}:{end}"` for `CACHE_TIMEOUT` (24h); when not settled, always compute. Geometry from `_place_geometry(place)` (fetched only on a cache miss). Response `{data: {place: place_json(place), days}}`, `Cache-Control` `public, max-age=86400` if settled else `public, max-age=900`. Every non-200 gets `Cache-Control: no-cache`. Docstring in the heat endpoint's style (it shows in the API browser).

- [ ] **Step 5: Run to verify they pass, then the whole app**

Run: `$T pytest camp/api/v2/hms/ camp/apps/hms/ camp/apps/regions/ -q`
Expected: all pass; baseline count + new tests.

- [ ] **Step 6: Commit**

```bash
git add camp/api/v2/hms/ camp/apps/regions/resolve.py
git commit -m "feat(hms): smoke/place/ endpoint, per-day density and coverage for a place"
```

---

### Task 3: Measure, document, full suite, PR

**Files:**
- Modify: `CLAUDE.md` ("Metadata Endpoints" → the **Place endpoints** bullet)

- [ ] **Step 1: Measure locally (read-only on the shared dev DB).** Run against the dev database (`--env-file .env`, not `.env.test`), worktree code mounted, no server swap needed:

```bash
podman run --rm --network sjvaircom_sjvair-net --env-file .env -v $PWD:/app:z -w /app sjvair-com-test:latest \
  python manage.py shell -c "
import time; from datetime import date
from camp.apps.regions.models import Region; from camp.apps.hms.place import smoke_days
r = Region.objects.get(type='county', external_id='06019')
t = time.perf_counter(); rows = smoke_days(r.boundary.geometry, date(2025,11,6), date(2026,11,5))
print(len(rows), sum(1 for x in rows if x['density']), round(time.perf_counter()-t, 3), 's')"
```

Expected: 365 rows, a few smoke days (local smoke only starts 2026-10-18), and under 1 s. Also time a ZIP (`zipcode` / `93728`) and a monitor point. If Fresno County exceeds 1 s, add `ST_Subdivide` on the place geometry (or `ST_Simplify` to ~10 m in 3310) inside the query and re-measure. Report the numbers in the PR. Note that local data is sparse; production has more outlines per day (expect proportionally more union work).

- [ ] **Step 2: Add the CLAUDE.md note.** Extend the "Place endpoints" bullet: `hms/smoke/place/` takes the same place params plus `date__gte`/`date__lte` (Pacific; default last 30 days; at most 366), returns one row per day (`density` = heaviest `smoke-density` key or `null`; `coverage` = share of the place's area under at least each level, 0/1 for a monitor), computed on request in `camp/apps/hms/place.py` in EPSG:3310; a day is settled at 22:00 UTC the next day (one hour after `fetch_smoke_final`), settled ranges cached 24h (server and client), others `max-age=900`; an empty day can't be told from a missed fetch (deferred).

- [ ] **Step 3: Full suite**

Run: `$T pytest -n 4 --dist loadscope -q`
Expected: same pass count as a `develop` baseline plus the new tests; report any failure with its output (tee to a log first, don't tail it away).

- [ ] **Step 4: Commit and open the PR** (only after the user approves opening it)

```bash
git add CLAUDE.md && git commit -m "docs: smoke/place/ in CLAUDE.md"
git push -u origin feature/smoke-place
gh pr create --base develop --title "hms/smoke/place/: per-day smoke over a place" --body "<summary, perf numbers, spec link; no AI attribution>"
```

Tell the coordinator (`data-dashboard-b7`) and `data-dashboard-13` the PR link and final shape. Merge only with the user's yes.

---

## SDK (sdk-js) — `getSmokeForPlace`

Separate repo, separate PR into `release/5.0.0`. Can start once Task 2's response shape is committed (it doesn't need the server PR merged, but its live test needs a local server running `feature/smoke-place`).

### Task 4: `getSmokeForPlace` wrapper and schema

**Setup:**

```bash
cd /home/alex/workspace/sjvair/sdk-js && git fetch
git worktree add -b feature/smoke-for-place .worktrees/smoke-for-place origin/release/5.0.0
cd .worktrees/smoke-for-place && cp ../../.env .
```

**Files:**
- Create: `lib/hms/smoke/get_smoke_for_place.ts`, `lib/hms/fixtures/smoke_for_place.json`
- Modify: `lib/hms/smoke/schema.ts`, `lib/hms/smoke/types.ts`, `lib/hms/smoke/mod.ts`, `lib/hms/smoke/mod_test.ts`, `deno.json` (exports), `api-urls.md`, `CHANGELOG.md`
- Pattern to follow: `lib/calheatscore/get_heat_for_place.ts`, its schema in `lib/calheatscore/schemas/calheatscore.ts`, and the place steps in `lib/calheatscore/mod_test.ts`.

**Interfaces:**
- Consumes: `PlaceRef`, `placeSearchParams` from `lib/meta/place.ts`; `placeSchema` from `lib/meta/schemas/mod.ts`; `jsonCall`, `RequestOptions` from `$http`.
- Produces:
  - `smokeDaySchema`: `{date: string, density: enum(light, medium, heavy).nullable(), coverage: {light: number, medium: number, heavy: number}}` (reuse the density enum from `hmsSmokeSchema`; explicit `interface ...Schema extends z.ZodObject<...>` like the heat schemas, with doc comments).
  - `smokeForPlaceSchema`: `{place: placeSchema, days: z.array(smokeDaySchema)}`.
  - Types `SmokeDay`, `SmokeForPlace` (via `zinfer`), `SmokeDates = {gte?: string; lte?: string}` (no `date`: the endpoint takes only a range).
  - `getSmokeForPlace(place: PlaceRef, dates: SmokeDates = {}, options?: RequestOptions): Promise<SmokeForPlace>` → `GET hms/smoke/place` with `date__gte` / `date__lte` only when given.
  - Export path `./hms/smoke/get_smoke_for_place` in `deno.json`.

- [ ] **Step 1: Write the failing test steps** in `lib/hms/smoke/mod_test.ts`:
  - "smoke-for-place fixture matches the schema": `getSimpleValidationTest(smokeForPlaceSchema)(fixture.data)`.
  - "getSmokeForPlace sends the place and range": `stubFetch(() => jsonResponse(fixture))`; call with `{region: {type: "county", external_id: "06019"}}` and `{gte: "2026-10-01", lte: "2026-10-31"}`; assert `pathname === "/api/2.0/hms/smoke/place/"`, `region_type=county`, `region=06019`, `date__gte=2026-10-01`, `date__lte=2026-10-31`, and no `date__gte` when `dates` is `{}`.
  - "live: getSmokeForPlace for Fresno County" against the local API: validates the response and asserts `days.length === 30` with no dates. Skip with a note (like the existing data-dependent steps) when the server answers 404 for the route (server not on `feature/smoke-place`).

  Fixture: a real response saved from the local server on `feature/smoke-place` (`/api/2.0/hms/smoke/place/?region_type=county&region=06019&date__gte=2026-10-26&date__lte=2026-10-29`), with at least one non-null day; trim nothing.

- [ ] **Step 2: Run to verify they fail**

Run: `deno test --allow-net --allow-env --allow-read --env-file=.env lib/hms/smoke/mod_test.ts`
Expected: FAIL — module `./get_smoke_for_place.ts` not found.

- [ ] **Step 3: Implement** the schema, types, wrapper (JSDoc with `@example Usage` and `@module`, like `get_heat_for_place.ts`; document that `density` is `null` on a day with no smoke and that an empty day can't be told from a missed fetch), `mod.ts` re-export, `deno.json` export, `api-urls.md` (`- [x] /api/2.0/hms/smoke/place/` under "HMS Smoke and Fire"), and a `CHANGELOG.md` line under 5.0.0 "Added".

- [ ] **Step 4: Run the full checks**

Run: `deno fmt --check && deno lint && deno check mod.ts && deno test --allow-net --allow-env --allow-read --env-file=.env`
(Exclude the account tests: they send a real SMS. The `closest/` steps fail locally without current PM2.5; note, don't fix.)
Expected: all pass except the known `closest/` steps.

- [ ] **Step 5: Commit and open the PR** (after the user approves opening it)

```bash
git add -A && git commit -m "feat(hms): getSmokeForPlace for hms/smoke/place/"
git push -u origin feature/smoke-for-place
gh pr create --base release/5.0.0 --title "getSmokeForPlace (hms/smoke/place/)" --body "<summary; needs a server running sjvair.com feature/smoke-place (or develop once merged); no AI attribution>"
```

No beta, tag or publish. Ask the user whether this goes into the next beta (and how betas are grouped across items) when the PR is ready. Tell the coordinator.

---

### Task 5: DEFERRED.md entry (data-dashboard docs)

- [ ] **Step 1:** In the docs worktree (create it if missing: `git -C /home/alex/workspace/sjvair/data-dashboard worktree add .worktrees/docs-explorer-layers origin/main`), `git fetch && git rebase origin/main`, re-read `DEFERRED.md`, and add one entry unless an equivalent exists:

  **Smoke "no data" vs "no smoke"** — `hms/smoke/place/` reads a day with no stored HMS outlines as no smoke; an empty HMS file and a fetch that never ran store the same nothing. Fix: record each successful daily fetch (a small per-day table) so a missed day reads as unknown. Why deferred: the user decided (2026-11-05) a new table isn't worth it yet; production fetches ~13 times a day plus a final pass. Revisit when a missed day turns up in production data or users report false clear days.

- [ ] **Step 2:** `../../node_modules/.bin/prettier --write DEFERRED.md`, commit (`docs(deferred): smoke no-data vs no-smoke`), rebase on `origin/main`, push straight to `main` (docs-only). Tell the coordinator.
