# Region Dashboards — Design

**Date:** 2026-09-18
**Branch:** `feature/region-dashboards`
**Audience:** CCAC staff. Builds on the Region admin panels from PR #273.

## Goal

The Region admin change page becomes the dashboard for a region. Staff open
the regions list, click a region, and see numbers first: a tile row, an air
quality trend, and the panels that make sense for that region type. No
separate dashboard pages; the Coverage by Community report keeps linking to
the admin change page.

## Panel plumbing (`camp/apps/regions/panels.py`)

- `Panel.order` (int, default 100). `panels_for()` sorts by order, then
  registration order.
- `Panel.context` is a cached property over `get_context()` so a panel's
  numbers are computed once per request even when both the tile row and
  the body read them.
- `Panel.tiles()` returns a list of `(label, value)` pairs for the header
  row; default empty. Value is a preformatted string.
- The change form template renders a `.region-tiles` row (every panel's
  tiles, in panel order) above the panels. The Region form fields (name,
  slug, external id, type, boundary, metadata, overview map) move into a
  collapsed fieldset titled "Region"; the monitor map stays visible at the
  top. Django's built-in `collapse` fieldset class does the collapsing.
- Panels that read query params (scope toggles, range, pollutant) build
  their links with `MonitorScope.toggle_links`-style helpers that preserve
  the other params.

## Panels

Orders: forecast 5, trend 10, type-specific coverage/CES 20, overlapping
communities 30, monitors 40.

### Air quality trend (every type with a boundary; `camp/apps/summaries/panels.py`)

Source: daily `RegionSummary` rows for the region (`resolution='day'`),
using `mean` only. The daily `maximum` carries raw sensor spikes and is not
shown.

- `?range=30d|90d|ytd|12m` (default `30d`): calendar days ending yesterday,
  Pacific time.
- `?pollutant=<entry_type>` (default `pm25`): choices are the entry types
  with any daily row for this region; the selector is shown only when there
  is more than one.
- Comparison line: for a non-county region, the county Region containing
  the region's centroid; for a county, the mean of all SJV counties' daily
  means for each day. Omitted when there is no such data.
- Tiles: period mean; worst day (date and mean); days at or above the
  pollutant's "Unhealthy for Sensitive Groups" level
  (`EntryModel.Levels.unhealthy_sensitive.value`, 35.5 for PM2.5); stations
  (the latest row's `station_count`).
- Chart: inline SVG from `camp/utils/charts.py` `line_chart()`: the
  region's series, the comparison series dashed, horizontal level bands
  colored from `EntryModel.Levels` at low opacity, month ticks on the x
  axis, a y axis from 0 to a rounded max. No JavaScript.
- With no daily rows in the range, the panel says so and shows no chart.

### Today's forecast (county; `camp/apps/forecasts/panels.py`)

The most recently issued `Forecast` rows for the county region with
`forecast_date` today or later, grouped by date then pollutant: AQI value
with the level color swatch, category, burn status text, air alert dates
when set. Says "no forecast" when empty. Tile: today's highest AQI category.

### Coverage (city, CDP, urban area) — as built, plus tiles

Tiles: population, counted monitors, per 10k. Unchanged otherwise.

### Communities and coverage (county) — as built, plus tiles

Tiles: communities without a monitor, population without a monitor.

### CalEnviroScreen (tract) — indicator grid

Replaces the headline table with an indicator grid built from the newest
CES5 and CES4 records on the region's boundaries:

- Columns: indicator, CES5 value, CES5 percentile, CES4 value, CES4
  percentile.
- Groups: "Pollution burden" (fields starting `pol_`), "Population
  characteristics" (fields starting `char_`), each preceded by its group
  score and percentile (`pollution`/`pollution_p`, `popchar`/`popchar_p`).
- Headline rows above the grid: CES score and percentile, SB535 DAC, DAC
  category, population, for each version.
- A record's full field list stays available collapsed, as now.
- Tiles: CES5 (or CES4 if no CES5) percentile; DAC yes/no.

### Communities overlapping (school district, zip code, legislative districts)

Cities and CDPs whose centroid is inside the region, with population,
monitors, per 10k from `CoverageCommunity.build_rows` filtered to those
places, linking to each place's admin page. Tile: communities inside.

### Outdoor monitors inside — as built, plus tiles

Tiles: active monitors / total.

## Chart helper (`camp/utils/charts.py`)

`line_chart(series, bands=(), width=720, height=240, y_label='')` returns a
`SafeString` SVG. `series` is a list of `{'label', 'points': [(date,
float)], 'color', 'dashed': bool}`; `bands` is a list of `(min_value,
color)` sorted ascending, drawn as background rectangles from each min to
the next. Handles gaps (a point missing for a date breaks the line),
single-point series, and an empty series (renders axes only). Dates on the
x axis are labelled at month starts, or every 7 days for ranges under 60
days. Pure Python, no dependencies.

## Testing

- `camp/utils/tests/test_charts.py`: SVG contains one `<path>` per series,
  one `<rect>` per band, the right number of tick labels, and survives
  empty and single-point input.
- `camp/apps/summaries/tests.py` (or a new panel test class there): a
  helper creates daily `RegionSummary` rows; tests cover tile arithmetic,
  the USG-day count, range and pollutant param validation, the comparison
  line for a city (its county) and for a county (the county mean), and the
  no-data message.
- `camp/apps/forecasts/tests.py`: the panel picks the latest issued rows
  and groups them; the tile shows today's category.
- `camp/apps/regions/tests.py`: panel ordering, tiles rendered in the
  change page header, the collapsed Region fieldset, the tract indicator
  grid values from the CES fixture, the overlapping-communities panel.
- Existing report and panel tests keep passing.

## Out of scope

- Public dashboards, interactive charts, and any JavaScript.
- Pesticide panels (after the pesticides branch merges).
- Alerts panels (after the alerts rework).
- School data (none exists yet).
