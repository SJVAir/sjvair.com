# Current Periods Written Nightly — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the on-request open-period rows with current-period rows the summarizer writes
each night (through yesterday), flagged `is_partial` so a missed night never reads as final.

**Architecture:** The branch already has the period daily statistic (columns, fill, rollup hooks,
command, guards, CO rule, meta keys; plan `2026-11-18-period-daily-statistic.md`, Tasks 1–5 and 8).
This plan removes that plan's open-period work (Tasks 6–7 and the centroid percentiles), then adds
`is_partial`, a "through yesterday" expected-days rule, a `roll_current_periods` function with two
nightly tasks, its callers, and the integrity counts.

**Tech Stack:** Django 5.2, PostGIS, Huey (`pacific_crontab`), django-resticus, pytest in podman.

**Spec:** `docs/superpowers/specs/2026-11-18-period-daily-statistic-design.md` (sections "Current
periods (written nightly)", "Model and migration", "Guards", "Production at deploy").

## Global Constraints

- Tests run in podman, inline from the worktree root (no shell variable for the command), with the
  test env file only:
  `podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token -v $PWD:/app:z -w /app sjvair-com-test:latest pytest <path> -v`
  (full suite: the same with `pytest -n 4 --dist loadscope -q`). Never the dev `.env`, never the
  `sjvaircom_*` containers, never `podman-compose`.
- Never start, restart, rebuild or migrate the shared containers, never run a management command
  against the shared database, never write to it. Tests only (they use the test database).
- Never write subscriptions or alerts (the local stack sends real SMS).
- Additive only: existing values and shapes stay as they are; the Pesticides and Facility Emissions
  explorers must not change. `daily/open/` ends byte-for-byte as on `develop` (5e669a70).
- No Claude or AI attribution in commits, docs or comments. No to-do lists for other projects.
- `0008` is already applied to the local dev DB and must not change. `is_partial` goes in a new
  `0009_summary_is_partial.py` with `SET LOCAL lock_timeout = '10s'` first, like `0008`.
- `is_partial`: `BooleanField(default=False)` on `BaseSummary`; never serialized.
- Nightly tasks: `current_monitor_periods` at `pacific_crontab(2, '15')`, `current_region_periods`
  at `pacific_crontab(2, '20')`, queue `summaries`, priorities 4 and 3 (below the yearly region
  rollup's 5, above `check_summary_integrity`'s 1).
- Periods come from the clock when the code runs, never from a scheduled date. All period math via
  `camp/apps/summaries/periods.py` (`period_start`, `period_end`), never a timedelta of a day or more.
- Integrity keys: `missing_current_periods`, `stale_partial_periods`; the old log message is
  verbatim when all new counts (with `missing_period_statistics`) are 0.
- Monitor ids can start with `-`: commands take `--monitor=<id>` with `=`.

## Review Focus

1. **A run that straddles midnight** (started on the period's last day, still writing after 00:00):
   it must stop and write nothing more, leaving the final row the 01:15 rollup writes untouched.
   Pinned in Task 4 (`test_stops_when_midnight_passes`).
2. **An owner that sent nothing yesterday:** its current row keeps its stats, but
   `daily_statistic_expected_days` moves on and the mean goes null below 75%. Pinned in Task 4
   (`test_unchanged_owner_expected_days_move`).
3. **January 1:** month, quarter and year all just ended (written in full, not partial); the
   season (Dec–Feb) is still running (partial through Dec 31). Pinned in Task 4
   (`test_january_first_mixed_periods`).
4. **A stale partial row inside a settled range:** the response must not be cached for a day, and
   the row reads `is_final: false`, in the single and the bulk lists. Pinned in Task 2
   (`test_stale_partial_row_not_cached_long`, `test_bulk_partial_row_not_final`).
5. **DST months:** a current November (fall-back) or March row counts calendar days, not 24-hour
   steps. Pinned in Task 3 (`test_current_period_expected_days_across_fall_back`).

---

### Task 1: Remove the open-period design

**Files:**
- Delete: `camp/apps/summaries/open_periods.py`, `camp/apps/summaries/test_open_periods.py`
- Restore to `5e669a70` exactly: `camp/apps/summaries/open_days.py`, `camp/apps/summaries/aggregators.py`,
  `camp/api/v2/summaries/endpoints.py`, `camp/api/v2/summaries/filters.py`,
  `camp/api/v2/summaries/monitor_urls.py`, `camp/api/v2/summaries/region_urls.py`,
  `camp/api/v2/summaries/bulk_urls.py`, `camp/api/v2/summaries/region_bulk_urls.py`
- Modify: `camp/api/v2/summaries/tests.py` (drop `OpenPeriodsEndpointTests`),
  `camp/api/v2/tests/test_openapi.py` (drop `test_open_period_paths_documented`,
  `test_bulk_open_period_paths_documented`), `CLAUDE.md` (drop the open-period and centroid text;
  Task 6 writes the new text)

**Interfaces:**
- Produces: a branch with no `open_periods`, `centroid_percentiles`, `percentiles=`,
  `BulkMonitorScopeFilter`, `OpenRowsMixin` or `OpenPeriodsMixin` anywhere under `camp/`.

- [ ] **Step 1:** `git checkout 5e669a70 -- <the eight restore paths>` and `git rm` the two files.
- [ ] **Step 2:** Remove the listed test classes/methods; keep `SummarySerializerFieldTests`, the
  integrity and CO tests.
- [ ] **Step 3: Verify the removal**

Run: `git diff 5e669a70 -- camp/apps/summaries/open_days.py camp/apps/summaries/aggregators.py camp/api/v2/summaries/endpoints.py camp/api/v2/summaries/filters.py camp/api/v2/summaries/*urls.py | wc -l`
Expected: `0`. And `grep -rn -e open_periods -e centroid_percentiles -e "percentiles=" -e BulkMonitorScopeFilter -e OpenRowsMixin camp` prints nothing.

- [ ] **Step 4:** Run `camp/apps/summaries/` and `camp/api/v2/summaries/` and `camp/api/v2/tests/test_openapi.py`. Expected: PASS.
- [ ] **Step 5:** Commit `Remove the on-request open-period rows`.

### Task 2: `is_partial`, the rollup flag and guard, and `is_final`

**Files:**
- Modify: `camp/apps/summaries/models.py`, `camp/apps/summaries/tasks.py`
  (`rollup_monitor_summaries`, `rollup_region_summaries`), `camp/apps/summaries/schedule.py`
  (`row_is_final`), `camp/api/v2/summaries/serializers.py`, `camp/api/v2/summaries/endpoints.py`
  (`SummaryMixin.dispatch`)
- Create: `camp/apps/summaries/migrations/0009_summary_is_partial.py`
- Test: `camp/apps/summaries/tests.py`, `camp/api/v2/summaries/tests.py`

**Interfaces:**
- Produces:
  - `rollup_monitor_summaries(target, source, window_start, window_end, monitor_ids=None, *, is_partial=False, guard=None)`
    and the region twin (`region_ids=None`). Every row built gets `is_partial`; `'is_partial'` is in
    both upserts' `update_fields`, so a full write clears it. `guard: Callable[[], bool] | None`:
    called right before the `bulk_create` and again before the fills; when it returns `False` the
    function returns without writing. Returns `True` when it wrote (or had nothing to write), `False`
    when the guard stopped it.
  - `row_is_final(resolution, timestamp, entry_type, now=None, is_partial=False)`: `False` when
    `is_partial`, else unchanged.
  - The serializers' `is_final` passes the row's `is_partial` (unsaved open-day rows read `False`).
  - Cache rule: `SETTLED_MAX_AGE` only when the range is settled AND no serialized row had
    `is_partial` set. Record it in the same context `serializing_at` opens (a flag the `is_final`
    function sets), and read it in `dispatch` after `super().dispatch`.

- [ ] **Step 1: Write the failing tests**
  - `test_partial_row_not_final`: `row_is_final('month', <a month ended a week ago>, 'pm25', now=..., is_partial=True) is False`; same call with `is_partial=False` is `True`.
  - `test_full_rollup_clears_is_partial`: create a MONTHLY row with `is_partial=True`, run `rollup_monitor_summaries(MONTHLY, DAILY, start, end)`; the row's `is_partial` is `False`.
  - `test_rollup_partial_flag`: `rollup_monitor_summaries(..., is_partial=True)` writes `is_partial=True`; region twin likewise.
  - `test_rollup_guard_false_writes_nothing`: with `guard=lambda: False`, no row is created or changed (compare the row's values before/after) and the call returns `False`.
  - `test_stale_partial_row_not_cached_long`: a settled-range monthly list request whose page holds one `is_partial=True` row returns `max-age=60` and that row's `is_final` is `false`; without it, `max-age=86400`.
  - `test_bulk_partial_row_not_final`: the bulk monitor and bulk region lists show `is_final: false` for a partial row and `max-age=60`.
  - `test_is_partial_not_serialized`: `'is_partial' not in` a monitor and a region row's JSON.
- [ ] **Step 2:** Run them. Expected: FAIL (`is_partial` unknown field).
- [ ] **Step 3:** Implement the field, `0009` (two `AddField`s after `RunSQL("SET LOCAL lock_timeout = '10s'", reverse_sql=migrations.RunSQL.noop)`, as in `0008`), and the interfaces above.
- [ ] **Step 4:** Run `camp/apps/summaries/` and `camp/api/v2/summaries/`. Expected: PASS (existing CO and settle tests unchanged).
- [ ] **Step 5:** Commit `is_partial: a partial row is never final`.

### Task 3: Expected days through yesterday

**Files:**
- Modify: `camp/apps/summaries/period_stats.py` (`fill_period_statistics`)
- Test: `camp/apps/summaries/test_period_stats.py`

**Interfaces:**
- Produces: `fill_period_statistics(..., now=None)` (keyword; default `timezone.now()`): each row's
  `until = min(period_end(row.resolution, row.timestamp), period_start('day', now))`; `expected =
  expected_days(row.timestamp, until)`; figures counted in `[row.timestamp, until)`. Ended periods
  are unchanged.

- [ ] **Step 1: Write the failing tests**
  - `test_current_period_expected_days_through_yesterday`: a MONTHLY row for the month holding `now = pacific(2026, 11, 18, 3)` with daily figures on Nov 1–17 → `daily_statistic_expected_days == 17`, `days == 17`, mean = their average.
  - `test_current_period_below_75_percent_is_null`: same month, figures on 12 of 17 days (`ceil(0.75*17) == 13`) → mean `None`, `days == 12`.
  - `test_current_period_expected_days_across_fall_back`: `now = pacific(2026, 11, 3, 3)` (after the Nov 1 fall-back) → expected `2`.
  - `test_ended_period_unchanged_by_now`: an October row filled with `now` in November → expected `31`.
- [ ] **Step 2:** Run. Expected: FAIL (`now` unexpected keyword / expected 30).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `camp/apps/summaries/test_period_stats.py`. Expected: PASS.
- [ ] **Step 5:** Commit `fill_period_statistics: a current period expects the days through yesterday`.

### Task 4: `roll_current_periods` and the nightly tasks

**Files:**
- Create: `camp/apps/summaries/current_periods.py`, `camp/apps/summaries/test_current_periods.py`
- Modify: `camp/apps/summaries/tasks.py` (two periodic tasks)

**Interfaces:**
- Consumes: Task 2's rollup `is_partial`/`guard`, Task 3's `now`.
- Produces:
  - `roll_current_periods(kind: str, ids: list | None = None, now: datetime | None = None, *, clock=timezone.now) -> dict`
    — returns `{'rolled': {resolution: owners_rolled}, 'refreshed': {resolution: rows_updated}, 'stopped': bool}`.
  - `current_monitor_periods(monitor_ids=None)` and `current_region_periods(region_ids=None)` in
    `tasks.py`, calling it with `'monitor'` / `'region'`.

Behaviour (spec "Current periods"):
- `today = period_start('day', now)`, `yesterday = period_start('day', today - timedelta(microseconds=1))`.
  `guard = lambda: period_start('day', clock()) == today`; check it before every write; on `False`,
  log a warning and return with `stopped=True`.
- For `month`, then `quarter`, `season`, `year` (sources DAILY for month, MONTHLY for the others):
  `P.start = period_start(res, yesterday)`, `end = min(period_end(res, P.start), today)`,
  `partial = period_end(res, P.start) > today`.
- Owners rolled: `ids` when given; otherwise, when `partial`, the owners with a DAILY row at
  `timestamp == yesterday` (one `values_list(..., flat=True).distinct()` per kind); when not
  partial (the period's first night), all owners (`None`), the same as the regular rollup.
- Call the kind's rollup with `(target, source, P.start, end, <ids>, is_partial=partial, guard=guard)`
  and `fill_period_statistics` is reached through it with `now`. Pass `now` through: the rollup's
  internal fill call needs `now=` (add a `now=None` keyword to the rollups, forwarded to the fill).
- Refresh (only when `ids is None` and `partial`): for rows with `resolution=res`,
  `timestamp=P.start`, `is_partial=True`, entry type in the peak types, owner not among those just
  rolled: one `UPDATE` setting `daily_statistic_expected_days = N` (`N = expected_days(P.start, today)`)
  and one `UPDATE` setting `daily_statistic_mean = NULL` where `daily_statistic_days < ceil(0.75 * N)`.

- [ ] **Step 1: Write the failing tests** (`test_current_periods.py`; build HOURLY→DAILY rows with the existing rollups, as `test_period_stats.py` does)
  - `test_writes_month_through_yesterday_partial`: `now = pacific(2026, 11, 18, 2, 15)`; the Nov MONTHLY row exists with `is_partial=True`, its `count` equals the sum of the Nov 1–17 daily rows' counts, `daily_statistic_expected_days == 17`.
  - `test_quarter_season_year_include_partial_month`: the Q4, fall season (Sep–Nov) and 2026 rows exist, are partial, and their `count` equals the sum of their stored MONTHLY rows including the partial November.
  - `test_first_night_writes_ended_period_in_full`: `now = pacific(2026, 12, 1, 2, 15)` → the November row has `is_partial=False` and equals, field for field (stats, t-digest, the three period fields), a row from `rollup_monitor_summaries(MONTHLY, DAILY, nov_start, dec_start)`; no December row exists.
  - `test_january_first_mixed_periods`: `now = pacific(2027, 1, 1, 2, 15)` → Dec, Q4 and 2026 rows `is_partial=False`; the winter season (Dec 2026–Feb 2027) row `is_partial=True` with expected days `31`.
  - `test_only_owners_with_yesterday_rolled`: two monitors, only one with a Nov 17 daily row; `result['rolled']['month'] == 1`; the other's row values (except the refreshed fields) are unchanged.
  - `test_unchanged_owner_expected_days_move`: the unrolled owner's partial row had `expected_days=16, days=12, mean=x` → after the run `expected_days == 17` and mean `None` (`12 < 13`); with `days=13` the mean stays `x`.
  - `test_stops_when_midnight_passes`: `clock` returns `pacific(2026, 12, 1, 0, 5)` while `now = pacific(2026, 11, 30, 2, 15)`; a final November row written beforehand is byte-for-byte unchanged; `result['stopped'] is True`.
  - `test_period_starting_today_gets_no_row`: `now = pacific(2026, 12, 1, 2, 15)` → no December MONTHLY row.
  - `test_regions_twin`: the region path writes partial region rows with `station_count` from the inputs.
  - `test_tasks_scheduled`: `current_monitor_periods` and `current_region_periods` validate at `pacific(2026, 11, 18, 2, 15)` / `2, 20` (UTC, as Huey calls them) and not at `2, 14`.
- [ ] **Step 2:** Run. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `camp/apps/summaries/`. Expected: PASS, including the existing test that checks `ROLLUP_LOCAL_TIME` against the crontabs.
- [ ] **Step 5:** Commit `Nightly current-period rows through yesterday`.

### Task 5: Callers — rebuilds, repair, backfill job, CIMIS finalize

**Files:**
- Modify: `camp/apps/summaries/management/commands/rebuild_summaries.py`,
  `camp/apps/summaries/management/commands/repair_summaries.py`, `camp/apps/summaries/tasks.py`
  (`_backfill_complete_chunk`), `camp/apps/monitors/cimis/tasks.py` (`finalize_cimis_data`)
- Test: `camp/apps/summaries/tests.py`, `camp/apps/summaries/test_period_consistency.py`, the CIMIS task tests

**Interfaces:**
- Consumes: `roll_current_periods`, `current_monitor_periods(monitor_ids=)`, `current_region_periods(region_ids=)`.

Behaviour: each runs the current periods for its own scope when its range reaches yesterday
(`range end > start of yesterday`):
- `rebuild_summaries`: sync path calls `roll_current_periods(kind, ids, now)` after its rollups;
  the enqueue path enqueues `current_monitor_periods(monitor_ids=ids)` / `current_region_periods(region_ids=ids)`
  after its rollups. Update the `finished_period_starts` docstring: the current periods are written
  through yesterday by `roll_current_periods`.
- `repair_summaries`: after its re-rolls (not on `--dry-run`, which prints `current periods: <n> owners`).
- Backfill job: when `_backfill_complete_chunk` sets `State.DONE` and the job's range reaches
  yesterday, `roll_current_periods('monitor', None, now)` and `('region', None, now)`.
- `finalize_cimis_data`: after the station loop, `current_monitor_periods(monitor_ids=<CIMIS ids>)`.

- [ ] **Step 1: Write the failing tests**
  - Extend the existing full-rebuild guard test (`test_period_consistency.py`): a rebuild through `now` leaves a partial current month, quarter, season and year row for every series with a daily row yesterday.
  - `test_repair_writes_current_periods` and `test_repair_dry_run_writes_no_current_periods`.
  - `test_backfill_done_writes_current_periods`.
  - `test_finalize_cimis_rolls_current_periods` (patch the fetch as the existing finalize tests do).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `camp/apps/summaries/` and `camp/apps/monitors/`. Expected: PASS.
- [ ] **Step 5:** Commit `Rebuilds, repair, backfill and CIMIS finalize write the current periods`.

### Task 6: Integrity counts and docs

**Files:**
- Modify: `camp/apps/summaries/tasks.py` (`check_summary_integrity`), `CLAUDE.md`
- Test: `camp/apps/summaries/tests.py`

**Interfaces:**
- `check_summary_integrity(now=None)` result gains `missing_current_periods` (series with a DAILY row
  at yesterday and no MONTHLY row at `period_start('month', yesterday)`; monitor series are
  monitor + entry type + processor) and `stale_partial_periods` (per coarse resolution, rows with
  `is_partial=True` and `timestamp < period_start(res, now - timedelta(days=1))`), both tables summed.

- [ ] **Step 1: Write the failing tests**
  - `test_counts_missing_current_periods`; `test_counts_stale_partial_periods` (a partial October row checked on Nov 18 counts 1; a partial November row counts 0).
  - The existing `test_old_log_message_is_unchanged_when_only_misaligned_fires` still passes with both new counts 0.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement; the error names each non-zero new count, as `missing_period_statistics` does.
- [ ] **Step 4:** CLAUDE.md: rewrite the "Period daily statistic" bullet for current periods
  (through yesterday, the period holding yesterday, 02:15/02:20, `is_partial` and `is_final`, the
  cache rule, the callers, the two integrity keys) and the deploy steps (`0008` and `0009` together:
  away from :40–:50, no `SummaryBackfillJob` running; the scoped `fill_period_statistics`; current
  rows appear the first night). Remove the remaining open-period mention from the "Summary cache
  rule" note if any.
- [ ] **Step 5:** Run the full suite. Expected: 0 failed.
- [ ] **Step 6:** Commit `Integrity counts current and stale partial periods; docs`.
