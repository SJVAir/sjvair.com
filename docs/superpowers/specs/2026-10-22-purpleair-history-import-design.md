# PurpleAir history import

Date: 2026-10-22. Branch: `feature/purpleair-history-import`, stacked on
`feature/legacy-entries-backfill` (PR #261).

## Goal

Re-import every PurpleAir sensor's full history from the PurpleAir API into
the `entries` app as RAW rows, so history comes from the source instead of the
legacy `Entry` table. The legacy backfill (PR #261) then fills only what the
API can't provide (sensors that are gone, periods it doesn't serve), because it
skips any legacy row with a RAW row within 60s.

Why the API beats the legacy table:

- PM2.5 before 2023-07-31: legacy rows only kept the calibrated `pm25`, so the
  backfill skips them. The API still serves the original `pm2.5_atm`.
- No crossed PM1.0/PM10 columns (migration 0020), no pressure-unit bug.

## Evidence (2026-10-22)

One `/v1/sensors/:index/history` request with `average=0` for 2019-06-01..28:

- Sensor 469 (dev key): 20,133 rows covering the full 28 days at 120s spacing
  (20,160 possible). All 21 fields 99.9–100% non-null.
- Sensor 17059 (production): 24,150 rows from 2019-06-06 at 80s spacing; the
  legacy table holds 24,154 rows per channel for the same window, so the API
  serves everything legacy has. 507,150 data points (rows x fields).

So one request covers one monitor for 28 days. Neither request hit a row or
span cap, but one may exist; the importer must detect a short response (below).

## Problems with the existing importer

`purpleair/tasks.py:import_monitor_history` + `purpleair/api.py:get_sensor_history`:

1. On `RateLimitExceededError` it recurses from the original `start_date`,
   re-fetching (and re-billing) every chunk already fetched.
2. Any other error prints and returns, silently dropping the rest of the range.
3. The only driver, `test_purpleair_historical_import`, is hardcoded to sensor
   8892 / 2024 and deletes that monitor's entries first.
4. One `exists()` query per entry (~11 per API row).
5. No job, no progress, no resume.

## Design

### API

- New `PurpleAirAPI.get_sensor_history_window(sensor_index, start, end, fields=None)`:
  exactly one request, returns the rows (dicts, sorted by `time_stamp`).
  Raises `PurpleAirRateLimited` on `RateLimitExceededError`,
  `PurpleAirNotFound` when the sensor doesn't exist / isn't accessible, and
  `PurpleAirAPIError` for anything else. No sleeping, no recursion.
- Fix `get_sensor_history`'s rate-limit branch to retry only the current
  chunk (with a bounded number of attempts), not restart the range.

### Job: `PurpleAirHistoryJob` (purpleair app)

Same shape and lifecycle as `EntryBackfillJob` (state, cursor, chunk_start,
range_start/range_end, pending_tasks, batch_id, phase_started_at,
last_progress_at, locked_at, consecutive_failures, last_error, sqid), with
`chunk_days` default 28 and counters `requests_made`, `rows_fetched`,
`raw_entries_created`, `data_points` (all `PositiveBigIntegerField`). Reuse the
existing tick/stall/fail helpers in `camp/apps/monitors/tasks.py`
(`_is_stalled`, `_fail_job`, the dispatch/complete/restart pattern) rather
than copying them; generalize a helper only where needed.

A per-(job, monitor, window) failure record is needed so a sensor that's gone
doesn't fail the whole job: `PurpleAirHistoryGap` (job FK, monitor FK,
window start/end, reason: `not_found` / `error` / `truncated`, message). These
are listed by `status` and can be retried with `import_purpleair_history retry`.

### Chunk task: `import_purpleair_history_chunk(job_id, monitor_id, start, end, batch_id)`

Secondary queue, fenced on `batch_id` like the backfill chunk tasks.

1. Fetch with `get_sensor_history_window`. On `PurpleAirRateLimited`, retry the
   same request with backoff (e.g. 5s, 15s, 45s), then record a gap.
   `PurpleAirNotFound` → `not_found` gap; other errors → `error` gap.
2. Short-response check: if rows came back and the last `time_stamp` is more
   than one hour before `end`, request again from last `time_stamp` + 1s, up to
   a small bound; if still short, record a `truncated` gap.
3. Build entries with `monitor.create_entries(payload, save=False)`; this path
   must not issue a query per entry (skip `validation_check` for this caller, or
   build entries without it).
4. Dedupe against existing RAW rows once per window: load existing
   `(sensor, timestamp)` per entry model for the window padded by
   `NEAR_DUPLICATE_WINDOW`, and skip near-duplicates using the same rule as the
   legacy backfill (reuse `NEAR_DUPLICATE_WINDOW` / `_has_near` from
   `legacy_backfill.py`). Existing rows are never overwritten.
5. Insert with the existing `_insert_raw_entries` helper (atomic bulk insert,
   per-row fallback).
6. Fenced update of counters and `last_progress_at`.

Does not run the pipeline: `reprocess_legacy_pipeline` already processes any
PurpleAir RAW rows without derived entries, oldest first.

### Which monitors per window

Only PurpleAir monitors with a `sensor_id`. Skip windows outside a monitor's
known lifetime when it is cheaply known (PurpleAir `date_created` if stored on
the monitor, and the monitor's latest entry / last_seen); otherwise request and
let an empty response cost nothing beyond the call.

### Command: `import_purpleair_history`

`start | status | cancel | retry`, with `--from` (required for start), `--to`
(default 24 hours ago, like `reprocess_legacy_pipeline`), `--monitor-id`
(repeatable), `--chunk-days` (default 28), `--force`, and `--dry-run` on start:
prints monitors, windows, request count and an estimated data-point count
(windows x expected rows at 120s x 21 fields), and creates nothing.

Remove `test_purpleair_historical_import` (it deletes data and is hardcoded).
`import_monitor_history` / `process_monitor_history` stay unless nothing else
uses them; if unused, remove them too.

## Run order (after #261 and this ship)

1. `import_purpleair_history start --from 2017-12-01 --dry-run`, then for real.
2. `backfill_legacy_entries start --from 2017-12-01` (fills only the gaps).
3. `fix_purpleair_pm_columns` (repairs older wrong RAW rows).
4. `reprocess_legacy_pipeline start --from 2017-12-01`.
5. `verify_legacy_backfill --from 2017-12-01`.

## Tests

API mocked throughout. Cover: one request per window; rate-limit retry hits
only that window and never restarts; not-found and error gaps don't fail the
job; short response triggers a follow-up request and a `truncated` gap when
still short; near-duplicate dedupe and no overwrite; no per-entry queries
(`assertNumQueries` bound); fenced batch updates; stall/resume; command
start/status/cancel/retry/dry-run; the `get_sensor_history` rate-limit fix.

## As built

CLI (final):

```
import_purpleair_history start --from YYYY-MM-DD [--to YYYY-MM-DD] [--monitor-id ID ...] [--chunk-days 28] [--force] [--dry-run]
import_purpleair_history status   # progress, counters, and the gap list
import_purpleair_history cancel
import_purpleair_history retry    # re-runs the latest job's gaps (untracked tasks; a window that fails again is re-recorded)
```

- Run order above is unchanged.
- Monitors per window: PurpleAir with a `sensor_id` whose newest `LatestEntry` is not older than the window (monitors with no `LatestEntry` are always included). No `date_created` is stored on the monitor.
- A follow-up request that returns no rows means the sensor stopped reporting; that is not a gap. `truncated` is only recorded when follow-ups keep returning rows and the response is still more than an hour short.
- `Monitor.create_entry` / `PurpleAir.create_entries` gained `validate=True`; the importer passes `validate=False` (with `save=False`) to skip the per-entry duplicate query.
