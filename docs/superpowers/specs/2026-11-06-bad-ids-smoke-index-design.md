# Bad ids answer 404, a date index on Smoke, weather display hints

Date: 2026-11-06. Three small server fixes found during the Get data layers work, plus one
request from data-dashboard spec 3b. Two PRs: sjvair.com first, then django-resticus.

## Why

- **Bad ids.** A detail request whose id can't be a valid small UUID (`monitors/nonexistent/`,
  `hms/smoke/abc%21/`) should answer 404, the same as a well-formed id that doesn't exist.
  Today `django_smalluuid`'s `to_python` raises `ValidationError` before any query runs.
  Nothing on the way catches it as "not found":
  - Locally (DEBUG) it is a 500. resticus's `dispatch` turns the `ValidationError` into
    `Http400(err.message)`, then `JSONErrorResponse.__init__` crashes on `data["meta"] = …`
    because the message is a lazy translation proxy, not a `str`.
  - In production (DEBUG off) it is a 400. This was worked out from the code only; no
    production logs were read. The body is a bare JSON string holding the unfilled template:
    `"'%(value)s' is not a valid short-form UUID."`.
  - A write to a monitor route that sends an access key runs the lookup in
    `MonitorAccessMiddleware.process_view`, outside resticus. There a bad id is a 500 even in
    production, and an unknown id gets Django's HTML 404 page instead of JSON.

  Answering 404 for every failed lookup also leaks less. Today the 400 tells a caller the id
  format and lets them tell "malformed" apart from "doesn't exist".
- **Smoke date index.** Apart from its primary key, `Smoke` has only the GiST index on
  `geometry`. Every stored outline
  touches the valley, so the geometry filter keeps nearly every row and the date filter does
  the narrowing. Affected: `hms/smoke/place/` (#312), `hms/smoke/`, and coverage. Measured
  2026-11-05: 0.14 s for a year over Fresno County on sparse local data, 1.4–1.7 s on a
  synthetic heavy season (2,280 outlines over 310 days). Ranges ending today aren't
  server-cached. `Fire` already has the index (`hms/0002_date_index`).
- **Weather totals display.** In `meta/datasets/`, `precipitation`, `eto` and `etr` are totals
  in inches. They should draw as bars from zero with hundredths. Today they fall through to the
  `meteorological` default, `(1, 'line', None)`. Requested by data-dashboard spec 3b and
  approved by the user on 2026-11-06.

## Audit: what is looked up from a URL id

`SmallUUIDField` ids exist on models in alerts, archive, calibrations, accounts, qaqc,
monitors, monitors/airgradient, hms and summaries. Only three are resolved from a URL id:

- `Monitor`: every `<monitor_id>` route in v1 and v2. This covers detail, entries, entry
  export and CSV, summaries, alerts and archive. All of them, `MonitorDetail` included, get
  the monitor from `MonitorAccessMiddleware`'s lazy proxy.
- `Smoke` and `Fire`: `hms/smoke/<smoke_id>/`, `hms/fire/<fire_id>/` (`lookup_field = 'id'`).

Sqid and code lookups (regions, pesticides, forecasts, emissions) already answer 404.

## Part 1: sjvair.com PR (into `develop`)

Branch `fix/ids-smoke-index` from `origin/develop`, worktree `.worktrees/fix-ids-smoke-index`.

### 1a. Monitor ids: 404 in the middleware

- One shared helper reports whether a value parses as a small UUID. It must accept exactly
  what `SmallUUIDField.to_python` accepts, including the 30+ character hex form. Use the
  field's own `to_python`, not a regex: some 22-character strings that aren't canonical ids
  still parse, e.g. `'a'*22`. Where it lives is left to the builder; `camp/utils/` is
  the obvious home.
- Today every monitor route resolves its monitor through the middleware's lazy proxy. Both
  v1/v2 `MonitorMixin.get_object` return `request.monitor`. `_get_monitor` uses Django's
  `get_object_or_404`, which resticus's `dispatch` turns into `http.Http404()` with no reason:
  `{"errors": {"detail": [{"message": null}]}}`.
- **The user's decision (2026-11-06): one 404 body for every failed monitor lookup**, the same
  one Smoke and Fire send: `{"errors": {"detail": [{"message": "Resource not found"}]}}`.
  - `_get_monitor` raises resticus `exceptions.NotFound(_('Resource not found'))`. It does
    this both when the id doesn't parse (the shared helper) and when no monitor has it. It
    no longer uses `get_object_or_404`. `dispatch` turns `NotFound` into its 404 response.
  - Write path: `process_view` reads `request.monitor.access_key` outside resticus, so it
    catches `NotFound` and returns `err.response`. That stops today's 500 (bad id) and the
    HTML 404 (unknown id).
  - **Builder's call:** whether a bad id also short-circuits in `process_view` before the
    proxy is built. Either way, the body has to be the same.
- This covers every `<monitor_id>` route in v1 and v2 (all are under `/api/`, and the
  middleware is in `MIDDLEWARE` with `process_view`), so no endpoint changes.
- Tests (TestCase, pytest-style asserts):
  - A bad id (`nonexistent`, `abc%21`, a region sqid) and a well-formed unknown id get the
    identical 404 body on these routes: `monitors/<id>/`, `monitors/<id>/entries/pm25/`,
    `monitors/<id>/summaries/pm25/daily/2026/`, and one v1 route.
  - Run them with DEBUG off and on (`override_settings`). Compare `errors` only, because
    under DEBUG a 404 raised in a view carries `meta.traceback`.
  - A POST with an access key and a bad id, then with an unknown id: JSON 404, not a 500 or
    HTML.
  - A valid id still answers 200.

### 1b. Smoke and Fire

There is no sjvair.com code change. resticus fixes these (Part 2). The sjvair.com tests for
Smoke and Fire 404s are a follow-up, after the resticus fix merges upstream and the image is
rebuilt (see "Later").

### 2. Smoke date index

- `Smoke.Meta.indexes = [models.Index(fields=['date'])]` and migration
  `hms/0003_smoke_date_index` (an `AddIndex`, written like `0002`).
- **Measure before and after** on the same synthetic data, using temporary tables only and no
  writes to real tables. Start from the #312 review scripts (`bench*.sql` in the old session's
  scratchpad, `/tmp/claude-1000/-home-alex-workspace-sjvair-sjvair-com/00448dfa-e3f2-4600-82f0-93cad7f0e32c/scratchpad/`;
  copy them into this session's scratchpad). The temp table needs the same index added to
  measure "after" (`CREATE INDEX` on the temp table). **My call:** besides the 2,280-outline
  season, also measure a multi-season table (e.g. five seasons, about 11k outlines) queried
  for one year. At 2,280 rows the planner may scan sequentially anyway, and most of the
  1.4–1.7 s is geometry work, so the index should show its gain as the table grows. Report
  the numbers honestly in the PR, including a gain of zero at today's size.
- Run `EXPLAIN ANALYZE` on the `hms/smoke/place/` query and on a `hms/smoke/?date__gte=` list
  query to show whether the index is used.
- Production: the migration runs at deploy. The table is small, so it should be quick. Say so
  in the PR and send it to the coordinator for `DEFERRED.md`'s deploy entry. The local shared
  database gets the migration only after asking the coordinator; undo is `migrate hms 0002`.
  The branch's own test database needs no approval.

### 3. Weather display hints

- `camp/api/v2/meta/catalog.py` `DISPLAY_OVERRIDES`: add `'precipitation': (2, 'bar', 0)`,
  `'eto': (2, 'bar', 0)`, `'etr': (2, 'bar', 0)`.
- Test: `meta/datasets/` shows `display == {"precision": 2, "chart": "bar", "y_min": 0}` for
  those three in the weather dataset. Other meteorological types keep `(1, 'line', None)`.
- Other consumers: only map-sdk reads a display hint, and only `display.precision`
  (`src/lib/data/metadata.ts`, `precisionOf`), so these three show two decimals there too,
  which is intended. Nothing in monitor-map, mobile or web-widget reads `chart` or `y_min`.

### Docs and the register

- data-dashboard `DEFERRED.md` (docs worktree, pushed straight to `main`, same change as the
  PR): remove "A date index on HMS `Smoke`". Narrow "a malformed id on detail endpoints gives
  500" to what's left: Smoke and Fire wait on the resticus PR (number) and an image rebuild.
- sjvair.com `CLAUDE.md`: no change expected.

## Part 2: django-resticus PR

From the user's fork (`alexandermccormick/django-resticus`) to `dmpayton/django-resticus`
`develop`. The branch starts from `develop` on its own, not stacked on the draft PRs #25 and
#26, so it can merge without them. It lives in a new worktree under
`/home/alex/workspace/django-resticus/.worktrees/`. It doesn't touch the local stack's mount
(`docker-compose.override.yml` stays on `session-csrf`). Testing is resticus's own suite.
Three commits, so the owner can take them one at a time:

1. **Lookup: a value that can't be parsed is not found.** `generics.get_object` catches
   `ValueError`, `TypeError` and `django.core.exceptions.ValidationError` from
   `queryset.get(**lookup)` the same way it catches `DoesNotExist`, and raises
   `exceptions.NotFound`. Django REST Framework's `get_object_or_404` does the same. Tests:
   with a typed key in the test app (an integer pk given `abc`, plus a UUID field if the test
   app has or can easily get one), a bad value answers 404.
2. **DEBUG crash on lazy messages.** `JSONErrorResponse.__init__` treats lazy strings
   (`django.utils.functional.Promise`) as strings, so they get wrapped in the `errors` shape
   and `data["meta"]` works. Test: an endpoint returning `Http400(gettext_lazy("…"))` under
   DEBUG answers 400 with `errors.detail[0].message` and `meta.traceback`.
3. **The `ValidationError` 400 body.** `dispatch`'s `except ValidationError` builds
   `{"errors": {"detail": [{"message": m}, …]}}` from `err.messages`, so the params are
   filled in and every message is kept. No `code` key: other resticus error bodies carry only
   `message`, and a Django code like `'invalid'` would collide with sdk-js's documents
   refusal codes (see the client check). **Builder's call:** for a `ValidationError` with
   `message_dict`, key the messages by field (like `form.errors.get_json_data()`, which
   resticus's own `exceptions.ValidationError` uses), with `detail` for non-field messages.
   Tests: a single message with params, a list, and a dict.

Client check for commit 3 (requested by the coordinator). Only a Django `ValidationError`
that reaches `dispatch` is affected. Every other resticus error is already
`{"errors": {"detail": [...]}}`, so the new body matches a shape clients already handle:
- sdk-js `genericAPIErrorHandler` copies `body.errors` into `cause.details`
  (`lib/http/error.ts:46`, on both `release/5.0.0` and `main`). With today's bare-string body
  `details` is `undefined`.
- sdk-js documents refusal codes (`lib/documents/refusal.ts`, `toDocumentRefusal`, on
  `release/5.0.0`) take `errors.detail[0].code` when it's a string, and otherwise
  `fallbackCode(status)`: 401 `unauthorized`, 403 `forbidden`, 404 `not_found`, anything else
  `unknown`. None of the changes here can change a documents refusal code:
  - The documents endpoints (`camp/api/v2/documents/`) are plain `Endpoint`s that return their
    own `refuse(code, …)` bodies. Their ids are `CharField`s (no parse failure), and they use
    no `generics.get_object`, Django `ValidationError` or `Http404`, and no `monitor_id`.
    Commits 1–3 and the monitor 404 change don't reach them.
  - Even if they did, the new bodies carry no `code`, so the code would still come from the
    status. The uniform monitor 404 maps to `not_found`, exactly as today's null-message 404
    does.
- mobile `extractFieldErrors` (`src/lib/utils/form-errors.ts`) maps `details` per field. For a
  `detail`-only body it returns `{detail: …}`, so a screen that reads only named fields (e.g.
  account `Management.svelte`) shows no toast. That's already true today for every other
  resticus 400, so it's not new with this change; note it in the PR as existing behavior.
- data-dashboard and monitor-map don't read 400 bodies.

The PR description is detailed. It covers the history (the lookup catch dates from 2015; the
view-level `ValidationError` → 400 catch came in 1c95246, 2019, as a general catch-all), the
id-leak argument, before and after responses for DEBUG on and off, the client check, and the
tests. When it merges, tell the coordinator: sjvair.com installs resticus `develop` unpinned,
so it reaches sjvair.com's next build.

## Order

Spec, then plan, then the sjvair.com PR, then the resticus PR. Neither PR merges without the
user's yes.

## Later (not in these PRs)

After the resticus merge and an image rebuild: sjvair.com tests that `hms/smoke/<bad>/` and
`hms/fire/<bad>/` answer 404, and the malformed-id entry leaves `DEFERRED.md`.

## Non-goals

- No path converters or URL regexes for ids: a converter miss answers Django's HTML 404, not
  JSON.
- No changes to other `SmallUUIDField` models; none is looked up from a URL id.
- No sjvair.com workaround for Smoke and Fire while resticus is pending.
- Nothing touches production.
