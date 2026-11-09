# Scale averaging periods and daily peak figures

Date: 2026-11-09. The server side of data-dashboard step 4, spec 5 (calendars and the hour ×
weekday heatmap). The SDK side will be in sdk-js, `docs/superpowers/specs/2026-11-09-scale-averaging-design.md`.

## Why

The dashboard's calendars color each day by a pollutant's level. Spec 5 decided (the user,
2026-11-09) that each pollutant's day is colored by the daily figure that matches its scale's
averaging period, "because this is how EPA does it":

- 24-hour scales (PM2.5, PM10): the daily mean.
- 1-hour scales (O3, NO2, SO2): the day's highest hourly average.
- 8-hour scales (CO): the day's highest 8-hour average.

The dashboard treats metadata as the source of truth and can't hardcode which scale is which.
Today the server publishes neither the averaging period nor the 1-hour and 8-hour figures.

## How it works today

- `camp/apps/entries/levels.py` defines one `LevelSet` per pollutant. PM25 and PM100 use EPA
  24-hour breakpoints. O3 (Good 0–125 ppb, no Moderate), NO2 and SO2 use 1-hour breakpoints,
  and CO uses 8-hour ones. `AQI` is the index itself (used by the forecast scale,
  `camp/apps/forecasts/scales.py`).
- `LevelSet.to_scale()` builds a `camp.utils.scales.Scale`, and `Scale.to_json()` is the shape
  published in `monitors/meta/` `entries.<type>.scale` (`get_scale` in
  `camp/api/v2/monitors/endpoints.py`) and in the HMS, heat and forecast meta endpoints. It has
  no averaging period. Entry types without `Levels` publish `scale: null`.
- Summaries (`camp/apps/summaries/`): hourly rows are computed from raw entries
  (`compute_monitor_summary`) and from monitor hourly rows for regions. Daily rows are rolled
  up from hourly rows (`rollup_monitor_summaries` / `rollup_region_summaries` in `tasks.py`,
  `rollup_summaries` / `rollup_region_stats` in `aggregators.py`), and longer resolutions from
  daily rows. `maximum` is the max of maxes, i.e. the highest single raw reading, not the highest
  hourly average. One local VOZBox day had a `maximum` of 4343 µg/m³.
- Monitor hourly `is_complete` is `count >= 0.8 * expected_count`. Region rows have no
  `is_complete`.
- The daily rollups run at 01:00 (monitors) and 01:10 (regions) Pacific (`ROLLUP_LOCAL_TIME['day']`
  is 01:10). The summaries
  endpoints cache a settled range for a day: `is_settled` with `SETTLE_MARGIN['day']` = 3 h, or
  `LATE_SETTLE_MARGIN` (7 h) for the CIMIS switch types.
- `rebuild_summaries` narrows only by monitor or region, `--monitors-only` / `--regions-only`
  and dates. It has no entry-type or resolution filter, so it rebuilds hourly rows too.
- Gas entry types (CO, NO2, O3, SO2) come from AirNow (one reading an hour). O3 also comes from
  AQLite (published series: `AQLiteHourlyAggregator`, one value an hour) and VOZbox
  (`VOZBox_QuinnCal`). Every monitor type that produces a 1-hour or 8-hour entry type is in scope;
  the rule is per entry type, not per monitor type. Locally there are 397 daily O3 monitor rows and 8,620 daily region rows of all types.

## Decisions (the user's, 2026-11-09)

1. **Color each day the EPA way**, "because this is how EPA does it": the daily mean for
   24-hour scales, the highest hourly average for 1-hour scales, the highest 8-hour average for
   8-hour scales.
2. **The new figures are stored on daily summary rows**, monitor and region. They aren't computed
   on request, and the dashboard doesn't derive them from hourly rows. The cost (a migration
   and backfilling past rows) was accepted in exchange for cheap calendar and bulk requests.
3. **Partial days follow EPA's completeness rule** (below). A day that fails it has no figure
   (`null`).
4. **CO's 8-hour averages are the ones that start during the day** (EPA's convention), so a
   day's figure depends on the next morning's hours and settles about a day later.
5. **The meta shape**: each `scale` gains `averaging_hours` and `daily_statistic`. Daily rows
   gain `max_1h` and `max_8h`.
6. **A new, narrow backfill command** fills the new fields on existing daily rows from stored
   hourly rows, instead of running `rebuild_summaries`.
7. **AQLite's `is_complete` is fixed in this work** (the user, after the builder check). Its
   published O3 series is one value an hour, but summaries expect 12 readings an hour, so every
   hourly row is incomplete and the series would never get a daily peak.

## Goals

- `monitors/meta/` says, for every scale, its averaging period and which daily summary field
  colors a day. The dashboard maps no pollutants itself.
- Daily monitor, region and bulk summary rows carry the 1-hour and 8-hour peak figures.
- The figures follow EPA's completeness rules, so a short day never shows a level lower than
  the data supports.
- Past days can be filled without rebuilding anything else, scoped like the other summary
  commands.

## Non-goals

- Peak figures on hourly, monthly or longer rows. Only daily rows get them (monthly "highest
  day" may come later; not asked for).
- Changing how the daily `mean` or `is_complete` is computed, apart from the AQLite fix
  (section 7). PM2.5 and PM10 keep the existing `mean` and `is_complete` (80% of readings);
  they don't get EPA's 18-of-24-hours rule (*my call*: the user's EPA rule was asked about the
  peaks).
- Averaging periods for non-pollutant scales: weather entry types have no `Levels`, and the
  category scales (smoke, heat, burn status) have no averaging period.
- An AQI value per day. Colors come from the pollutant's own scale levels.
- The hour × weekday heatmap's figure. It reads hourly summaries, which already exist.
- Any production command. Production steps go into data-dashboard `DEFERRED.md`'s deploy entry
  through the coordinator.

## Design

### 1. Averaging period on the scale

- `LevelSet.__init__` takes an optional keyword `averaging_hours: int | None = None`.
  Declarations in `levels.py`: `PM25` and `PM100` 24, `O3`, `NO2` and `SO2` 1, `CO` 8, `AQI`
  none. Because `LevelSet` already accepts levels as keyword arguments, the builder must keep
  `averaging_hours` from being read as a level, either as a keyword-only parameter checked
  before the level kwargs or another way that does the same job.
- `LevelSet.daily_statistic` derives the summary field name: 24 → `'mean'`, 1 → `'max_1h'`,
  8 → `'max_8h'`, none → `None`. Any other value is a programming error: raise at definition.
- `Scale` gains `averaging_hours: int | None = None` and `daily_statistic: str | None = None`.
  `to_json()` always includes both keys, so every scale (HMS, heat, forecast, burn status)
  carries them as `null` unless set. `LevelSet.to_scale()` passes its values through. The AQI
  forecast scale stays `null`/`null`.
- Resulting `monitors/meta/` `entries.o3.scale`:

  ```json
  {"id": "o3", "label": "Ozone", "units": "ppb", "kind": "range", "source": {...},
   "averaging_hours": 1, "daily_statistic": "max_1h", "levels": [...]}
  ```

### 2. The daily figures

Two nullable `FloatField`s on `BaseSummary` (so both `MonitorSummary` and `RegionSummary`):
`max_1h` and `max_8h`. On a daily row, an entry type gets only the field its scale's
`daily_statistic` names, and the other stays `null`. Every non-daily row and every type without
a 1-hour or 8-hour scale has both `null`.

The "standard" below is the scale's Unhealthy for Sensitive Groups breakpoint
(`Levels.UNHEALTHY_SENSITIVE.value`: O3 125 ppb, NO2 101 ppb, SO2 76 ppb, CO 9.5 ppm), which
is where EPA's standards sit on these scales.

The day is the Pacific calendar day. Its hours come from `periods.py` (`iter_hours`), so it has
23, 24 or 25 hours.

An hour **has data**:
- for a monitor, when its hourly row exists and `is_complete` is true;
- for a region, when its hourly row exists (region rows have no completeness flag).

The input value for each hour is that hourly row's `mean`.

**`max_1h` (1-hour scales)**: the highest hourly mean among the day's hours that have data.
It is stored when at least 75% of the day's hours have data (rounded up: 18 of 23 or 24, 19 of
25), or when it is at least the standard. Otherwise it's `null`.

**`max_8h` (8-hour scales)**: one 8-hour window starts at each hour of the day and covers that
hour and the 7 after it, so the later windows run into the next day.
- A window is valid with at least 6 of its 8 hours having data, and its average is the mean of
  those hours' means.
- `max_8h` is the highest valid window average. It's stored when at least 75% of the day's
  windows are valid (rounded up the same way), or when it is at least the standard. Otherwise it's
  `null`.

Rounding: none at storage. The values are floats like `mean`.

### 3. When they're computed

- **Daily rollup** (`rollup_monitor_summaries` / `rollup_region_summaries` with target DAILY):
  - Computes `max_1h` from the day's hourly rows, which it already reads.
  - Adds `timestamp`, `mean` and (monitors) `is_complete` to the values it selects, and adds
    `max_1h` / `max_8h` to `update_fields`.
  - Computes `max_8h` with a separate query for the 8-hour types only, covering the day plus
    the following 7 hours. At the 01:10 run the next day's hours are mostly missing, so late
    windows are invalid and the stored figure is provisional (or `null` if too few windows are
    valid).
  - Rollups into MONTHLY and longer leave both fields `null`.
- **Next-night refresh**: the scheduled daily task for day D also recomputes `max_8h` for day
  D−1 (8-hour types only, monitors and regions), using the same function as the backfill
  command. It updates only `max_8h`. By then D's hourly rows are in, so D−1 is final.
- **Re-rolls on late arrival** (`summarize_monitor_hours`, `reroll`, `repair_summaries`,
  `rebuild_summaries`) recompute daily rows through the same rollup, so they fill `max_1h` and
  the provisional `max_8h` naturally. A late hour early on day D+1 doesn't update day D's
  `max_8h` until the next-night refresh. That's accepted.
- **Settle margin**: `is_settled` needs a margin for daily rows of 8-hour types that covers the
  refresh (run at 01:10 two days after the day starts, i.e. about 25 h 10 min after the day ends),
  plus the usual hour of slack: 27 h. The summaries endpoint picks it the way it picks `late`
  today. Only `day` changes. Longer resolutions keep their margins because they don't carry
  `max_8h`. The crontab test (`camp/apps/summaries/tests.py`) asserts
  `set(ROLLUP_LOCAL_TIME) == set(SETTLE_MARGIN)` and that each margin covers its rollup, so the
  8-hour margin and the refresh's run time need their own structure in `schedule.py`, checked
  by an added assertion, rather than a new key in those dicts (*builder's call how*).

### 4. API

- `MonitorSummarySerializer` and `RegionSummarySerializer` gain `max_1h` and `max_8h` on every
  row (null where not computed). The bulk serializers nest these serializers, so they follow.
- No new endpoints and no new filters. The ETag covers the new fields like the others.

### 5. Migration

- One migration adding `max_1h` and `max_8h` (`FloatField(null=True, blank=True)`, no
  default) to both summary tables. In Postgres, adding a nullable column with no default only
  updates the catalog and doesn't rewrite the table. The builder must confirm the generated SQL
  is a plain `ADD COLUMN ... NULL` with no `DEFAULT` (`sqlmigrate`).
- It still takes a brief `ACCESS EXCLUSIVE` lock on each table, which waits behind open
  transactions on those tables (the hourly summaries at :40–:50, or a `SummaryBackfillJob` tick,
  whose chunk completion runs inside `transaction.atomic()`), and every read and write then
  queues behind it. So the migration's first operation is `SET LOCAL lock_timeout = '10s'`
  (the migration is atomic, so it holds for the `ALTER TABLE`s): a blocked deploy fails its
  release phase instead of stalling the tables, and can be retried.
- There's no separate migrate step: the Procfile's `release: invoke release` runs
  `migrate --no-input` on every deploy. The deploy itself must be timed away from :40–:50 with
  no `SummaryBackfillJob` running.

### 6. Backfill command

`fill_daily_peaks <start> <end>` (Pacific dates, `end` exclusive and `start < end`, like
`repair_summaries`):

- Fills `max_1h` / `max_8h` on existing daily rows for the 1-hour and 8-hour entry types only,
  from stored hourly rows, using the same function as the rollup. It never creates, deletes
  or changes any other column or any non-daily row.
- **Always scoped**, like `repair_summaries`: `--monitor`, `--monitor-type`, `--region`
  (numeric pk), `--region-type`, repeatable, combinable. An unscoped run is an error.
  `--entry-type` optionally narrows to some of the eligible types.
- `--dry-run` prints how many rows per entry type it would update and writes nothing.
- Batched (`--batch-size`, default about 1000 rows), with each batch committed separately and
  progress printed per batch. Idempotent: re-running writes the same values.
- The day `end` itself (the day after the last filled day) must have its hourly rows for the last day's `max_8h` to be final. The
  command just computes from what's stored and doesn't extend the range itself.

### 7. AQLite hourly completeness

- Today `compute_monitor_summary` and `backfill.py` set `expected_count` to
  `monitor.expected_hourly_entries` (from `EXPECTED_INTERVAL`, 12 for AQLite). The published
  AQLite O3 series (processor `AQLiteHourlyAggregator`, CALIBRATED) holds one value an hour, so
  its hourly rows are `count=1, expected_count=12, is_complete=False`, and its daily rows are
  incomplete too.
- Fix: a processor that writes one value an hour declares it (for example a class attribute
  `output_interval = '1h'` on `AQLiteHourlyAggregator`; the exact name is the builder's). The
  hourly summary of that series uses `expected_count = 1`.
- `is_complete` for such an hour comes from the readings the value was averaged from: the hour
  is complete when that hour's CLEANED readings reach the usual 80% of
  `expected_hourly_entries` (10 of 12). The aggregator writes an hour from even one reading, and
  EPA counts an hour only with most of it covered (*my call*; without it, one reading would
  make a complete hour).
- The aggregator itself, the CALIBRATED values, alerts and `LatestEntry` don't change.
- Region rows are unaffected: their `expected_count` comes from monitor weights, not monitor
  expected counts.
- Existing AQLite rows need rebuilding: `rebuild_summaries <first AQLite date> <today>
  --monitor=<id> --monitors-only` per AQLite monitor (hourly and up, all types for those monitors only).
  That runs before `fill_daily_peaks` for AQLite, and the rebuild itself fills the peaks.

## Addendum (2026-11-09, after the first review)

Three decisions came after the design above was built. Where they conflict with it, this
section wins.

### 8. PM 24-hour completeness: `mean_24h` (the user, via spec 5 and here)

- Spec 5's decision (the user: "yes, use the 18-hour rule"): a 24-hour scale's day follows EPA's
  24-hour completeness rule. A day with fewer than 75% of its hours can't be rated. The shape is
  the one the user picked here: a new figure, not a flag.
- New nullable daily field `mean_24h` on `BaseSummary`, for 24-hour scales (PM2.5, PM10). It's
  the mean of the hourly means of the day's hours that have data (EPA computes a 24-hour average
  from hourly averages). It's stored when at least `ceil(0.75 * n)` of the day's n hours have data
  (18 of 23 or 24, 19 of 25), otherwise `null`. There's no "reaches the standard" exception:
  EPA's 24-hour rule doesn't have one.
- "Has data" is the same rule as for the peaks: a complete monitor hourly row, or any existing
  region hourly row.
- `daily_statistic` for 24-hour scales becomes `'mean_24h'` (was `'mean'`). For every
  pollutant, the dashboard reads the field `daily_statistic` names, and `null` means "this day
  can't be rated". `mean` and `is_complete` are unchanged.
- It's written by the same writer, rollup and command as the peaks. Its settle margin is the
  normal one, since it uses only the day's own hours. The migration is still the single
  `0007_summary_peaks`, which adds three columns, because 0007 hasn't been applied anywhere.
  The production backfill now also covers the PM monitor types and regions, which is most of the
  summary data. It's chunked by month and grouped by owner like the rest.

### 9. Sentinel values (the user, via the coordinator)

- Keep the deploy cleanup order: `backfill_airnow` over the affected range, then rebuild those
  monitors' summaries, before `fill_daily_peaks`.
- Also, the daily figures skip any hourly mean at or below -900, treating that hour as having no
  data, so a leftover -999 can't count toward the 75% rule or drag an average down.
- Skips are never silent. `fill_daily_peaks` (the command) prints how many hourly values it
  skipped. The rollup and the next-night refresh log a warning with the count when it's above
  zero (*my call*).

### 10. Reminder in `backfill_airnow` (the user)

- `backfill_airnow` re-imports readings but never rebuilds summaries, so on its own it leaves
  the daily figures stale.
- Its help text, and its closing output, name the follow-ups: rebuild the affected monitors'
  summaries (`rebuild_summaries <start> <end> --monitor=<id> --monitors-only`, which also fills
  the daily figures), or at least run `fill_daily_peaks` scoped to `--monitor-type airnow` over
  the range.
- `rebuild_summaries` and the automated `backfill_summaries` job need no reminder, because they
  go through the daily rollup, which fills the figures itself.

### 11. `daily_statistic_label` (the user, via spec 5)

- Each scale gains `daily_statistic_label` next to `daily_statistic`: the figure's display name,
  translatable (`gettext_lazy`, like level labels). The values are `mean_24h` "24-hour average",
  `max_1h` "Highest 1-hour average", `max_8h` "Highest 8-hour average", and `null` where
  `daily_statistic` is `null`.
- It's declared next to `DAILY_STATISTIC` in `levels.py`, and `Scale.to_json()` always includes
  it, like the other two keys.

## Testing

- `LevelSet` / `Scale`: declared periods, derived `daily_statistic`, the JSON keys on every
  scale kind (range and category), and that the `averaging_hours` keyword isn't treated as a
  level.
- `monitors/meta/`: `averaging_hours` and `daily_statistic` for each entry type with levels.
- `max_1h`: full day, 18-of-24 boundary (17 → null), short day with a peak at or above the
  standard, incomplete hours not counting, 23- and 25-hour days, region rows.
- `max_8h`: window validity (6 of 8), the 75% window rule, the standard exception, windows
  running into the next day, the provisional value at rollup time and the final value after
  the refresh.
- Other types and non-daily rows stay null, and rollups into months leave both null.
- Settle margin for 8-hour daily rows, and the crontab consistency test.
- `fill_daily_peaks`: scope required, dry run writes nothing, only the target columns change,
  idempotent.
- Serializers: fields present on monitor, region and bulk rows.
- AQLite: the aggregated series' hourly `expected_count` is 1, `is_complete` follows the cleaned
  readings (9 of 12 is incomplete, 10 is complete), daily rows become complete, and other
  AQLite series and other monitor types are unchanged.

## Deploy (through the coordinator, into DEFERRED.md's deploy entry)

1. Deploy (the release phase migrates) away from :40–:50 and with no `SummaryBackfillJob`
   running (section 5).
2. `backfill_airnow` over the -999 range, then `rebuild_summaries <start> <end> --monitor=<id>
   --monitors-only` for those AirNow monitors, then `rebuild_summaries <start> <end>
   --monitor=<id> --regions-only` for each (it rebuilds that monitor's regions; `rebuild_summaries`
   has no region-type flag, only `--region=<pk>` or `--monitor=<id>` scoping). Region hourly rows
   built during the -999 period are FEM-weighted means that include -999, usually above -900, so
   the sentinel skip can't catch them; they must be rebuilt before any region fill. The command's
   closing output prints all of it, with Pacific dates. Monitor ids can start with `-`, so
   ids are always passed as `--monitor=<id>`.
3. Per AQLite monitor: `rebuild_summaries <first AQLite date> <today> --monitor=<id>
   --monitors-only` (section 7). This also fills AQLite's peaks. Region rows that include AQLite
   monitors don't change from this step. Their peaks come from step 4.
4. `fill_daily_peaks <first date> <today> --monitor-type <type> --dry-run`, then without
   `--dry-run`, for `airnow`, `aqlite`, `vozbox`, `purpleair`, `airgradient`, `aqview` and
   `bam1022` (every enabled monitor type with PM or gas daily rows), then each region type with PM or
   gas rows. `<today>` as the exclusive end fills through yesterday. Hourly means <= -900 are
   skipped and counted.
5. Run the backfill before announcing the feature: settled daily responses are cached 24 h, so
   nulls served before the backfill stick for a day.

Locally: the migration and any `fill_daily_peaks` run need the coordinator's approval first,
sent with the branch, the migration name and the exact scoped commands.

## Docs

CLAUDE.md: a short section on the scale fields, the daily peak fields and their EPA rules, the
8-hour settle margin, and `fill_daily_peaks`.

## Left to the builder

- Function names and where the peak computation lives (`aggregators.py` is the natural home).
- How the rollup's extra 8-hour query is shaped, as long as it reads only the 8-hour types'
  hourly rows.
- Exact batch size and progress wording for the command.
