# Metadata enablers, second batch, spec 1: scales, tiers, hierarchy, hints, wrappers

**Status: approved by the user (2026-11-03).**

Repos: sjvair.com (branch from `origin/develop`, PR into `develop`) and sdk-js (branch from
`origin/release/4.8.0`, PR into it). First batch: sjvair.com #293
(`2026-10-22-metadata-enablers-design.md`) and sdk-js #32.

## Why

The SJVAir Dashboard (data-dashboard) takes every label, unit, breakpoint, color, and scale
from server metadata. Release 1 step 4 (Widget Creation and the non-map widgets: Current
conditions, Forecast strip, "Can we go outside?", charts, calendars, heatmap, data table,
the shared place picker) needs, first:

- per-domain scale metas with a shared 0–4 action `tier`;
- region hierarchy metadata for the place picker;
- display hints and readable stage/processor labels;
- sdk-js wrappers for forecasts and CalHeatScore.

The rest of the second batch (cache headers, location search, `places/lookup/` by
coordinates, the remaining wrappers, cleanup) comes in later specs (see "Later specs").

## Decided so far

### 1. One scale shape for every domain

```
Scale  { id, label, units, kind: "range" | "category", levels: Level[] }
Level  { key (permanent), label, color, opacity (0–1 or null), tier (0–4 or null),
         description, guidance, min/max (range scales) | value (category scales) }
```

- `description`: official wording, quoted, with the source credited once per scale
  (`Scale.source: { name, url }`). Sources (_my call_): heat, CalHeatScore's interpretation
  table; AQ levels and the AQI scale, EPA's AQI category descriptions (AirNow "AQI Basics",
  US government, public domain); burn status, the Valley Air feed's own status text. Smoke
  and fire have no official per-level text, so their `description` is empty.
- `guidance`: SJVAir's short "what to do" line. **Empty for AQ "Good" and heat "Low"**
  (decided with the user).
- Each scale is built server-side from one source per domain (`entries/levels.py` stays the
  single source for AQ). Each domain's meta endpoint serves its own scales; the catalog's
  `meta_url` points at them.
- **Which scale goes with which data** (_my call_): a domain meta's `scales` are keyed by the
  catalog entry-type id they describe (`pm25`, `o3`, `heat-score`, `aqi-forecast`,
  `burn-status`, `smoke-density`, `fire-frp`). Burn status becomes a catalog entry type
  `burn-status` (kind `other`, resolution `day`) in the `forecasts` dataset.
- **Range boundaries** (_my call_): levels are half-open, `min <= value < max`; the top
  level's `max` is `null`. Values are compared as given (no rounding by the client).

### 2. Scales per domain

- **Air quality (`monitors/meta/`)**: tiers Good 0, Moderate 1, USG 2, Unhealthy 3, Very
  Unhealthy 4, Hazardous 4. The server's extra "Very Hazardous" level is also 4 (_my call_).
  **No breaking change** (_my call_; batch 1's anti-goal): each entry type keeps today's
  `levels` dict exactly as sdk-js's schema, monitor-map, and mobile read it (uppercase keys,
  `name`, `range` with "next minus 0.1"), with `tier` added to each entry; and gains a new
  `scale` field in the shared shape, which the dashboard reads. Both come from the same
  `LevelSet`. Kept compatible on purpose (the user's call, 2026-11-03): installed mobile
  apps read the old dict for alerts and can't be forced to update. A test asserts the two
  agree. Retiring the old dict is deferred (data-dashboard `DEFERRED.md` → "Mobile app").
- **Heat (`calheatscore/meta/`, new)**: Low 0, Mild 1, Moderate 2, High 3, Severe 4.
  Colors from CalHeatScore's official interpretation table: 1 `#fae0c8`, 2 `#ea8753`,
  3 `#c23a00`, 4 `#700006`; score 0 has none there, so `#DEDEDE` from their API example
  (_my call_). Descriptions are the official "Meaning" text. Guidance (approved by the user):

  | Score      | Guidance                                                                                                                                         |
  | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
  | 0 Low      | (none)                                                                                                                                           |
  | 1 Mild     | People sensitive to heat should drink extra water and take breaks somewhere cool.                                                                |
  | 2 Moderate | People sensitive to heat should limit time outdoors in the afternoon, drink extra water, and stay somewhere cool during the hottest hours.        |
  | 3 High     | Everyone should drink extra water, limit strenuous outdoor activity, and spend the hottest hours somewhere cool.                                  |
  | 4 Severe   | Everyone should stay somewhere cool when possible, drink at least 2 glasses of water an hour, and check on people at higher risk.                 |

- **Forecasts (`forecasts/meta/`, new)**: the AQI scale. AQI is used **only** by the Valley
  Air District forecast feed (monitors report concentrations, not AQI), so it lives here,
  not as a general AQ scale. Also burn status as a category scale and the forecast zone
  list (for the "containing zone" rule).
  - **Burn status values** (_my call_): the Valley Air "Check Before You Burn" statuses:
    `discouraged` ("Burning Discouraged"), `registered` ("No Burning Unless Registered"),
    `no_burning` ("No Burning For All"). Only "Discouraged" and "Registered" have been seen
    in the feed locally; the third is from the program's published statuses and should be
    confirmed against the feed during the build. Colors are SJVAir's choice (none are
    published): yellow `#ffff00`, orange `#ff7e00`, red `#ff0000`, borrowing the AQ palette
    (_my call_; the user can change them). A feed value not on the list is still stored
    and served with its feed text as the label, no color, and `tier: null`, and logged so
    the list can be extended.
- **HMS (`hms/meta/`, new)**: smoke density Light 1, Medium 2, Heavy 3 (decided with the
  user); fire FRP classes (<10, 10–49, 50–149, 150–349, ≥350 MW). Colors move unchanged
  from monitor-map's hardcoded values so map-sdk can drop its copies (_my call_). Smoke
  levels also carry monitor-map's fill `opacity` (light `#bfc8c3` 0.2, medium `#757b78`
  0.3, heavy `#333634` 0.4); `opacity` is `null` on every other level (requested by the
  map-sdk session, 2026-11-03, so its smoke preset keeps today's look from metadata).
- **`tier: null`** for fire intensity and burn status: they aren't health conditions, so
  they never outrank air or heat on "Can we go outside?" (_my call_; bends "tier on every
  level of every scale"; the user didn't object).

### 3. CalHeatScore findings (2026-11-03)

CalHeatScore publishes **no official per-score recommended actions**, only per-score risk
descriptions ("Meaning"), a general stay-cool list, and organization-level steps in its
User Guide. ARCHITECTURE.md's "official recommended actions" line must be corrected: tier
meanings rest on the official descriptions; guidance is SJVAir's text. No attribution terms
beyond "© State of California". The API gives today + 6 days, updated 5 and 8 AM Pacific;
the importer already stores all 7 days.

Sources: calheatscore.calepa.ca.gov (interpretation table), /api/, API use-case example 2
(colors), User Guide (Aug 2026), Methods (Feb 2025).

### 4. Region hierarchy (`regions/meta/`)

Each type gains `count` (current regions), `parents` (types it can be browsed under), and
`referenceable` (`false` for land use) (_my call_ on the field set). `parents` is a
hand-written mapping, not computed (_my call_):

- under `county`: city, cdp, zipcode, tract, school_district, urban_area, ab617;
- top level (no parents): county, congressional_district, state_assembly, state_senate,
  air_district, protected, custom (forecast zones);
- not browsable (no parents, reached by search or code only): mtrs (about 28k sections),
  land_use.

No `summarized` flag: any region with a monitor inside gets summaries regardless of type,
so a type-level flag would say nothing; the coverage endpoint already answers per place.

**Regions that cross county lines** (local data: 39 of 237 ZIPs, 27 of 200 school
districts, 2 tracts; cities and CDPs none) show under **every county they meaningfully
overlap** (decided with the user):

- threshold: at least 1% of the region's own area (slivers are under 0.1%; real straddles
  several percent) (_my call_);
- a separate opt-in browse mode (e.g. `within_mode=overlaps`); today's `within=` (99%
  containment) is unchanged (_my call_);
- each result names the other counties it's in (type + code) for "also in Kings County".

### 5. Choice lists and display hints

- **`monitors/meta/`**: labels and descriptions for stages (raw, corrected, cleaned,
  calibrated) and processors (today bare code names like `PM25_EPA_Oct2021`), for the data
  table and "where this number comes from" notes. Drafted from the code; **the plan puts
  the drafted texts in front of the user for approval before they ship** (as with the heat
  guidance).
- **Display hints** per entry type, in the catalog: `precision`, `chart` (line or bar),
  `y_min` (start at zero). Defaults the dashboard uses (_my call_ on the field set).

### 6. Forecast and CalHeatScore APIs and wrappers

Findings: no client (monitor-map, mobile, sdk-js) uses `forecasts/` or `calheatscore/` yet,
so they can be reshaped. `forecasts/` embeds each region's full boundary geometry in every
row (about 700 KB locally) and filters by region sqid only. `calheatscore/` is per ZIP only.

**The server answers for any place** (decided with the user), so the dashboard asks once by
code:

- **Heat for an area** = the highest score among ZIPs overlapping it by **at least 1% of
  the ZIP's area** (same rule as cross-county browsing; decided with the user). A ZIP target
  is itself. The response names the ZIP that set the score and how many ZIPs were
  considered, so the dashboard can label "highest in Fresno County today".
- **Forecast for an area**, in order (_my call_; Kern's and Tulare's centers can miss
  their own zones):
  1. a zone region is itself;
  2. a county uses the zone named after it (the `ZONE_TO_REGION` mapping: e.g. Kern County
     → "Kern (SJV Air Basin portion)", Tulare County → "Tulare (SJV Valley portion)");
  3. otherwise the zone containing the area's point-on-surface;
  4. otherwise the zone the area overlaps most;
  5. otherwise no forecast (`null`), e.g. an area outside the Valley.
  The response names the zone used and which rule picked it, so the dashboard can label
  it.
- Both take a region by code (`region_type` + `region`, the coverage endpoint's
  convention); `?monitor=` (the monitor's position) is _my call_, cheap and useful for
  monitor-targeted "now" widgets. Points wait for the coordinates `places/lookup/` spec.
- **Forecast rows drop the embedded boundary**; `region` becomes `{ id, type, external_id,
  name }`.
- Cost (measured locally, Fresno County): ZIPs touching the county 16 ms, max score per day
  2 ms, containing zone 19 ms. The region → ZIPs and region → zone answers change only on
  boundary re-import: cache them a day or more. Responses cache until the next import
  (heat: 5 and 8 AM Pacific; forecasts: daily). Durations are the builder's call.

**sdk-js** (branch from `origin/release/4.8.0`; no release without the user's yes):
wrappers for `forecasts/` and `calheatscore/` (both modes), the new metas
(`calheatscore/meta/`, `forecasts/meta/`, `hms/meta/`), the shared `Scale`/`Level` types,
`tier` on monitor levels, the region meta fields and the overlap browse mode, stage and
processor labels, and catalog display hints. Also the **`regions/geojson/` wrapper**
(moved from a later spec at the map-sdk session's request, 2026-11-03: forecast rows drop
their boundaries, so map-sdk's region-fill, CalHeatScore-ZIP, and forecast-zone presets
need geometry from it): `type` required, regions by code (`external_id`, several at once),
plus the endpoint's existing `within`, `slug`, `name`, and `simplify` options. All take the
4.7.0 request options (`signal`/`init`).

## Not changed by this spec

- **Dataset licenses** stay as they are (`license: ""` except HMS and TEMPO): the user
  supplies the real texts before go-live (data-dashboard `DEFERRED.md` → "Open decisions").
  CalHeatScore's "© State of California" is noted above for that decision, not applied.

## Later specs (agreed order: this one first)

- **Pesticides** (its own spec, agreed with the user 2026-11-03): `pesticides/meta/` (badges,
  categories, IARC groups, the "flagged" rule, methods with colors, narrowing choices, the
  health notes in `datafiles/pesticide-health-notes.yaml`), aggregate endpoints for widgets
  (place totals, time series, top lists, movers) reusing the explorer's cached stats, and
  the explorer reading the same metadata. Research notes:
  data-dashboard `docs/reference/pesticides-explorer-research.md`.
- Cache headers on summary endpoints; location name search and wrappers;
  `places/lookup/` by rounded coordinates (POST) or `?monitor=`; remaining sdk-js wrappers
  (`calenviroscreen/`, `buffer`) and `api-urls.md`; hardcoded-value cleanup in sjvair.com.
- Production data checks are out of scope (user, 2026-10-20); verify locally, then ask the
  user whether to drop those TODO.md items.

## To record in data-dashboard docs (docs PR from a worktree)

- ARCHITECTURE.md: the scale shape; the CalHeatScore correction; AQI as forecast-only;
  smoke tiers; `tier: null` for non-health scales; the hierarchy fields and overlap browse.
- DEFERRED.md: the pesticide spec; the probable acres double-count (below).

## Open issues found along the way

- **Probable bug**: `api/v2/pesticides/endpoints.py` region summary sums `acres_treated` per
  ingredient row, so a multi-ingredient record's acres count several times (the explorer
  uses the once-per-record fields). Not yet proven with data. Also uncached; Fresno County
  2023 is about 1.8 MB and 2.5 s.
- The pesticide map's server-side and JavaScript color ramps differ.
