# Summary Rollup Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stamp every summary period at its Pacific start, keep hourly region summaries from
being skipped, and provide a scoped repair command and a daily integrity check for the rows
production already has wrong.

**Architecture:** A new `camp/apps/summaries/periods.py` owns all period math (Pacific
calendar boundaries, UTC hour stepping). The backfill, scheduled tasks, `rebuild_summaries`,
the API date filter, the new `repair_summaries` command and the new integrity check all use
it. The hourly parent tasks take their hour from their schedule and run above their children.

**Tech Stack:** Django 5 / PostGIS, Huey (`PriorityRedisHuey`, `utc=True`), `zoneinfo`,
pytest with `django.test.TestCase`.

**Spec:** `docs/superpowers/specs/2026-11-04-summary-rollup-followup-design.md`

## Global Constraints

- Pacific is `settings.DEFAULT_TIMEZONE` (`zoneinfo` America/Los_Angeles); `TIME_ZONE` stays `UTC`.
- Period starts are built with `make_aware(datetime(y, m, d), DEFAULT_TIMEZONE)`, never by adding a `timedelta` of days or more. Hours step in UTC.
- Resolutions are `BaseSummary.Resolution` values: `hour`, `day`, `month`, `quarter`, `season` (Dec–Feb, Mar–May, Jun–Aug, Sep–Nov), `year`.
- Test rule: every time-related summary test goes through the database and covers both DST changes (2026-03-08 and 2026-11-01), and asserts Pacific facts, never the code's own arithmetic.
- Tests: `django.test.TestCase`, pytest-style `assert`, fixtures from `/fixtures/*.yaml`.
- Management commands and tasks are always scoped; nothing in this plan runs unscoped, locally or in docs.
- No production work. No Claude or AI attribution in commits, PRs or docs.
- Test command (from the worktree): `podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token -v $PWD:/app:z -v ~/workspace/django-resticus/.worktrees/session-csrf/resticus:/usr/local/lib/python3.14/site-packages/resticus:ro,z -w /app sjvair-com-test:latest pytest <args>` (written `TEST <args>` below). Full-suite baseline: 4225 passed.

## Review Focus

- Fall-back day (2026-11-01): the daily window is 25 hours and holds both 01:00 hours; the hour lists contain 09:00Z exactly once. Pinned in Task 1 and Task 3.
- A hour-early row one hour before the repair range's start (e.g. `2026-02-28T23:00-08:00` for a range starting Mar 1) is found and deleted. Pinned in Task 5.
- A repair with no scope flag, or an unknown monitor/region pk, refuses before writing anything. Pinned in Task 5.
- The hourly parent run at exactly :50:00, at :49:59 of the next hour, and at :50 of the next hour picks the right hour. Pinned in Task 4.
- The repair never writes a period that hasn't ended yet (the current month or quarter). Pinned in Task 5.

---

### Task 1: The period module

**Files:**
- Create: `camp/apps/summaries/periods.py`
- Modify: `camp/apps/summaries/schedule.py` (move `period_end` and `_pacific_midnight` out; import `period_end` from `periods` so `schedule.period_end` and `is_settled` keep working)
- Test: `camp/apps/summaries/test_periods.py`

**Interfaces:**
- Produces:
  - `period_start(resolution: str, ts: datetime) -> datetime`: start of the period containing aware `ts`. `hour` truncates in UTC; others are Pacific midnights.
  - `period_end(resolution: str, ts: datetime) -> datetime`: moved unchanged from `schedule.py`.
  - `iter_period_starts(resolution: str, start: datetime, end: datetime) -> Iterator[datetime]`: starts of every period overlapping `[start, end)`, ascending (the first may be before `start`).
  - `iter_hours(start: datetime, end: datetime) -> Iterator[datetime]`: each UTC hour in `[start, end)`, as UTC-aware datetimes, whatever zone the inputs are in.
  - `is_period_start(resolution: str, ts: datetime) -> bool`: `period_start(resolution, ts) == ts`.

- [ ] **Step 1: Write the failing tests** (`PeriodsTests`). Inputs are given both as Pacific and as UTC (`.astimezone(dt_timezone.utc)`), with the same expected results:
  - `period_start('day', 2026-11-01 12:00 PST)` is `2026-11-01T00:00-07:00`; `period_end` of that is `2026-11-02T00:00-08:00` (25 hours later).
  - `period_start('month', 2026-03-01T07:00Z)` is `2026-02-01T00:00-08:00`: Feb 28 23:00 Pacific belongs to February.
  - `period_start('season', 2026-01-15)` is `2025-12-01T00:00-08:00`; `('season', 2026-03-01T00:00-08:00)` is itself; `('quarter', 2026-11-05)` is `2026-10-01T00:00-07:00`; `('year', 2026-07-04)` is `2026-01-01T00:00-08:00`.
  - `list(iter_hours(2026-11-01 00:00 Pacific, 2026-11-01 04:00 Pacific))` is the five UTC hours 07:00Z–11:00Z; `iter_hours` over 2026-03-08 00:00–04:00 Pacific is 08:00Z, 09:00Z, 10:00Z (three, no repeats).
  - `list(iter_period_starts('day', 2026-10-31 Pacific, 2026-11-03 Pacific))` is Oct 31, Nov 1, Nov 2 Pacific midnights; `iter_period_starts('season', 2026-01-10, 2026-06-02)` is Dec 1 2025, Mar 1 2026, Jun 1 2026.
  - `is_period_start('month', 2026-02-28T23:00-08:00)` is `False`.

- [ ] **Step 2: Run them to see them fail**: `TEST camp/apps/summaries/test_periods.py -v`. Expected: ImportError on `camp.apps.summaries.periods`.

- [ ] **Step 3: Implement the module.** Every boundary is built from Pacific calendar values via `localtime()` and `make_aware(datetime(...))`. `iter_period_starts` steps with `period_end(resolution, current)`. `iter_hours` converts `start` to UTC, floors it to the hour, and adds `timedelta(hours=1)`.

- [ ] **Step 4: Run `test_periods.py` and the existing schedule tests**: `TEST camp/apps/summaries -k "period or schedule or settled" -v`. Expected: all pass.

- [ ] **Step 5: Commit**: `git commit -m "Add one module for summary period boundaries"`

### Task 2: Backfill steps Pacific days

**Files:**
- Modify: `camp/apps/summaries/backfill.py` (`chunk_start_for`, `iter_chunk_days`, `daily_rollup_window`, `higher_rollup_windows`, `hour_range`; delete `_months_later`)
- Modify: `camp/apps/summaries/test_backfill.py` (replace `ChunkStartForTests`, `HourRangeTests`, `IterChunkDaysTests`, `DailyRollupWindowTests` and the window-arithmetic asserts in `HigherRollupWindowsTests` with Pacific-fact tests; move in `BackfillDstReproTests` from `test_dst_repro.py`; Task 4 moves the rest and deletes the file)

**Interfaces:**
- Consumes: `period_start`, `period_end`, `iter_period_starts`, `iter_hours` (Task 1).
- Produces: same signatures as today. Every returned day or window start is a Pacific period start, whatever the input zone. `hour_range` is `iter_hours`.

- [ ] **Step 1: Write the failing tests.**
  - `BackfillJobDstTests.test_summer_end_backfill_stamps_pacific_period_starts`: the existing reproduction (`backfill_summaries start --from 2026-02-27 --to 2026-03-10`, ticks to DONE). It asserts:
    - every non-hourly row satisfies `is_period_start(row.resolution, row.timestamp)`;
    - a `month` and a `season` row exist at `2026-03-01T00:00-08:00`;
    - the `day` row for 2026-03-08 has `count == 23` (one hourly row per hour, built with `compute_stats([10.0], 1)`).
  - `test_standard_end_backfill_across_fall_back`: same, with `--from 2026-10-30 --to 2026-11-04`. The `day` row for 2026-11-01 has `count == 25`.
  - `test_chunk_start_for_a_cursor_read_back_as_utc`: save a job with `cursor=` Pacific 2026-03-10, `refresh_from_db()`, then `chunk_start_for(job.cursor, job.range_start, 3)` is `2026-03-07T00:00-08:00`.

- [ ] **Step 2: Run them to see them fail**: `TEST camp/apps/summaries/test_backfill.py -k "Dst or utc" -v`. Expected: the first fails with a missing `2026-03-01T00:00-08:00` month row.

- [ ] **Step 3: Rewrite the five helpers on top of `periods`.**
  - `chunk_start_for`: `max(period_start('day', localtime(cursor) - days), range_start)`, where the subtraction is on the Pacific date.
  - `iter_chunk_days`: `iter_period_starts('day', ...)`.
  - `daily_rollup_window` ends at `period_end('day', day)`.
  - `higher_rollup_windows` reads `day`/`month` from `localtime(day)`, and each window ends at `period_end(resolution, day)`.

- [ ] **Step 4: Run the summaries tests**: `TEST camp/apps/summaries -v`. Expected: all pass.

- [ ] **Step 5: Commit**: `git commit -m "Step backfill days in Pacific dates so standard-time periods start at midnight"`

### Task 3: Scheduled tasks, rebuild_summaries and the API use the period module

**Files:**
- Modify: `camp/apps/summaries/tasks.py`. Delete `_add_3_months`, `_yesterday`, `_last_month_start`, `_last_quarter_start` and `_last_season_start`. Each rollup task's default becomes `period_start(res, period_start(res, now) - 1µs)` (the previous period), and its window end becomes `period_end(res, start)`.
- Modify: `camp/apps/summaries/management/commands/rebuild_summaries.py`. Replace `_iter_hours`, `_iter_days`, `_iter_months`, `_iter_quarters`, `_iter_seasons`, `_iter_years` and `_window_end` with `iter_hours` / `iter_period_starts` / `period_end`.
- Modify: `camp/api/v2/summaries/endpoints.py` (`get_date_filter`): `end = period_end('day'|'month'|'year', start)`.
- Test: `camp/apps/summaries/test_period_consistency.py`

**Interfaces:**
- Consumes: Task 1 and Task 2.
- Produces: `_previous_period_start(resolution: str, now: datetime | None = None) -> datetime` in `tasks.py`, used by every rollup task's default.

- [ ] **Step 1: Write the failing tests** (`PeriodConsistencyTests`, fixtures `purple-air.yaml`, `regions.yaml`; the monitor is placed inside one region; PM2.5 RAW entries every 30 minutes from 2026-10-25 to 2026-11-05 Pacific).
  - `test_three_paths_write_the_same_rows`: build the scope three ways, wiping all summaries between runs:
    1. the backfill job (`--from 2026-10-26 --to 2026-11-04`, ticks to DONE);
    2. `rebuild_summaries 2026-10-26 2026-11-04 --monitor <pk>`;
    3. the hourly tasks for each hour, then `daily_*_summaries(day=...)` for each day.

    The set of `(table, resolution, timestamp, count, mean)` for `day` rows is identical across all three, and every row passes `is_period_start`.
  - `test_rebuild_includes_the_repeated_fall_back_hour`: after `rebuild_summaries 2026-11-01 2026-11-02 --region <pk>`, the region has an hourly row at `2026-11-01T09:00Z` and 25 hourly rows that day.
  - `test_default_periods`, with `timezone.now` patched to `2026-03-01T09:30Z` (01:30 PST, when the monthly and seasonal runs fire): `_previous_period_start('month')` is `2026-02-01T00:00-08:00` and `('season')` is `2025-12-01T00:00-08:00`. At `2026-11-01T09:10Z`, `('day')` is `2026-10-31T00:00-07:00`.
  - In `camp/api/v2/summaries/tests.py`: a `day` row stored at `2026-11-01T00:00-07:00` is returned by `.../daily/2026/11/`, and `.../hourly/2026/11/1/` returns all 25 seeded hourly rows for that day.

- [ ] **Step 2: Run them to see them fail**: `TEST camp/apps/summaries/test_period_consistency.py camp/api/v2/summaries -v`. Expected: `test_rebuild_includes_the_repeated_fall_back_hour` fails (24 rows); the others fail on the missing `_previous_period_start`.

- [ ] **Step 3: Make the three changes listed under Files.**

- [ ] **Step 4: Run the summaries and summaries-API tests**: `TEST camp/apps/summaries camp/api/v2/summaries -v`. Expected: all pass, including #301's crontab/settle-margin test.

- [ ] **Step 5: Commit**: `git commit -m "Use the period module in the scheduled rollups, rebuild_summaries and the API"`

### Task 4: Hourly parents take their hour from the schedule

**Files:**
- Modify: `camp/apps/summaries/schedule.py` (add `hour_for_run`, `HOURLY_FIRE_MINUTE`, `LATE_RUN_WARNING`)
- Modify: `camp/apps/summaries/tasks.py`: `hourly_monitor_summaries` becomes `priority=110` and `hourly_region_summaries` becomes `priority=105`; children stay at 100 and 90. Both parents' default hour comes from `hour_for_run`, and both log the warning. Update the priority comment block.
- Modify: `camp/apps/summaries/test_backfill.py` / `tests.py`: move `LateRegionFanOutReproTests` in, flipped to the fixed behavior.

**Interfaces:**
- Produces:
  - `HOURLY_FIRE_MINUTE = {'monitor': 45, 'region': 50}`
  - `LATE_RUN_WARNING = timedelta(minutes=10)`
  - `hour_for_run(fire_minute: int, now: datetime | None = None) -> tuple[datetime, timedelta]`: returns `(hour, lateness)`. `fire` is the latest `HH:fire_minute` UTC at or before `now`; `hour = fire` floored to the hour minus 1 h; `lateness = now - fire`.
  - The parents log `logger.warning('%s started %s after its :%02d run; summarizing %s', ...)` on logger `camp.apps.summaries` when `lateness > LATE_RUN_WARNING`.

- [ ] **Step 1: Write the failing tests** (`HourlyParentScheduleTests`; monitor rows exist for 09:00Z, as in the reproduction):
  - `hourly_region_summaries` with `now` at 10:50:00Z, 11:01Z and 11:49:59Z each writes the 09:00Z region row. At 11:50Z it writes nothing for 09:00Z and targets 10:00Z.
  - The run at 11:01Z logs one warning on `camp.apps.summaries` (`assertLogs`); the run at 10:55Z logs none.
  - `hourly_monitor_summaries` with `now` at 11:30Z summarizes the 09:00Z hour (one PM25 entry at 09:10Z gives a 09:00Z monitor row).
  - `hourly_monitor_summaries.settings['priority'] == 110` (or the task's `default_priority`, whichever the Huey 3.3 wrapper exposes); region parent `105`; `summarize_monitor_hour` 100; `summarize_region_hour` 90.
  - `hour_for_run(50, now=2026-11-01T09:55Z)` returns `(08:00Z, 5 min)` (the hour that holds both 01:00 Pacific hours works like any other).

- [ ] **Step 2: Run them to see them fail**: `TEST camp/apps/summaries -k HourlyParent -v`. Expected: the 11:01Z case writes no row; ImportError on `hour_for_run`.

- [ ] **Step 3: Implement `hour_for_run` and wire it into both parents with the new priorities.**

- [ ] **Step 4: Run the summaries tests**: `TEST camp/apps/summaries -v`. Expected: all pass.

- [ ] **Step 5: Commit**: `git commit -m "Take the hourly summary hour from the schedule and run the hourly parents first"`

### Task 5: `repair_summaries` command

**Files:**
- Create: `camp/apps/summaries/management/commands/repair_summaries.py`
- Create: `camp/apps/summaries/repair.py` (the logic; the command parses and reports)
- Test: `camp/apps/summaries/test_repair.py`

**Interfaces:**
- Consumes: Task 1; `rollup_monitor_summaries`, `rollup_region_summaries` (tasks.py); `backfill_region_hours` (backfill.py); `Monitor.health_check_queryset_filter`-style type filtering via `{f'{monitor_type}__isnull': False}`.
- Produces:
  - CLI: `repair_summaries START END [--monitor PK]... [--monitor-type TYPE]... [--region PK]... [--region-type TYPE]... [--region-hours] [--dry-run]`. START/END are Pacific dates (END exclusive).
  - `repair.find_misaligned(model, ids_field: str, ids: list, start, end) -> dict[str, list[datetime]]`: resolution → bad timestamps. It scans `timestamp >= start - 1 day, < end`, excluding `hour`, using `values_list('resolution', 'timestamp').distinct()` and `not is_period_start(...)`.
  - `repair.missing_region_hours(region_ids, start, end) -> dict[int, list[datetime]]`: hours that have hourly MonitorSummary rows from a monitor in the region but no hourly RegionSummary row for that region.
  - `repair.reroll(kind: 'monitor'|'region', ids, start, end, now) -> dict[str, int]`: windows rolled per resolution (`day`, `month`, `quarter`, `season`, `year`, in that order). It only covers periods overlapping `[start, end)` whose `period_end <= now`.

**Behavior:**
- No scope flag → `CommandError` before any query. An unknown pk or type → `CommandError` naming it.
- Monitor flags scope the MonitorSummary work; region flags scope the RegionSummary work and `--region-hours`.
- Order:
  1. region hours (only with `--region-hours`);
  2. delete misaligned rows (one `DELETE ... WHERE resolution=%s AND timestamp IN (...)` per resolution and id batch of 500);
  3. re-roll.
- `--dry-run` prints the counts for each step and writes nothing.
- Output: one line per step and resolution, e.g. `monitor month: 3 misaligned deleted, 14 windows rolled`.

- [ ] **Step 1: Write the failing tests** (`RepairSummariesTests`). Set up the wrong rows by running the *old* stepping inline, so the test doesn't depend on deleted code: hourly rows Feb 1–Mar 10 2026, then call `rollup_monitor_summaries` / `rollup_region_summaries` for windows starting at `2026-03-01T07:00Z - n days` (the hour-early shape), plus a `season` row at `2026-05-01T00:00-07:00`. Delete the region's hourly rows for 2026-03-05.
  - With `--dry-run`: output reports the misaligned and missing counts, and `MonitorSummary`/`RegionSummary` row counts and values are unchanged.
  - Without: every non-hourly row passes `is_period_start`; the `2026-02-28T23:00-08:00` month and season rows and the May 1 season are gone; the region has 24 hourly rows for 2026-03-05; the `day` and `month` rows equal those from a clean `rebuild_summaries` of the same scope (compare `count`, `mean`, `minimum`, `maximum`).
  - With `timezone.now` at 2026-03-10: no `month` row for March and no `season` row for Mar–May is written.
  - A second run reports 0 misaligned, 0 missing hours, and the same values.
  - No scope flag → `CommandError`; `--region 999999` → `CommandError` mentioning `999999`.

- [ ] **Step 2: Run them to see them fail**: `TEST camp/apps/summaries/test_repair.py -v`. Expected: unknown command `repair_summaries`.

- [ ] **Step 3: Implement `repair.py` and the command.**

- [ ] **Step 4: Run the repair tests, then EXPLAIN `find_misaligned` and `missing_region_hours` on the local database** (scope: one county; range 2026-10-20 to 2026-11-04) through `podman exec sjvaircom_web_1 python manage.py shell` with `connection.queries` / `.explain(analyze=True)`. Expected: index scans on `(resolution, timestamp)` / the unique constraints, under 100 ms. Record the numbers for the PR.

- [ ] **Step 5: Commit**: `git commit -m "Add repair_summaries for misaligned periods and missing region hours"`

### Task 6: Daily integrity check

**Files:**
- Modify: `camp/apps/summaries/tasks.py` (new task `check_summary_integrity`)
- Modify: `camp/apps/summaries/schedule.py` (`ROLLUP_LOCAL_TIME` is unaffected; no new UTC hour needed)
- Test: `camp/apps/summaries/tests.py` (`SummaryIntegrityCheckTests`)

**Interfaces:**
- Consumes: `repair.find_misaligned`, `repair.missing_region_hours` (Task 5).
- Produces: `@db_periodic_task(pacific_crontab(2, '30'), priority=1, queue='summaries') check_summary_integrity(now=None) -> dict`, returning `{'misaligned': int, 'missing_region_hours': int}`. It checks:
  - misaligned rows in both tables with timestamps in the last 400 days (all ids);
  - missing region hours for the previous Pacific day.

  It logs `logger.error(...)` on `camp.apps.summaries` when either is non-zero (Sentry captures errors), and nothing otherwise.

- [ ] **Step 1: Write the failing tests:**
  - clean data → returns zeros and logs nothing;
  - one month row at `2026-02-28T23:00-08:00` → `misaligned == 1` and one error logged;
  - a region with yesterday's monitor rows but no region row for 03:00 → `missing_region_hours == 1`;
  - `check_summary_integrity.validate_datetime` fires once on 2026-11-01 (fall-back) at 02:30 Pacific (scan every UTC minute of that day, as #301's schedule test does).

- [ ] **Step 2: Run them to see them fail**: `TEST camp/apps/summaries -k Integrity -v`.

- [ ] **Step 3: Implement the task.**

- [ ] **Step 4: Run it against the local database once (read-only) and time it**: `podman exec sjvaircom_web_1 python manage.py shell -c "import time; from camp.apps.summaries.tasks import check_summary_integrity as c; t=time.time(); print(c.call_local(), time.time()-t)"`. Expected: a result dict, under 2 s. Then `TEST camp/apps/summaries -v`: all pass.

- [ ] **Step 5: Commit**: `git commit -m "Check summary periods and region hours daily"`

### Task 7: Prove the repair locally, document, open the PR

**Files:**
- Modify: `CLAUDE.md`: under "Rollup timing", add the period module, the hourly parents (schedule hour, priorities 110/105, lateness warning), `repair_summaries` (with the scoped dry-run example) and `check_summary_integrity`.
- Create: `docs/superpowers/reports/2026-11-04-summary-rollup-followup.md`: findings 2 and 3, the evidence, and the local repair proof.
- Data-dashboard docs (worktree `.worktrees/docs-summaries` from `origin/main`): DEFERRED.md deploy entry and the three "Analysis & data" entries; TODO.md own step 3 item.

- [ ] **Step 1: Message `data-dashboard-2c`** before writing to the shared local DB (scope: 2 monitors and 1 county, 2026-10-20 to 2026-11-04). Wait for an OK.

- [ ] **Step 2: Create the wrong rows locally in a throwaway container on `origin/develop` code.** Mount a clean `git worktree` of `origin/develop` at `/app`. Call the old `iter_chunk_days` / `higher_rollup_windows` with a UTC cursor of 2026-11-04 Pacific, scoped to the two monitors and the county. Then delete the county's hourly rows for 2026-10-28. Record each scope's non-hourly row stamps (expect 01:00 PDT stamps before Nov 1).

- [ ] **Step 3: Repair from this branch in a throwaway container:**
  - first `--dry-run` (record its counts);
  - then the real run, with the same scope and `--region-hours`.

  Check: every row passes `is_period_start`; the county has 24 or 25 hourly rows per day; the re-rolled `day` rows match a clean `rebuild_summaries` of one of the monitors. Message `data-dashboard-2c` that the stack data is back to normal (the scoped rows are now correct).

- [ ] **Step 4: Full suite**: `TEST -n 4 --dist loadscope`. Expected: about 4225 plus the new tests passed, 0 failed (ignore the trailing "not a git repository" line).

- [ ] **Step 5: Write the docs and commit:** `git commit -m "Document the period module, repair_summaries and the integrity check"`. Push the branch and open a PR into `develop`. The PR body holds the summary, the EXPLAIN/timing numbers, the full-suite result and the local repair proof; no merge without the user's yes.

- [ ] **Step 6: Update data-dashboard docs** following TODO.md → "Docs rules for the other sessions". Re-read each file before editing, run prettier, and push the docs-only commit to `main`. The deploy entry gains the ordered pre-deploy list from the spec ("Production" section). Each step carries:
  - a **size first** command (the `--dry-run` with explicit scope, and counts by resolution and type);
  - a **check after** (the report's curl requests: Pacific-midnight stamps; region hourly 24/25 rows per day).

  The list:
  1. checks: worker logs, dyno formation, Sentry, Redis, `backfill_summaries status`;
  2. deploy within #301's window;
  3. region hours;
  4. misaligned rows and re-roll (one monitor and one county first, wider after a yes);
  5. #301's catch-up;
  6. how the list grows.

  Update the three "Analysis & data" entries to point at the PR (move them out only once deployed). Message `data-dashboard-2c` with the PR link and that the repair plan is in DEFERRED.md.
