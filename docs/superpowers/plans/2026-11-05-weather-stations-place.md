# Weather Stations Near a Place Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /api/2.0/monitors/weather/place/` lists the weather stations (CIMIS) inside and near a place, closest first, and the SDK wraps it as `getWeatherStationsForPlace`.

**Architecture:** A cached selector in `camp/apps/regions/resolve.py` turns a resolved place into an ordered list of `(station pk, miles, inside)`; a thin endpoint in a new `camp/api/v2/monitors/places.py` resolves the place, reads the selector, and serializes the stations fresh with `MonitorSerializer` plus `distance` and `inside`. The SDK adds the wrapper and widens its entry-type list to the CIMIS types.

**Tech Stack:** Django 5 / GeoDjango (PostGIS), django-resticus; Deno + Zod (sdk-js).

**Spec:** `docs/superpowers/specs/2026-11-05-get-data-place-layers-design.md` (sections "How the dashboard names a place", "Item 2", "SDK").

## Global Constraints

- Place addressing is `resolve_place()` / `place_json()` from `camp/apps/regions/resolve.py`, unchanged: `?region_type=&region=` (retired regions answer; `land_use` is a 400) or `?monitor=` (hidden 404; no position 400). Errors as `calheatscore/place/` returns them: `{error}`, 400 or 404.
- Response: `{"data": {"place": <place_json>, "stations": [<MonitorSerializer row> + "distance" + "inside"]}}`.
- Stations: monitor types from `Monitor.get_opt_in_subclasses('weather')` (today CIMIS); `is_hidden=False`; `position` set; active within `settings.MONITOR_ACTIVE_WINDOW_DAYS` days (90), **not** the type's `LAST_ACTIVE_LIMIT`.
- Order: every station inside the place (`distance` 0, `inside: true`, sorted by distance from the place's point-on-surface); then up to **5** outside within **25 miles** (inclusive), sorted by distance from the place's edge; when the list would be empty, the single nearest station however far.
- Monitor place: distances from the monitor's position; `inside` is true only for the monitor itself when it is a station.
- `distance` in miles, rounded to 0.1, measured on the spheroid.
- Server-side cache of the selection 24h keyed with `_place_key('weather_stations_for', place)`; station rows serialized fresh. 200 header `public, max-age=900`.
- `monitors/<entry_type>/closest/` is unchanged.
- sdk-js: branch from `origin/release/5.0.0`, PR into it. No `v*` tag, publish or beta without the user's explicit yes for that release. sjvair.com: PR into `develop`; no merge without the user's yes.
- No Claude or AI attribution in commits, PRs or docs.

## Decision recorded here (no user question)

`monitorEntryTypeSchema` stays a `z.enum` and gains the 12 CIMIS entry ids. Reasons, from the code: SDK responses aren't parsed at runtime (`jsonCall<T>` is a type cast; only `lib/schema.ts` test helpers and `documents` parse), so the enum's job is compile-time typing and autocompletion of `entryType` in `getMonitorEntries`, `getMonitorSummaries`, etc. A metadata-driven list can't give static types. The account subscription schema also uses the enum; widening it is harmless (the server refuses unsupported subscriptions). Item 4 needs the same ids: whichever of item 2 and item 4 merges into `release/5.0.0` first adds them, and the other rebases.

## Review Focus

1. **A region without a boundary** (`boundary_id` null) → 200 with `stations: []`; nothing to measure from, and the "at least one" rule can't apply.
2. **A monitor place that is itself a station** → that station first, `distance: 0`, `inside: true`, and not repeated in the outside list.
3. **A place far from every station** (nothing inside, nothing within 25 mi) → exactly one row, the nearest, with its real distance.
4. **Stations that shouldn't appear**: hidden, no position, inactive for more than 90 days, or a non-weather type (a PurpleAir sitting inside the region) → never listed, even as the "at least one" fallback.
5. **A retired region** → answers like a current one (resolve uses `all_objects`).

---

### Task 1: Station selector `weather_stations_for(place)`

**Files:**
- Modify: `camp/apps/regions/resolve.py` (add constants + function after `forecast_zone_for`)
- Test: `camp/apps/regions/tests/test_resolve.py` (new class `WeatherStationsForTests`; reuse the module's `make_region`)

**Interfaces:**
- Consumes: `_place_key`, `_place_geometry`, `CACHE_TIMEOUT` (same module); `Monitor.get_opt_in_subclasses`, `subclass.type_queryset_filter()`, `MonitorQuerySet.get_active(seconds)`.
- Produces:
  - `STATION_RADIUS_MILES = 25`, `STATION_OUTSIDE_LIMIT = 5`
  - `weather_stations_for(place: Region | Monitor) -> list[tuple[str, float, bool]]` — `(station pk as str, miles rounded to 0.1, inside)`, in response order.

Test geometry (lat ~36.75, where 0.1° of longitude ≈ 5.54 mi): region `make_region('Box County', Region.Type.COUNTY, 'box', (-119.9, 36.6, -119.6, 36.9))`. Stations via a helper `make_station(name, number, lon, lat, **kw)` that creates a `CIMIS` (`location=CIMIS.LOCATION.outside`) and, unless `active=False`, calls `station.create_entry(entry_models.Temperature, timestamp=timezone.now(), value=60, sensor='')` so a `LatestEntry` exists. Call `cache.clear()` in `setUp`.

- [ ] **Step 1: Write the failing tests**

```python
def test_inside_first_then_nearby_outside(self):
    a = make_station('A', '1', -119.75, 36.75)    # inside, at the middle
    b = make_station('B', '2', -119.62, 36.88)    # inside, near a corner
    c = make_station('C', '3', -119.50, 36.75)    # 0.1° east of the edge ≈ 5.5 mi
    make_station('D', '4', -119.00, 36.75)        # ≈ 33 mi: beyond 25
    rows = weather_stations_for(self.region)
    assert [r[0] for r in rows] == [str(a.pk), str(b.pk), str(c.pk)]
    assert rows[0][1:] == (0.0, True) and rows[1][1:] == (0.0, True)
    assert rows[2][2] is False and abs(rows[2][1] - 5.5) <= 0.2

def test_at_most_five_outside(self):
    # seven stations east of the edge, 0.02° apart, all within 25 mi
    ids = [make_station(f'S{i}', str(10 + i), -119.58 + 0.02 * i, 36.75).pk for i in range(7)]
    rows = weather_stations_for(self.region)
    assert [r[0] for r in rows] == [str(pk) for pk in ids[:5]]

def test_far_place_gets_single_nearest(self):
    far = make_station('Far', '5', -119.00, 36.75)
    make_station('Farther', '6', -118.50, 36.75)
    rows = weather_stations_for(self.region)
    assert len(rows) == 1 and rows[0][0] == str(far.pk) and rows[0][2] is False
    assert 30 < rows[0][1] < 36

def test_excluded_stations(self):
    make_station('Hidden', '7', -119.75, 36.75, is_hidden=True)
    make_station('Stale', '8', -119.74, 36.75, active=False)
    make_station('Old', '9', -119.73, 36.75, latest=timezone.now() - timedelta(days=91))
    make_station('NoPos', '10', None, None)
    PurpleAir.objects.create(name='PA', sensor_id=1, position=Point(-119.75, 36.76, srid=4326))
    assert weather_stations_for(self.region) == []

def test_monitor_place_measures_from_monitor(self):
    pa = PurpleAir.objects.create(name='PA', sensor_id=1, position=Point(-119.75, 36.75, srid=4326))
    near = make_station('Near', '11', -119.70, 36.75)   # ≈ 2.8 mi
    rows = weather_stations_for(pa)
    assert rows == [(str(near.pk), rows[0][1], False)] and abs(rows[0][1] - 2.8) <= 0.2

def test_station_place_is_itself_first(self):
    me = make_station('Me', '12', -119.75, 36.75)
    other = make_station('Other', '13', -119.70, 36.75)
    rows = weather_stations_for(me)
    assert rows[0] == (str(me.pk), 0.0, True)
    assert [r[0] for r in rows] == [str(me.pk), str(other.pk)]

def test_region_without_boundary_is_empty(self):
    make_station('A', '1', -119.75, 36.75)
    bare = make_region('Bare', Region.Type.CITY, 'bare', None)
    assert weather_stations_for(bare) == []

def test_answer_is_cached(self):
    make_station('A', '1', -119.75, 36.75)
    weather_stations_for(self.region)
    with self.assertNumQueries(0):
        weather_stations_for(self.region)
```

(`make_station(..., latest=dt)` sets the entry timestamp; `active=False` makes no entry.)

- [ ] **Step 2: Run to verify they fail**

Run (from the worktree, with `.env` and `.env.test` copied in): `podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token -v $PWD:/app:z -v ~/workspace/django-resticus/.worktrees/session-csrf/resticus:/usr/local/lib/python3.14/site-packages/resticus:ro,z -w /app sjvair-com-test:latest pytest camp/apps/regions/tests/test_resolve.py -k WeatherStationsFor -v`
Expected: FAIL with `ImportError: cannot import name 'weather_stations_for'`.

- [ ] **Step 3: Implement `weather_stations_for` in `camp/apps/regions/resolve.py`**

Approach: cache check first (`cache.get(key)`; an empty list is a valid cached answer, so use a sentinel like `_MISS`). Base queryset: `Monitor.objects.filter(is_hidden=False, position__isnull=False)` OR-ed over `type_queryset_filter()` of `Monitor.get_opt_in_subclasses('weather')` (as `MonitorList.get_queryset` does), then `.get_active(settings.MONITOR_ACTIVE_WINDOW_DAYS * 86400)`. `get_active` adds `.distinct()`; if ordering by a `Distance` annotation clashes with it, filter activity with `Exists(LatestEntry ...)` instead. Inside (region): `position__intersects=geometry`, ordered by `Distance('position', geometry.point_on_surface, spheroid=True)`. Outside: exclude the inside pks (and, for a monitor place, the monitor itself), annotate `Distance('position', geometry_or_point, spheroid=True)`, keep `distance <= D(mi=25)`, order by distance, first 5; if both lists are empty, the first row of the same queryset without the 25 mi filter. Confirm `Distance(..., spheroid=True)` against a MultiPolygon gives metres on this PostGIS (the 5.5 mi assertion checks it); if not, cast to geography. Return pks as `str`, miles as `round(d.mi, 1)`, inside stations `0.0`.

- [ ] **Step 4: Run to verify they pass**

Same command. Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/regions/resolve.py camp/apps/regions/tests/test_resolve.py
git commit -m "feat(regions): weather_stations_for selects stations near a place"
```

### Task 2: `monitors/weather/place/` endpoint, URL and docs

**Files:**
- Create: `camp/api/v2/monitors/places.py`
- Modify: `camp/api/v2/monitors/urls.py` (add the route directly after `meta/`)
- Modify: `CLAUDE.md` ("Metadata Endpoints" → the "Place endpoints" bullet)
- Test: `camp/api/v2/monitors/tests/test_weather_place.py`

**Interfaces:**
- Consumes: `weather_stations_for` (Task 1); `resolve_place`, `place_json`, `PlaceError`, `PlaceNotFound`; `MonitorSerializer`.
- Produces: `WeatherStationsPlace(generics.Endpoint)`; URL name `api:v2:monitors:weather-place` at `monitors/weather/place/`.

- [ ] **Step 1: Write the failing tests**

Reuse Task 1's `make_station` pattern (copy the helper into the test module) and a county `make_region(...)` with code `box`.

```python
def test_region_lists_stations(self):
    a = make_station('A', '1', -119.75, 36.75)
    c = make_station('C', '3', -119.50, 36.75)
    response = self.client.get(self.url, {'region_type': 'county', 'region': 'box'})
    assert response.status_code == 200
    assert response['Cache-Control'] == 'public, max-age=900'
    body = response.json()['data']
    assert body['place'] == {'region': {'type': 'county', 'external_id': 'box', 'name': 'Box County'}}
    assert [s['id'] for s in body['stations']] == [str(a.pk), str(c.pk)]
    assert body['stations'][0]['type'] == 'cimis'
    assert body['stations'][0]['distance'] == 0.0 and body['stations'][0]['inside'] is True
    assert body['stations'][1]['inside'] is False

def test_monitor_place(self):
    me = make_station('Me', '12', -119.75, 36.75)
    body = self.client.get(self.url, {'monitor': str(me.pk)}).json()['data']
    assert body['place'] == {'monitor': str(me.pk)}
    assert body['stations'][0]['id'] == str(me.pk)

def test_no_stations_is_empty_200(self):
    response = self.client.get(self.url, {'region_type': 'county', 'region': 'box'})
    assert response.status_code == 200 and response.json()['data']['stations'] == []

def test_retired_region_answers(self):
    self.region.retired_at = timezone.now(); self.region.save()
    make_station('A', '1', -119.75, 36.75)
    response = self.client.get(self.url, {'region_type': 'county', 'region': 'box'})
    assert response.status_code == 200 and len(response.json()['data']['stations']) == 1

def test_errors(self):
    assert self.client.get(self.url).status_code == 400
    assert self.client.get(self.url, {'region_type': 'land_use', 'region': '1'}).status_code == 400
    assert self.client.get(self.url, {'region_type': 'county', 'region': 'nope'}).status_code == 404
    hidden = make_station('H', '20', -119.75, 36.75, is_hidden=True)
    assert self.client.get(self.url, {'monitor': str(hidden.pk)}).status_code == 404

def test_url_does_not_shadow_monitor_routes(self):
    assert resolve('/api/2.0/monitors/weather/place/').func.view_class is WeatherStationsPlace
    assert resolve('/api/2.0/monitors/pm25/closest/').url_name == 'monitor-closest'
    assert resolve('/api/2.0/monitors/weather/').url_name == 'monitor-detail'
```

- [ ] **Step 2: Run to verify they fail**

Run: the Task 1 command with `pytest camp/api/v2/monitors/tests/test_weather_place.py -v`.
Expected: FAIL (`NoReverseMatch` for `weather-place` / import error).

- [ ] **Step 3: Implement `WeatherStationsPlace.get(request)` in `camp/api/v2/monitors/places.py` and the route**

Shape after `CalHeatScorePlace.get`: resolve → 404/400 as heat does; `rows = weather_stations_for(place)`; fetch the monitors with `Monitor.objects.filter(pk__in=...).select_related('health').prefetch_related('latest_entries').with_last_entry_timestamp()` (the `MonitorMixin` queryset; the inheritance iterable yields the CIMIS subclass), serialize each with `MonitorSerializer`, add `distance` and `inside` from the row, keep the rows' order, and drop any pk no longer found (a station hidden since the answer was cached). Route: `path('weather/place/', places.WeatherStationsPlace.as_view(), name='weather-place')` right after `meta/`.

CLAUDE.md: extend the "Place endpoints" bullet with one sentence: `monitors/weather/place/` (same addressing) lists weather-dataset stations active within `MONITOR_ACTIVE_WINDOW_DAYS`: inside the place first (distance 0, `inside`, by distance from the point-on-surface), then up to 5 within 25 miles by distance from the edge, always at least the nearest one; `distance` in miles; selection cached 24h in `resolve.py` (`weather_stations_for`), rows serialized fresh.

- [ ] **Step 4: Run to verify they pass**

Same command. Expected: 6 passed. Then the full suite (baseline on `develop` 0a603d90 first, same command with `pytest -n 4 --dist loadscope`); expected: no new failures against the baseline.

- [ ] **Step 5: Hand check on the shared stack (ask the coordinator `data-dashboard-b7` before swapping the web container; tell them when it's back)**

Serve the branch (copy `docker-compose.override.yml`, `.env`, `.env.test` into the worktree; `podman stop sjvaircom_web_1 && podman rm sjvaircom_web_1`; from the worktree `podman-compose -p sjvaircom --profile web up -d --no-deps web`). Check `curl -s 'localhost:8000/api/2.0/monitors/weather/place/?region_type=county&region=06039' | jq '.data.stations[] | {name, distance, inside}'` (Madera: no station inside, ≥ 1 row) and `...region=06019` (Fresno: 7 inside first). Restore the main checkout the same way.

- [ ] **Step 6: Commit**

```bash
git add camp/api/v2/monitors/places.py camp/api/v2/monitors/urls.py camp/api/v2/monitors/tests/test_weather_place.py CLAUDE.md
git commit -m "feat(monitors): weather stations near a place (monitors/weather/place/)"
```

---

## SDK (sdk-js, branch `feature/weather-stations-place` from `origin/release/5.0.0`)

Run checks with: `deno fmt --check && deno lint && deno check mod.ts && deno test --allow-net --allow-env --allow-read --env-file=.env` against the local API, skipping the account tests (they send a real SMS). The `closest/` steps fail locally when the DB has no current PM2.5; that's not this change.

### Task 3: CIMIS entry types in `monitorEntryTypeSchema`

**Files:**
- Modify: `lib/monitors/schemas/monitor_entry_type.ts` (both the `MonitorEntryTypeSchema` type literal and the `z.enum` list)
- Modify: `CHANGELOG.md` (5.0.0 section, "Added")
- Test: `lib/monitors/mod_test.ts`

**Interfaces:**
- Produces: `MonitorEntryType` now also includes `"dewpoint" | "soiltemperature" | "windspeed" | "winddirection" | "precipitation" | "solarradiation" | "netradiation" | "vaporpressure" | "eto" | "etr"` (`temperature` and `humidity` are already there). Item 4 relies on these; if item 4 already added them, skip this task.

- [ ] **Step 1: Write the failing test** — a step asserting `monitorEntryTypeSchema.safeParse(id).success` for each of the 12 CIMIS ids (`temperature, humidity, dewpoint, soiltemperature, windspeed, winddirection, precipitation, solarradiation, netradiation, vaporpressure, eto, etr`), and a type-level use `const t: MonitorEntryType = "eto";`.
- [ ] **Step 2: Run** `deno test --allow-net --allow-env --allow-read --env-file=.env lib/monitors/mod_test.ts` — Expected: FAIL (`deno check` error on `"eto"` / safeParse false).
- [ ] **Step 3: Add the 10 ids** to both lists, keeping the existing order and appending the new ones; CHANGELOG line: "`MonitorEntryType` includes the CIMIS weather types (`dewpoint`, …, `etr`)."
- [ ] **Step 4: Run** the full SDK check command — Expected: pass (apart from the known local `closest/` note).
- [ ] **Step 5: Commit** `git commit -m "feat(monitors): CIMIS entry types in MonitorEntryType"`

### Task 4: `getWeatherStationsForPlace`

**Files:**
- Create: `lib/monitors/get_weather_stations_for_place.ts`
- Create: `lib/monitors/schemas/weather_stations_for_place.ts` (and re-export from the schemas barrel the module already uses)
- Create: `lib/monitors/fixtures/weather_stations_for_place.json` (captured from the local stack in Task 2 step 5, trimmed to 2 stations)
- Modify: `lib/monitors/types.ts`, `lib/monitors/mod.ts`, `CHANGELOG.md`
- Test: `lib/monitors/mod_test.ts`

**Interfaces:**
- Consumes: `PlaceRef`, `placeSearchParams` (`lib/meta/place.ts`); `monitorDataSchema`; `jsonCall`, `RequestOptions` (`$http`).
- Produces:
  - `weatherStationsForPlaceSchema = z.object({ place: <the place schema heatForPlaceSchema uses>, stations: z.array(monitorDataSchema.extend({ distance: z.number(), inside: z.boolean() })) })`
  - `type WeatherStationsForPlace`, `type WeatherStation` (one row)
  - `getWeatherStationsForPlace(place: PlaceRef, options?: RequestOptions): Promise<WeatherStationsForPlace>` → `jsonCall` to `monitors/weather/place`.

- [ ] **Step 1: Write the failing tests**, modelled on `lib/calheatscore/mod_test.ts`'s place steps: (a) the fixture validates against `weatherStationsForPlaceSchema` (the module's `getSimpleValidationTest`); (b) with `stubFetch`, a region place sends `pathname === "/api/2.0/monitors/weather/place/"`, `region_type`, `region`, and returns `stations[0].inside`; (c) a monitor place sends `monitor` and no `region`; (d) a land-use region throws before any request.
- [ ] **Step 2: Run** `deno test ... lib/monitors/mod_test.ts` — Expected: FAIL (module not found).
- [ ] **Step 3: Implement** the schema, types, wrapper (JSDoc in the `getHeatForPlace` style: what "inside", the 25 mi / 5 rule and "at least one" mean; `distance` in miles), `mod.ts` export, CHANGELOG "Added" line.
- [ ] **Step 4: Run** the full SDK check command — Expected: pass.
- [ ] **Step 5: Commit** `git commit -m "feat(monitors): getWeatherStationsForPlace"`

### Task 5: PRs and notices

- [ ] **Step 1:** Push `feature/weather-stations-place` (sjvair.com, base `develop`; it carries the specs commit if item 1's PR hasn't merged yet) and open the PR; push the sdk-js branch and open its PR into `release/5.0.0`. Bodies: what, why (Get data), test results; no AI attribution.
- [ ] **Step 2:** Tell the coordinator (`data-dashboard-b7`) and `data-dashboard-13`: both PR links, the final response shape, and that no beta is cut until the user says yes.
