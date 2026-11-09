# Alert Current Value Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the stored result of the 10-minute alert run per monitor at
`GET /api/2.0/monitors/<id>/alerts/current/`, and publish each evaluated pair's alert config in
`monitors/meta/`.

**Architecture:** `AlertEvaluator` gains a full per-entry-type result. Its existing
`get_level`, `get_levels` and `evaluate` derive their levels from that result, so callers are
unchanged. `periodic_alerts` writes each monitor's results to the cache through a small new
module, `camp/apps/alerts/current.py`. A new resticus endpoint reads that one cache key and
never evaluates. `MonitorMetaEndpoint.get_monitors` adds an `alerts` block built from
`ENTRY_CONFIG['alerts']` and the evaluator's constants.

**Tech Stack:** Django, django-resticus, pandas `Timedelta`, the Django cache (LocMem in tests,
Memcached in production).

**Spec:** `docs/superpowers/specs/2026-11-08-alert-current-design.md`

## Global Constraints

- No migration, no new model.
- SMS behaviour, alert records and `get_alert_monitors()` are unchanged. `get_level`,
  `get_levels()` and `evaluate()` keep returning `Level` or `None` (a level only when status is
  `ok`). The existing alert tests and scenario tests must pass unchanged.
- Statuses: `ok`, `insufficient`, `no_data`, plus `pending` on the endpoint only.
- Cache timeout: 30 minutes. 200s: `public, max-age=60`. Errors: `no-cache`.
- Hidden monitors are served. Unknown and malformed ids 404 through `MonitorAccessMiddleware`.
- The meta `alerts` block is `{window: "60 min", min_coverage: 0.5, stage, processor, expected_interval}`, or `null`.
- Tests use `django.test.TestCase`, fixtures, and pytest-style `assert`.
- No Claude or AI attribution in commits.
- Test command (from the worktree root; `$DBURL` is `.env.test`'s `DATABASE_URL` with the
  database renamed to `sjvair_alert_current`. Never print it):
  ```bash
  DBURL=$(grep ^DATABASE_URL .env.test | cut -d= -f2- | sed 's#/sjvair$#/sjvair_alert_current#')
  podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 \
    -e TWILIO_AUTH_TOKEN=test-token -e DATABASE_URL="$DBURL" -v "$PWD":/app:z -w /app \
    sjvair-com-test:latest pytest <paths> -q
  ```
  The full suite adds `-n 4 --dist loadscope`.

## Review Focus

1. **A cache error while writing must not stop texts.** If `cache.set` raises, the monitor's
   `notify_subscribers` still runs. Task 2 tests this.
2. **A result stored before a monitor went inactive still serves until it expires**, at most 30
   minutes, then `no_data`. The cache-miss branch must check activity fresh, not through
   `request.monitor.is_active`, which can be stale on the middleware's cached monitor. Task 3
   tests an inactive monitor whose `is_active` attribute was cached as `True`.
3. **A monitor type with no alertable entry types** (VOZbox, CIMIS) answers `{"data": {}}`,
   never a 500. Task 3 tests this.
4. **`previous` on the first run after a gap** reads an older window that may be empty. It
   comes back as `no_data` or `insufficient` with null value and level, never an error. Task 1
   tests this.
5. **Timestamps in the response carry a UTC offset**, and the level is the scale key
   (`unhealthy_sensitive`), not the label. Task 3 asserts both.

---

### Task 1: Evaluator results

**Files:**
- Modify: `camp/apps/alerts/evaluator.py`
- Test: `camp/apps/alerts/tests.py` (new class `AlertResultTests`; reuse the setup style of
  `AlertEvaluatorTests` and `HourlyAndMultiPollutantTests`)

**Interfaces:**
- Produces:
  - `AlertResult`, a dataclass in `evaluator.py` with these fields, all `None` unless stated:
    - `status: str` (`'ok' | 'insufficient' | 'no_data'`)
    - `value: float | None`
    - `level: Level | None`
    - `window_start: datetime`
    - `window_end: datetime`
    - `latest_timestamp: datetime | None`
    - `readings: int`
    - `required: int`
    - `previous: AlertResult | None` (always `None` on a previous result)
  - `AlertEvaluator.get_result(entry_model, lookup, interval=None, now=None) -> AlertResult`,
    including `previous`
  - `AlertEvaluator.get_results(now=None) -> dict[entry_model, AlertResult]`
  - `AlertEvaluator.evaluate(results=None) -> dict[entry_model, Level | None]`. It uses
    `results` when given, else calls `get_results()`.
  - `get_level(entry_model, lookup, interval=None)` returns `get_result(...).level` without
    computing `previous`.
  - `get_levels()` returns `{m: r.level for m, r in get_results().items()}`.

- [ ] **Step 1: Write the failing tests** in `AlertResultTests`
  - **`test_average_ok`:** with PurpleAir and 30 readings of 40 over the trailing hour,
    `get_results()[PM25]` gives `status == 'ok'`, `value == 40`,
    `level == AQLevel.scale.UNHEALTHY_SENSITIVE`, `readings == 30`, `required == 15`, and
    `latest_timestamp` equal to the newest reading's timestamp. Also
    `window_end - window_start == timedelta(minutes=60)`.
  - **`test_average_insufficient`:** with 5 readings: `status == 'insufficient'`, `value is None`,
    `level is None`, `readings == 5`, and `latest_timestamp` set.
  - **`test_average_no_data`:** with no readings: `status == 'no_data'`, `readings == 0`,
    `latest_timestamp is None`.
  - **`test_previous_is_hour_before_window`:**
    - 30 readings of 40 in the last hour, and 30 readings of 10 between 60 and 120 minutes ago
    - `previous.status == 'ok'`, `previous.value == 10`, `previous.level == AQLevel.scale.GOOD`
    - `previous.window_end == window_start`
    - `previous.previous is None`
  - **`test_previous_empty_after_gap`:** with only the last hour filled, `previous.status ==
    'no_data'` and `previous.value is None`.
  - **`test_latest_reading_ok`:** for the AirNow setup with an O3 reading of 125 from 50 minutes
    ago:
    - `status == 'ok'`, `value == 125`, `readings == 1`, `required == 1`
    - `window_end - window_start == timedelta(hours=2)`
  - **`test_latest_reading_insufficient_when_stale`:** with the same reading 5 hours old,
    `status == 'insufficient'`, `value is None`, `readings == 0`.
  - **`test_one_now_per_monitor`:** with the AirNow setup, the PM25 and O3 results share
    `window_end`.
  - **`test_evaluate_accepts_results`:** `evaluate(results)` returns
    `{m: r.level for m, r in results.items()}` and creates the same Alert as `evaluate()`.

- [ ] **Step 2: Run them to verify they fail**

  Run: `pytest camp/apps/alerts/tests.py::AlertResultTests -q`
  Expected: FAIL (`AlertResult` / `get_results` not defined)

- [ ] **Step 3: Implement**
  - `now` defaults to `timezone.now()`, once per `get_results` call.
  - **Averaged feeds:** one `aggregate(avg=Avg('value'), count=Count('value'), latest=Max('timestamp'))`
    over `[now - WINDOW, now]`. Status `no_data` when the count is 0, `insufficient` when it's
    under `required`, else `ok`.
  - **Latest-reading feeds** (interval ≥ `WINDOW`): the window is `[now - 2×interval, now]`,
    `required` is 1, and `readings` is 0 or 1. Status `ok` when a reading is found, else
    `insufficient`.
  - `previous` calls the same private helper with `now - WINDOW`.
  - Keep `get_average_level` / `get_current_level` only if something else uses them (grep).
    Otherwise fold them into the helper.

- [ ] **Step 4: Run the new tests plus all existing alert tests**

  Run: `pytest camp/apps/alerts -q`
  Expected: all pass, including `test_scenarios.py`

- [ ] **Step 5: Commit**: `git commit -m "Alerts: full evaluator result with previous hour"`

### Task 2: Store results from the 10-minute run

**Files:**
- Create: `camp/apps/alerts/current.py`
- Modify: `camp/apps/alerts/tasks.py` (`periodic_alerts`)
- Test: `camp/apps/alerts/tests.py` (new class `StoredResultTests`)

**Interfaces:**
- Consumes: `AlertEvaluator.get_results`, `evaluate(results)`, `AlertResult` (Task 1).
- Produces, in `current.py`:
  - `CACHE_TIMEOUT = 30 * 60`
  - `cache_key(monitor_id) -> str`, which returns `f'alerts:current:{monitor_id}'`
  - `serialize(results: dict, evaluated_at: datetime) -> dict[str, dict]`. It is keyed by
    `entry_model.entry_type`. Each value is:
    ```python
    {
        'status': ..., 'value': ..., 'level': level.key or None,
        'window': {'start': dt, 'end': dt},
        'latest_timestamp': dt or None, 'readings': int, 'required': int,
        'previous': {'status', 'value', 'level'},
        'evaluated_at': dt,
    }
    ```
    Datetimes stay `datetime` objects, so resticus serializes them like the other endpoints.
  - `store(monitor, results, evaluated_at) -> None`. It calls `cache.set` and catches and logs
    any exception (`logger.exception`).
  - `load(monitor_id) -> dict | None`, which wraps `cache.get`.

- [ ] **Step 1: Write the failing tests** in `StoredResultTests`
  - **`test_periodic_alerts_stores_results`:**
    - `mark_active` plus 30 readings of 40, as in `PeriodicAlertsTests`
    - after `periodic_alerts.call_local()`, `current.load(self.monitor.pk)['pm25']` has
      `status == 'ok'` and `level == 'unhealthy_sensitive'`
    - its `evaluated_at` is a `datetime`
  - **`test_serialize_shape`:** the keys equal exactly `{'status', 'value', 'level', 'window',
    'latest_timestamp', 'readings', 'required', 'previous', 'evaluated_at'}`, and `previous` has
    exactly `{'status', 'value', 'level'}`.
  - **`test_cache_error_does_not_block_notifications`:**
    - patch `camp.apps.alerts.current.cache.set` to raise, and patch
      `camp.apps.alerts.tasks.notifications.notify_subscribers`
    - with a subscribed, active monitor, `periodic_alerts.call_local()` still calls
      `notify_subscribers` once
  - **`test_stored_with_timeout`:** patch `cache.set` and assert it was called with
    `timeout=current.CACHE_TIMEOUT` (1800).

- [ ] **Step 2: Run them to verify they fail**

  Run: `pytest camp/apps/alerts/tests.py::StoredResultTests -q`
  Expected: FAIL (`camp.apps.alerts.current` missing)

- [ ] **Step 3: Implement**
  - Create `current.py`.
  - In `periodic_alerts`:
    ```python
    evaluator = AlertEvaluator(monitor)
    results = evaluator.get_results()
    levels = evaluator.evaluate(results)
    current.store(monitor, results, now)
    ```
    `now` is the `window_end` of any result, or `timezone.now()` when the monitor has none.
    Then notify as before. `daily_reminders` is unchanged.

- [ ] **Step 4: Run alert tests**

  Run: `pytest camp/apps/alerts -q`
  Expected: all pass

- [ ] **Step 5: Commit**: `git commit -m "Alerts: store each run's results in the cache"`

### Task 3: `alerts/current/` endpoint

**Files:**
- Modify: `camp/api/v2/alerts/endpoints.py` (new `CurrentAlertValues(generics.Endpoint)`, documented, with a docstring)
- Modify: `camp/api/v2/alerts/urls.py` (`path('current/', ..., name='current')`)
- Test: `camp/api/v2/alerts/tests.py` (new class `CurrentAlertValuesTests`); `camp/api/v2/tests/test_openapi.py`

**Interfaces:**
- Consumes: `current.load`, `current.serialize` (Task 2); `AlertEvaluator` results (Task 1);
  `Monitor.alertable_entry_types`; `request.monitor`.
- Produces: the URL name `api:v2:monitors:alerts:current` (kwarg `monitor_id`).

- [ ] **Step 1: Write the failing tests.** Call the view with `RequestFactory`, setting
  `request.monitor` as `test_monitor_detail` does. Use `fixtures = ['purple-air.yaml']`.
  - **`test_serves_stored_result`:**
    - store results for PurpleAir 8892 via `current.store`, from 30 readings of 40
    - 200; `data['pm25']['status'] == 'ok'`, `data['pm25']['level'] == 'unhealthy_sensitive'`
    - `data['pm25']['window']['end']` ends with an offset (`-08:00` or `-07:00`, or matches
      `[+-]\d\d:\d\d$`)
    - `response['Cache-Control'] == 'public, max-age=60'`
  - **`test_miss_active_is_pending`:**
    - `mark_active` (copy the helper from `PeriodicAlertsTests`), with no stored result
    - `data == {'pm25': {status: 'pending', every other field None}}`
  - **`test_miss_inactive_is_no_data`:**
    - no `LatestEntry` rows, and `monitor.__dict__['is_active'] = True` set to simulate the
      middleware's stale cached monitor
    - `data['pm25']['status'] == 'no_data'`
  - **`test_type_without_alerts_is_empty`:**
    - a VOZbox monitor (create it minimally, or use a fixture if one exists)
    - 200, `data == {}`
  - **`test_hidden_monitor_is_served`:** with `is_hidden=True` and a stored result, 200 with
    the stored status.
  - **`test_unknown_id_404s`:** through the test client (so the middleware runs),
    `GET /api/2.0/monitors/doesnotexist/alerts/current/` gives a 404.
  - **`test_current_alerts_is_documented`** (in `test_openapi.py`): a path ending
    `{monitor_id}/alerts/current/`.

- [ ] **Step 2: Run them to verify they fail**

  Run: `pytest camp/api/v2/alerts/tests.py::CurrentAlertValuesTests camp/api/v2/tests/test_openapi.py -q`
  Expected: FAIL (no route)

- [ ] **Step 3: Implement `CurrentAlertValues.get`**
  - Load the stored dict.
  - On a miss, decide activity with
    `type(monitor).objects.filter(pk=monitor.pk).get_active().exists()`, the same rule as
    `get_alert_monitors`.
  - Build one placeholder per `alertable_entry_types` key.
  - Return `{'data': stored or placeholders}`.
  - Restrict a hit's keys to the type's alertable entry types, so a config change never serves
    a removed pair.
  - Wrap errors in `no-cache`, as `places.py` does.

- [ ] **Step 4: Run the tests**

  Run: `pytest camp/api/v2/alerts camp/api/v2/tests/test_openapi.py -q`
  Expected: all pass

- [ ] **Step 5: Commit**: `git commit -m "API: monitors/<id>/alerts/current/"`

### Task 4: `alerts` block in `monitors/meta/`

**Files:**
- Modify: `camp/api/v2/monitors/endpoints.py` (`MonitorMetaEndpoint.get_monitors`, new `get_alerts(monitor_model, entry_model)`)
- Test: `camp/api/v2/monitors/tests/test_meta_labels.py` (new class `MonitorMetaAlertsTests`, same `_fetch` pattern)

**Interfaces:**
- Consumes: `Monitor.alertable_entry_types`, `AlertEvaluator.WINDOW`, `MIN_COVERAGE` and
  `split_config`.
- Produces: `monitors.<type>.entries.<entry_type>.alerts`.

- [ ] **Step 1: Write the failing tests.** Fetch the meta, and use only types present in
  `MONITOR_ENABLED_TYPES`. Skip a type with `pytest.skip` if it isn't enabled.
  - **`test_purpleair_pm25_alerts`:** equals
    `{'window': '60 min', 'min_coverage': 0.5, 'stage': 'calibrated', 'processor': 'PM25_UnivariateLinearRegression', 'expected_interval': None}`.
  - **`test_aqlite_o3_override`:** `stage == 'calibrated'`, `processor is None`,
    `expected_interval == '1h'`.
  - **`test_airnow_o3_no_processor`:** `stage == 'raw'`, `processor is None`.
  - **`test_non_alertable_is_null`:** PurpleAir `pm10` `alerts is None`.
  - **`test_every_entry_has_alerts_key`:** every entry of every monitor type has the `alerts`
    key.

- [ ] **Step 2: Run them to verify they fail**

  Run: `pytest camp/api/v2/monitors/tests/test_meta_labels.py -q`
  Expected: FAIL (`KeyError: 'alerts'`)

- [ ] **Step 3: Implement `get_alerts`**
  - `window` is built from `AlertEvaluator.WINDOW` as `f'{int(minutes)} min'`.
  - `processor` is `config['processor'].name` when present.

- [ ] **Step 4: Run all monitor API tests**

  Run: `pytest camp/api/v2/monitors -q`
  Expected: all pass. Update any snapshot or fixture of the meta response that now lacks
  `alerts`.

- [ ] **Step 5: Commit**: `git commit -m "Meta: alerts block per monitor entry type"`

### Task 5: Docs and full suite

**Files:**
- Modify: `CLAUDE.md` (Metadata Endpoints: one bullet)

- [ ] **Step 1: Add one bullet to `CLAUDE.md`** under Metadata Endpoints. It covers:
  - `monitors/<id>/alerts/current/` serves the stored result of the 10-minute `periodic_alerts`
    run (`camp/apps/alerts/current.py`) and never evaluates on request
  - the statuses and the `pending`/`no_data` miss rule
  - the 30-minute expiry, and `pending` for up to 10 minutes after a cache restart
  - hidden monitors are served
  - `monitors/meta/`'s `alerts` block, `null` when the pair isn't evaluated

- [ ] **Step 2: Run the full suite**

  Run: the test command with `-n 4 --dist loadscope`, teeing to a log.
  Expected: 0 failures. Compare against the baseline on `develop` before calling any failure
  new.

- [ ] **Step 3: Commit**: `git commit -m "CLAUDE.md: alerts/current/ and meta alerts block"`
