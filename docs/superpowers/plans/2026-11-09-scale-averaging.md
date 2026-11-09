# Scale Averaging and Daily Peaks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish each scale's averaging period in its metadata, and store EPA-style daily peak
figures (`max_1h`, `max_8h`) on daily monitor and region summaries. Also fix AQLite's hourly
`is_complete`.

**Architecture:** `LevelSet` declares `averaging_hours`, and `Scale.to_json()` carries it plus
the derived `daily_statistic`. A new module `camp/apps/summaries/peaks.py` holds pure peak math
and one writer, `fill_daily_peaks(...)`, which updates only the peak columns of existing daily
rows from stored hourly rows. Three things call that writer: the daily rollup (for the rolled
window), the daily tasks (refreshing the previous day's `max_8h`), and a new `fill_daily_peaks`
management command. AQLite's hourly-aggregate series gets `expected_count = 1`, and completeness
comes from its CLEANED readings.

**Tech Stack:** Django, PostGIS/Postgres, Huey, django-resticus.

**Spec:** `docs/superpowers/specs/2026-11-09-scale-averaging-design.md`

## Global Constraints

- Averaging hours: PM25 and PM100 `24`; O3, NO2 and SO2 `1`; CO `8`; AQI and every category
  scale `None`. `daily_statistic`: 24 → `'mean'`, 1 → `'max_1h'`, 8 → `'max_8h'`, None → `None`.
- Standard = `Levels.UNHEALTHY_SENSITIVE.value` (O3 125, NO2 101, SO2 76, CO 9.5).
- 75% rule: `math.ceil(0.75 * n)`, where n is the day's hour count (23/24/25) for `max_1h`, or
  its window count (same n) for `max_8h`. An 8-hour window needs >= 6 of its 8 hours.
- A monitor hour has data when its hourly row exists and `is_complete`. A region hour has data
  when its hourly row exists. The input value is the hourly row's `mean`.
- Peaks only on DAILY rows. Every other row and every other entry type keeps both fields `null`.
- AQLite: an hourly-output series has `expected_count = 1`. It's complete when that hour's
  CLEANED readings are at least `0.8 * monitor.expected_hourly_entries`.
- Period math only through `camp/apps/summaries/periods.py` (`period_end`, `iter_hours`,
  `iter_period_starts`). Never a `timedelta` of a day or more for a Pacific date.
- Tests use `django.test.TestCase` with pytest-style `assert`.
- No Claude or AI attribution in commits, docs or PRs.
- No migration, `migrate`, rebuild or backfill on the shared local stack without the
  coordinator's approval. Tests use their own DB (below), which is fine.
- Test command, run from the worktree root. First copy the main checkout's `.env.test` into the
  worktree if it's missing. Never print `$DBURL`:
  ```bash
  DBURL=$(grep ^DATABASE_URL .env.test | cut -d= -f2- | sed 's#/sjvair$#/sjvair_scale_avg#')
  podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 \
    -e TWILIO_AUTH_TOKEN=test-token -e DATABASE_URL="$DBURL" -v "$PWD":/app:z -w /app \
    sjvair-com-test:latest pytest <paths> -q
  ```
  Full suite: replace `<paths> -q` with `-n 4 --dist loadscope`.

## Deviations from the spec (plan-level calls)

- The rollup doesn't fold peak math into its existing loop. After its upsert, it calls
  `fill_daily_peaks` for the same window. That gives one code path for rollup, refresh and
  backfill, and the spec leaves the function shape to the builder.
- The 8-hour settle margin is **28 h**, not 27 h. On fall-back day the following day has 25
  hours, so the refresh lands 26 h 10 min after the day ends, plus 1 h of slack.

## Review Focus

1. **A day whose next day has no hourly rows yet** (today's rollup). `max_8h` must use only valid
   windows and must not raise. Pinned in Task 3 (`test_max_8h_missing_next_day`).
2. **Monitors with several processors for one gas type** (AQLite RAW `''` and CALIBRATED
   `AQLiteHourlyAggregator`). Each daily row's peak comes from its own processor's hourly rows,
   never mixed. Pinned in Task 4 (`test_peaks_per_processor`).
3. **DST days (23 and 25 hours).** The thresholds are 18 and 19, and the windows step in UTC.
   Pinned in Task 3 (`test_max_1h_dst_days`).
4. **A daily row re-rolled after its peaks were filled** (late arrival, `repair_summaries`). The
   re-roll's upsert must not wipe the peaks with `null`, and the fill rewrites them. Pinned in
   Task 4 (`test_reroll_keeps_and_refreshes_peaks`).
5. **A negative or zero hourly mean** (raw O3 can be slightly negative). It's a valid data point
   and is never treated as missing (no truthiness checks on values). Pinned in Task 3
   (`test_zero_and_negative_count_as_data`).

---

### Task 1: Averaging period on scales

**Files:**
- Modify: `camp/apps/entries/levels.py` (`LevelSet.__init__`, new `daily_statistic`, `to_scale`, the declarations at the bottom)
- Modify: `camp/utils/scales.py` (`Scale`, `to_json`)
- Test: `camp/apps/entries/tests/test_scales.py`, and the `monitors/meta/` tests in `camp/api/v2/monitors/` (find the existing meta test class with `grep -rn "meta" camp/api/v2/monitors/tests*`)

**Interfaces:**
- Produces: `LevelSet(*levels, averaging_hours: int | None = None, **named_levels)`;
  `LevelSet.averaging_hours: int | None`; `LevelSet.daily_statistic: str | None`;
  `Scale.averaging_hours`, `Scale.daily_statistic` (both default `None`, always in `to_json()`).

- [ ] **Step 1: Write failing tests** in `ScaleTests`:

```python
def test_averaging_hours_declared(self):
    assert levels.PM25.averaging_hours == 24 and levels.PM100.averaging_hours == 24
    assert levels.O3.averaging_hours == 1 and levels.NO2.averaging_hours == 1
    assert levels.SO2.averaging_hours == 1 and levels.CO.averaging_hours == 8
    assert levels.AQI.averaging_hours is None

def test_daily_statistic(self):
    assert levels.PM25.daily_statistic == 'mean'
    assert levels.O3.daily_statistic == 'max_1h'
    assert levels.CO.daily_statistic == 'max_8h'
    assert levels.AQI.daily_statistic is None

def test_averaging_hours_is_not_a_level(self):
    assert 'averaging_hours' not in [lvl.key for lvl in levels.O3]

def test_invalid_averaging_hours(self):
    with pytest.raises(ValueError):
        levels.LevelSet(levels.AQLevel.GOOD(0), averaging_hours=3)

def test_to_json_carries_averaging(self):
    data = levels.O3.to_scale('o3', 'Ozone', 'ppb').to_json()
    assert data['averaging_hours'] == 1 and data['daily_statistic'] == 'max_1h'
    aqi = levels.AQI.to_scale('aqi', 'AQI', 'AQI').to_json()
    assert aqi['averaging_hours'] is None and aqi['daily_statistic'] is None
```

  Update `test_to_json_keys` to include the two new keys. Add to the meta tests: `entries.o3.scale.averaging_hours == 1`, `entries.co.scale.daily_statistic == 'max_8h'`, `entries.pm25.scale.daily_statistic == 'mean'`. In the HMS meta test (`camp/api/v2/hms/tests.py` `get_scales`), add that a category scale has `averaging_hours is None`.

- [ ] **Step 2: Run them** (`camp/apps/entries/tests/test_scales.py` plus the meta test files). Expected: FAIL (`AttributeError` / `KeyError`).

- [ ] **Step 3: Implement.**
  - `averaging_hours` is a keyword-only parameter, popped before the `**kwargs` levels loop.
  - Validate it against `{None, 1, 8, 24}` and raise `ValueError` otherwise.
  - `daily_statistic` is a property built from a module-level mapping `DAILY_STATISTIC = {24: 'mean', 1: 'max_1h', 8: 'max_8h'}`.
  - `to_scale` passes both fields to `Scale`.
  - Declare the values from Global Constraints. Category scales built elsewhere (`camp/utils/scales.py` users) keep the dataclass defaults.

- [ ] **Step 4: Run the same tests, plus `camp/api/v2/hms camp/api/v2/forecasts camp/api/v2/calheatscore`** (to catch tests that compare exact scale dicts). Expected: PASS. Fix exact-dict assertions by adding the two keys.

- [ ] **Step 5: Commit** `Scales: averaging_hours and daily_statistic`.

### Task 2: AQLite hourly completeness

**Files:**
- Modify: `camp/apps/calibrations/core/processors/o3/aqlite.py` (`AQLiteHourlyAggregator`)
- Modify: `camp/apps/summaries/aggregators.py` (`compute_stats`, `compute_monitor_summary`, new helper)
- Modify: `camp/apps/summaries/backfill.py` (`backfill_monitor_hours`)
- Test: `camp/apps/summaries/tests.py` (new class `HourlyOutputCompletenessTests`; reuse the AQLite helpers in `camp/apps/monitors/aqlite/tests.py`, `make_monitor` and `make_cleaned`, by importing them or copying their few lines)

**Interfaces:**
- Produces: `AQLiteHourlyAggregator.output_interval = '1h'` and `.source_stage = O3.Stage.CLEANED`;
  `hourly_output_processor(processor: str) -> type | None` in `aggregators.py` (the registered
  processor class when it has `output_interval == '1h'`, else `None`; `''` → `None`);
  `compute_stats(values, expected_count, is_complete: bool | None = None)` (an explicit value
  overrides the 80% rule).

- [ ] **Step 1: Write failing tests:**
  - `test_aggregated_hour_expected_one`: an AQLite monitor with 10 CLEANED readings in an hour and one CALIBRATED `AQLiteHourlyAggregator` entry. `compute_monitor_summary(monitor, hour, O3, 'AQLiteHourlyAggregator')` gives `expected_count == 1`, `count == 1`, `is_complete is True`.
  - `test_aggregated_hour_incomplete_below_80pct`: the same with 9 CLEANED readings gives `is_complete is False`.
  - `test_raw_series_unchanged`: the RAW `''` series of the same monitor keeps `expected_count == 12`.
  - `test_backfill_matches_hourly`: `backfill_monitor_hours(monitor, hour, hour + 1h, [O3])` writes the CALIBRATED row with the same `expected_count` and `is_complete` as above (10 → True, and a second hour with 9 → False).
  - `test_daily_rollup_complete`: 24 complete aggregated hours roll into a daily row with `expected_count == 24` and `is_complete is True`.

- [ ] **Step 2: Run** `camp/apps/summaries/tests.py::HourlyOutputCompletenessTests`. Expected: FAIL (`expected_count == 12`).

- [ ] **Step 3: Implement.**
  - Look processors up through `camp.apps.calibrations.processors`: `name in processors`, then `processors[name]`.
  - In `compute_monitor_summary`, when the series is hourly-output, count `EntryModel` rows with `stage=cls.source_stage` in the hour and pass `expected_count=1, is_complete=count >= 0.8 * monitor.expected_hourly_entries`.
  - In `backfill_monitor_hours`, run one extra grouped count query per entry model that has hourly-output processors in the chunk (CLEANED readings per hour), not one per hour.

- [ ] **Step 4: Run** the new class, plus `camp/apps/summaries camp/apps/monitors/aqlite`. Expected: PASS.

- [ ] **Step 5: Commit** `Summaries: AQLite hourly-aggregate completeness`.

### Task 3: Peak math (pure functions)

**Files:**
- Create: `camp/apps/summaries/peaks.py`
- Test: `camp/apps/summaries/test_peaks.py` (create)

**Interfaces:**
- Produces, in `peaks.py`:
  - `max_1h(day_hours: list[datetime], hourly: dict[datetime, float], standard: float) -> float | None`
  - `max_8h(day_hours: list[datetime], hourly: dict[datetime, float], standard: float) -> float | None`.
    `hourly` holds only hours that have data and may include the next day's hours. Windows are
    `[h + timedelta(hours=k) for k in range(8)]` for each `h` in `day_hours` (UTC steps).
  - `day_hours(day_start: datetime) -> list[datetime]`: `list(iter_hours(day_start, period_end('day', day_start)))`.
  - `peak_entry_models() -> dict[type, str]`: entry model → `'max_1h'` or `'max_8h'`, for every
    `BaseEntry.get_subclasses()` whose `Levels` has `daily_statistic` in those two.
  - `standard_for(entry_model) -> float`: `float(entry_model.Levels.UNHEALTHY_SENSITIVE.value)`.

- [ ] **Step 1: Write failing tests** (`PeakMathTests(TestCase)`; build day hours with `day_hours(make_aware(datetime(2026, 7, 1)))` etc.):
  - `test_max_1h_full_day`: 24 values, peak 130 → `130.0`.
  - `test_max_1h_threshold`: 18 hours with data (peak 50) → `50.0`; 17 hours → `None`.
  - `test_max_1h_short_day_over_standard`: 5 hours with peak 125, standard 125 → `125.0`; peak 124.9 → `None`.
  - `test_max_1h_dst_days`: 2026-03-08 has 23 hours (18 → value, 17 → None); 2026-11-01 has 25 hours (19 → value, 18 → None).
  - `test_zero_and_negative_count_as_data`: 18 hours of `-0.5`/`0.0` → `0.0`.
  - `test_max_8h_window_validity`: a window with 6 of 8 hours counts and averages only those 6; with 5 it's ignored.
  - `test_max_8h_threshold`: 18 of 24 valid windows → value; 17 → `None` unless max >= standard.
  - `test_max_8h_uses_next_day`: a peak placed in the next day's 00:00–06:00 hours raises day D's `max_8h` (window starting 23:00).
  - `test_max_8h_missing_next_day`: a full day D with no next-day hours → the windows from 19:00–23:00 drop out (fewer than 6 hours), there are 19 valid windows, so a value with no error.
  - `test_peak_entry_models`: `{O3: 'max_1h', NO2: 'max_1h', SO2: 'max_1h', CO: 'max_8h'}`, with PM25 absent.

- [ ] **Step 2: Run** `camp/apps/summaries/test_peaks.py`. Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** the five functions. Use `math.ceil(0.75 * len(day_hours))` for both thresholds. No rounding of values.

- [ ] **Step 4: Run.** Expected: PASS.

- [ ] **Step 5: Commit** `Summaries: daily peak math`.

### Task 4: Peak columns, writer, rollup and API

**Files:**
- Modify: `camp/apps/summaries/models.py` (`BaseSummary`: `max_1h`, `max_8h`, `FloatField(_('highest 1-hour average'), null=True, blank=True)` and `_('highest 8-hour average')`)
- Create: `camp/apps/summaries/migrations/0007_summary_peaks.py` (`makemigrations summaries -n summary_peaks`)
- Modify: `camp/apps/summaries/peaks.py` (add the writer)
- Modify: `camp/apps/summaries/tasks.py` (`rollup_monitor_summaries`, `rollup_region_summaries`)
- Modify: `camp/api/v2/summaries/serializers.py` (both row serializers)
- Test: `camp/apps/summaries/test_peaks.py`, `camp/api/v2/summaries/tests.py`

**Interfaces:**
- Consumes: Task 3's functions.
- Produces: `fill_daily_peaks(kind: str, ids: list | None, start: datetime, end: datetime, *, entry_models: list | None = None, fields: tuple[str, ...] = ('max_1h', 'max_8h'), dry_run: bool = False, batch_size: int = 1000, progress=None) -> dict[str, int]`.
  - `kind` is `'monitor'` or `'region'`; `ids=None` means all.
  - It covers DAILY rows with `start <= timestamp < end` for the peak entry types (or the given subset).
  - It returns rows updated (or that would be updated) per entry type.
  - `progress(message: str)` is called once per batch when given.

- [ ] **Step 1: Write failing tests** (`FillDailyPeaksTests(TestCase)`, using the existing summary test helpers/fixtures in `camp/apps/summaries/tests.py` to make a monitor, hourly rows and a region):
  - `test_fills_monitor_o3`: 24 complete hourly O3 rows (peak 130) plus a DAILY row → after `fill_daily_peaks('monitor', [m.pk], day, next_day)`, `max_1h == 130` and `max_8h is None`.
  - `test_incomplete_hours_ignored`: 7 hourly rows with `is_complete=False` holding a higher mean don't raise `max_1h`.
  - `test_region_rows`: region hourly O3 rows → the region daily row gets `max_1h`.
  - `test_co_gets_max_8h_only`: CO → `max_8h` set and `max_1h is None`.
  - `test_pm25_untouched`: the PM25 daily row keeps both `None`.
  - `test_peaks_per_processor`: one monitor with O3 `''` (peak 200) and `AQLiteHourlyAggregator` (peak 90) hourly rows → each daily row gets its own peak.
  - `test_fields_subset`: `fields=('max_8h',)` leaves an existing `max_1h` value alone.
  - `test_dry_run_writes_nothing`: returns `{'o3': 1}` and the row stays `None`.
  - `test_rollup_fills_peaks`: `rollup_monitor_summaries(DAILY, HOURLY, day, next_day)` sets `max_1h`; `rollup_monitor_summaries(MONTHLY, DAILY, ...)` leaves the monthly row's `max_1h` `None`. The same for `rollup_region_summaries`.
  - `test_reroll_keeps_and_refreshes_peaks`: fill, change one hourly mean to 150, re-run the daily rollup → `max_1h == 150`. Without the change, re-running keeps the value (the upsert's `update_fields` doesn't list the peaks).
  - API (`camp/api/v2/summaries/tests.py`): the monitor daily, region daily and bulk monitor/region responses include `max_1h` and `max_8h`, and an hourly row has both `None`.

- [ ] **Step 2: Run** `camp/apps/summaries/test_peaks.py camp/api/v2/summaries/tests.py`. Expected: FAIL.

- [ ] **Step 3: Implement.**
  - Add the fields and generate the migration, then confirm with `python manage.py sqlmigrate summaries 0007` (inside the test container) that each statement is `ADD COLUMN "max_1h" double precision NULL` with no `DEFAULT`. Paste that output into the commit message body.
  - The writer reads the hourly rows for `[start, period_end('day', last day) + 7 h)` once per id (monitor or region) for the needed entry types, not per row. It groups by `(entry_type, processor)` for monitors and by `entry_type` for regions, and updates with `bulk_update(rows, fields, batch_size=batch_size)`, one transaction per batch.
  - Both rollups call it after their upsert only when `target_resolution == DAILY`, with `ids=monitor_ids` / `region_ids`.
  - Add `'max_1h', 'max_8h'` to both row serializers.

- [ ] **Step 4: Run** `camp/apps/summaries camp/api/v2/summaries`. Expected: PASS.

- [ ] **Step 5: Commit** `Summaries: max_1h and max_8h on daily rows`.

### Task 5: Next-night 8-hour refresh and settle margin

**Files:**
- Modify: `camp/apps/summaries/tasks.py` (`daily_monitor_summaries`, `daily_region_summaries`)
- Modify: `camp/apps/summaries/schedule.py` (`is_settled` and new constants)
- Modify: `camp/api/v2/summaries/endpoints.py` (the `dispatch` settle check)
- Test: `camp/apps/summaries/tests.py` (the schedule test class with `test_margin_covers_registered_crontabs`), `camp/api/v2/summaries/tests.py`

**Interfaces:**
- Consumes: `fill_daily_peaks`, `peak_entry_models`.
- Produces:
  - `PEAK_8H_REFRESH_DELAY = timedelta(days=1)`: the refresh runs in the next day's rollup.
  - `PEAK_8H_SETTLE_MARGIN = timedelta(hours=28)`, applying to `day` only.
  - `is_settled(resolution, range_end, now=None, late=False, peak_8h=False)`: with `peak_8h` and `resolution == 'day'`, the margin is `max(PEAK_8H_SETTLE_MARGIN, the late/normal margin)`.

- [ ] **Step 1: Write failing tests:**
  - `test_daily_task_refreshes_previous_max_8h`: CO hourly rows for day D−1 and D, with D−1's rolled before D's morning hours existed (provisional). Calling `daily_monitor_summaries(day=D)` raises D−1's `max_8h` to the final value. The same for `daily_region_summaries`.
  - `test_peak_8h_margin`: for a day ending at `pacific(2026, 11, 2)`, `is_settled('day', end, now=pacific(2026, 11, 3, 3), peak_8h=True)` is False. At `pacific(2026, 11, 3, 4)` it's True, and `peak_8h=True` doesn't change `month`.
  - `test_peak_8h_margin_covers_refresh_crontab`: for day ends `pacific(2026, 1, 2)`, `pacific(2026, 7, 2)` and `pacific(2026, 11, 1)` (the day after it has 25 hours), `daily_region_summaries` fires within the 48 h after the end. Its second run + 1 h is ≤ end + `PEAK_8H_SETTLE_MARGIN`. Use the existing `effective_runs` helper.
  - The endpoint: a CO daily range that's settled under the normal margin but not the 28 h one is sent `max-age=60`. PM25 for the same range is `86400`.

- [ ] **Step 2: Run.** Expected: FAIL.

- [ ] **Step 3: Implement.**
  - Each daily task, after its rollup, calls `fill_daily_peaks(kind, None, prev_start, start, entry_models=[models with 'max_8h'], fields=('max_8h',))`. Here `start` is the rolled day and `prev_start = _previous_period_start('day', start)`.
  - The endpoint passes `peak_8h=self.entry_model.Levels is not None and self.entry_model.Levels.averaging_hours == 8`.
  - Leave `ROLLUP_LOCAL_TIME` and `SETTLE_MARGIN` keys unchanged, so `test_margin_covers_schedule` stays as is.

- [ ] **Step 4: Run** `camp/apps/summaries camp/api/v2/summaries`. Expected: PASS.

- [ ] **Step 5: Commit** `Summaries: next-night max_8h refresh and its settle margin`.

### Task 6: `fill_daily_peaks` command and docs

**Files:**
- Create: `camp/apps/summaries/management/commands/fill_daily_peaks.py`
- Modify: `CLAUDE.md` (new bullets under "Metadata Endpoints", next to the summary cache rule)
- Test: `camp/apps/summaries/test_peaks.py` (`FillDailyPeaksCommandTests`)

**Interfaces:**
- Consumes: `fill_daily_peaks`, `peak_entry_models`.
- Produces: `manage.py fill_daily_peaks <start> <end> [--monitor PK]... [--monitor-type TYPE]... [--region PK]... [--region-type TYPE]... [--entry-type TYPE]... [--batch-size N] [--dry-run]`.
  - Dates are Pacific and `end` is exclusive.
  - Scope parsing reuses `repair_summaries`' `_monitor_ids` / `_region_ids` and `_parse_date`. Move them to a small shared mixin in `camp/apps/summaries/management/commands/_scope.py` and use it from both commands.

- [ ] **Step 1: Write failing tests:**
  - `test_requires_scope`: no scope flags → `CommandError`.
  - `test_start_before_end`: `start >= end` → `CommandError`.
  - `test_rejects_non_peak_entry_type`: `--entry-type pm25` → `CommandError`, with a message naming the eligible types.
  - `test_dry_run_counts`: prints a per-type count (e.g. `o3: 2 rows`) and writes nothing.
  - `test_fills_and_is_idempotent`: a run sets the values. A second run gives the same values, and the other columns (`mean`, `maximum`, `is_complete`, `tdigest`) are unchanged.
  - `test_monitor_type_scope`: `--monitor-type airnow` fills AirNow rows and not another type's.
  - The existing `repair_summaries` command tests still pass after the mixin move.

- [ ] **Step 2: Run.** Expected: FAIL.

- [ ] **Step 3: Implement.**
  - Call `fill_daily_peaks` once for monitors and once for regions with the resolved ids.
  - Convert the dates with `make_aware` at Pacific midnight, as `repair_summaries` does.
  - Write a progress line per batch.

- [ ] **Step 4: Update CLAUDE.md.**
  - The scale shape line gains `averaging_hours` and `daily_statistic`.
  - A new **Daily peaks** bullet covers:
    - which types get `max_1h` / `max_8h`;
    - the EPA rules from Global Constraints;
    - CO's windows that start in the day;
    - the next-night refresh and the 28 h margin;
    - AQLite's hourly-output completeness;
    - `fill_daily_peaks` usage, with the scoped example:
      `fill_daily_peaks 2026-01-01 2026-11-10 --monitor-type airnow --dry-run`.

- [ ] **Step 5: Run the full suite** (`-n 4 --dist loadscope`). Expected: all pass, with the same skips as `develop`.

- [ ] **Step 6: Commit** `Summaries: fill_daily_peaks command; CLAUDE.md`.

### After the tasks (not implementation)

- Send the coordinator the branch, the migration name (`summaries.0007_summary_peaks`) and the
  exact scoped local commands, and wait for approval before running any of them:
  - `migrate summaries`;
  - `rebuild_summaries ... --monitor <id> --monitors-only` per AQLite monitor;
  - `fill_daily_peaks ... --monitor-type airnow` / `vozbox` / per region type, `--dry-run` first.
- Push and open the PR into `develop` only with the user's go-ahead. Merging needs the user's
  own yes.
