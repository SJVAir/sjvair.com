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
- The current, unfinished month, quarter, season and year get stored rows, written each
  night by the summarizer through yesterday, so the dashboard never computes the figure
  itself and no request builds one (see "Current periods").
- `monitors/meta/` names the field per scale, next to `daily_statistic`.
- Every path that builds coarse rows fills the figure; a gap is caught by a test and by
  the nightly integrity check.

## Non-goals and anti-goals

- **Nothing is replaced.** `mean`, `minimum`, `maximum`, `stddev`, `p25`/`p75`,
  `count`, `expected_count`, `sum`, `max_1h`/`max_8h`/`mean_24h`, `is_complete`,
  `is_final`, `station_count` and every existing endpoint keep their values and output;
  the only exception is `is_final` on CO coarse rows (see "CO and the last day").
  Adding is allowed (the user, 2026-11-18): the rule protects values and shapes that
  something already relies on, above all the explorers, not new rows. So the coarse
  lists gain a current-period row, and no existing row or value changes.
- No change to hourly or daily rows' values. Today is not in any stored row: today's
  daily figure stays on `daily/open/`, unchanged by this work. Replacing `daily/open/`
  with daily rows the hourly summarizer writes is a separate follow-up, not this branch.
- Weather (CIMIS) types and others without a `daily_statistic` get nothing: their new
  fields are null.
- The Pesticides and Facility Emissions explorers don't change behaviour. Neither reads
  `MonitorSummary` or `RegionSummary` (checked 2026-11-18).

## Names

Decided with the user (2026-11-18): one set of fields used by every pollutant (each entry
type has exactly one daily figure), named after the meta key they are built from.

Row fields (model columns and API fields, on every monitor and region summary row):

| Field | Meaning |
|---|---|
| `daily_statistic_mean` | Mean of the period's daily figures (the field the scale's `daily_statistic` names). `null` when fewer than 75% of the expected days have a figure. |
| `daily_statistic_days` | Days in the period whose daily figure is not null. |
| `daily_statistic_expected_days` | Pacific calendar days in the period; for the current period, the days from its start through yesterday. |

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

- `expected = number of Pacific days from P.start to the earlier of P.end and the start
  of today` (28 to 366 for a finished period, fewer for the current one; built from
  calendar dates via `periods.py`, never a timedelta of days). One rule for every row,
  so the fill needs no flag for current periods.
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
   the two rollup functions, it is also the deploy backfill and fills the nightly
   current-period rows. One rule in one place; a quarter can never drift
   from its months. Costs re-reading one float per daily row per coarse row, which is
   small against the rollups' t-digest reads.

The user picked 2 (2026-11-18), after a comparison that showed the efficiency gap is only
real on open quarter/season/year requests. With current periods written nightly instead
of built on request (below), that gap is a nightly cost, not a request's.

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
- A pure helper `period_figure(figures, expected) -> (mean, days)` holds the rule.
- `expected` follows the rule's "earlier of P.end and the start of today", so the same
  call fills finished and current rows.

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

### Current periods (written nightly)

Decided with the user (2026-11-18), replacing the open-period endpoints this branch first
built: the production server is slower than the dev machine, and a row computed once a
night is ready when people ask for it. Today is left out, so the row only changes once
a night; today's figure stays on `daily/open/`.

- **What is written:** for each owner, the rows of the month, quarter, season and year
  that hold yesterday, through yesterday, in the existing `MonitorSummary` and
  `RegionSummary` tables, for every summarized entry type (my call: the row is an
  ordinary partial summary row, so a consumer finds one for every type, not only the six
  with a daily figure). The existing rollup functions build them: the month from its
  stored DAILY rows, then quarter, season and year from their stored MONTHLY rows,
  including the partial month just written. Real t-digest merge, so `p25`/`p75` match
  what the stored rows use. `fill_period_statistics` runs after the upsert as for every
  coarse row, with `expected` through yesterday by the rule.
- **The task:** `current_monitor_periods` at 02:15 Pacific and `current_region_periods` at
  02:20 (`pacific_crontab`), after the last nightly rollup (yearly regions, 02:05) and
  before `check_summary_integrity` (02:30), at a lower priority than the rollups.
- **Only what changed is re-rolled:** the stats re-roll only owners with a DAILY row
  for yesterday (an owner that sent nothing has the same inputs as last night). Every
  other current-period row only needs its `daily_statistic_expected_days` moved to
  the new day count, and its `daily_statistic_mean` set to null when
  `daily_statistic_days` falls below 75% of it: one UPDATE per resolution, no reads of
  daily figures.
- **Which periods (the guard):** the periods are worked out from the clock when the
  task runs, never from its scheduled date. A period is written only when
  `P.start < start of today < P.end`. An ended period belongs to its regular rollup,
  and a period that starts today has no finished days. The check is repeated right
  before each write batch, so a run that started on the last night of a period and is
  still going after midnight stops instead of writing over the final row the 01:15
  rollup wrote. On the 1st the new month has no row until the night of the 2nd. Between
  midnight and the regular rollup, the ended period's partial row (through its
  second-to-last day) stays until the rollup replaces it.
- **When the period ends:** the regular monthly, quarterly, seasonal or yearly rollup
  upserts the final row over the partial one, as it already would. `is_final` is the
  settle rule per row, so a partial row reads `false`, and the summary cache rule gives
  its responses `max-age=60`.
- **Late data:** the CO `max_8h` refresh (01:00 / 01:10) runs before the task, so the
  current rows pick it up the same night. `finalize_cimis_data` (04:00–05:00) re-rolls
  the current periods of the stations it re-pulled, after the finished ones.
- **Rebuilds leave nothing missing:** `rebuild_summaries`, `repair_summaries` and the
  backfill job's completion write the current periods for their scope when their range
  reaches yesterday, through the same function the task uses (`roll_current_periods(kind,
  ids, now)`). `rebuild_summaries`' and `repair_summaries`' notes that unfinished periods
  are "left for the scheduled rollup" change to say the current ones are written
  through yesterday.
- **Integrity check:** `check_summary_integrity` also counts series with a DAILY row for
  yesterday and no current-month row (`missing_current_periods`), in its result and
  Sentry error. The old message is verbatim when both new counts are 0.

Removed from the branch, with the open-period design: `open_periods.py`, the 16
`.../{monthly,quarterly,seasonal,yearly}/open/` routes and their OpenAPI entries,
`BulkMonitorScopeFilter`, `aggregators.centroid_percentiles` and the `percentiles=`
keyword, and the changes made for them to `open_days.py` and the daily open views
(`with_tdigest=`, the public `daily_statistic`, the `open_rows`/`open_since`/
`open_owner_q` hooks). `daily/open/` is then byte-for-byte as on `develop`.

Earlier timing, kept as the reason for this change (dev DB, read-only, PM2.5, 100 owners,
on-request open-period build): t-digest merge 2.2–2.8 s, centroids 0.22–0.30 s. The
nightly task's own run time on the dev DB goes in the PR.

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
3. **Current periods, tested:** a full `rebuild_summaries` through yesterday leaves a
   current month, quarter, season and year row for every series with a daily row
   yesterday; a run of the task started late (after the period ended) writes nothing and
   leaves the final row byte-for-byte; a period that starts today gets no row.
4. **Integrity check:** `missing_current_periods` (see "Current periods").

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
4. Current-period rows appear on their own the first night after the deploy (02:15 /
   02:20 Pacific). Announce the feature after that night and after step 2. The nightly
   task's cost on production is about one monthly rollup plus three small ones per
   night, for the owners that reported yesterday; the dev-DB timing is in the PR.

Consumers react to: three new fields on every summary row, two new keys on every scale,
and, in the existing monthly, quarterly, seasonal and yearly lists, one row for the
current period (through yesterday, `is_final: false`, `max-age=60`) that wasn't there
before. No existing value changes, except `is_final` on CO coarse rows (step "CO and the
last day"). `daily/open/` is unchanged. No new endpoints.

## Left to the builder

- Module layout inside `camp/apps/summaries/` and owner-group sizing.
- Test fixtures (bulk-created `RegionSummary` rows need a non-empty t-digest).
- Performance: time the nightly task against the dev database (it writes, so only with
  the coordinator's OK and in the agreed window); report the numbers in the PR.
- Whether the "only what changed" UPDATE shares code with the fill or is its own query.
- CLAUDE.md: a "Period daily statistic" note under Metadata Endpoints, and the
  `fill_period_statistics` step in the deploy order.
