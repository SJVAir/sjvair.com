# Summary rollup follow-up: hour-early periods and missing region rows

Findings 2 and 3 of `docs/superpowers/reports/2026-11-03-summary-rollups.md`. Finding 1
(UTC crontabs) was fixed in #301. Approved 2026-11-04. Nothing here touches production; production steps go
into data-dashboard DEFERRED.md → the `develop` deploy entry.

## Finding 2: standard-time periods stamped an hour early

### Cause

The full-history backfill (`backfill_summaries start`, driven by `backfill_summaries_tick`)
steps days in UTC.

- The command stores `cursor = range_end` as Pacific midnight. Each tick reloads the job, so
  `cursor` and `chunk_start` come back from the database as **UTC** datetimes.
- `chunk_start_for()` and `iter_chunk_days()` (`camp/apps/summaries/backfill.py`) subtract and
  add `timedelta(days=1)`. On a UTC datetime that's 24 absolute hours. On a Pacific
  `zoneinfo` datetime it would be wall-clock and correct.
- Starting from a summer-time `range_end` (07:00 UTC), every day stays at 07:00 UTC. In
  standard time that is **23:00 the day before**.
- `higher_rollup_windows(day)` checks `day.day == 1` and `day.month` on the UTC value.
  `2026-03-01T07:00Z` (Feb 28 23:00 PST) passes as "March 1", so the March month and the
  spring season are written starting at `2026-02-28T23:00-08:00`. That is exactly
  production's row.

Scheduled runs are correct: they build period starts with `make_aware(datetime(...))` in
Pacific. So production's hour-early rows all come from the backfill. The pattern (months
starting Dec–Mar wrong, Apr–Nov right; years at Dec 31 23:00) matches a backfill whose
`--to` was in summer time.

**Reproduced:** `test_backfill_from_a_summer_time_end_stamps_standard_time_periods` runs
`backfill_summaries start --from 2026-02-27 --to 2026-03-10` through the real ticks. It
writes `month` and `season` rows at `2026-02-28T23:00:00-08:00`, and daily rows at 23:00 for
every standard-time day.

### What the report didn't have (affects the repair)

- **Daily rows are misstamped too**, for every standard-time day the backfill covered. Each
  window runs 23:00 to 23:00, shifted by an hour. The last chunk is clamped to
  `range_start` (a correct midnight), so it overlaps the 23:00 row next to it.
- **Some correctly stamped rows hold wrong values.** The higher windows end at a correct
  Pacific midnight, so a window that ends in standard time also picks up the next period's
  misstamped first row:
  - a month ending in standard time (Nov–Feb) includes the next month's first day;
  - Q4 includes January;
  - the winter season includes March;
  - a year includes the next January.
- So re-stamping isn't enough. Daily and longer rows in the backfilled range have to be
  recomputed from the hourly rows. **Hourly rows are fine:** they are computed per UTC hour
  from entries.

### Related bug: `rebuild_summaries` hour list

`rebuild_summaries._iter_hours` steps a Pacific `start` by `timedelta(hours=1)`, which is
wall-clock arithmetic. On fall-back day it skips the second 01:00 (09:00Z). On spring-forward
day it yields 10:00Z twice. Only the region side is affected (it takes that hour list;
monitor hours come from entries). `backfill.hour_range` has the same flaw if given a Pacific
start; the backfill job happens to pass UTC.

### Fix

- `backfill.py`: work in Pacific calendar dates.
  - `chunk_start_for` and `iter_chunk_days` convert to Pacific, step by date, and re-localize
    with `make_aware(datetime(...), DEFAULT_TIMEZONE)`.
  - `daily_rollup_window` ends at the next Pacific midnight, so DST days are 23 or 25 hours.
  - `higher_rollup_windows` reads `day`/`month` from the Pacific date.
  - `hour_range` steps in UTC whatever the input zone.
- `rebuild_summaries._iter_hours`: step in UTC.
- Tests: DST on both sides (Nov 1 and Mar 8, 2026), including a cursor read back from the
  database, and the end-to-end tick test above as a regression test.

## Finding 3: region summaries mostly missing

### Cause

`hourly_region_summaries` works out its hour from the time it **executes**
(`timezone.now()` floored, minus one hour), not the time it was **scheduled**.

- The summaries queue is `PriorityRedisHuey`: strict priority, FIFO within a priority
  (huey 3.3 `RedisPriorityQueue`, a sorted set scored by `-priority`).
- `hourly_monitor_summaries` (priority 100) runs at :45 and enqueues one task per (monitor,
  entry type, processor), also at 100. `hourly_region_summaries` is enqueued at :50 at
  priority 90, so it can't start until every pending priority-100 task has been picked up.
- If that takes past the top of the hour, the region job computes the hour that has just
  ended. That hour has no monitor summaries yet (they're made at the next :45), so every
  region task returns `None` and writes nothing. The hour that should have run is never
  revisited. The daily region rollup then has nothing to roll up.
- Monitors are unaffected: their job is top priority and starts on time.

This matches production: monitors complete; region rows intermittent, getting worse
(September 17 daily rows, October 2, none on Nov 2). Monitor work grows with monitors and
table size, so the margin shrinks over time.

**Reproduced:** `LateRegionFanOutReproTests`. A run at 10:50 writes hour 09:00. A run at
11:01 writes nothing.

**Local measurement** (20:45 UTC run, 2026-11-04, summaries worker on the local stack):

| step | time |
|---|---|
| `hourly_monitor_summaries` parent | 192 s (per-entry-type `DISTINCT` scan of the hour) |
| 6,428 monitor tasks | avg 57 ms, p95 81 ms, all done by 20:49:09 |
| region job | started 20:50:56, on time |
| 5,435 region tasks | avg 46 ms |

Locally the region job had about 11 minutes to spare. Production's margin isn't known from
here; its worker logs can confirm it (pre-deploy list).

### Not the cause (checked)

- **The region list query:** 0.13 s locally, 1,347 regions × 5 entry types = 6,735 tasks an
  hour.
- **Region task errors:** no exception path in `compute_region_summary` beyond the ones
  monitors share. Locally, region hourly rows track monitor rows hour for hour.
- **Redis memory from Huey stats:** stats are stored in Postgres (`huey_event`), and only
  for the primary queue.

Still possible on production, to check before the deploy:
- the summaries worker dyno being scaled down;
- `summarize_region_hour` errors in Sentry;
- Redis maxmemory or eviction.

### Fix

1. **Derive the hour from the schedule, not the clock.** The hour is the one before the most
   recent scheduled fire time at or before now (:45 for monitors, :50 for regions). A run
   that starts up to 59 minutes late still summarizes the right hour.
2. **Run the two hourly parents above their children** (for example monitor parent 110,
   region parent 105; children keep 100 and 90). Each parent then starts as soon as a worker
   is free instead of queuing behind the monitor tasks. The children's order is unchanged:
   region tasks still run after the hour's monitor tasks.
3. **Log a warning when a parent starts more than 10 minutes after its scheduled time**, so
   production logs show any future lateness.

Left out (decided 2026-11-04): a self-healing pass that redoes recent hours with monitor rows
but no region rows. The schedule fix and the daily production check cover it.

## Guards against the next time bug

Findings 1 and 2 have the same shape: the code reads as correct, the tests confirm the
code, and nothing checks the stored result. For example, the existing
`assert chunk_start_for(cursor, range_start) == cursor - timedelta(days=1)` repeats the code's
arithmetic on a Pacific datetime that never goes through the database.

1. **One module for period math** (`camp/apps/summaries/periods.py`). It turns any aware
   datetime (UTC or Pacific) into Pacific period starts and ends, for every resolution, and
   steps hours in UTC. The scheduled tasks, the backfill, `rebuild_summaries`, the repair
   command and the API's date filters all use it instead of their own copies
   (`_add_3_months`, `_months_later`, `_window_end`, `_iter_*`, `_last_*_start`).
2. **Test rule:** every summary test that involves time goes through the database and covers
   both DST changes (Nov 1 and Mar 8, 2026). It asserts things that have to be true in
   Pacific time, never the code's own arithmetic:
   - every daily-and-longer row starts at a Pacific period start for its resolution;
   - each window covers exactly its period's hours (23, 24 or 25 for a day);
   - the same scope built by the backfill job, by `rebuild_summaries` and by the scheduled
     tasks gives the same rows.
3. **Daily production check** (small follow-up in this PR, a summaries task after the daily
   rollups). It counts the previous day's misaligned rows, and the hours with monitor rows
   but no region rows, and sends a Sentry message if either isn't zero. The check queries
   are indexed and timed locally (EXPLAIN).

## Repair tooling

`rebuild_summaries` can't do the repair: it always recomputes hourly rows and has no dry
run. A new command (decided 2026-11-04 over extending `rebuild_summaries`), `repair_summaries`, always scoped. It takes `--monitor`,
`--region` and `--region-type` (each repeatable), plus a required date range.

- `--dry-run` counts and writes nothing.
- **Misaligned rows:** finds daily and longer rows whose start isn't a Pacific period start
  (not 00:00 Pacific; a month not on the 1st; a quarter not starting Jan/Apr/Jul/Oct; a
  season not starting Dec/Mar/Jun/Sep; a year not starting Jan 1). It reports them, then
  deletes them. This covers the hour-early rows and the scheduled job's May 1 style seasons.
- **Re-rolls up** daily → monthly → quarterly / seasonal → yearly with correct Pacific
  windows from the existing rows below, through `rollup_monitor_summaries` /
  `rollup_region_summaries` with explicit ids.
- **`--region-hours`** recomputes hourly region rows for the hours in range that have
  monitor rows (the finding 3 gap), before the re-rollup.
- Batched, with progress per batch, and idempotent.

The repair is proven locally on rows written the same wrong way:
1. Run the old backfill code in a throwaway container on a scoped local range across a DST
   change.
2. Delete region hours to mimic finding 3.
3. Run the command and compare against a clean rebuild of the same scope.

Queries are checked with EXPLAIN on the local database.

## Production (pre-deploy list, not run now)

This goes into data-dashboard DEFERRED.md → the deploy entry, as ordered steps, each with how
to size it first and how to check it after:

1. **Checks:**
   - the summaries worker logs (start times of `hourly_region_summaries` against :50, and how
     long the monitor fan-out takes);
   - the dyno formation;
   - Sentry for `summarize_region_hour`;
   - Redis memory and policy;
   - `backfill_summaries status` (no job running).
2. **Deploy**, with #301's deploy window.
3. **Size the repair:** misaligned row counts per resolution and per monitor/region type;
   region hours missing.
4. **Repair, one monitor and one region first,** then the wider run after a yes:
   - region hours first;
   - then delete misaligned rows and re-roll up;
   - then #301's catch-up periods.
5. **Check after:** the report's curl requests return Pacific-midnight stamps and complete
   region rows.

**How the list grows until the deploy:** the region gap grows every hour production keeps
the old code. #301's late months, quarters and seasons keep adding up. The hour-early rows
don't grow, unless someone runs a backfill.

**Cache:** settled periods are cached 24 hours in browsers, so run the repair right after
the deploy, before the dashboard's monthly/region widgets are live.
