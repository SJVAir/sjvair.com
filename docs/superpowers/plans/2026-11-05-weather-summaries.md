# Weather Summaries for CIMIS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CIMIS stations get monitor summaries (hour through year) for 11 weather types, built from correctly stamped readings, summarized when the readings arrive.

**Architecture:** First fix how CIMIS readings are stamped (start of hour, fixed PST) and re-stamp stored history with a scoped command. Then add a per-monitor-type summaries switch in `ENTRY_CONFIG`, with one selection module that every summaries call site uses. CIMIS readings are summarized by the ingest itself (changed hours each import, all of yesterday at finalize), not by the :45 hourly parent; settled-cache margins are widened for those types. Monitor summary rows gain `sum`.

**Tech Stack:** Django 5 / PostGIS, Huey (`django_huey`), pytest with `django.test.TestCase`; sdk-js (Deno, Zod).

**Spec:** `docs/superpowers/specs/2026-11-05-weather-summaries-design.md`

## Global Constraints

- Branch `feature/weather-summaries` from `feature/get-data-layers` (which holds the specs), worktree `sjvair.com/.worktrees/weather-summaries`. Copy `.env`, `.env.test`, `docker-compose.override.yml` in. PR into `develop`; merge only with the user's yes.
- Tests (`TEST`): `podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token -e DATABASE_URL=<.env.test URL with db name sjvair_weather> -v $PWD:/app:z -v ~/workspace/django-resticus/.worktrees/session-csrf/resticus:/usr/local/lib/python3.14/site-packages/resticus:ro,z -w /app sjvair-com-test:latest pytest <args>`. Take a full-suite baseline (`-n 4 --dist loadscope`) before Task 1 and compare at the end. Ignore the trailing "not a git repository" line.
- Summarized CIMIS types (11): `temperature, humidity, dewpoint, soiltemperature, windspeed, precipitation, solarradiation, netradiation, vaporpressure, eto, etr`. `winddirection` stays raw.
- Air quality unchanged: no model's `summarize` flag changes; region summaries, region rollups and the :45 / :50 hourly parents keep exactly today's entry types.
- No region rows for weather types, ever.
- `is_complete` and `rollup_summaries` unchanged. Weather coverage (`weather_span`, `monitor_span`) unchanged. `BulkMonitorSummaryList` unchanged (air quality only).
- Nothing touches production. Writes to the shared local database (re-stamp, rebuild, measurements that write) only after the coordinator (`data-dashboard-b7`) says yes, each step.
- Every management command run is scoped (`--monitor`, dates) with `--dry-run` counts first.
- No Claude or AI attribution in commits, PRs or docs.

## Review Focus

1. **Fall-back day (2026-11-01)**: CIMIS sends 24 labels; they must map to 24 distinct UTC hours. Test in Task 1.
2. **A PurpleAir's (or any air sensor's) temperature or humidity is never summarized**, by the ingest path, rebuild, backfill job or hourly parent. Tests in Tasks 3 and 5.
3. **Re-running the re-stamp is a no-op**, including the first hour of the range in a PST month (whose new stamp lies just before the delete window). Test in Task 2.
4. **A reading that arrives after its day (or month) was rolled up** updates the daily (and monthly) row. Test in Task 5.
5. **Weather-only hours don't trip `check_summary_integrity`** ("monitor hourly rows but no region rows"). Test in Task 3.

---

## Evidence: CIMIS hours are Pacific Standard Time all year

Settled from local data (read-only, 2026-11-05). Fresno State (CIMIS #80) hourly solar radiation, stored under today's parsing (label read as `America/Los_Angeles`, end of hour). The sun's position doesn't move in UTC across a clock change, but the stored peak did:

| Day | Peak stored hour (UTC) | Neighbours |
|---|---|---|
| 2026-10-26 (PDT) | 19:00 (1394) | 18:00 1318, 20:00 1345 |
| 2026-10-27 (PDT) | 19:00 (1414) | 18:00 1329, 20:00 1355 |
| 2026-11-03 (PST) | 20:00 (1328) | 19:00 1264, 21:00 1229 |
| 2026-11-05 (PST) | 20:00 (1353) | 19:00 1245, 21:00 1265 |

The stored peak moved one hour later in UTC on the 2026-11-01 change, so CIMIS labels don't follow daylight saving. Reading them as Pacific wall clock put summer readings an hour early. Solar noon at Fresno is about 19:43 UTC in early November, so the peak hour runs 19:00–20:00 UTC. Its hour-ending label stamped in fixed PST is 20:00 UTC, which matches the PST days. So **a label `(date, HHMM)` means the hour ending at HH:MM PST (UTC−8)**, and the start-of-hour stamp is `date + HH h − 1 h` at UTC−8. Task 1 Step 1 re-runs this check before changing code.

## Task 1: Stamp CIMIS readings at the start of the hour, fixed PST

**Files:**
- Modify: `camp/apps/monitors/cimis/models.py` (`CIMIS.parse_timestamp`)
- Test: `camp/apps/monitors/cimis/tests.py` (`CimisParseTimestampTests`)

**Interfaces:**
- Produces: `CIMIS.parse_timestamp(record: dict) -> datetime` (aware, tz `CIMIS_TZ`), and module constant `CIMIS_TZ = datetime.timezone(timedelta(hours=-8), 'PST')`. Also `CIMIS.legacy_timestamp(record: dict) -> datetime`: today's parsing (end of hour, `settings.DEFAULT_TIMEZONE` via `replace(tzinfo=...)`), kept only for Task 2's delete window.

- [ ] **Step 1: Re-check the evidence (read-only)**

Run: `podman exec sjvaircom_web_1 python manage.py shell -c "<print Fresno State SolarRadiation by UTC hour, 14–23, for 2026-10-26..27 and 2026-11-03..05>"`
Expected: peaks at 19:00 UTC before 11-01 and 20:00 UTC after. If not, stop and report to the user.

- [ ] **Step 2: Replace the two existing tests and add new ones (failing)**

```python
from datetime import datetime, timezone as dt_timezone

def utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)

def test_summer_label_is_the_start_of_the_hour_in_pst(self):
    # 0100 = 00:00-01:00 PST
    assert self.monitor.parse_timestamp({'Date': '2026-07-01', 'Hour': '0100'}) == utc(2026, 7, 1, 8)

def test_winter_label_is_the_start_of_the_hour_in_pst(self):
    assert self.monitor.parse_timestamp({'Date': '2026-01-15', 'Hour': '1300'}) == utc(2026, 1, 15, 20)

def test_2400_is_the_last_hour_of_the_same_date(self):
    assert self.monitor.parse_timestamp({'Date': '2026-07-01', 'Hour': '2400'}) == utc(2026, 7, 2, 7)

def test_fall_back_day_has_24_distinct_hours(self):
    stamps = {self.monitor.parse_timestamp({'Date': '2026-11-01', 'Hour': f'{h:02d}00'}) for h in range(1, 25)}
    assert len(stamps) == 24
    assert min(stamps) == utc(2026, 11, 1, 8) and max(stamps) == utc(2026, 11, 2, 7)

def test_spring_forward_day_has_24_distinct_hours(self):
    stamps = {self.monitor.parse_timestamp({'Date': '2026-03-08', 'Hour': f'{h:02d}00'}) for h in range(1, 25)}
    assert len(stamps) == 24

def test_legacy_timestamp_matches_the_old_parsing(self):
    # end of hour, Pacific wall clock
    assert self.monitor.legacy_timestamp({'Date': '2026-07-01', 'Hour': '1300'}) == utc(2026, 7, 1, 20)
    assert self.monitor.legacy_timestamp({'Date': '2026-01-15', 'Hour': '2400'}) == utc(2026, 1, 16, 8)
```

Also update `CimisHandlePayloadTests` / `ProcessCimisDataTests` / `FinalizeCimisDataTests` assertions that pin a stored timestamp to the new stamps.

- [ ] **Step 3: Run, verify the new tests fail** — `TEST camp/apps/monitors/cimis/tests.py -v`; expected: the new timestamp tests FAIL.

- [ ] **Step 4: Implement** `parse_timestamp`: `datetime(date, tzinfo=CIMIS_TZ) + timedelta(hours=int(HH)) - timedelta(hours=1)` (HH from `Hour.zfill(4)[:2]`; `2400` gives 23:00 the same date with no special case). Move the old body to `legacy_timestamp`. Update the class docstring: labels are hour-ending, fixed PST.

- [ ] **Step 5: Run** `TEST camp/apps/monitors/cimis/tests.py -v`; expected: PASS.

- [ ] **Step 6: Commit** — `git commit -m "fix(cimis): stamp readings at the start of the hour in fixed PST"`

## Task 2: `restamp_cimis` command (re-pull stored history with new stamps)

**Files:**
- Create: `camp/apps/monitors/cimis/management/commands/restamp_cimis.py`
- Create: `camp/apps/monitors/cimis/restamp.py` (the logic; the command only parses options and prints)
- Test: `camp/apps/monitors/cimis/test_restamp.py`

**Interfaces:**
- Consumes: `CIMIS.parse_timestamp`, `CIMIS.legacy_timestamp` (Task 1); `CIMISAPI.get_hourly_data`; `Monitor.create_entry`, `Monitor.update_latest_entry`.
- Produces: `restamp_station(monitor: CIMIS, end: date, dry_run: bool, api: CIMISAPI | None = None) -> RestampResult` where `RestampResult` is a dataclass `(monitor_id: str, start: date | None, end: date, labels: int, deleted: int, written: int)`.

The command: `restamp_cimis --monitor <id> [--monitor <id> ...] [--end YYYY-MM-DD] [--dry-run]`. `--monitor` is required; `--end` defaults to today (Pacific). The start is always the station's first stored date (the Pacific date of its earliest CIMIS entry in any of the 12 tables). There is no `--start`: a later start in a PST month would overwrite the previous day's 2400 reading at the seam.

Algorithm per station (all in `restamp_station`):
1. `start` = first stored date; nothing stored → `labels=deleted=written=0`.
2. Fetch every date in `[start, end]` from the API, one call per date for this station, before touching the database. Any API error aborts this station with no writes.
3. Delete window, in UTC: `[legacy_timestamp((start, '0100')), legacy_timestamp((end, '2400'))]`, inclusive. Every entry of this station in the 12 CIMIS tables inside it (any stage) goes. Dry run: count only.
4. In one `transaction.atomic()` per station: delete, then write every fetched record through `handle_payload` (new stamps, same QC rules), then delete this station's CIMIS `LatestEntry` rows and rebuild them from each type's newest RAW entry with `update_latest_entry`.
5. Print per station: first stored date, labels fetched, rows in the window per type, rows written.

- [ ] **Step 1: Write the failing tests** (mock `CIMISAPI.get_hourly_data` to return fixed records; build stored rows with `legacy_timestamp` to mimic old data)

```python
def test_dry_run_counts_and_writes_nothing(self): ...
    # 2 dates stored old-style; result.deleted == stored rows, written == 0 rows changed in DB
def test_restamps_a_pdt_day_and_a_pst_day(self): ...
    # after: temperature rows at parse_timestamp() stamps only; none left at legacy stamps that differ
def test_running_twice_is_a_no_op(self): ...
    # second run: same row set (timestamps, values) as after the first, for a PST month range
def test_first_hour_of_a_pst_range_is_kept(self): ...
    # start in January: row for (start, '0100') exists once, at utc(start, 8)
def test_latest_entry_points_at_an_existing_entry_with_the_new_newest_timestamp(self): ...
def test_api_error_leaves_the_station_untouched(self): ...
def test_other_stations_and_other_monitor_types_are_untouched(self): ...
def test_command_requires_monitor(self): ...  # CommandError without --monitor
```

- [ ] **Step 2: Run** `TEST camp/apps/monitors/cimis/test_restamp.py -v`; expected: FAIL (module missing).
- [ ] **Step 3: Implement** `restamp.py` and the command as above.
- [ ] **Step 4: Run** the same; expected: PASS. Then `TEST camp/apps/monitors/cimis/ -v`: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(cimis): restamp_cimis re-pulls a station's stored history with start-of-hour stamps"`

## Task 3: The summaries switch and the summary-type selection

**Files:**
- Create: `camp/apps/summaries/selection.py`
- Modify: `camp/apps/monitors/cimis/models.py` (`ENTRY_CONFIG`: `'summarize': True` on the 11 types)
- Modify: `camp/apps/summaries/tasks.py` (remove `get_summarizable_entry_models`; hourly parents, region parents, backfill job, `check_summary_integrity`)
- Modify: `camp/apps/summaries/management/commands/rebuild_summaries.py`
- Modify: `camp/apps/summaries/backfill.py` (only if `backfill_monitor_hours`'s caller changes need it)
- Test: `camp/apps/summaries/test_selection.py`; update `GetSummarizableEntryModelsTests` in `camp/apps/summaries/tests.py`

**Interfaces:**
- Produces (in `camp/apps/summaries/selection.py`):
  - `is_summarized(monitor_model: type[Monitor] | Monitor, entry_model: type[BaseEntry]) -> bool`: `entry_model.summarize` or `monitor_model.ENTRY_CONFIG.get(entry_model, {}).get('summarize', False)`.
  - `monitor_summary_entry_models(monitor_model) -> list[type[BaseEntry]]`: every entry model (from `get_all_entry_models()`) that `is_summarized` for that monitor type, sorted by `entry_type`.
  - `region_summary_entry_models() -> list[type[BaseEntry]]`: models with `summarize = True` (today's `get_summarizable_entry_models()`).
  - `switch_entry_types() -> frozenset[str]`: entry types turned on by some monitor type's `ENTRY_CONFIG` and not by the model flag (today: the 11 CIMIS types).
  - `monitor_types_summarizing(entry_model) -> list[type[Monitor]]`: monitor subclasses for which `is_summarized` is true.

Call-site rules:
- `hourly_monitor_summaries` and `hourly_region_summaries`: `region_summary_entry_models()`. The :45 parent keeps skipping switch types; CIMIS is summarized by the ingest (Task 5).
- Region rollup tasks, `backfill_region_chunk`, `rebuild_summaries` region work: `region_summary_entry_models()`.
- `_backfill_dispatch_monitors`: `monitors_with_data_in(..., region_summary_entry_models() + sorted switch models)`. `backfill_monitor_chunk`: `monitor_summary_entry_models(monitor)`.
- `rebuild_summaries` monitor work: per monitor, `monitor_summary_entry_models(monitor)` (sync path); async path: for each entry model, only `monitor_ids` whose type is in `monitor_types_summarizing(model)`.
- `check_summary_integrity`'s hour check counts only `MonitorSummary` rows with `entry_type__in` the region types.

- [ ] **Step 1: Write the failing tests** (`test_selection.py`)

```python
def test_cimis_summarizes_eleven_types(self):
    assert {m.entry_type for m in monitor_summary_entry_models(CIMIS)} == {
        'temperature', 'humidity', 'dewpoint', 'soiltemperature', 'windspeed', 'precipitation',
        'solarradiation', 'netradiation', 'vaporpressure', 'eto', 'etr'}
def test_purpleair_temperature_is_not_summarized(self):
    assert not is_summarized(PurpleAir, Temperature) and is_summarized(PurpleAir, PM25)
def test_region_types_are_the_model_flag_types(self):
    assert {m.__name__ for m in region_summary_entry_models()} == {'PM25', 'O3', 'CO', 'NO2', 'SO2'}
def test_switch_types_are_the_cimis_types(self):
    assert switch_entry_types() == frozenset({...the 11...})
def test_rebuild_for_a_cimis_station_writes_weather_rows_and_no_region_rows(self): ...
    # call_command('rebuild_summaries', start, end, monitor=cimis.pk, monitors_only=True)
def test_rebuild_for_a_purpleair_writes_no_temperature_rows(self): ...
def test_hourly_monitor_parent_skips_weather(self): ...
    # CIMIS Temperature entry in the hour -> no MonitorSummary row from hourly_monitor_summaries(hour)
def test_backfill_job_summarizes_cimis_weather_types(self): ...
def test_integrity_check_ignores_weather_only_hours(self): ...
    # a CIMIS hourly temperature MonitorSummary in yesterday, no region rows -> missing_region_hours == 0
```

Rename `GetSummarizableEntryModelsTests` to test `region_summary_entry_models()` (same assertions).

- [ ] **Step 2: Run** `TEST camp/apps/summaries/test_selection.py -v`; expected: FAIL.
- [ ] **Step 3: Implement** `selection.py`, the CIMIS config keys, and the call-site rules. `grep -rn "get_summarizable_entry_models" camp` must return nothing afterwards.
- [ ] **Step 4: Run** `TEST camp/apps/summaries/ -n 4 --dist loadscope`; expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(summaries): per-monitor-type summaries switch; CIMIS opts in 11 weather types"`

## Task 4: Catalog and coverage read the selection

**Files:**
- Modify: `camp/api/v2/meta/catalog.py` (`_monitor_entry_types`)
- Modify: `camp/api/v2/meta/coverage.py` (`require_summarized` → `region_summary_entry_models`; `is_summarized(monitor, model, processor)` → `selection.is_summarized(monitor, model)` for its flag check)
- Modify: `camp/api/v2/meta/tests/catalog_snapshot.json` (regenerated)
- Test: `camp/api/v2/meta/tests/test_catalog.py`

**Interfaces:**
- Consumes: `is_summarized`, `region_summary_entry_models` (Task 3).

A dataset's entry type lists `SUMMARIZED` when any monitor type in that dataset `is_summarized` it, else `RAW_ONLY`. Weather: the 11 types summarized, `winddirection` raw. Air quality: unchanged (temperature, humidity, pressure stay raw there).

- [ ] **Step 1: Failing tests**

```python
def test_weather_types_have_summary_resolutions(self):
    assert self.entry('weather', 'precipitation')['resolutions'] == ['raw', 'hour', 'day', 'month', 'quarter', 'season', 'year']
    # (use catalog.SUMMARIZED rather than a literal if the order differs)
def test_wind_direction_stays_raw(self):
    assert self.entry('weather', 'winddirection')['resolutions'] == ['raw']
def test_air_quality_temperature_stays_raw(self):
    assert self.entry('air-quality', 'temperature')['resolutions'] == ['raw']
```

- [ ] **Step 2: Run** `TEST camp/api/v2/meta/tests/ -v`; expected: the new tests FAIL.
- [ ] **Step 3: Implement**; regenerate the snapshot with `-e WRITE_CATALOG_SNAPSHOT=1 ... pytest camp/api/v2/meta/tests/test_catalog.py`, and check the snapshot diff touches only weather `resolutions`.
- [ ] **Step 4: Run** `TEST camp/api/v2/meta/ -v`; expected: PASS (coverage tests unchanged and passing).
- [ ] **Step 5: Commit** — `git commit -m "feat(meta): catalog lists summary resolutions for CIMIS weather types"`

## Task 5: Summarize CIMIS readings when they arrive

**Files:**
- Modify: `camp/apps/summaries/tasks.py` (new task + windows helper)
- Modify: `camp/apps/monitors/cimis/tasks.py` (`_ingest_cimis_data`, `import_cimis_data`, `finalize_cimis_data`)
- Test: `camp/apps/summaries/test_arrival.py`; extend `ImportCimisDataTests` / `FinalizeCimisDataTests`

**Interfaces:**
- Consumes: `monitor_summary_entry_models` (Task 3); `backfill_monitor_hours` (`backfill.py`); `reroll` (`repair.py`, imported inside the function: `repair` imports `tasks`).
- Produces:
  - `rollup_windows_for(hours: list[datetime], now: datetime) -> dict[str, list[datetime]]` in `tasks.py`: for each resolution in `repair.RESOLUTIONS`, the distinct `period_start(res, hour)` over `hours` whose period has ended (`period_end <= now`). Months, quarters, seasons and years are included only when finished. No widening (unlike `repair_range`).
  - `@db_task(priority=100, queue='summaries') summarize_monitor_hours(monitor_id: str, hours: list[datetime]) -> None`: `backfill_monitor_hours(monitor, min(hours), max(hours) + 1h, monitor_summary_entry_models(monitor))`, then `reroll('monitor', [monitor.pk], min, max + 1h, now, windows=rollup_windows_for(hours, now))`. Does nothing for a monitor type with no switch types. Hours span at most 2 days (callers guarantee it).
  - `_ingest_cimis_data(target_date) -> dict[str, set[datetime]]`: `{monitor_id: {hour starts}}` of entries that `handle_payload` created or changed (it returns them; unchanged values return nothing), counting only summarized entry types.
  - `import_cimis_data`: after ingest, `summarize_monitor_hours(monitor_id, sorted(hours))` per monitor with changes.
  - `finalize_cimis_data`: after ingest, `summarize_monitor_hours(monitor_id, every hour of yesterday)` for **every** CIMIS monitor, changed or not. This is the daily safety net that also re-rolls yesterday.

- [ ] **Step 1: Failing tests** (Huey runs immediately in tests; fix "now" with `timezone.override` / `mock.patch('django.utils.timezone.now')`)

```python
def test_import_summarizes_the_hours_it_wrote(self): ...
    # mock API -> 2 records for 13:00, 14:00 labels -> hourly MonitorSummary rows for those 2 hours,
    # temperature and precipitation, none for winddirection
def test_unchanged_reimport_enqueues_nothing(self): ...
def test_late_reading_updates_an_already_rolled_day(self): ...
    # day D rolled up (daily row count=23); a missing hour arrives via import_cimis_data -> daily row count=24
def test_late_reading_in_a_finished_month_rerolls_the_month(self): ...
def test_unfinished_month_is_not_rolled(self): ...
    # rollup_windows_for([hour in current month], now) has no 'month' key/empty list
def test_finalize_resummarizes_all_of_yesterday_for_every_station(self): ...
def test_daily_sum_is_the_total_of_the_hours(self): ...
    # precipitation 0.01 x 3 hours -> daily sum_value == 0.03 (pytest.approx)
def test_air_sensor_temperature_is_not_summarized_by_summarize_monitor_hours(self): ...
    # PurpleAir monitor id -> no rows
```

- [ ] **Step 2: Run** `TEST camp/apps/summaries/test_arrival.py camp/apps/monitors/cimis/tests.py -v`; expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** the same, then `TEST camp/apps/summaries/ camp/apps/monitors/ -n 4 --dist loadscope`; expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(summaries): summarize CIMIS readings on arrival and re-roll yesterday at finalize"`

## Task 6: Settle margins for late-arriving types

**Files:**
- Modify: `camp/apps/summaries/schedule.py`
- Modify: `camp/api/v2/summaries/endpoints.py` (`SummaryMixin.dispatch`)
- Test: `camp/apps/summaries/tests.py` (next to `test_margin_covers_registered_crontabs`)

**Interfaces:**
- Consumes: `switch_entry_types()` (Task 3); `finalize_cimis_data` (its crontab, 12:00 UTC).
- Produces: `LATE_SETTLE_MARGIN = {'hour': 30h, 'day': 7h, 'month': 7h, 'quarter': 7h, 'season': 7h, 'year': 7h}` and `is_settled(resolution, range_end, now=None, late=False)`; `late=True` uses `LATE_SETTLE_MARGIN`. The endpoint passes `late=self.entry_model.entry_type in switch_entry_types()`.

Why those values: a reading can change until the next day's finalize (12:00 UTC = 04:00 PST / 05:00 PDT) plus its re-roll. A day's last change lands about 5 h after it ends (PDT), and an hour's about 29 h (first hour of the day, PDT).

- [ ] **Step 1: Failing tests**

```python
def test_late_margin_covers_finalize(self):
    # for period ends in PST and PDT, for every resolution: the first finalize_cimis_data run after
    # the period end (effective_runs over 48h) + 1h slack <= end + LATE_SETTLE_MARGIN[res].
    # For 'hour', use the first hour of a day (the worst case).
def test_weather_summary_response_uses_the_late_margin(self): ...
    # GET a CIMIS station's daily temperature for yesterday at 03:30 Pacific -> max-age=60 (unsettled);
    # same request for pm25 on a PurpleAir -> max-age=86400 (settled at 03:00)
```

- [ ] **Step 2: Run**; expected: FAIL. **Step 3: Implement.** **Step 4: Run** `TEST camp/apps/summaries/tests.py camp/api/v2/summaries/tests.py -v`; expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(summaries): longer settle margins for summaries fed by late-arriving CIMIS data"`

## Task 7: `sum` on monitor summary rows

**Files:**
- Modify: `camp/api/v2/summaries/serializers.py` (`MonitorSummarySerializer.fields`: add `('sum', lambda s: s.sum_value)` after `count`)
- Test: `camp/api/v2/summaries/tests.py`

The bulk endpoint reuses `MonitorSummarySerializer`, so its rows gain `sum` too (additive). `RegionSummarySerializer` doesn't change.

- [ ] **Step 1: Failing test** — `test_monitor_summary_rows_include_sum`: a daily row with `sum_value=0.03` → `response['data'][0]['sum'] == pytest.approx(0.03)`; `test_region_summary_rows_have_no_sum`.
- [ ] **Step 2–4:** run (FAIL), implement, run `TEST camp/api/v2/summaries/tests.py -v` (PASS).
- [ ] **Step 5: Commit** — `git commit -m "feat(summaries): monitor summary rows return sum"`

## Task 8: Docs and full suite

**Files:**
- Modify: `CLAUDE.md`: a "CIMIS Weather Summaries" section (after "BAM 1022 Mirror"): the switch (`'summarize': True` in `ENTRY_CONFIG`, `camp/apps/summaries/selection.py`), on-arrival summarizing, the 11 types, no region rows, fixed-PST start-of-hour stamps, `restamp_cimis` usage and order (deploy → re-stamp per station → rebuild per station), `LATE_SETTLE_MARGIN`. One line under "Metadata Endpoints" → summaries: monitor rows carry `sum`.

- [ ] **Step 1:** write the docs. **Step 2:** full suite `TEST -n 4 --dist loadscope`; expected: same as the baseline plus the new tests, no new failures. **Step 3: Commit** — `git commit -m "docs: CIMIS weather summaries"`

## Task 9: Local data run and measurement (stop points)

No code. Each **STOP** means: message the coordinator with the exact command and the dry-run counts, and wait for a yes. Serving the branch locally: swap only the web container (Local recipes in the brief); never restart the shared Huey workers on branch code. The commands below run in a one-off branch container (`podman-compose -p sjvaircom run --rm web python manage.py ...` from the worktree), not in `sjvaircom_web_1`.

- [ ] **Step 1: Measure the cost.** In a one-off branch container, inside `transaction.atomic()` with `transaction.set_rollback(True)`: time `summarize_monitor_hours.call_local(<one station>, <24 hours of yesterday>)` (the finalize cost per station) and `.call_local(<station>, [<one hour>])` (the per-import cost), 5 runs each, and the existing `hourly_monitor_summaries` parent's enumeration for one hour (read-only queries; don't call children). Record: per-import ≈ stations × changed hours tasks; finalize ≈ 23 × the 24-hour time. Report in the PR whether batching is needed (threshold: finalize total > 5 min, or per-import > 60 s).
- [ ] **Step 2: Pick 3 stations.** Fresno State (#80), Shafter (#5) and Westlands (#105); record their monitor ids.
- [ ] **Step 3: `restamp_cimis --monitor <Fresno State> --dry-run`** → **STOP** (coordinator yes) → run without `--dry-run` → check row counts per type and `LatestEntry`.
- [ ] **Step 4:** same for the other 2 stations → **STOP** → run.
- [ ] **Step 5:** same for all 23 (`--monitor` repeated) → **STOP** → run.
- [ ] **Step 6: Rebuild one station:** `rebuild_summaries <first date> <today> --monitor <Fresno State> --monitors-only` → **STOP** → run → spot-check one day's precipitation `sum` against the hourly readings, and that no `RegionSummary` rows have a weather `entry_type`.
- [ ] **Step 7:** repeat Step 6 for the other 2, then all 23, each behind a **STOP**.
- [ ] **Step 8:** tell the coordinator the stack is back on the main checkout.

## Task 10: Handoff (coordinator, Get data session, DEFERRED.md)

- [ ] **Step 1: Production steps** → send to `data-dashboard-b7` for the deploy entry in data-dashboard `DEFERRED.md` ("Production deploy of sjvair.com develop → main"), in order, after the deploy:

```bash
# per station, smallest first; dry run, then real
heroku run -a <app> -- python manage.py restamp_cimis --monitor <id> --dry-run
heroku run -a <app> -- python manage.py restamp_cimis --monitor <id>
# after all 23 are re-stamped, per station:
heroku run -a <app> -- python manage.py rebuild_summaries <first CIMIS date> <today> --monitor <id> --monitors-only
```

  Note to include: don't start a re-stamp at :40–:50 past the hour (it overlaps `import_cimis_data` at :45).
- [ ] **Step 2: Tell `data-dashboard-13`** (coordinator copied): CIMIS timestamps move to start-of-hour fixed PST (summer readings stay where they were, winter readings move one hour earlier); weather monitor summaries exist for the 11 types; `sum` on monitor summary rows; weather summaries settle later (`max-age=60` until about 7 h after a day ends).
- [ ] **Step 3: DEFERRED.md** in the data-dashboard docs worktree (`git -C /home/alex/workspace/sjvair/data-dashboard worktree add .worktrees/docs-explorer-layers origin/main`, or reuse it). Re-read the file, then add two entries (skip any already there):
  - *Region-level weather summaries*: region weighting is built on air-sensor grades and health checks, so weather needs its own rule. Revisit when a place needs one blended weather value instead of a station's.
  - *Wind direction summaries (circular mean)*: averaging angles is wrong. Revisit when a chart needs prevailing wind.
  Add a "Release 1, step 3" bullet in `TODO.md` for this work. Run prettier (`../../node_modules/.bin/prettier --write <files>`), rebase on `origin/main`, commit (no attribution), push to `main`.
- [ ] **Step 4: PR** `feature/weather-summaries` → `develop`. Body: what changed, the visible timestamp change, the measurement from Task 9, the production steps. No attribution. Don't merge without the user's yes.

---

## SDK (sdk-js, `release/5.0.0`)

Branch `feature/weather-summaries` from `origin/release/5.0.0` in `sdk-js/.worktrees/weather-summaries`; PR into `release/5.0.0`. **No tag, beta or publish without the user's yes for that specific release.**

### Task S1: `sum` and the CIMIS entry types

**Files:**
- Modify: `lib/monitors/schemas/monitor_summary.ts`: `sum: z.ZodNumber` in the interface (doc: "The total of the values recorded during this summary's period"), `sum: z.number()` in the schema. Check that `monitor_summary_bulk.ts` reuses it; if it duplicates the fields, add it there too.
- Modify: `lib/monitors/schemas/monitor_entry_type.ts`: add `dewpoint, soiltemperature, windspeed, winddirection, precipitation, solarradiation, netradiation, vaporpressure, eto, etr`, unless item 2's SDK PR has already added them. Check `origin/release/5.0.0` first and skip this file if so.
- Modify: `CHANGELOG.md` (Unreleased).
- Test: `lib/monitors/mod_test.ts`

- [ ] **Step 1: Failing tests:** a CIMIS station's daily `precipitation` summaries parse, with `typeof row.sum === "number"`. The station id comes from `getMonitors({dataset: "weather"})` or the equivalent existing call; skip with a note when the local DB has none. `monitorEntryTypeSchema.parse("eto")` succeeds.
- [ ] **Step 2:** run `deno test --allow-net --allow-env --allow-read --env-file=.env lib/monitors/mod_test.ts` against the stack serving the branch; expected: FAIL.
- [ ] **Step 3: Implement.** **Step 4:** `deno fmt --check && deno lint && deno check mod.ts && deno test --allow-net --allow-env --allow-read --env-file=.env lib/monitors/` (not the account tests); expected: PASS.
- [ ] **Step 5: Commit**, PR into `release/5.0.0`, tell the coordinator. Ask the user about a beta only when the PR is ready.
