# The average of the daily figures on coarser summaries

## Why

The data dashboard has a rule: a dataset has one date range and one resolution. A
monthly Map therefore colours monitors and region fills with the pollutant's daily AQI
scale ("a monthly figure gives a general idea of each day's exposure"). The rows it has
for a month today carry `mean`, the mean of the period's hours, which understates ozone
badly: nights sit near zero. The right figure is the average of the period's daily
figures (each day's `max_1h` for O3, its `mean_24h` for PM2.5, ...), computed on the
server, with the field named in metadata so the dashboard never maps pollutants to
fields itself.

## Goals

- Every `MonitorSummary` and `RegionSummary` row coarser than a day (month, quarter,
  season, year) of a pollutant with a daily figure carries the average of that period's
  daily figures, the number of days that had one, and the number of days expected.
- The current, unfinished month, quarter, season and year get open-period rows built on
  request, like today's open days, so the dashboard never computes the figure itself.
- `monitors/meta/` names the field per scale, next to `daily_statistic`.
- Every path that builds coarse rows fills the figure; a gap is caught by a test and by
  the nightly integrity check.

## Non-goals and anti-goals

- **Nothing is replaced.** `mean`, `minimum`, `maximum`, `stddev`, `p25`/`p75`,
  `count`, `expected_count`, `sum`, `max_1h`/`max_8h`/`mean_24h`, `is_complete`,
  `is_final`, `station_count` and every existing endpoint keep their values and output;
  the only exception is `is_final` on CO coarse rows (see "CO and the last day").
- No new periodic task. No change to hourly or daily rows' values.
- Weather (CIMIS) types and others without a `daily_statistic` get nothing: their new
  fields are null.
- The Pesticides and Facility Emissions explorers don't change behaviour.

## Names

Decided with the user (2026-11-18): one set of fields used by every pollutant (each entry
type has exactly one daily figure), named after the meta key they are built from.

Row fields (model columns and API fields, on every monitor and region summary row):

| Field | Meaning |
|---|---|
| `daily_statistic_mean` | Mean of the period's daily figures (the field the scale's `daily_statistic` names). `null` when fewer than 75% of the expected days have a figure. |
| `daily_statistic_days` | Days in the period whose daily figure is not null. |
| `daily_statistic_expected_days` | Pacific calendar days in the period; for an open period, the days from its start through today, today included. |

All three are `null` on hourly and daily rows, and on rows of entry types without a
`daily_statistic`. On a coarse row of a type with one, after a fill, `days` and
`expected_days` are never null (`days` may be 0).

Scale keys (`camp/utils/scales.py` `Scale.to_json`, so every scale in every meta
endpoint carries them; `null` unless set):

| Key | Value |
|---|---|
| `period_statistic` | `"daily_statistic_mean"` when `daily_statistic` is set, else `null`. |
| `period_statistic_label` | e.g. "Average of daily highest 1-hour averages" (`max_1h`), "Average of daily highest 8-hour averages" (`max_8h`), "Average of 24-hour averages" (`mean_24h`); `null` otherwise. |

They sit after `daily_statistic_label` in the JSON. Adding them to `Scale` (not only to
the monitors meta) keeps the one scale shape the CLAUDE.md "Scale shape" note documents;
the heat, HMS, forecast and pesticide scales gain two `null` keys. None of those meta
endpoints is behind `CachedEndpointMixin`, so no cache version moves.

## The rule

For one series (monitor + entry type + processor, or region + entry type) and one
period P:

- `expected = number of Pacific days in P` (28 to 366; built from calendar dates via
  `periods.py`, never a timedelta of days).
- `figures` = the daily figure (the column `daily_statistic` names) of each stored DAILY
  row of the series with `P.start <= timestamp < P.end` whose value is not null. Daily
  figures already skip sentinel hours and apply the 75% hour rule (`peaks.py`).
- `days = len(figures)`.
- `mean = sum(figures) / days` if `days >= ceil(0.75 * expected)`, else `null`.

Decided with the user: 75% of the period's days (EPA's quarterly completeness rule,
matching the hour rule within a day), and the day count is shown.

## Approaches

1. **Carry it through the rollups.** The month rollup sums daily figures; quarter,
   season and year add up the months' sums and counts. Needs a hidden
   `daily_statistic_sum` column, a second code path for open periods, and the CO fix
   re-runs the whole cascade. Cheapest for open quarter/season/year requests (at most
   11 stored months plus the current month's days per owner).
2. **A separate fill that reads the daily rows (picked).** Like `fill_daily_peaks` for
   daily rows: for each coarse row, read the period's daily figures (one float per day,
   at most 366 per series), apply the rule, write the three fields. Called from inside
   the two rollup functions, it is also the deploy backfill and, with the open days
   added, the open-period builder. One rule in one place; a quarter can never drift
   from its months. Costs re-reading one float per daily row per coarse row, which is
   small against the rollups' t-digest reads.

The user picked 2 (2026-11-18), after a comparison that showed the efficiency gap is only
real on open quarter/season/year requests.

## Design

### Model and migration

`BaseSummary` gains `daily_statistic_mean` (FloatField), `daily_statistic_days` and
`daily_statistic_expected_days` (PositiveSmallIntegerField), all `null=True,
blank=True`. Migration `0008` adds them to both tables with `SET LOCAL lock_timeout =
'10s'` first, as `0007` does (nullable, no default: metadata-only in Postgres, but each
ALTER takes a brief ACCESS EXCLUSIVE lock).

### The fill (`camp/apps/summaries/period_stats.py`)

`fill_period_statistics(kind, ids, start, end, *, resolutions=COARSE, entry_models=None,
dry_run=False, batch_size=1000, progress=None) -> dict[str, int]`

- `kind` 'monitor' or 'region'; `ids=None` means all owners; rows with
  `start <= timestamp < end` of the given coarse resolutions and of the peak entry types
  (`peaks.peak_entry_models()`, optionally narrowed).
- For each group of owners (bounded like `peaks._owner_group_size`), one read of the
  daily rows' `(owner, entry_type, processor, timestamp, <figure column>)` covering
  the group's coarse periods, then the rule per row. Only changed rows are written
  (`bulk_update` of the three fields, batched, one transaction per batch).
- Returns rows updated (or that would be) per entry type.
- A pure helper `period_figure(figures, expected) -> (mean, days)` holds the rule, so the
  open-period builder uses the same code.

### Hooked into the rollups

`rollup_monitor_summaries` and `rollup_region_summaries` (`tasks.py`) call
`fill_period_statistics(kind, ids, window_start, window_end, resolutions=[target])`
right after their upsert when `target` is month or coarser, as they already call
`fill_daily_peaks` for daily targets. The upserts' `update_fields` don't list the new
columns, so a re-roll keeps them until the fill rewrites them. Every coarse write goes
through these two functions: the nightly monthly/quarterly/seasonal/yearly tasks, the
backfill job (`_backfill_complete_chunk`), `repair_summaries` (`repair.reroll`),
`rebuild_summaries` and the CIMIS on-arrival re-roll (checked 2026-11-18; `backfill.py`'s
own `bulk_create`s write hourly rows only). A full rebuild therefore needs no extra step.
Order holds: a period's daily rows get their figures in the day rollup before the month
rollup reads them.

### CO and the last day

A day's `max_8h` is provisional until the next night's `_refresh_previous_max_8h`. The
month rollup (01:15 / 01:25 on the 1st) and the quarter, season and year rollups run
before the refresh of the month's last day (01:00 / 01:10 on the 2nd), so they read a
provisional figure. Fix: `_refresh_previous_max_8h(kind, start)` also calls
`fill_period_statistics` for the coarse periods that end at the refreshed day's end
(the day is the last of a month, and maybe of a quarter, season, year), for the max_8h
types only.

That makes a CO coarse row's `daily_statistic_mean` change up to ~26 h after the period
ends, so `is_settled(..., peak_8h=True)` widens the margin to `PEAK_8H_SETTLE_MARGIN`
(28 h) for month, quarter, season and year as well as day. Consequence: `is_final`, and
the summary endpoints' `max-age`, on CO coarse rows read `false` / 60 s for 28 h after
the period ends instead of 4–5 h. This is the one change to an existing field's value;
the user accepted it (2026-11-18) so a client never caches a provisional CO figure as
final for a day. The change is in `is_settled` (`schedule.py`), so `row_is_final` and the
`SummaryMixin` max-age rule follow it; tests that pin CO coarse `is_final` or max-age
move with it.

### Open periods (`camp/apps/summaries/open_periods.py`)

Rows for months, quarters, seasons and years the scheduled rollups haven't written,
built on request and never saved.

- **Which periods:** the period holding today, plus the previous period while it is
  not settled (`is_settled(resolution, prev.end)`, plain margins) and the series has no
  stored row for it. At most 2 rows per series.
- **Inputs:** the stored DAILY rows of the series in the period, plus the open-day rows
  (`build_open_rows`) for the days that have no stored daily row. For quarter, season
  and year the stored MONTHLY rows of finished months stand in for those months' days in
  the ordinary stats; the daily figures are read from the daily rows in all cases.
- **Stats:** `count`, `expected_count`, `sum`, `minimum`, `maximum`, `mean`, `stddev`,
  `p25`/`p75` roll up over those inputs (`rollup_summaries` / `rollup_region_stats`),
  as a stored row would. The open-day rows need their t-digests for that, so the open
  builder asks `build_open_rows` to keep them (a new keyword; the daily open endpoints
  keep `with_tdigest=False`). `is_complete` (monitor) is relative to the hours so far;
  `station_count` is the max over the inputs; `max_1h`/`max_8h`/`mean_24h` are null, as
  on stored coarse rows; `is_final` is `false`.
- **Percentiles (decided with the user, 2026-11-18, after timing):** open-period rows take
  `p25`/`p75` from the inputs' combined t-digest centroids in one weighted-percentile
  pass (`aggregators.centroid_percentiles`, `rollup_*(..., percentiles='centroids')`)
  instead of merging t-digests. They are an approximation and can differ slightly from
  the stored row the rollup writes once the period ends. Stored rows and the daily open
  rows keep the t-digest merge, unchanged. Timing on the dev DB (read-only,
  `build_open_period_rows` called directly, no cache, PM2.5, 100 owners; local data from
  2026-10-19): PurpleAir month 2.17 s → 0.22 s, year 2.23 s → 0.30 s; regions month
  2.41 s → 0.28 s, year 2.76 s → 0.29 s; 3–4 queries each. O3 builds (33 monitors, 52
  regions) were 0.06–0.09 s before the change.
- **The figure:** `period_figure` over the stored daily figures plus the open days'
  figures (today's is its "so far" figure, yesterday's the strict one), with
  `expected` = days from the period's start through today. For the previous period,
  `expected` is its full length.
- **Cache:** `cached_open_period_rows`, the `cached_open_rows` pattern: 60 s, keyed by
  kind, resolution, entry type, series filter, hashed owner set and open-period set.

Endpoints, mirroring the daily open ones (same params, scope forms, pagination by owner,
100 per page, `private, max-age=60` with ETag, errors `no-cache`):

- `monitors/<id>/summaries/<entry_type>/{monthly,quarterly,seasonal,yearly}/open/`
  (`?processor=`, default `''`)
- `regions/<id>/summaries/<entry_type>/{monthly,quarterly,seasonal,yearly}/open/`
- `monitors/<entry_type>/summaries/{monthly,...}/open/` (bulk; scoped like
  `daily/open/`)
- `regions/<entry_type>/summaries/{monthly,...}/open/` (bulk; `region` or `type`
  required)

The bulk ones list owners with a DAILY row of the series in use in the open period(s)
or an HOURLY row since the first open day (an EXISTS in the owner query, as the daily
open ones do with hourly rows).

### Serializers

`MonitorSummarySerializer` and `RegionSummarySerializer` add the three fields after
`mean_24h`. They are part of every summary response (null below month), so the bulk
group serializers carry them too. The summary endpoints set ETags from the body and are
not behind `CachedEndpointMixin`; the open-days row cache key (`open_days:v2:...`) holds
model instances, which pick up the new attributes as `None`, so it needs no bump.

### Command `fill_period_statistics`

`manage.py fill_period_statistics <start> <end>` (Pacific dates, end exclusive), scoped
exactly like `fill_daily_peaks` (`--monitor=`, `--monitor-type`, `--region=`,
`--region-type`; one required), plus `--resolution` (repeatable; default all four),
`--entry-type`, `--batch-size`, `--dry-run`. Works on rows whose timestamp is in the
range, one Pacific year at a time. Prints the counts per entry type. Idempotent.

### Guards

1. **Test:** a full `rebuild_summaries` over a fixture spanning more than a quarter
   asserts every coarse row of a peak type has `daily_statistic_days` and
   `daily_statistic_expected_days` set.
2. **Integrity check:** `check_summary_integrity` also counts coarse rows (both tables,
   timestamp in the last 400 days) of peak types with `daily_statistic_days` null, and
   includes the count in its result and its Sentry error (`missing_period_statistics`).
   A CO coarse row is never null for this reason: the fill writes `days` even when the
   mean is null.

## Production at deploy

1. Deploy. The release phase runs migration `0008` (two tables, three nullable columns
   each, 10 s lock timeout): away from :40–:50 and with no `SummaryBackfillJob` running.
   From then on every coarse row written fills itself.
2. Existing coarse rows: after the daily-peaks steps in the existing deploy entry (step
   2's AirNow backfill and rebuilds, the AQLite rebuilds and the scoped
   `fill_daily_peaks`), run, `--dry-run` first:

   ```bash
   python manage.py fill_period_statistics <first summary date> <today> --monitor-type <type> --dry-run
   python manage.py fill_period_statistics <first summary date> <today> --region-type <type> --dry-run
   ```

   for each monitor type and region type listed in the `fill_daily_peaks` step. It must
   follow those steps because it averages the daily figures they write; rows re-rolled
   by the rebuilds in step 2 already fill themselves. It is idempotent, so re-running it
   after any of them is safe.
3. Size: it writes three columns on each existing coarse row of the six peak types and
   reads one float per daily row of those types. Locally (2026-11-18, data from
   2026-10-19) that is 37 coarse rows and ~15 000 daily rows; production is larger by
   its years of history and its monitor count, still a read of one column per daily row,
   batched by owner group.

Consumers react to: three new fields on every summary row, two new keys on every scale,
and eight new open endpoints. Nothing existing changes, except `is_final` on CO coarse
rows (step "CO and the last day").

## Left to the builder

- Module layout inside `camp/apps/summaries/`, owner-group sizing, and whether the open
  builder reuses `build_open_rows` directly or shares its internals.
- Test fixtures (bulk-created `RegionSummary` rows need a non-empty t-digest).
- Performance: time a bulk open-month and open-year page (100 owners) against the dev
  database in a throwaway container mounting the worktree; report the numbers in the PR.
- OpenAPI declarations for the new endpoints, like the daily open ones.
- CLAUDE.md: a "Period daily statistic" note under Metadata Endpoints, and the
  `fill_period_statistics` step in the deploy order.
