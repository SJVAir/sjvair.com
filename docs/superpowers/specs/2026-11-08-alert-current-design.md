# Alert current value per monitor

Date: 2026-11-08. The server side of data-dashboard step 4, spec 4 (Current conditions). The
SDK side is in sdk-js, `docs/superpowers/specs/2026-11-08-alert-current-design.md`.

## Why

The dashboard's Current conditions tile must show the same trailing 60-minute average, and
level, that the SMS alert evaluator uses (the user's decision, 2026-11-08). The goal is that the
tile never disagrees with a text someone just got. The server doesn't publish that value today.

Regions are out of scope: their tile keeps using the latest hourly summary.

## How it works today

- `camp/apps/alerts/tasks.py` `periodic_alerts` runs every 10 minutes (`*/10`). For every
  monitor from `get_alert_monitors()` (active monitors of types with alertable entry types, plus
  any monitor with an open alert) it calls `AlertEvaluator(monitor).evaluate()` and texts
  subscribers from the returned levels. The text names the level only, not the value.
- `camp/apps/alerts/evaluator.py` `AlertEvaluator`:
  - `WINDOW` is 60 min and `MIN_COVERAGE` is 0.5, so an average needs
    `max(1, ceil(WINDOW / interval × 0.5))` readings.
  - When the expected interval is ≥ `WINDOW`, it uses the latest reading instead, provided
    that reading is no older than 2× the interval. This applies to BAM, AQview and AirNow (all
    `1 hour`) and to AQLite O3 (`expected_interval: '1h'` override).
  - The series it reads is each monitor type's `ENTRY_CONFIG[model]['alerts']`: lookup kwargs
    plus an optional `expected_interval`. It often differs from the published default. For
    example, PurpleAir and AirGradient PM2.5 use calibrated `PM25_UnivariateLinearRegression`,
    while the published default is `PM25_EPA_Oct2021`.
  - It returns `{entry_model: Level or None}` only. "Too few readings" and "no readings" both
    come back as `None`, and the average itself is discarded.
- `daily_reminders` calls `get_levels()`. `notifications.py` consumes the levels dict.

## Decisions (the user's, 2026-11-08)

1. **Serve the evaluator's stored result**, not a value computed on request and not a
   client-side calculation. Only the result of the 10-minute run matches the SMS by
   construction. A fresh average at 4:07 isn't the one the 4:00 run texted from.
2. **The tile shows the last stored number** even when it's up to 10 minutes old, so it always
   matches the text. The tile shows its age using `latest_timestamp`.
3. **The result is stored in the cache, not a table.** There is no migration. After a cache
   flush or restart, results are missing for up to 10 minutes (`pending`).
4. **`monitors/meta/` publishes the full alert config** for every evaluated monitor type and
   entry type pair: window, minimum coverage, stage, processor, and the expected-interval
   override. The full block was chosen over a slim one so the dashboard can chart the same
   series the alerts read.
5. **The endpoint is `GET /api/2.0/monitors/<monitor_id>/alerts/current/`**, with `data` as a
   dict keyed by entry type.
6. **A pair the run never evaluates is a missing key**, not a `not_evaluated` status.
   `monitors/meta/` says beforehand which pairs are evaluated.
7. **No cached result and an inactive monitor means `no_data`**; with an active monitor it
   means `pending`. This keeps inactive monitors from showing `pending` forever.

## Goals

- The tile's value and level are exactly what the most recent `periodic_alerts` run decided.
- One cheap request per tile: a single cache read plus the monitor lookup the middleware already
  does. Nothing is evaluated on request.
- The dashboard can tell apart:
  - ok
  - not enough readings
  - no readings
  - not evaluated yet
  - never evaluated
- The dashboard can explain the number ("based on a 60-minute average") and chart the same
  series from server metadata, without hard-coding anything.

## Non-goals

- No change to which monitors are evaluated, the levels, alert records, or SMS behaviour. The
  existing alert tests must pass unchanged, except where they read return values whose shape
  this changes. Keep those changes minimal.
- No list or bulk variant: spec 4 needs one monitor per request.
- No regions.
- No migration and no new model.

## Anti-goals

- The tile and the SMS disagreeing because the endpoint computed something itself.
- Evaluating on request, for one monitor or many.

## 1. The evaluator returns a full result

Add a result object (a small dataclass is fine) per entry type:

| field | meaning |
|---|---|
| `status` | `ok`, `insufficient` or `no_data` (see below) |
| `value` | the average (or the latest reading, for hourly feeds), unrounded, in the entry type's units; `None` unless `ok` |
| `level` | the `Level` from `entry_model.Levels.get_level(value)`; `None` unless `ok` |
| `window_start`, `window_end` | the period read (below) |
| `latest_timestamp` | timestamp of the newest reading in the window, or `None` when there is none |
| `readings` | how many readings were in the window |
| `required` | how many were needed |
| `previous` | the same evaluation 60 minutes earlier (below) |

Status:
- **Averaged feeds:**
  - `no_data` when the window holds 0 readings
  - `insufficient` when it holds 1 to `required - 1`
  - `ok` otherwise
- **Latest-reading feeds** (interval ≥ `WINDOW`): the window is `[now - 2 × interval, now]` and
  `required` is 1.
  - `ok` when a reading falls in it
  - `insufficient` otherwise (spec 4 counts "an hourly feed's latest reading older than 2× the
    interval" as not enough readings)
  - `no_data` doesn't arise for these feeds

`previous` is the same rule evaluated as of `now - WINDOW`: the hour before the window, or, for
hourly feeds, the latest reading as of an hour earlier. It carries `status`, `value`, `level`
and `latest_timestamp`. **My call:** it reuses the same code with a shifted `now`, so the trend follows exactly
the rules of the current value.

**`previous.latest_timestamp`** (the user's decision, 2026-11-08) follows the same rule as the
current `latest_timestamp`: the newest reading in its window, `null` when the window has none.
A lagging hourly feed's `previous` can be the very reading the current value uses; equal
timestamps tell the dashboard to show no trend, while equal values with different timestamps
are a real "unchanged".

Each monitor's evaluation uses one `now` for all its entry types. Today each entry type reads
the clock separately. **My call:** one shared `now` makes `window_end` the same across a
monitor's pollutants and changes no outcome that matters.

`get_levels()` and `evaluate()` must keep returning `{entry_model: Level or None}` (a level only
when `ok`), so `notifications.py`, `daily_reminders` and the alert tests are unaffected. Add a
method that returns the full results; `get_levels()` derives from it. The `previous` evaluation
is one more aggregate (or one more latest-row query) per entry type per run. That's a small cost
on a 10-minute job, but it is the job's only new database work.

## 2. The 10-minute run stores the result

- In `periodic_alerts`, after each monitor's `evaluate()`, write that monitor's results to the
  cache under one key per monitor (e.g. `alerts:current:<monitor pk>`). The value is a dict
  keyed by entry type id plus `evaluated_at`.
- Store plain serializable data (level key, not the `Level` object), so the endpoint doesn't
  need to rebuild anything.
- **Timeout: 30 minutes (my call).** Three missed runs, so a stalled job or a monitor that drops
  out of the run stops being served instead of lingering.
- The write is best effort: a cache error is logged and doesn't stop the monitor's
  notifications.
- `daily_reminders` doesn't write (it runs `get_levels` at a different moment).
- Monitors evaluated only because they have an open alert (inactive) are stored too, since they
  were evaluated.

## 3. `GET /api/2.0/monitors/<monitor_id>/alerts/current/`

Added to `camp/api/v2/alerts/urls.py`, next to `subscribe/` and `unsubscribe/`. Monitor lookup
and 404s (unknown or malformed id) work as they do for the other `<monitor_id>/` endpoints
(`MonitorAccessMiddleware` / `request.monitor`). **Hidden monitors are served** (the user's
decision, 2026-11-08), like the monitor detail and entries endpoints. The alert run evaluates
and texts hidden monitors, so the tile shows the same thing the texts are based on. Whether
hidden monitors should alert at all is deferred (data-dashboard `DEFERRED.md`); if they stop
being evaluated, this endpoint follows on its own.

```json
{"data": {
  "pm25": {
    "status": "ok",
    "value": 38.2,
    "level": "unhealthy_sensitive",
    "window": {"start": "2026-11-08T15:00:00-08:00", "end": "2026-11-08T16:00:00-08:00"},
    "latest_timestamp": "2026-11-08T15:58:00-08:00",
    "readings": 29,
    "required": 15,
    "previous": {"status": "ok", "value": 31.0, "level": "moderate",
      "latest_timestamp": "2026-11-08T14:58:00-08:00"},
    "evaluated_at": "2026-11-08T16:00:04-08:00"
  }
}}
```

- **Keys** are the entry type ids of the monitor type's alertable entry types
  (`alertable_entry_types`). A monitor type with none answers `{"data": {}}`.
- **`level`** is the level key from the same scale `monitors/meta/` publishes (`good` …
  `hazardous`). `value` and `level` are `null` unless `status` is `ok`, here and in `previous`.
- **When there's no cached result**, each alertable entry type is answered with `value`,
  `level`, `window`, `latest_timestamp`, `previous` and `evaluated_at` as `null`, and `readings`
  and `required` as `null`:
  - `status: "pending"` when the monitor is active (`is_active`)
  - `status: "no_data"` when it isn't
- **`evaluated_at`** is when the run evaluated the monitor. It also sits in each entry so a
  client reading one pollutant has it.
- **Timestamps** are ISO 8601 with offset, serialized like the other v2 endpoints.
- **Cache headers (my call):**
  - 200s: `public, max-age=60`
  - errors: `no-cache`
  - no server-side response cache, since the result is already a single cache read

## 4. `monitors/meta/`: the `alerts` block

In `MonitorMetaEndpoint.get_monitors`, each entry under `monitors.<type>.entries.<entry_type>`
gains `alerts`:

```json
"alerts": {
  "window": "60 min",
  "min_coverage": 0.5,
  "stage": "calibrated",
  "processor": "PM25_UnivariateLinearRegression",
  "expected_interval": null
}
```

- **`alerts` is `null` when the pair isn't evaluated (my call).** That matches how the other
  fields there are always present. A non-null block means the pair is evaluated and appears in
  `alerts/current/`.
- **`window`** uses the same human-readable string style as `expected_interval`. **My call:**
  `"60 min"`, from `AlertEvaluator.WINDOW`.
- **`min_coverage`** comes from `AlertEvaluator.MIN_COVERAGE`.
- **`stage` and `processor`** come from the `'alerts'` config. `processor` is the processor
  name, or `null` when the config has none (AirNow O3, AQLite O3).
- **`expected_interval`** is the override as configured (`"1h"` for AQLite O3), else `null`.
  The monitor type's own `expected_interval` is already published one level up.
- Everything comes from the existing config and constants, so nothing is duplicated.

## Tests

`django.test.TestCase` with fixtures and pytest-style asserts, as in the repo.

- **Evaluator results.** For each of these, check `status`, `value`, `readings`, `required`,
  `latest_timestamp`:
  - an averaged feed at `ok`, `insufficient` and `no_data`
  - a latest-reading feed at `ok` and `insufficient`
  - `previous` from the shifted `now`
- **`get_levels()` / `evaluate()` unchanged.** Same levels as before for the same data, and the
  existing alert and scenario tests pass.
- **Storage.** `periodic_alerts` writes the cache key with the expected content, and a cache
  error doesn't stop notifications.
- **Endpoint:**
  - a cached result is served as stored
  - a cache miss gives `pending` for an active monitor and `no_data` for an inactive one
  - a monitor type with no alertable entry types gives `{}`
  - unknown and malformed ids 404; a hidden monitor is served
  - the cache headers
- **Meta.** The `alerts` block for a few pairs: PurpleAir PM2.5 with a processor, AQLite O3
  with the override, AirNow O3 with no processor, and a non-alertable pair (`null`). Update any
  meta snapshot or fixture.

## Docs

- `CLAUDE.md`, under Metadata Endpoints: a short entry for `alerts/current/` and the meta
  `alerts` block. This includes that the value is the stored 10-minute result, the statuses, the
  30-minute expiry, and that a cache restart gives `pending` for up to 10 minutes.
- The v2 OpenAPI schema, if endpoints are listed there by hand.

## Deploy

Nothing to run. Results appear within 10 minutes of the first `periodic_alerts` run after deploy.

## Left to the builder

- The result object's name and where it lives.
- The cache key's exact name.
- How the endpoint class is built (a plain resticus endpoint is fine).
- Whether `previous` shares the current window's query or runs separately.
