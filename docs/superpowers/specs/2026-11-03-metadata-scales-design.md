# Metadata enablers, second batch, spec 1: scales, tiers, hierarchy, hints, wrappers

**Status: DRAFT, still being brainstormed (2026-11-03). Not approved. No code until it is.**

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
Level  { key (permanent), label, color, tier (0–4 or null), description, guidance,
         min/max (range scales) | value (category scales) }
```

- `description`: official wording, quoted and credited (CalHeatScore's interpretation table
  for heat).
- `guidance`: SJVAir's short "what to do" line. **Empty for AQ "Good" and heat "Low"**
  (decided with the user).
- Each scale is built server-side from one source per domain (`entries/levels.py` stays the
  single source for AQ). Each domain's meta endpoint serves its own scales; the catalog's
  `meta_url` points at them.

### 2. Scales per domain

- **Air quality (`monitors/meta/`)**: existing per-pollutant levels gain `tier`: Good 0,
  Moderate 1, USG 2, Unhealthy 3, Very Unhealthy 4, Hazardous 4. The server's extra
  "Very Hazardous" level is also 4 (_my call_).
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
  not as a general AQ scale. Also burn status as a category scale ("Discouraged",
  "Registered", …) and the forecast zone list (for the "containing zone" rule).
- **HMS (`hms/meta/`, new)**: smoke density Light 1, Medium 2, Heavy 3 (decided with the
  user); fire FRP classes (<10, 10–49, 50–149, 150–349, ≥350 MW). Colors move unchanged
  from monitor-map's hardcoded values so map-sdk can drop its copies (_my call_).
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

Each type gains `count` (current regions), `parents` (types it can be browsed under, e.g.
city/CDP/ZIP/tract/school district under county), `referenceable` (`false` for land use),
and `summarized` (_my call_ on the field set).

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
  table and "where this number comes from" notes. Drafted from the code for the user's
  approval.
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
- **Forecast for an area** = the forecast zone containing the area's center
  (point-on-surface); a zone region is itself. The response names the zone used.
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
processor labels, and catalog display hints. All take the 4.7.0 request options
(`signal`/`init`).

## Later specs (agreed order: this one first)

- **Pesticides** (its own spec, agreed with the user 2026-11-03): `pesticides/meta/` (badges,
  categories, IARC groups, the "flagged" rule, methods with colors, narrowing choices, the
  health notes in `datafiles/pesticide-health-notes.yaml`), aggregate endpoints for widgets
  (place totals, time series, top lists, movers) reusing the explorer's cached stats, and
  the explorer reading the same metadata. Research notes:
  data-dashboard `docs/reference/pesticides-explorer-research.md`.
- Cache headers on summary endpoints; location name search and wrappers;
  `places/lookup/` by rounded coordinates (POST) or `?monitor=`; remaining sdk-js wrappers
  (`calenviroscreen/`, `regions/geojson/`, `buffer`) and `api-urls.md`; hardcoded-value
  cleanup in sjvair.com.
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
