# Summary rollup follow-up: findings 2 and 3 and the local repair proof

Follow-up to `2026-11-03-summary-rollups.md`. Finding 1 (UTC crontabs) was fixed in #301.
The design is in `docs/superpowers/specs/2026-11-04-summary-rollup-followup-design.md`.

## Finding 2: standard-time periods stamped an hour early

### Cause

The full-history backfill steps days in UTC. The job's `cursor` is a Pacific midnight, but
each tick reloads it from the database as a UTC datetime. `chunk_start_for()` and
`iter_chunk_days()` then subtract and add `timedelta(days=1)`, which is 24 absolute hours on
a UTC value. A summer-time `range_end` is 07:00 UTC, so every day stays at 07:00 UTC. In
standard time that is 23:00 the day before.

`higher_rollup_windows()` read `day.day` and `day.month` from the UTC value. So
`2026-03-01T07:00Z` (Feb 28, 23:00 PST) passed as "March 1" and the March month and spring
season were written starting at `2026-02-28T23:00-08:00`. Scheduled rollups build Pacific
dates and were correct. Every bad row in production came from the backfill.

### Evidence

- Production rows: months starting Dec to Mar were wrong, Apr to Nov right, years started
  at Dec 31, 23:00.
- Daily rows were also misstamped for every standard-time day the backfill covered.
- Some correctly stamped rows held wrong values: a window ending in standard time also picked
  up the next period's misstamped first row (a month took the next month's first day, Q4 took
  January, winter took March, a year took the next January).
- Hourly rows are fine. They are computed per UTC hour from entries.

### Reproduction tests

Regression tests on this branch (`010b88a4` first added `camp/apps/summaries/test_dst_repro.py` with separate reproduction tests that failed against the old code):

- `camp/apps/summaries/test_backfill.py::BackfillJobDstTests::test_summer_end_backfill_stamps_pacific_period_starts`
- `camp/apps/summaries/test_backfill.py::BackfillJobDstTests::test_standard_end_backfill_across_fall_back`
- `camp/apps/summaries/test_backfill.py::HigherRollupWindowsTests::test_march_first_is_a_month_start_when_given_as_utc`
- `camp/apps/summaries/test_backfill.py::HigherRollupWindowsTests::test_an_hour_early_stamp_is_not_a_month_start`
- `camp/apps/summaries/test_period_consistency.py::PeriodConsistencyTests::test_three_paths_write_the_same_rows`

### Fix

`camp/apps/summaries/periods.py` is now the one place for period math. The backfill, the
scheduled rollups, `rebuild_summaries` and the API use it. It steps Pacific calendar dates
and hours in UTC, so DST days have 23 or 25 hours. `rebuild_summaries` also no longer skips
or repeats an hour on DST days.

## Finding 3: region summaries mostly missing

### Cause

`hourly_region_summaries` worked out its hour from when it ran, not when it was scheduled.
The summaries queue is strict priority, first in first out within a priority. The region
parent (priority 90) is enqueued at :50 but cannot start until every pending monitor task
(priority 100) is picked up. If that takes past the top of the hour, the job computes the
hour that just ended. That hour has no monitor rows yet, so every region task writes nothing,
and the missed hour is never revisited. The daily region rollup then has nothing to roll up.
Monitors were unaffected because their parent is top priority.

### Evidence

- Production: monitors complete, region rows intermittent and getting worse (17 daily rows
  in September, 2 in October, none on Nov 2). Monitor work grows with the table, so the
  margin shrinks.
- Local measurement (20:45 UTC run, 2026-11-04): the monitor parent took 192 s, 6,428
  monitor tasks finished by 20:49:09 and the region job started 20:50:56. It had about 11
  minutes to spare locally.
- Ruled out: the region list query (0.13 s), region task errors, Huey stats in Redis.
- Still to check on production: the summaries worker dyno scaled down, `summarize_region_hour`
  errors in Sentry, Redis eviction.

### Reproduction tests

Regression tests on this branch (`camp/apps/summaries/tests.py`, `HourlyParentScheduleTests`;
`010b88a4` first added the failing reproductions in `test_dst_repro.py`):

- `test_late_run_logs_a_warning`
- `test_slightly_late_run_logs_nothing`
- `test_monitor_parent_late_run_summarizes_the_scheduled_hour`
- `test_hour_for_run_across_the_fall_back_hour`
- `test_hour_for_run_before_the_fire_minute_uses_the_previous_fire`
- `test_priorities`
- `test_fire_minutes_match_the_crontabs`

### Fix

1. The parents take their hour from the schedule (`hour_for_run`), so a late start still
   summarizes the right hour.
2. The parents run at priority 110 (monitors) and 105 (regions), above their children.
3. A parent that starts more than 10 minutes late logs a warning.

Tooling: `repair_summaries` fixes existing damage and `check_summary_integrity` (02:30
Pacific) logs misaligned rows or skipped region hours to Sentry.

## Local repair proof

The old (`origin/develop`) code made the damage and this branch's `repair_summaries` fixed it.
Only summary rows were written, only for the scope below. Pacific dates, end exclusive.

### Scope

- Range: 2026-10-01 to 2026-11-04.
- Kings County (region pk 1) and two monitors inside it:
  `LU10CFrcTPmEbWrVic_guA` (Hanford - S. Irwin Street) and `t2wccARDQ5qiSDwxMOTOyQ` (Hanford2).
- Everything ran in throwaway containers with `HUEY_IMMEDIATE=1`, so nothing was enqueued.

### Making the damage

With the old code, a UTC cursor equal to 2026-11-04 00:00 Pacific walked back day by day,
calling the old `daily_rollup_window` and `higher_rollup_windows` and the old rollups for the
scope. Then Kings' hourly region rows for 2026-10-28 were deleted (12 rows).

| rows in scope | before | after damage | after repair |
|---|---|---|---|
| monitor day | 12 | 62 (9 stamps off) | 56 (0 off) |
| monitor month | 0 | 18 (2 stamps off) | 6 (0 off) |
| monitor quarter | 0 | 12 (1 stamp off) | 6 (0 off) |
| region day | 4 | 24 (9 stamps off) | 22 (0 off) |
| region month / quarter | 0 / 0 | 6 / 4 (2 / 1 off) | 2 / 2 (0 off) |
| region hour | 182 | 170 | 188 |
| Kings hourly rows on 2026-10-28 | 12 | 0 | 12 |

The off stamps were at 01:00 PDT on Oct 19 to Oct 29 and Oct 1/Nov 1 for months and the quarter,
the old code's hour-late pattern in summer time.

### Repair

Command: `repair_summaries 2026-10-01 2026-11-04 --monitor <a> --monitor <b> --region 1 --region-hours`.

- Dry run: 10 missing region hours in Kings; 62 misaligned monitor rows (44 day, 12 month,
  6 quarter) and 24 region rows (18, 4, 2) to delete; 34 day and 1 month windows to roll for
  both tables. Nothing written.
- Real run: the same 86 rows deleted, 18 region hour rows written for the 10 hours, windows
  rolled. Second real run: 0 misaligned rows deleted and the same window counts rolled (34 day,
  1 month, for both tables). Per-row values before and after the second run were not saved.
  November's month and the quarter, season and year were left for the scheduled rollup because
  they are unfinished.
- The 12 Oct 28 rows came back. The other 4 missing hours were gaps already in the data
  (Oct 26, Nov 2, Nov 3), where monitor hourly rows had no region row; the repair filled them
  (region hourly rows rose from 182 to 188).

### Checks

- Every non-hourly row in scope is on a Pacific period start (0 misaligned in every
  table and resolution).
- Kings has hourly rows for every hour that has monitor rows, including Oct 28, except one.
  Both real runs (and the second dry check) list 1 hour that still has no region row:
  2026-11-04 06:00 UTC (Nov 3, 22:00 PST). Eleven pm25 monitor rows exist for it, from six
  monitors, but all six have a health score of 0 for that hour, so `get_monitor_weight` is 0 for
  each and `compute_region_summary` returns `None`. It is correct that no row is written, and
  the scan will keep listing it (query and output: `task7/missing_hour.out`,
  `task7/missing_hour_why.out`). The local data is sparse, so days have 10 to 16 rows rather
  than 24. No Kings data fell on Nov 1.
- Day rows equal an independent aggregation of the stored hourly rows by Pacific day (count,
  mean, minimum, maximum): 34 monitor-days for the first monitor and 22 for the second, 0
  mismatches, 0 extra day rows.
- A clean `rebuild_summaries --monitors-only` in a rolled-back transaction is not a fair
  comparison here. It recomputes hourly rows from entries, and the stored hourly rows in this
  database are partial, so it produced more hours and different day values. The comparison
  against the stored hourly rows is the right one.
- Scope: every command took explicit monitor and region ids, and the delete counts equal the
  in-scope misaligned counts from the dry run. I have no before snapshot of rows outside the
  scope, so "nothing else changed" is not proven by a comparison.

### Full suite

`pytest -n 4 --dist loadscope`: 4287 passed (baseline 4225).
