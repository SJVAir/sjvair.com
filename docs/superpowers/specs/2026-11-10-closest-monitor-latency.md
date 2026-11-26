# Closest monitor latency

`GET /api/2.0/monitors/<entry_type>/closest/` (`ClosestMonitor`) is the one request the
mobile "My air" screen waits on. Production showed ~0.85 s TTFB on desktop and 1-2 s typical,
multi-second outliers on Android. Investigated on the local stack only (2026-11-10).

## Findings

Baseline (local, debug toolbar off, 30 requests per point after warmup; Fresno, Bakersfield,
Stockton, NYC): 4 queries, SQL ~450 ms, wall p50 ~560 ms, p95 ~750-880 ms, max ~900 ms (pm25);
~410 ms for o3. One query was ~440 ms of it.

1. **Postgres JIT.** `get_active()` joins monitors to `LatestEntry` and adds `DISTINCT`, so
   384 candidate monitors became 3,524 rows. The planner estimated 47k rows (cost 2.0M), over
   `jit_above_cost` (100k), and compiled 110 functions on every request: 413 ms of the 475 ms
   execution. The same SQL with `jit=off` took 61 ms. (`camp/settings/test.py` already sets
   `jit=off`, which is why tests never saw it.)
2. **Whole candidate set loaded.** `with_latest_entry()` evaluates its queryset, so the view
   loaded every candidate monitor plus the `latest_entries` prefetch (~6,000 rows) before
   `[:3]`. With JIT off, the old view was still 160 ms p50, ~440 ms max.
3. Minor: one `airgradient_place` query per AirGradient monitor in the result
   (`data_providers`).

Ruled out: a missing spatial index (`position` has a GiST index, and the exact spheroid
distance over ~400 rows costs a few ms), `published_for()` (one tiny query). Caching isn't
needed after the fix; a key on rounded coordinates would hit rarely and shift `distance`.

## Change

- `MonitorQuerySet.with_latest_entry()` is split into `annotate_latest_entry()` (SQL only)
  and `attach_latest_entries()`; `with_latest_entry()` composes them, so its other callers
  are unchanged.
- `ClosestMonitor` builds its own queryset: active as an `EXISTS` on `LatestEntry` (same
  cutoff as `get_active()`), no `latest_entries` prefetch, `select_related('health',
  'airgradient__place')`, `order_by('distance', 'id')` (the old `DISTINCT` sort already broke
  ties by id). `?device=` still filters before the slice; entries are attached to the 3 kept
  monitors only. `get_active()` itself is unchanged.
- No migration, no cache, no response change. The new plan's cost is ~16k, below the JIT
  threshold.

## Result

Same measurement: 3 queries, SQL ~13-16 ms, wall p50 ~20-23 ms, p95 <= 26 ms, max <= 27 ms.
Old and new responses were byte-identical for pm25, o3 and temperature at the four points
and with `?device=`.

Tests (`ClosestMonitorTests`): distance order and the 3-result limit, distance in feet,
`latest` shape, exclusion of hidden/inside/inactive/no-entry monitors, and a fixed 3-query
count that doesn't grow with candidates (AirGradient included).

## Not verified locally

- Whether production Postgres has JIT on (the fix helps either way: the Python-side load was
  ~100 ms on its own).
- Infrastructure variance: sync gunicorn workers queueing behind slow requests, database CPU
  contention, mobile network latency. Production before/after timing is a post-deploy check.

## Deferred

- App-wide `jit=off`, or fixing other queries that trip JIT (other `get_active()` callers
  share the join + `DISTINCT` fan-out). Recorded in data-dashboard `DEFERRED.md`.
- `with_latest_entry()` takes the first `LatestEntry` row per (monitor, entry type) with no
  ordering; for monitors with both cleaned and calibrated PM2.5 rows it returns the calibrated
  one only because of index order. Unchanged here.
