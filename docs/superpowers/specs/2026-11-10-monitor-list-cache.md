# Monitor list: encoded cache and AirGradient N+1

Follow-up to `2026-11-10-closest-monitor-latency.md`. `GET /api/2.0/monitors/` showed a fast
TTFB but a slow body in production (0.49 s TTFB, 2.97 s total on desktop). Investigated on
the local stack only (2026-11-10).

## Findings

1. **Cache hits re-streamed the data.** `CachedEndpointMixin` cached the data dict and
   streamed it on every hit. resticus' `StreamingJSONResponse` passes `iterencode()` straight
   to `StreamingHttpResponse`, one chunk per JSON token: 87,045 chunks for the 486 KB list.
   Reading the cache took 9 ms and encoding 12 ms, but the hit took ~180 ms (gzip ~195 ms):
   the rest is per-chunk overhead in Django's streaming path and `GZipMiddleware`.
2. **AirGradient place N+1.** `AirGradient.data_providers` reads `place`, one query per
   AirGradient: 268 queries on a list miss locally.

The cache fits memcached: bmemcached zlib-compresses values over 128 bytes, so production's
~1 MB list is ~110 KB stored (from the code; whether production hits is a post-deploy check
of `X-Cache-Status`).

## Change

- `CachedEndpointMixin.cache_encoded` (opt-in): on a miss the data is encoded once with
  resticus' `JSON_ENCODER`, cached as bytes and served as a plain `application/json`
  response; a hit serves the bytes. Errors (responses) pass through and still aren't cached.
  The body is byte-identical to the streamed one. A dict left in the cache would still be
  served (streamed).
- `MonitorList` and `CurrentData` opt in and set `cache_key_version = 1`, so entries written
  by the old code are never read.
- `MonitorMixin` adds `select_related('airgradient__place')` (list, `current/`, `at/`).
- Clients see the same body, plus a `Content-Length` header; gzip now compresses the whole
  body (slightly smaller).

## Result (local, same harness both sides)

| | miss queries | miss p50 | hit p50 plain / gzip |
|---|---|---|---|
| `/monitors/` before | 268 | 664 ms | 180 / 195 ms |
| `/monitors/` after | 2 | 385 ms | 1 / 3 ms |
| `pm25/current/` before | 67 | ~980 ms | 159 / 178 ms |
| `pm25/current/` after | 4 | ~930 ms | 1 / 4 ms |

Same list body SHA before and after.

## Deferred

- resticus streams JSON one token per chunk, which still affects every other streaming
  endpoint. Fix in resticus (group into ~64 KB chunks). Recorded in data-dashboard
  `DEFERRED.md`.
- `current/` misses are still ~950 ms (likely the `get_active()` join and JIT, see the
  JIT deferral); it is prewarmed, so readers mostly hit the cache.
