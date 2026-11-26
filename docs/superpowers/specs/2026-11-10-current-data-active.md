# current/: activity check without the JIT

Follow-up to `2026-11-10-closest-monitor-latency.md`, same cause. Investigated on the local
stack only (2026-11-10).

## Findings

`CurrentData` (`monitors/<entry_type>/current/`) filtered with `get_active()`, which joins
monitors to every `LatestEntry` row and adds `DISTINCT`. For pm25 that turned 527 monitors
into 4,638 rows; the planner's cost (~2.4M) crossed `jit_above_cost` and Postgres
JIT-compiled the query on every run:

| main query | JIT on | JIT off | of which JIT compiling |
|---|---|---|---|
| pm25 | 607 ms | 100 ms | 511 ms |
| o3 | 384 ms | 2 ms | 382 ms |

Readers mostly get the cache: `refresh_cached_endpoints` re-runs `current/` every minute
(22 entry types; only pm25 and o3 are published, the rest short-circuit with no query). So the
cost was ~1 s of JIT compiling per minute on the database, around the clock, plus slow
cold-cache misses.

## Change

- Active is an `EXISTS` on `LatestEntry` with the same cutoff (`MONITOR_ACTIVE_WINDOW_DAYS`).
  `get_active()` itself is unchanged.
- `order_by('name', 'id')`: `Monitor.Meta.ordering` is `name`, and the old `DISTINCT` sort
  broke same-name ties by id. Without it, same-named monitors came back in any order.
- The `latest_entries` prefetch is dropped for this view (`prefetch_related(None)`); nothing
  reads it (`is_active` uses the `last_entry_timestamp` annotation).

## Result (local, same harness both sides)

| | queries | total p50 | main SQL |
|---|---|---|---|
| pm25 before | 67 | ~830 ms | ~613 ms |
| pm25 after | 66 | ~230 ms | ~73 ms |
| o3 before | 4 | ~400 ms | ~383 ms |
| o3 after | 3 | ~40 ms | ~29 ms |

pm25's remaining 66 queries are the AirGradient place N+1 fixed separately in #327 (4 queries
with both). Responses: o3 byte-identical; pm25 same monitors, same order, same fields (the
only differences across runs were readings that arrived in between).

JIT still fires on the new plans (cost ~320-410k, above `jit_above_cost` 100k but below the
500k optimize/inline thresholds), costing ~25-50 ms. That's left to the deferred app-wide JIT
item.

## Tests (`CurrentDataActiveTests`)

The active window (inside, near the edge, outside), each monitor once with several
`LatestEntry` rows, order by name then id, and a fixed 3-query count whose main query has no
`DISTINCT`.

## Noticed, not changed

`camp/apps/monitors/cimis/test_restamp.py::RestampCommandTests::test_command_reports_a_short_answer`
is flaky: it passes `'--monitor', monitor.pk` as two arguments, so a random id starting with
`-` (about 1 run in 64) is read as a flag. Fix: `f'--monitor={monitor.pk}'`.
