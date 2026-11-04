# Summary cache headers and place lookup by point or monitor

Release 1, step 3, second batch, spec 2 (sjvair.com + sdk-js). Drafted 2026-11-03.

Earlier work: spec 1 (`2026-11-03-metadata-scales-design.md`, sjvair.com #300, sdk-js #37,
@sjvair/sdk 4.8.0-beta.4). The dashboard's requirements live in data-dashboard
`ARCHITECTURE.md` → "Data resolution & live refresh" and "Widget data selection (partial
datasets)" → "Location privacy", and in `TODO.md` → "Release 1, step 3".

## Why

Step 4 of the dashboard (widgets) needs two things from the server soonest:

1. **HTTP cache headers on the summary endpoints.** The dashboard keeps no persistent data
   cache of its own. Across reloads, the browser's HTTP cache does that job, so the server
   must say how long a summary response can be reused. Without headers, every reload and
   every reopened dashboard refetches history the server already sent.
2. **Point and monitor lookups on `regions/places/lookup/`.** "Use my location" shows air
   quality for the smallest containing region with data (ZIP → city → county), and the
   dashboard maps a monitor to its regions. Today the endpoint only takes a name.

## Goals

- The summary rollups run on Pacific periods: each lands shortly after its period ends,
  and seasons cover the real Dec/Mar/Jun/Sep windows (Part 0).
- Every summary endpoint sends `Cache-Control` and an `ETag`. Settled responses are reused
  for a day, everything else for about a minute.
- `regions/places/lookup/` answers a rounded point (POST body) or a monitor (`?monitor=`)
  with the list of regions containing it. The name mode is unchanged.
- Coordinates never reach logs, Sentry, or Scout.
- sdk-js `lookupRegionPlace` gains the point and monitor modes.

## Non-goals

- **The other two rollup findings** in `docs/superpowers/reports/2026-11-03-summary-rollups.md`: period starts in
  standard time stamped an hour early, and region summaries mostly missing on production.
  Neither has a known cause, and both need production logs or data repair. They go to a
  separate follow-up investigation (the user, 2026-11-03), recorded in DEFERRED.md.
- Any server-side caching of summary responses. These are response headers only.
- A CDN or shared cache.
- Location (school, child-care) search, the other SDK wrappers, and the hardcoded-value
  cleanup. Those are later specs in this batch.

## Anti-goals

- A cached response that hides a period whose rollup hasn't run yet. If the browser caches
  "yesterday" for a day before yesterday's row exists, the dashboard shows a hole for a day.
  That is worse than no caching.
- Long or "immutable" caching of history. Past summaries are rarely rewritten (the user,
  2026-11-03), but `rebuild_summaries`, late AirNow or BAM data and recalibrations do
  rewrite them, and a year-long cache would keep the old numbers in browsers with no way
  to correct them.
- A coordinate in a URL, a log line, a Sentry event, or a Scout trace.

## Part 0: Rollups on Pacific time

The user first left this for later, then chose (2026-11-03) to fix it here after it was
confirmed. Evidence and reproducible checks: `docs/superpowers/reports/2026-11-03-summary-rollups.md` → finding 1.

**The bug.** Huey 3.3 defaults to `utc=True` and `DJANGO_HUEY` sets no `utc` option, so
`camp/apps/summaries/tasks.py`'s crontabs fire on UTC. The daily job runs at ~17:00
Pacific the next day. Monthly, quarterly and yearly jobs run on the period's last
Pacific day and roll up the period before. The seasonal job rolls up windows starting
Nov/Feb/May/Aug, which aren't seasons. A dyno `TZ` can't change this (`utc=True`
ignores it).

**The fix (decided):** it must not depend on the server's timezone. Crontabs stay on
UTC. Each rollup task decides from the **Pacific** clock whether it's time and which
period ended. For example, it runs at both possible UTC hours for 01:xx Pacific (08 and
09 UTC) and acts only in the one that is 01:xx Pacific. The builder may pick another
mechanism with the same effect, e.g. a single hourly dispatcher. Requirements:

- Each daily, monthly, quarterly, seasonal and yearly rollup runs once, about an hour
  after its Pacific period ends, in both PST and PDT, including on DST-change days.
- Seasons are Dec–Feb, Mar–May, Jun–Aug and Sep–Nov, matching `higher_rollup_windows`
  in `backfill.py`.
- A rollup that runs twice for the same period is harmless (check the rollups' upsert
  behavior).
- Hourly monitor and region tasks (:45, :50) are unaffected: they already work in UTC
  hours.
- Tests freeze time across PST, PDT and both DST changes. They assert which period each
  task rolls up and that it runs exactly once.

**Catch-up after deploy (my call):** a management-command run, scoped and checked for
blast radius first, rolls up the periods the late schedule hasn't reached yet when the
fix deploys: the last finished month, quarter and season. The PR's deploy notes list the
exact commands. Misaligned seasonal rows already in the DB (windows starting Nov/Feb/May/
Aug) are not deleted here. They belong to the follow-up investigation, since the
investigation may repair those rows anyway.

## Part 1: Summary cache headers

### Endpoints

All six summary views in `camp/api/v2/summaries/endpoints.py`: per-monitor and per-region
path endpoints (`…/summaries/<entry_type>/<resolution>/<year>/[<month>/[<day>/]]`), and the
monitor and region bulk endpoints (`…/<entry_type>/summaries/<resolution>/?start=&end=`).
Every page of a paginated response is treated the same way.

### The rule

A response is **settled** when every period it can contain has ended **and** the rollup
for its last period should already have run, plus a margin.

- The range's end is the end of the URL's period for the path endpoints (the year, month or
  day), and `end_exclusive` for the bulk endpoints.
- The last period is the last period of the response's resolution that starts before that
  end.
- **Settled:** `Cache-Control: private, max-age=86400` (a day).
- **Not settled** (the range includes now, or a rollup is still due):
  `Cache-Control: private, max-age=60`.
- **Both** get an `ETag`, so a stale copy is revalidated with a cheap 304 when nothing
  changed.
- Only 200 responses get these headers. Errors (400, 404) get `no-cache`.

### Settle times (with Part 0's schedule)

A period is settled a margin after its rollup runs:

| Resolution | Rollup runs (Pacific)                          | Settled from                    |
| ---------- | ---------------------------------------------- | ------------------------------- |
| hour       | H+1:45 (monitors), H+1:50 (regions)            | 2 hours after the hour ends     |
| day        | ~01:00–01:10 after the day ends                | 3 hours after the day ends      |
| month+     | ~01:15–02:05 on the 1st after the period ends  | 3 hours after the period ends   |

The builder sets the exact margins from Part 0's final schedule. A margin covers the
rollup's run time on the real local data, plus slack. The settle times live in **one
place**, next to the schedule they depend on, so the two can't drift apart. A test fails
if a rollup's scheduled time moves past its settle time.

### Decided

- A day for settled responses, about a minute for the rest (the user, 2026-11-03).
- The UTC crontab bug is fixed in this spec (Part 0; the user, 2026-11-03).

### The builder's calls (marked as the drafter's)

- **`private`, not `public`.** There's no shared cache in front of the API, so `private`
  costs nothing and stays safe if a response ever depends on who asks. Hidden monitors get
  no special rule. (Reads never check `MonitorAccessMiddleware`'s access key, which only
  guards writes. See "Hidden monitors" below.)
- **The monitor bulk endpoint's live fields** (`is_active`, `health` on each nested
  monitor) can be up to a day old in a settled response. Accepted (the user, 2026-11-03):
  the dashboard reads live status from the current endpoints. A body-hash ETag will rarely
  match on that endpoint for the same reason, which is fine. A cheaper ETag must account
  for these fields.
- **How the ETag is computed.** A hash of the body (Django's `ConditionalGetMiddleware`
  approach, applied to these views only) saves bandwidth but still runs the query and
  serialization. That is acceptable for this spec. A cheaper ETag (from row `updated` times)
  is allowed if the builder shows it's correct. The ETag must survive `GZipMiddleware`
  (a weak ETag is fine).
- **`Vary`.** Check what the views send today (`Cookie` from session access, `Origin` from
  CORS). A `Vary: Cookie` is acceptable for a private browser cache. Note the finding in the
  PR.
- If a period's rollup ran late (the workers were down), a settled response can cache a
  missing row for up to a day. That is accepted, and the PR notes it.

### Heads-up for dashboard step 4 (goes into data-dashboard docs, not code)

The browser only gets a hit when it asks for the **same URL** again. History stays cached
only if the dashboard requests settled periods with stable URLs (e.g. whole past months,
or the path endpoints) separately from the live tail. A single "last 7 days" request whose
dates shift daily never reaches the long cache.

## Part 2: `regions/places/lookup/` by point or monitor

### Decided earlier (data-dashboard ARCHITECTURE.md, 2026-09-28)

- Same endpoint, no new URL. The name mode (`GET ?q=&type=`) keeps its single-region
  response.
- A point arrives as `lat`/`lon` in a **POST body**, rounded by the client to 3 decimals
  (about 100 m). A monitor arrives as `GET ?monitor=`.
- Both modes return a **list** of the regions containing the place, narrowed by `type`.
  The geometry rule is intersection (`Region.objects.intersects`, which
  `Monitor.regions()` already uses). For a point that means containment. (This is not
  `within=`'s default `contained` mode, which tests a region's area against a parent.)
- The server scrubs `lat`/`lon` from Sentry, Scout and application logs.

### The drafter's calls (approved in conversation, 2026-11-03)

- **`type` takes a comma-separated list**, so one call can return ZIP, city and county
  together. With no `type`, every type is returned except `land_use` and `mtrs`. An unknown
  type is a 400. `land_use` asked for explicitly is a 400 (not referenceable, like spec 1's
  place endpoints). `mtrs` asked for explicitly is allowed.
- **The server rounds to 3 decimals as well**, so a client that forgets can't leak precision
  into the computation or the cache.
- **Only current regions** (`Region.objects`). A point or monitor outside every region gives
  an empty list, not an error. On a shared edge, both regions are returned.
- **Response:** `{"data": [region, …]}`, geometry-free (`RegionListSerializer`), ordered by
  type, then `external_id`.
- **Caching:** answers are cached 24 hours through `camp/apps/regions/resolve.py`, like spec
  1's place answers. Point keys are built from the rounded coordinates and the sorted type
  list, monitor keys from `_place_key`. All keys are memcached-safe (no spaces, bounded
  length). A boundary re-import can leave a point's answer stale for up to 24 hours (same
  trade-off as spec 1; note it in DEFERRED.md next to spec 1's entry).
- **CSRF:** nothing special. Our resticus config authenticates by token only
  (`RESTICUS` → `TokenAuth`), and resticus (with the #25 fix) checks CSRF only for
  session-signed-in users making an unsafe request without a token. So an anonymous POST
  needs no CSRF token, and a signed-in one must send it. sdk-js already adds
  `X-CSRFToken` to same-origin browser POSTs (`lib/http/request_init.ts`). Tests cover an
  anonymous POST with no token (200) and a signed-in POST without one (403). `@csrf_exempt`
  would do nothing here: resticus's own check never sees it.

### Hidden monitors (the user, 2026-11-03)

`?monitor=` answers only for **public** monitors (`Monitor.objects.get_public()`). A hidden
monitor or a disabled type gets the same 404 as an unknown id, so its ZIP doesn't reveal
roughly where it is. `resolve_place` is shared, so spec 1's `calheatscore/place/` and
`forecasts/place/` get the same rule. Tests cover all three.

Hidden monitors' per-monitor summaries (and probably raw entries) are readable by anyone
who has the id. That predates this spec and is out of scope: fixing it means deciding what
"hidden" means for reads. It goes in DEFERRED.md.

### Requests

- `POST regions/places/lookup/` with a JSON body `{"lat": 36.737, "lon": -119.787,
  "type": "zipcode,city,county"}` (`type` optional). Missing or out-of-range `lat`/`lon`
  is a 400.
- `GET regions/places/lookup/?monitor=<id>&type=…`. An unknown or hidden monitor is a 404. A monitor
  without a position is a 400 (reuse `resolve_place`'s messages).
- `q` together with `monitor`, or a POST that also has `q`, is a 400.
- `lat`/`lon` in the query string is a 400 saying coordinates go in a POST body. The value is
  never echoed back.

### Scrubbing

- **Sentry:** generalize `camp/apps/documents/sentry.py`'s `before_send` (drop request
  `data` and frame `vars`) to cover the lookup path too. Also drop the query string for that
  path, for clients that send coordinates there anyway.
- **Scout:** confirm it records no request bodies and filters the query string
  (`SCOUT_URI_REPORTING`). Change the setting if needed.
- **Logs and error emails:** confirm nothing logs the body. Mark the view so Django's error
  reports leave out the POST data.
- Tests cover the Sentry scrubber for the new path.

### Performance

Run the point query on the real local DB with `EXPLAIN ANALYZE`: a Fresno point, a rural
point, and one outside the valley, with and without `type`. It must use the boundary
geometry's spatial index. `Region.objects` holds ~67k rows, mostly `land_use`, so the
default type filter must apply in the same query, not after it. Record the cold and warm
timings in the PR.

### sdk-js

On a branch from `origin/release/4.8.0`, PR into it.

- `lookupRegionPlace` gains a point mode (`{ lat, lon, type? }`, rounds to 3 decimals before
  sending, POSTs the body) and a monitor mode (`{ monitor, type? }`). Both return a list.
  The name mode and its return type are unchanged. `type` accepts an array or a single type.
  All modes take the existing request options (`signal` and the rest, per
  data-dashboard ARCHITECTURE.md → "SDK request options").
- Schemas, types, tests against the local API, and `api-urls.md` updated.
- No beta is cut without the user's yes for that specific release.

## Part 3: Listing weather stations (opt-in monitor types)

Added 2026-11-04 (the user: widgets are next, so this isn't deferred).

**The gap.** The catalog's Weather dataset is CIMIS stations (places of kind `monitor`), but no
public endpoint lists them. `MONITOR_ENABLED_TYPES` leaves CIMIS out, and the monitor list
applies `get_public()` before any filter, so the dashboard can't offer stations or match the
nearest one. Adding CIMIS to the whitelist would put weather stations in every list,
`closest`, `current`, `at` and `meta` answer, which installed apps read.

**Decided (the user, 2026-11-04): an opt-in setting.**
- `settings.MONITOR_OPT_IN_TYPES = {'cimis': 'weather'}` maps a monitor type to the catalog
  dataset that opts it in. Opt-in types never appear by default: every endpoint answers
  exactly as today without the parameter below.
- `GET /api/2.0/monitors/?dataset=<id>`:
  - `weather` returns that dataset's opt-in types only (CIMIS), not hidden, in the usual
    monitor shape.
  - `air-quality` returns today's default list.
  - Without `dataset`, the list is unchanged.
  - An unknown or non-monitor dataset id is a 400.
  - Other filters (`device`, `name`, `position`) still apply on top.
- The catalog's Weather and Air Quality datasets gain `places_url`, the list URL with their
  `dataset=`. Other datasets get `places_url: ""`. The field is additive.
- Only the list endpoint opts in. `closest`/`current`/`at`/`meta` are unchanged. The nearest
  station is computed in the browser (about 23 stations).
- The list's response cache keys on the query string already, so `?dataset=weather` is cached
  separately.
- sdk-js: a new `listMonitors({ dataset? })` wraps the plain `monitors/` list, which no
  function wraps today. `getMonitors` wraps `current`/`at` and stays unchanged. The catalog
  schema gains `places_url`. Both go in Part 2's sdk-js PR.

## Delivery

- sjvair.com: branch `feature/summary-cache-lookup` from `origin/develop`, one PR into
  `develop`. Update CLAUDE.md → "Metadata Endpoints" (the lookup modes, the cache rule, and
  where the settle times live).
- sdk-js: one PR into `release/4.8.0`.
- Merges into `develop` or `release/4.8.0` need the user's yes.
- Testing on the shared podman stack: message the map-sdk and design pass sessions before
  swapping the web container, and again when it's back on the main checkout.
- Summary cache tests need settled and unsettled periods. Tests freeze time. A hand check on
  the local stack uses scoped `rebuild_summaries` runs (one region or monitor, a tight date
  range; check the blast radius first).

## Docs to update in data-dashboard (after the PRs, docs-only push to `main`)

- `TODO.md` → "Release 1, step 3": mark the cache headers and the lookup done (with PR
  numbers), and this session's row in "Start here".
- `ARCHITECTURE.md` → "Data resolution & live refresh": the settled rule, the two max-ages,
  and the stable-URL heads-up above. "Widget data selection" → "Location privacy" and the
  lookup bullet: the `type` list, the default type set, and the server-side rounding.
- `DEFERRED.md`: the two rollup findings left for the follow-up (period starts an hour
  early, region summaries missing on production, the misaligned seasonal rows; see
  `docs/superpowers/reports/2026-11-03-summary-rollups.md`), hidden monitors' summaries readable by id, and the lookup's 24-hour cache after a boundary re-import.
