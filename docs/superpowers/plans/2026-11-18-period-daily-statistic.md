# Period Daily Statistic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every month/quarter/season/year monitor and region summary row of a pollutant with a daily figure carries the average of the period's daily figures (`daily_statistic_mean`) with its day counts, unfinished periods get open-period rows on request, and every scale names the field in `period_statistic`.

**Architecture:** A separate fill (`camp/apps/summaries/period_stats.py`) reads each coarse period's DAILY rows and writes three columns; the two rollup functions in `tasks.py` call it after their upsert, so every path that builds coarse rows fills them. Open periods (`open_periods.py`) are built on request from stored monthly/daily rows plus the existing open-day rows, through one shared rule (`period_figure`).

**Tech Stack:** Django 5.2, PostgreSQL/PostGIS, django-resticus, Huey, pytest (Django `TestCase`, pytest-style asserts).

**Spec:** `docs/superpowers/specs/2026-11-18-period-daily-statistic-design.md` (read it first; this plan argues from it).

## Global Constraints

- Branch `feature/period-daily-statistic` in `.worktrees/period-daily-statistic`, PR into **`develop`**, never `main`.
- **Additive only:** no existing field, endpoint or output changes, except `is_final`/`max-age` on CO (`max_8h`) coarse rows (28 h margin).
- Names, verbatim: row fields `daily_statistic_mean`, `daily_statistic_days`, `daily_statistic_expected_days`; scale keys `period_statistic` (value `"daily_statistic_mean"` or `null`), `period_statistic_label`.
- Labels, verbatim: `max_1h` "Average of daily highest 1-hour averages", `max_8h` "Average of daily highest 8-hour averages", `mean_24h` "Average of 24-hour averages".
- Rule: `expected` = Pacific calendar days in the period (open period: start through today, today included); `days` = daily rows with a non-null figure; mean only when `days >= ceil(0.75 * expected)`.
- Coarse = `month`, `quarter`, `season`, `year`. Hour/day rows and types without `daily_statistic` keep all three fields null.
- Period math only via `camp/apps/summaries/periods.py` (no `timedelta` of a day or more).
- No new periodic task. No Claude/AI attribution in commits, PR, docs. Never run anything against the shared stack's DB or containers (`sjvaircom_*`) without the coordinator's OK.
- Tests: Django `TestCase`, pytest asserts. Bulk-created `RegionSummary` rows need a non-empty t-digest (`tdigest_to_dict` of a one-value `TDigest`). `pk__in=` takes pks or a queryset, never a list of instances.

**Test command** (podman-compose doesn't work from a worktree; run from the worktree root, `.env.test` is already copied in; one "fatal: not a git repository" line is harmless):

```bash
T="podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token -v $PWD:/app:z -w /app sjvair-com-test:latest pytest"
$T camp/apps/summaries/test_period_stats.py -v
```

resticus hides tracebacks in tests (`Http500` with no detail): patch the view's `server_error` to print the exception when debugging.

## Review Focus

1. **DST months:** November (25-hour day) and March (23-hour day) still have 30 and 31 expected days: `expected` counts calendar days, not hours/24. Test in Task 2.
2. **Exactly at the threshold:** 23 of 30 days gives a mean, 22 gives `null`; `days` is 22, not `null`. Test in Task 2.
3. **A coarse row whose days all have null figures:** `days == 0`, `expected_days` set, mean `null` (and the integrity check does not flag it). Tests in Tasks 2 and 5.
4. **Several processors on one monitor:** each series averages only its own daily rows. Test in Task 2.
5. **Just after a period ends** (e.g. 00:30 on Jan 1): the previous year and the new one may both be open, never more than 2 rows per series, and the previous one drops out once stored or settled. Test in Task 6.

---

### Task 1: Columns, serializers and scale keys

**Files:**
- Modify: `camp/apps/summaries/models.py` (BaseSummary)
- Create: `camp/apps/summaries/migrations/0008_period_daily_statistic.py`
- Modify: `camp/api/v2/summaries/serializers.py`
- Modify: `camp/utils/scales.py`, `camp/apps/entries/levels.py`
- Test: `camp/apps/summaries/tests.py` (serializer), `camp/apps/entries/tests/test_scales.py`

**Interfaces:**
- Produces: model fields `daily_statistic_mean: FloatField(null)`, `daily_statistic_days: PositiveSmallIntegerField(null)`, `daily_statistic_expected_days: PositiveSmallIntegerField(null)` on both summary tables; `PERIOD_STATISTIC_FIELD = 'daily_statistic_mean'` and `PERIOD_STATISTIC_LABELS` in `levels.py`; `Scale.period_statistic`, `Scale.period_statistic_label` (default `None`).

- [ ] **Step 1: Failing tests.**
  - `test_scales.py::test_period_statistic`: `levels.O3` scale JSON has `period_statistic == 'daily_statistic_mean'` and `period_statistic_label == 'Average of daily highest 1-hour averages'`; CO's label is the `max_8h` one, PM2.5's `'Average of 24-hour averages'`; a scale with `daily_statistic` `None` (e.g. the calheat scale from `camp/apps/calheatscore`) has both `None`; key order: `list(json)` has `period_statistic`, `period_statistic_label` right after `daily_statistic_label`.
  - `tests.py::SummarySerializerFieldTests::test_period_fields`: a saved monthly `MonitorSummary` with the three fields set serializes them (keys after `mean_24h`); a `RegionSummary` likewise; an hourly row serializes them as `None`.
- [ ] **Step 2: Run; expect FAIL** (unknown field / missing key).
- [ ] **Step 3: Implement.** Fields on `BaseSummary` after `mean_24h`, verbose names "average of daily figures", "days with a daily figure", "expected days". Migration `0008` depends on `0007_summary_peaks`, starts with `migrations.RunSQL("SET LOCAL lock_timeout = '10s'", migrations.RunSQL.noop)` and the same comment as `0007`, then six `AddField`s. `LevelSet.to_scale` passes `period_statistic=PERIOD_STATISTIC_FIELD if self.daily_statistic else None` and the label from `PERIOD_STATISTIC_LABELS[self.daily_statistic]`; `Scale.to_json` emits both after `daily_statistic_label` (`str()` the lazy label like `daily_statistic_label`). Serializers list the three names after `mean_24h`.
- [ ] **Step 4: Run** `$T camp/apps/entries/tests/test_scales.py camp/apps/summaries/tests.py camp/api/v2/summaries/tests.py camp/api/v2/tests/test_openapi.py`, then the same `podman run ...` with `python manage.py makemigrations summaries --check --dry-run` in place of `pytest`; expect PASS and "No changes detected". Existing tests that compare whole scale or row dicts get the new keys added (that is the only edit allowed to them).
- [ ] **Step 5: Commit** "Period daily statistic columns, serializer fields and scale keys".

### Task 2: The rule and the fill

**Files:**
- Create: `camp/apps/summaries/period_stats.py`
- Test: `camp/apps/summaries/test_period_stats.py`

**Interfaces:**
- Consumes: Task 1 fields; `peaks.peak_entry_models()`, `peaks._owner_group_size`, `periods.period_end`, `periods.iter_period_starts`.
- Produces:
  - `COARSE_RESOLUTIONS = ('month', 'quarter', 'season', 'year')`
  - `PERIOD_FIELDS = ('daily_statistic_mean', 'daily_statistic_days', 'daily_statistic_expected_days')`
  - `expected_days(period_start: datetime, until: datetime) -> int` (Pacific days from `period_start` to `until`, exclusive; `until` is a day start)
  - `period_figure(figures: list[float], expected: int) -> tuple[float | None, int]` → `(mean, days)`
  - `fill_period_statistics(kind: str, ids: list | None, start: datetime, end: datetime, *, resolutions=COARSE_RESOLUTIONS, entry_models: list | None = None, dry_run: bool = False, batch_size: int = 1000, progress=None) -> dict[str, int]` (rows updated per entry type)

- [ ] **Step 1: Failing tests** in `test_period_stats.py` (fixtures `purple-air.yaml`, `regions.yaml`; helpers like `test_peaks.py`'s `pacific_day` and `_stats`):
  - `PeriodFigureTests`: `period_figure([10.0]*23, 30) == (10.0, 23)`; `period_figure([10.0]*22, 30) == (None, 22)`; `period_figure([], 31) == (None, 0)`; `period_figure([1.0, 2.0, 3.0], 3) == (2.0, 3)`; `expected_days(pacific(2026,11,1), pacific(2026,12,1)) == 30`; March 2026 is 31; Q4 2026 is 92; season Dec 2025–Feb 2026 is 90; year 2028 is 366.
  - `FillPeriodStatisticsTests`:
    - `test_month_monitor`: O3 DAILY rows Nov 1–23 2026 with `max_1h` 40..62 and Nov 24–30 with `max_1h=None`, plus a stored MONTHLY row (any stats): after `fill_period_statistics('monitor', None, pacific(2026,11,1), pacific(2026,12,1))` the monthly row has `daily_statistic_mean == mean(40..62)`, `days == 23`, `expected_days == 30`.
    - `test_below_threshold`: 22 non-null days → mean `None`, days 22, expected 30.
    - `test_no_figures`: monthly row with only null-figure daily rows → `(None, 0, 30)`.
    - `test_quarter_reads_daily_rows`: a QUARTERLY row for Q4 2026 with daily PM2.5 `mean_24h` rows on 80 days → expected 92, days 80, mean of the 80.
    - `test_processors_kept_apart`: two processors' daily rows on one monitor, one monthly row each; each monthly mean equals its own series' mean.
    - `test_region`: same as month for `RegionSummary`.
    - `test_non_peak_type_untouched`: a monthly `temperature` row keeps all three `None`.
    - `test_scope_and_dry_run`: `ids=[other]` leaves the row unchanged; `dry_run=True` returns the counts and writes nothing; a second real run returns `{}` (only changed rows written).
- [ ] **Step 2: Run; expect FAIL** (module missing).
- [ ] **Step 3: Implement** `period_stats.py`. `expected_days` steps day starts with `iter_period_starts('day', ...)`. The fill mirrors `fill_daily_peaks`: coarse rows of the peak types in `[start, end)` and `resolutions`, owner groups sized by `_owner_group_size(first_period_start, last_period_end)`, one `values_list(owner, 'entry_type', ['processor',] 'timestamp', <figure column per type>)` read of DAILY rows per group covering the group's periods, figures grouped by series then bucketed into each coarse row's `[row.timestamp, period_end(row.resolution, row.timestamp))`, `expected = expected_days(row.timestamp, period_end(...))`, `bulk_update(PERIOD_FIELDS)` of changed rows in `transaction.atomic()` batches.
- [ ] **Step 4: Run** `$T camp/apps/summaries/test_period_stats.py -v`; expect PASS.
- [ ] **Step 5: Commit** "fill_period_statistics: the average of a period's daily figures".

### Task 3: Fill inside the rollups; CO refresh and settle margin

**Files:**
- Modify: `camp/apps/summaries/tasks.py` (`rollup_monitor_summaries`, `rollup_region_summaries`, `_refresh_previous_max_8h`)
- Modify: `camp/apps/summaries/schedule.py` (`is_settled`)
- Test: `camp/apps/summaries/test_period_stats.py`, `camp/apps/summaries/tests.py` (`test_peak_8h_margin`)

**Interfaces:**
- Consumes: `fill_period_statistics`, `COARSE_RESOLUTIONS` (Task 2).
- Produces: every coarse rollup fills `PERIOD_FIELDS`; `is_settled(resolution, ..., peak_8h=True)` uses `PEAK_8H_SETTLE_MARGIN` for `day` and every coarse resolution.

- [ ] **Step 1: Failing tests.**
  - `RollupFillsTests::test_monthly_rollup_fills`: daily O3 rows for Nov 2026 (with `max_1h`), then `monthly_monitor_summaries.call_local(month_start=pacific(2026,11,1))` and `monthly_region_summaries...`: the monthly rows have the three fields set. Same for `quarterly_*` (Q4 needs Oct–Dec daily + monthly rows; run the monthly rollups first).
  - `RollupFillsTests::test_reroll_keeps_then_rewrites`: change a daily figure, rerun the monthly rollup: the mean follows.
  - `CORefreshTests::test_last_day_refresh_refills_month`: CO hourly rows for Nov 30 2026 whose last windows need Dec 1 morning hours; run `daily_monitor_summaries(day=Nov 30)`, the monthly rollup for Nov, then add the Dec 1 hours and run `daily_monitor_summaries(day=Dec 1)`: Nov's monthly `daily_statistic_mean` equals the mean over the refreshed `max_8h` (Nov 30's final value). Reuse `test_peaks.NextNightRefreshTests` helpers for the hours.
  - In `tests.py::...::test_peak_8h_margin` replace the "Only the day resolution is affected" assertion: `not is_settled('month', month_end, now=month_end_plus(27h), peak_8h=True)`, `is_settled(... 28h ..., peak_8h=True)`, and plain `is_settled('month', ..., now=+4h)` still true. Add `test_co_monthly_row_not_final`: `row_is_final('month', Nov 1, 'co', now=Dec 1 05:00)` is `False`, `'o3'` is `True`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** After each upsert: `if target_resolution in COARSE_RESOLUTIONS: fill_period_statistics(kind, ids, window_start, window_end, resolutions=[target_resolution])`. In `_refresh_previous_max_8h(kind, start)`: after the daily refill, let `day = previous day start`; for each coarse resolution where `period_end(res, day) == start` (the refreshed day is that period's last), call `fill_period_statistics(kind, None, period_start(res, day), start, resolutions=[res], entry_models=<max_8h models>)`. In `is_settled`, apply `PEAK_8H_SETTLE_MARGIN` when `peak_8h and resolution != 'hour'`; update its docstring and the `PEAK_8H_SETTLE_MARGIN` comment ("day and coarser").
- [ ] **Step 4: Run** `$T camp/apps/summaries/ camp/api/v2/summaries/ -n 4 --dist loadscope`; expect PASS. Any existing test pinning CO coarse `is_final`/`max-age` moves to the 28 h rule (the only allowed edit).
- [ ] **Step 5: Commit** "Coarse rollups fill the period daily statistic; CO waits for the last day's refresh".

### Task 4: `fill_period_statistics` command

**Files:**
- Create: `camp/apps/summaries/management/commands/fill_period_statistics.py`
- Test: `camp/apps/summaries/test_period_stats.py`

**Interfaces:**
- Consumes: `fill_period_statistics`; `_scope.ScopeMixin` (`_parse_date`, `_monitor_ids`, `_region_ids`, `_fmt`, `_progress`) as `fill_daily_peaks.py` uses it.
- Produces: `manage.py fill_period_statistics START END [--monitor=PK ...] [--monitor-type T ...] [--region=PK ...] [--region-type T ...] [--resolution R ...] [--entry-type T ...] [--batch-size N] [--dry-run]`.

- [ ] **Step 1: Failing tests** (`FillPeriodStatisticsCommandTests`, `call_command` with `stdout=StringIO()`): no scope → `CommandError` naming the four flags; `--resolution day` → `CommandError` (choices are the four coarse ones); `--entry-type temperature` → `CommandError` listing eligible types; a scoped run fills a monthly row and prints `monitor o3: 1 row changed`; `--dry-run` prints `would change` and writes nothing; a re-run prints `monitor period statistics: nothing to do`; output starts with `Range:` and ends `Done.` / `Dry run done.`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement**, structured like `fill_daily_peaks.py`, chunking one Pacific **year** at a time (`iter_period_starts('year', ...)`, chunk `[max(year, start), min(period_end, end))`) and passing rows whose timestamp is in the chunk.
- [ ] **Step 4: Run** `$T camp/apps/summaries/test_period_stats.py -v`; expect PASS.
- [ ] **Step 5: Commit** "fill_period_statistics command for existing coarse rows".

### Task 5: Guards: rebuild test and integrity check

**Files:**
- Modify: `camp/apps/summaries/test_period_consistency.py`
- Modify: `camp/apps/summaries/tasks.py` (`check_summary_integrity`)
- Test: `camp/apps/summaries/tests.py` (`SummaryIntegrityCheckTests`)

**Interfaces:**
- Consumes: `COARSE_RESOLUTIONS`, `peak_entry_models()`.
- Produces: `check_summary_integrity` result gains `'missing_period_statistics': int`.

- [ ] **Step 1: Failing tests.**
  - `PeriodConsistencyTests::test_rebuild_fills_every_coarse_row`: seed PM2.5 entries (half-hourly, like `_seed_entries`) from 2026-06-25 to 2026-10-05 Pacific, `rebuild_summaries 2026-07-01 2026-10-01 --monitor=<pk>` and the region variant; assert monthly and quarterly rows exist for both kinds and every coarse row of a peak type has `daily_statistic_days is not None` and `daily_statistic_expected_days is not None`. Keep the seeding coarse (e.g. one entry per hour) so the test stays under ~20 s.
  - `SummaryIntegrityCheckTests::test_counts_missing_period_statistics`: a monthly pm25 `MonitorSummary` and `RegionSummary` with the fields null, inside the 400 days → result `missing_period_statistics == 2` and the error log names it; one with `days=0` and mean null is not counted; a monthly `temperature` row with nulls is not counted.
- [ ] **Step 2: Run; expect FAIL** for the integrity test (the rebuild test may already pass, which proves Task 3's hook; keep it).
- [ ] **Step 3: Implement**: in `check_summary_integrity` count, per table, rows with `resolution__in=COARSE_RESOLUTIONS`, peak entry types, `timestamp__gte=start`, `daily_statistic_days__isnull=True`; add to `result`, include it in the `logger.error` condition and message (`'%d coarse row(s) missing the period daily statistic'`), and time it with the other scans.
- [ ] **Step 4: Run** `$T camp/apps/summaries/tests.py::SummaryIntegrityCheckTests camp/apps/summaries/test_period_consistency.py camp/apps/summaries/test_selection.py -v`; expect PASS.
- [ ] **Step 5: Commit** "Guards: rebuilds fill every coarse row; the integrity check counts misses".

### Task 6: Open-period rows

**Files:**
- Create: `camp/apps/summaries/open_periods.py`
- Modify: `camp/apps/summaries/open_days.py` (`build_open_rows` gains `with_tdigest: bool = False`)
- Test: `camp/apps/summaries/test_open_periods.py`

**Interfaces:**
- Consumes: `build_open_rows`, `open_days`, `rollup_summaries`, `rollup_region_stats`, `period_figure`, `expected_days`, `peak_entry_models`, `is_settled`.
- Produces:
  - `open_periods(resolution: str, now: datetime) -> list[datetime]`: `[previous_start, current_start]` while the previous period is not settled (plain margins), else `[current_start]`.
  - `build_open_period_rows(kind, owner_ids, entry_model, resolution, now, processor_q=None) -> dict[owner_id, list[MonitorSummary | RegionSummary]]`
  - `cached_open_period_rows(...)` same signature; cache key `f'open_periods:v1:{kind}:{resolution}:{entry_type}:{sha256(series|owners|periods)}'`, 60 s (`OPEN_ROWS_CACHE_SECONDS`), the `cached_open_rows` str(pk) pattern.

- [ ] **Step 1: Failing tests** (`now` passed explicitly, `cache.clear()` in `setUp`):
  - `OpenPeriodsWindowTests`: `open_periods('month', pacific(2026,12,1,0,30)) == [pacific(2026,11,1), pacific(2026,12,1)]`; at `pacific(2026,12,1,4,0)` → `[pacific(2026,12,1)]`; `open_periods('year', pacific(2027,1,1,0,30))` → `[pacific(2026,1,1), pacific(2027,1,1)]`; `'quarter'` and `'season'` at Dec 1 00:30 → season `[Sep 1, Dec 1]`, quarter `[Oct 1]` only (Q4 hasn't ended).
  - `BuildOpenPeriodRowsTests` (O3, monitor and region):
    - `test_current_month`: stored DAILY rows Nov 1–16 2026 with `max_1h` and hourly rows for Nov 17 (today, `now = pacific(2026,11,17,12)`): one monthly row, `timestamp == Nov 1`, `daily_statistic_expected_days == 17`, `days == 17` (today's so-far figure counts), mean over the 16 stored + today's so-far `max_1h`; `count`/`mean` equal `rollup_summaries` over the 16 daily rows plus today's hourly rows; `max_1h`, `max_8h`, `mean_24h` are `None`; `is_final` serializes `False`.
    - `test_yesterday_unstored`: at `pacific(2026,11,17,1,0)` with no stored Nov 16 daily row, Nov 16's strict figure is used.
    - `test_previous_month_while_open`: at `pacific(2026,12,1,0,30)` with no stored November monthly row → two rows (Nov with expected 30, Dec with expected 1); with a stored November monthly row → only Dec.
    - `test_quarter_uses_stored_months`: Q4 open on Nov 17 with a stored October monthly row and November daily rows: stats equal `rollup_summaries([oct_monthly, *nov_dailies, *today_hourlies])`, and the figure averages Oct's and Nov's daily figures (expected 48).
    - `test_threshold`: 10 of 17 days with figures → mean `None`, days 10, expected 17.
    - `test_non_peak_type`: temperature rows get the stats and all three fields `None`.
    - `test_no_rows`: an owner with nothing in the period is absent.
    - `test_cached`: a second call inside 60 s runs no queries (`CaptureQueriesContext`).
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** Stats inputs for period P per series: stored MONTHLY rows inside P (only when `resolution != 'month'`), plus stored DAILY rows in P not covered by one of those months, plus `build_open_rows(..., with_tdigest=True)` rows for open days in P with no stored DAILY row; roll up with `rollup_summaries` / `rollup_region_stats` (`with_tdigest=False` on the result). Figures: the stored DAILY rows' figure column in P plus the open-day rows' figure; `expected = expected_days(P.start, min(period_end(P), period_end('day', today)))`. `station_count` max of the inputs; peaks `None`. Batch the stored reads: one MONTHLY and one DAILY `values()` query for all owners and both open periods. `build_open_rows`'s default keeps `with_tdigest=False` so the daily open endpoints are unchanged.
- [ ] **Step 4: Run** `$T camp/apps/summaries/test_open_periods.py camp/apps/summaries/test_open_days.py -v`; expect PASS.
- [ ] **Step 5: Commit** "Open-period rows for the unfinished month, quarter, season and year".

### Task 7: Open-period endpoints

**Files:**
- Modify: `camp/api/v2/summaries/endpoints.py`, `monitor_urls.py`, `region_urls.py`, `bulk_urls.py`, `region_bulk_urls.py`, `filters.py` (if a filter class is needed for the schema)
- Test: `camp/api/v2/summaries/tests.py` (`OpenPeriodsEndpointTests`), `camp/api/v2/tests/test_openapi.py`

**Interfaces:**
- Consumes: `cached_open_period_rows`, `open_periods` (Task 6).
- Produces: classes `MonitorOpenPeriods`, `RegionOpenPeriods`, `BulkMonitorOpenPeriods`, `BulkRegionOpenPeriods`; URL names `{monitor,region}-summary-{monthly,quarterly,seasonal,yearly}-open` and `{monitor,region}-summary-bulk-{monthly,...}-open`; paths `<entry_type>/{monthly,quarterly,seasonal,yearly}/open/` (per owner) and `{monthly,...}/open/` (bulk), each placed **before** the matching `<int:year>/` route.

- [ ] **Step 1: Failing tests** (pattern of `OpenDaysEndpointTests`, `timezone.now` patched to a fixed Pacific instant):
  - `/api/2.0/monitors/<pk>/summaries/o3/monthly/open/` → 200, `data` is one row with `resolution == 'month'`, the three fields, `is_final False`; `Cache-Control` contains `private` and `max-age=60`; a repeat with `If-None-Match` is 304; `?processor=` picks the series; unknown entry type and unknown monitor 404 with `no-cache`.
  - region single, bulk monitor (`region`, `bbox`, `processor` scoping, 100 per page, owners without daily rows in the open periods or hourly rows since the first open day are not listed), bulk region (`region` or `type` required; neither → 400).
  - All four resolutions resolve to the right class (`resolve(...)`); `daily/open/` still resolves to the existing classes and its output in the existing tests is unchanged.
  - `test_openapi.py`: the bulk `monthly/open/` paths are documented with `{'region', 'type'}` (regions) and `{'region', 'bbox', 'processor'}` (monitors) parameters.
- [ ] **Step 2: Run; expect FAIL** (404s).
- [ ] **Step 3: Implement.** Subclass the four open-day views; move only what differs behind two hook methods on the existing classes, `open_rows(kind, ids, processor_q=None)` (default `cached_open_rows`) and `open_since()` (default `open_days(self.now)[0]`, the hourly EXISTS start), so the daily views behave byte-for-byte as before. The open-period subclasses return `cached_open_period_rows(..., self.resolution, ...)` and widen the owner EXISTS to "a DAILY row of the series with `timestamp >= open_periods(self.resolution, self.now)[0]` OR an HOURLY row since `open_days(self.now)[0]`". Docstrings say what the rows are (they become the OpenAPI descriptions).
- [ ] **Step 4: Run** `$T camp/api/v2/summaries/tests.py camp/api/v2/tests/test_openapi.py -v`; expect PASS.
- [ ] **Step 5: Commit** "Open-period summary endpoints".

### Task 8: Docs, timing, full suite

**Files:**
- Modify: `CLAUDE.md` (Metadata Endpoints)

- [ ] **Step 1: CLAUDE.md.** Add a "**Period daily statistic**" bullet after "Open days": the three fields and rule, `period_statistic`/`period_statistic_label` (and add both to the "Scale shape" key list), the hook in the two rollup functions, the CO refresh and 28 h margin for coarse CO rows, the open-period endpoints and rows (inputs, at most 2 per series, 60 s cache, `is_final false`), the integrity count, and the deploy order: migrate `0008` (10 s lock timeout, away from :40–:50, no backfill job), then after the daily-peaks deploy steps (including the AirNow -999 region rebuild) a scoped `fill_period_statistics`, `--dry-run` first, per monitor type and region type listed there. Also update the "Daily peaks" bullet's sentence that the peak margin applies to day only, if it says so.
- [ ] **Step 2: Timing.** With the coordinator's OK only (it touches the dev DB read-only): in a throwaway container mounting the worktree with the dev `.env` (`podman run --rm --network sjvaircom_sjvair-net --env-file ../../.env -v $PWD:/app:z -w /app sjvair-com-test:latest python manage.py shell -c ...`), time `build_open_period_rows` for 100 PurpleAir monitors and 100 counties/ZIPs, `month` and `year`, O3 and PM2.5. Record the numbers for the PR. Never write.
- [ ] **Step 3: Full suite** `$T -n 4 --dist loadscope 2>&1 | tee /tmp/claude-1000/-home-alex-workspace-sjvair-sjvair-com/e68a74bd-6af7-4dae-8428-e2a1077382d9/scratchpad/period-stat-suite.log | tail -5`; expect all pass (keep the log; don't filter evidence away).
- [ ] **Step 4: Commit** "Docs: period daily statistic".
