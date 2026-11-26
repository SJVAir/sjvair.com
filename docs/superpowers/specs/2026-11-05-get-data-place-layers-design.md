# Get data place layers: pesticides, weather stations, smoke

Release 1, step 3 follow-up (sjvair.com + sdk-js). Drafted 2026-11-05. Asked for by step 4
spec 3 of the SJVAir Dashboard (data-dashboard), the "Get data" page (nav "Data", route
`/workspace/data`; formerly called the Data Explorer). Items 1–3 of four "Get data layers"
additions; item 4 (weather summaries) is `2026-11-05-weather-summaries-design.md`.

## Why

The user decided (2026-11-05, step 4 spec 3) that Get data overlays layers on a place's chart.
Spec 3 ships with air quality, forecasts and burn status, which already work through
`forecasts/place/`. Each layer here appears in the dashboard once its server piece lands, so
nothing here blocks spec 3. **Each item ships on its own** (its own plan, branch and PR), in
the order below.

## How the dashboard names a place

Confirmed with the spec 3 session (2026-11-05). The dashboard's places are a monitor, a region
`{type, code}`, a location (school or child-care site), a map point, or a selection. The client
turns locations and points into the smallest containing region with data (ZIP → city →
county) through `regions/places/lookup/`, so **every request the server sees is a monitor or a
region by `(type, code)`**. Coordinates never go in a URL. Counties and ZIPs matter most
(schools resolve to ZIPs), then cities, then the rest.

So all three endpoints use the existing place addressing in `camp/apps/regions/resolve.py`
(`resolve_place`, `place_json`), exactly as `calheatscore/place/` and `forecasts/place/` do:

- `?region_type=&region=` (a region code; retired regions answer; land use is a 400), or
  `?monitor=` (hidden monitors 404; a monitor without a position is a 400).
- Errors as the heat endpoint returns them: 400 for a bad request, 404 for an unknown place,
  `{error}` body, `no-cache`.
- The response is `{data: {place, ...}}` with `place` from `place_json()`.

## Item 1: monthly pesticide use for a place

### Verified (develop 0a603d90)

- `pesticides/region/<sqid>/summary/` (`PesticideRegionSummary`) groups the **raw**
  `PesticideUse` records by year × chemical × commodity. The catalog lists `month` and `year`
  for `pounds-applied` and `acres-treated` (`camp/api/v2/meta/catalog.py`), but nothing
  serves months.
- `PesticideUseRollup` already holds year × month (0 when the record has no application
  date) per county and MTRS section; the section endpoints read it. Locally, month 0 is 5
  rows out of ~5 million.

### Decisions (the user, 2026-11-05)

- **One total per month for the place by default**, narrowed by the existing filters
  (`chemical`, `commodity`, `category`, `iarc_group`, `aerial_ground`). Not a
  per-chemical breakdown: the chart overlays one line on a place's timeline, and a
  chemical × commodity × month breakdown is ~12× today's rows.
- **Read the rollup**, not the raw records.
- **Region rule:** a county uses its own rollup rows (`county=`); any other region sums the
  MTRS sections that touch it (the rule the region endpoints already use; the spec 3 session
  confirmed it). A ZIP therefore counts every one-square-mile section touching it, edges
  included; that is the existing behavior and is accepted.
- **Monitor places use the ZIP the monitor sits in**, `zips_for(monitor)` (the heat rule). A
  monitor outside every ZIP answers with empty lists.
- **Undated records** (month 0) never land on a month. They come back per year as an
  `undated` total. The dashboard will likely leave them off the chart and show them in the
  table and CSV.
- **The old endpoint** `region/<sqid>/summary/` stays unchanged.

### The contract

`GET /api/2.0/pesticides/place/?region_type=&region=` or `?monitor=`

Filters (all optional, combinable): `chemical` (chem code), `commodity` (site code),
`category`, `iarc_group`, `aerial_ground` (the existing summary filter's names and values),
`year__gte`, `year__lte`. Without a year range: every imported year. An invalid filter value
is a 400.

```json
{"data": {
  "place": {"region": {"type": "county", "external_id": "06019", "name": "Fresno County"}},
  "months": [
    {"year": 2023, "month": 1, "pounds": 812345.6, "acres": 120345.0, "applications": 5321}
  ],
  "years": [
    {"year": 2023, "pounds": 9876543.2, "acres": 1500000.0, "applications": 64000,
     "undated": {"pounds": 12.0, "acres": 3.0, "applications": 1}}
  ]
}}
```

- `months`: only months with use (no zero rows), ordered by year, month. The client fills
  gaps; a month with no row has no reported use.
- `years`: one row per year that has any use (a year whose only use is undated still gets a
  row). **A year's `pounds`, `acres` and `applications` include its undated records**, so
  `undated` is a part of them and the sum of a year's `months` plus its `undated` equals the
  year total. `undated` is zeros when there are none.
- Labels and units come from the catalog's `pounds-applied` (lbs) and `acres-treated`
  (acres), not from this response.

### Counting (the plan settles the exact rule; these are the constraints)

`PesticideUseRollup` has two sets of columns (see the model's comment):

- Per ingredient row: `lbs_chemical`, `acres_treated`, `applications`. Right only when the
  rows are restricted to one chemical.
- Once per use record (on a designated row): `records`, `acres_once`, `lbs_product_once`.
  What any sum across chemicals must read.

`pounds` is always pounds of active ingredient (`lbs_chemical`); summing that across
chemicals is correct. For `acres` and `applications`: with a `chemical` filter, read the
per-ingredient columns; with no chemical-narrowing filter, read the once-per-record columns.
A `category` or `iarc_group` filter selects several chemicals, and neither set is right as
is: a record with two matching ingredients counts twice per ingredient, and the record's
designated row may be a non-matching ingredient. **The plan must work out a correct rule for
that case** (and test it against the raw records), or bring the problem back before building.

### Builder's calls

- Cache: the data changes only when a PUR year is imported. Suggested `public, max-age=3600`
  plus the 24h server-side cache of the place → sections resolution (like `zips_for`);
  whether to also cache the aggregate is the plan's call, with the import invalidating it.
- Performance: a county is an indexed filter; for other regions, resolve the section set once
  (cached) and sum `mtrs__in=`. Measure a large region (Fresno County via sections isn't
  needed: counties use `county=`; measure a big city and an AB 617 community).

## Item 2: weather stations near a place

### Verified

- `monitors/<type>/closest/` leaves CIMIS out twice: `get_public()` keeps only
  `MONITOR_ENABLED_TYPES`, and `published_for()` needs a `DefaultCalibration` row, which no
  weather type has. It also takes coordinates in the query string, which the dashboard
  doesn't send.
- Locally: 23 CIMIS stations, all active. Uneven: Fresno County holds 7, Madera County none.
  A station's nearest neighbour is 15–123 km away (median ~29 km).

### Decisions (the user, 2026-11-05)

- **A list of nearby stations, closest first**, not one chosen station; the dashboard shows
  the first by default and lets the person pick or compare.
- **Which stations:**
  - every station inside the place, at distance 0, `inside: true`, sorted by distance from
    the place's point-on-surface;
  - then up to 5 stations outside it within 25 miles, sorted by distance from the place's
    edge;
  - **always at least one**: when nothing is inside or within 25 miles, the single nearest
    station, however far.
- For a monitor place, distance is from the monitor's position; `inside` is true only for
  the monitor itself when it is a station.
- `closest/` stays unchanged.

### The contract

`GET /api/2.0/monitors/weather/place/?region_type=&region=` or `?monitor=`

```json
{"data": {
  "place": {"region": {"type": "county", "external_id": "06039", "name": "Madera County"}},
  "stations": [
    {"...": "the normal monitor row (MonitorSerializer)", "distance": 7.4, "inside": false}
  ]
}}
```

- `distance` in miles, rounded to 0.1.
- Stations are the weather dataset's monitor types (`Monitor.get_opt_in_subclasses('weather')`,
  today CIMIS), non-hidden, with a position, active within `MONITOR_ACTIVE_WINDOW_DAYS` (the
  `current/` window, 90 days; not CIMIS's 3-hour `LAST_ACTIVE_LIMIT`, which a lagging feed
  would trip).
- Readings come from the existing monitor entries endpoints (hourly raw today; daily and
  monthly once item 4 lands).

### Builder's calls

- Cache: the place → station-ids answer cached 24h server-side (like the other place answers,
  keyed with `_place_key`); the monitor rows serialized fresh so `latest` data isn't stale.
  Response `public, max-age=900` like heat.
- Distances on the geography (spheroid), as `closest/` does.
- URL placement in `camp/api/v2/monitors/urls.py` must not collide with
  `monitors/<monitor_type>/...` or `monitors/<monitor_id>/...` patterns.

## Item 3: smoke over a place, per day

### Verified

- `hms/smoke/` returns raw HMS outlines (`Smoke`: `date`, `density` light/medium/heavy,
  `geometry`) filtered by region and date. Nothing per day or per place.
- The ingest (`camp/apps/hms/tasks.py`) fetches the day's file about hourly from ~8am to
  ~8pm Pacific, plus a final pass for the previous day at 21:00 UTC. It keeps outlines that
  touch the valley. An empty file stores nothing, the same as a fetch that never ran.
- The smoke scale (`hms/meta/`, id `smoke-density`) has levels `light`, `medium`, `heavy` and
  no "none" level.

### Decisions (the user, 2026-11-05)

- **Both** the heaviest density over the place and how much of it was covered.
- **Coverage** is the share of the place's area under at least light, at least medium, and at
  least heavy smoke: three numbers 0–1, correct when outlines of different densities overlap
  (union the outlines at or above each level, then intersect with the place).
- **Computed on request and cached**, not stored. No backfill.
- **No "no data" distinction:** a day with no outlines reads as no smoke. Telling "no smoke"
  from "never fetched" would need a per-day fetch record (a new table); deferred, see below.
- `hms/smoke/` stays unchanged.

### The contract

`GET /api/2.0/hms/smoke/place/?region_type=&region=` or `?monitor=`, with `date__gte`,
`date__lte` (Pacific dates).

```json
{"data": {
  "place": {"monitor": "abc123"},
  "days": [
    {"date": "2026-10-27", "density": "heavy",
     "coverage": {"light": 1.0, "medium": 0.62, "heavy": 0.15}},
    {"date": "2026-10-29", "density": null,
     "coverage": {"light": 0.0, "medium": 0.0, "heavy": 0.0}}
  ]
}}
```

- One row per day in the range, no holes, ascending.
- `density` is a `smoke-density` level key or `null` for no smoke.
- For a monitor (a point), coverage values are 0 or 1.
- Range: no range means the last 30 days through today; at most 366 days (a longer range is
  a 400, as is `date__gte` after `date__lte`). Only `date__gte`/`date__lte` are accepted.

### Builder's calls

- Area math in an equal-area projection (e.g. California Albers, EPSG:3310) or on geography;
  not in degrees.
- Caching: a day is settled once the next day's final pass has run (after 21:00 UTC on the
  following day, with a margin). A response whose whole range is settled can be cached long;
  otherwise short (the summaries' settled/short pattern). Server-side caching per place and
  day is the plan's call.
- Performance: a year of days for a county with complex boundaries. Do it in one SQL query
  per request where possible, not per day in Python; measure on Fresno County.

## SDK (sdk-js, `release/5.0.0`)

Per item, in the same order, each its own PR into `release/5.0.0`:

- Item 1: `getPesticidesForPlace(place, filters)` + schema.
- Item 2: `getWeatherStationsForPlace(place)` + schema (stations extend the monitor schema with
  `distance`, `inside`), **and** the CIMIS entry types added to `monitorEntryTypeSchema` (9
  types today) so `getMonitorEntries` accepts them. The plan checks whether that list should
  be derived from server metadata instead of a fixed enum; shared with item 4.
- Item 3: `getSmokeForPlace(place, range)` + schema.

Names follow the existing `getHeatForPlace` / `getForecastForPlace`, and the place argument
is the same type those take. **No beta is cut without the user's yes for that specific release**; how betas
are grouped across items is asked when the first SDK PR is ready.

## Deferred (data-dashboard `DEFERRED.md`)

- **Pesticide use within a distance of any place** (schools, points, monitors), instead of
  region membership. Revisit when the dashboard wants a distance option or users ask about
  nearby use.
- **Smoke "no data" vs "no smoke"**: a per-day record of successful HMS fetches, so a missed
  day reads as unknown. Revisit when a missed day turns up in production data or users report
  false clear days.

Fires within a distance or per day, TEMPO, and emissions were already out of scope; their
`DEFERRED.md` entries are checked (added if missing) with this work.

## Shipping

Nothing touches production. Items 1–3 need no migration, data step or deploy step. Each PR
goes into `develop` only with the user's yes.
