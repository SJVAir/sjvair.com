# Bad ids 404, Smoke date index, weather display hints: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every failed monitor/Smoke/Fire id lookup answers one JSON 404, `Smoke` gets a date
index, and the precipitation/ETo/ETr display hints become 2-decimal bars from zero.

**Architecture:** Part 1 is the sjvair.com PR. The monitor middleware's lazy lookup raises
resticus `NotFound` for bad and unknown ids alike. It also adds migration `hms/0003` and three
`DISPLAY_OVERRIDES` rows. Part 2 is a separate django-resticus PR with three commits:
`get_object` treats unparseable lookups as not found; lazy messages no longer crash the error
response in DEBUG; and the `ValidationError` 400 body is filled in and wrapped.

**Tech Stack:** Django 5.2, PostGIS, django-resticus, django-smalluuid 1.2.1, pytest-django.

**Spec:** `docs/superpowers/specs/2026-11-06-bad-ids-smoke-index-design.md`

## Global Constraints

- Uniform 404 body: `{"errors": {"detail": [{"message": "Resource not found"}]}}`. A bad id
  and an unknown id on the same route must give identical `errors`.
- Under DEBUG, compare `errors` only; `meta.traceback` may differ.
- The resticus 400 body has no `code` key; each detail item is only `{"message": …}`.
- Tests: `django.test.TestCase`, pytest-style `assert`.
- No Claude/AI attribution anywhere. Never merge without the user's yes.
- Nothing touches production. Applying `hms/0003` to the shared DB, or swapping the shared web
  container or the resticus mount, needs the coordinator (`data-dashboard-23`) first. Undo is
  `migrate hms 0002`.
- sjvair.com tests run on their own database, `sjvair_fixids`. From the worktree:
  ```bash
  source <(grep '^DATABASE_URL=' /home/alex/workspace/sjvair/sjvair.com/.env.test)
  podman run --rm --network sjvaircom_sjvair-net --env-file /home/alex/workspace/sjvair/sjvair.com/.env.test \
    -e DATABASE_URL="${DATABASE_URL%/*}/sjvair_fixids" -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token \
    -v "$PWD":/app:z -w /app localhost/sjvair-com-test:latest pytest <args> 2>&1 | tee <scratchpad>/<name>.log
  ```
  ("fatal: not a git repository" is harmless.) Below, `RUN <args>` means this command.
  `<scratchpad>` is `/tmp/claude-1000/-home-alex-workspace-sjvair-sjvair-com/77fff993-760d-4665-9cc1-06191288ca40/scratchpad`.
  Keep full logs; filter after with `grep`.
- resticus tests: host `python3 -m pytest tests/` from the resticus worktree (sqlite,
  `tests.settings`).

## Review Focus

1. **Write with an access key and a bad id:** a JSON 404, not a 500. Today the
   `ValidationError` escapes `process_view`. Tested in Task 1 (`test_write_with_bad_id_is_json_404`).
2. **Write with an access key and an unknown well-formed id:** a JSON 404, not Django's HTML
   page. Tested in Task 1 (`test_write_with_unknown_id_is_json_404`).
3. **A 22-character non-canonical string that parses (`'a'*22`):** it must behave like an
   unknown id (404, same body), not error. Tested in Task 1 (`test_parseable_noncanonical_id_is_not_found`).
4. **The monitor cache:** a failed lookup must not be cached, and a valid id still caches and
   answers 200. Tested in Task 1 (`test_valid_id_still_200_and_cached`, existing cache tests
   in `camp/api/tests.py` stay green).
5. **A long hex-form id (> 30 chars, invalid hex):** 404, not a 500 from `UUID(hex=…)`. Tested
   in Task 1 (bad-id list includes `'z'*32`).

---

## Part 1: sjvair.com (worktree `.worktrees/fix-ids-smoke-index`, branch `fix/ids-smoke-index`)

### Task 0: Baseline

- [ ] **Step 1:** `RUN -n 4 --dist loadscope` on the branch before any change (it is develop
  plus the spec commits), logged to `<scratchpad>/baseline.log`.
  Expected: record the pass/fail/skip counts; any failures are pre-existing and noted.

### Task 1: Uniform monitor 404 in the middleware

**Files:**
- Create: `camp/utils/ids.py`
- Modify: `camp/api/middleware.py` (`MonitorAccessMiddleware.process_view`, `_get_monitor`)
- Test: `camp/api/tests.py` (new class `MonitorNotFoundTests`), `camp/utils/tests/` or
  `camp/api/tests.py` for the helper (builder's call)

**Interfaces:**
- Produces: `is_small_uuid(value: str) -> bool` in `camp/utils/ids.py`. It returns True iff
  `Monitor._meta.pk.to_python(value)` (any `SmallUUIDField`; use a module-level
  `SmallUUIDField()` instance) raises neither `ValidationError` nor `ValueError`/`TypeError`.
- Produces: `NOT_FOUND = _('Resource not found')`, used for `exceptions.NotFound(NOT_FOUND)`.

- [ ] **Step 1: Write the failing tests** in `MonitorNotFoundTests` (fixtures
  `['purple-air.yaml']`, Django test `Client`, real URLs so the middleware runs):

```python
BAD_IDS = ['nonexistent', 'abc!', 'z' * 32]           # plus a region sqid string, e.g. 'jR'
UNKNOWN_ID = 'AAAAAAAAAAAAAAAAAAAAAA'
NOT_FOUND = {'detail': [{'message': 'Resource not found'}]}
ROUTES = ['/api/2.0/monitors/{}/', '/api/2.0/monitors/{}/entries/pm25/',
          '/api/2.0/monitors/{}/summaries/pm25/daily/2026/', '/api/1.0/monitors/{}/']

def test_bad_and_unknown_ids_share_one_404(self):           # DEBUG off
    for route in ROUTES:
        for id in BAD_IDS + [UNKNOWN_ID]:
            r = self.client.get(route.format(quote(id, safe='')))
            assert r.status_code == 404, (route, id)
            assert r.json()['errors'] == NOT_FOUND, (route, id)

@override_settings(DEBUG=True)
def test_bad_and_unknown_ids_share_one_404_debug(self): ...  # same loop

def test_parseable_noncanonical_id_is_not_found(self):      # 'a' * 22, all ROUTES → 404, NOT_FOUND

def test_write_with_bad_id_is_json_404(self):
    r = self.client.post('/api/2.0/monitors/nonexistent/entries/', {}, HTTP_ACCESS_KEY=str(uuid4()))
    assert r.status_code == 404 and r.json()['errors'] == NOT_FOUND

def test_write_with_unknown_id_is_json_404(self):           # UNKNOWN_ID, same asserts

def test_valid_id_still_200_and_cached(self):
    # GET /api/2.0/monitors/<fixture id>/ → 200; cache.get(f'monitor:{id}') is the monitor;
    # after a 404 for UNKNOWN_ID, cache.get(f'monitor:{UNKNOWN_ID}') is None
```

  Also unit tests for `is_small_uuid`: a real monitor id → True, `'a'*22` → True, each of
  `BAD_IDS` → False, `''` → False.
  Check the URL names/paths against `camp/api/v{1,2}/monitors/urls.py`; adjust if the CSRF
  enforcement in the test image blocks the POSTs (use `Client(enforce_csrf_checks=False)`).

- [ ] **Step 2:** `RUN camp/api/tests.py -v` and expect the new tests to fail. Today a bad id
  gives 400/500, an unknown id gives `message: null`, and a write gives a 500 or an HTML 404.

- [ ] **Step 3: Implement.**
  - `camp/utils/ids.py`: `is_small_uuid` as above.
  - `_get_monitor`: raise `exceptions.NotFound(NOT_FOUND)` when `not is_small_uuid(monitor_id)`,
    or when no monitor has that pk. Look it up through the same manager `get_object_or_404(Monitor, …)`
    used (`Monitor._default_manager`), so the class it returns doesn't change. Cache only found
    monitors. Drop the `get_object_or_404` import.
  - `process_view` write path: wrap the `request.monitor.access_key` read in
    `try/except exceptions.NotFound as err: return err.response`. An early bad-id return
    before the proxy is the builder's call; the body must be the same either way.

- [ ] **Step 4:** `RUN camp/api/tests.py camp/api/v2/monitors camp/api/v1/monitors -v`;
  everything passes, the existing `MonitorAccessMiddlewareTests` included.

- [ ] **Step 5: Commit** `Monitor routes: one JSON 404 for bad and unknown ids`.

### Task 2: Smoke date index

**Files:**
- Modify: `camp/apps/hms/models.py` (`Smoke.Meta`)
- Create: `camp/apps/hms/migrations/0003_smoke_date_index.py` (generated)
- Bench (not committed): `<scratchpad>/bench-index.sql`

- [ ] **Step 1: Measure before.** Copy the #312 scripts from
  `/tmp/claude-1000/-home-alex-workspace-sjvair-sjvair-com/00448dfa-e3f2-4600-82f0-93cad7f0e32c/scratchpad/bench*.sql`
  into `<scratchpad>`. Write `bench-index.sql`, which uses temp tables only:
  - `fake` (2,280 outlines, as `bench3.sql`) and `fake5` (five seasons, about 11k outlines).
  - Each runs twice: the "NEW county" `hms/smoke/place/` query for one year, and a list query
    `SELECT … FROM fake WHERE date BETWEEN … ORDER BY date DESC, id LIMIT 100`.
  - Each gets an `EXPLAIN (ANALYZE, BUFFERS)` and a `\timing` run. Then
    `CREATE INDEX ON fake (date); ANALYZE fake;` and repeat for "after".
  Run it read-only against the shared DB through `psql` in the db container (temp tables are
  allowed; never write to real tables). Save the output to `<scratchpad>/bench-index.out`.
  Expected: timings and plans for before and after on both tables.
- [ ] **Step 2:** Add `indexes = [models.Index(fields=['date'])]` to `Smoke.Meta`. Generate the
  migration with `RUN python manage.py makemigrations hms --name smoke_date_index` (against
  `sjvair_fixids`, not the shared DB). Check it is a single `AddIndex` that depends on
  `0002_date_index`.
- [ ] **Step 3:** `RUN camp/apps/hms camp/api/v2/hms -v` passes, and
  `RUN python manage.py makemigrations --check --dry-run` reports no changes.
- [ ] **Step 4: Commit** `HMS: date index on Smoke`. Put the bench numbers, including a gain
  of zero if that's what they show, in the PR description, not the commit.

### Task 3: Weather display hints

**Files:**
- Modify: `camp/api/v2/meta/catalog.py` (`DISPLAY_OVERRIDES`)
- Test: `camp/api/v2/meta/tests/test_catalog.py` (`test_display_values`)

- [ ] **Step 1:** Add to `test_display_values`:

```python
for id in ('precipitation', 'eto', 'etr'):
    assert self.entry('weather', id)['display'] == {'precision': 2, 'chart': 'bar', 'y_min': 0}
assert self.entry('weather', 'humidity')['display'] == {'precision': 1, 'chart': 'line', 'y_min': None}
```

- [ ] **Step 2:** `RUN camp/api/v2/meta -v` fails on precipitation.
- [ ] **Step 3:** Add `'precipitation': (2, 'bar', 0)`, `'eto': (2, 'bar', 0)` and
  `'etr': (2, 'bar', 0)` to `DISPLAY_OVERRIDES`.
- [ ] **Step 4:** `RUN camp/api/v2/meta -v` passes.
- [ ] **Step 5: Commit** `Catalog: precipitation, ETo and ETr chart as 2-decimal bars from zero`.

### Task 4: Full suite, PR, register

- [ ] **Step 1:** `RUN -n 4 --dist loadscope` gives the baseline counts plus the new tests,
  with no new failures. Log to `<scratchpad>/final.log`.
- [ ] **Step 2:** Push the branch and open a PR into `develop`. The body covers: what changed
  and why (link the spec); the bench table; **"Deploy: migration `hms/0003_smoke_date_index`
  runs at deploy (an `AddIndex` on a small table, expected quick)"**; that Smoke and Fire bad
  ids wait on the resticus PR; and the client notes (404 status unchanged, only the monitor
  404 message goes from `null` to `"Resource not found"`). End with no attribution.
- [ ] **Step 3:** Tell the coordinator the PR number and the production step
  (`migrate` applies `hms/0003` at deploy; undo `migrate hms 0002`).
- [ ] **Step 4:** data-dashboard `DEFERRED.md`, in a docs worktree off `origin/main`, pushed
  straight to `main`: remove "A date index on HMS `Smoke`". Narrow the malformed-id entry to
  "monitors fixed in sjvair.com #N; Smoke and Fire wait on resticus #M plus an image rebuild,
  then add sjvair.com tests". Fill in #M after Part 2 opens. Tell the coordinator first, since
  it owns the cross-track docs; if it wants to make the edit itself, send the text instead.

## Part 2: django-resticus (new worktree `/home/alex/workspace/django-resticus/.worktrees/lookup-not-found`, branch `fix/lookup-not-found` from `origin/develop`)

### Task 5: `get_object` treats unparseable lookups as not found

**Files:**
- Modify: `resticus/generics.py` (`get_object`, lines ~70-73)
- Modify: `tests/testapp/urls.py` (add `path('publishers/by-str/<pk>', PublisherDetail.as_view(), name='publisher_detail_str')`;
  the existing routes use `<int:…>` converters, so a bad value never reaches `get_object`)
- Test: `tests/test_generics.py`

- [ ] **Step 1:** Write the failing tests:
  - `test_detail_unparseable_pk_is_404`: GET `publisher_detail_str` with `pk='abc'` gives 404,
    and `r.json['errors']['detail'][0]['message'] == 'Resource not found'`.
  - `test_detail_validation_error_is_404`: patch the queryset's `get` (`mock.patch.object`
    on `QuerySet.get`) to raise `django.core.exceptions.ValidationError('bad')`; the same
    route gives 404.
  - The existing `publisher_detail` 404 for a missing pk is unchanged.
- [ ] **Step 2:** `python3 -m pytest tests/test_generics.py -v` fails: 400/500.
- [ ] **Step 3:** In `get_object`, catch `(self.model.DoesNotExist, ValueError, TypeError, ValidationError)`
  and raise `exceptions.NotFound(_("Resource not found"))`. Import `ValidationError` from
  `django.core.exceptions`.
- [ ] **Step 4:** `python3 -m pytest tests/ -v` passes.
- [ ] **Step 5: Commit** `Lookup: an id that can't be parsed is not found`.

### Task 6: Lazy messages don't crash the error response

**Files:**
- Modify: `resticus/http.py` (`JSONErrorResponse.__init__`)
- Test: `tests/test_endpoint.py`

- [ ] **Step 1:** Write a failing test. Under `override_settings(DEBUG=True)`, call
  `http.Http400(gettext_lazy('Lazy reason'))` inside an `except` block (so `sys.exc_info()` is
  set). It gives status 400, `json.loads(r.content)['errors']['detail'][0]['message'] == 'Lazy reason'`,
  and `'traceback' in …['meta']`. Add the same check with DEBUG off (no `meta`).
- [ ] **Step 2:** `python3 -m pytest tests/test_endpoint.py -v` fails with `TypeError`.
- [ ] **Step 3:** Treat `django.utils.functional.Promise` as a string: `isinstance(data, (str, Promise))`.
  Wrap with `str(data)` so the encoder sees a plain string.
- [ ] **Step 4:** `python3 -m pytest tests/ -v` passes.
- [ ] **Step 5: Commit** `Error responses: treat lazy strings as strings`.

### Task 7: `ValidationError` 400 body

**Files:**
- Modify: `resticus/views.py` (`dispatch`, the `except ValidationError` branch)
- Modify: `tests/testapp/views.py`, `tests/testapp/urls.py` (one `RaisesValidationError`
  endpoint that raises the error given by a `?kind=` param: `single`, `list`, `dict`)
- Test: `tests/test_endpoint.py`

- [ ] **Step 1:** Write the failing tests, each a 400:
  - `single`: `ValidationError("'%(value)s' is bad.", params={'value': 'x'})` gives
    `errors == {'detail': [{'message': "'x' is bad."}]}`.
  - `list`: `ValidationError(['one', 'two'])` gives `errors == {'detail': [{'message': 'one'}, {'message': 'two'}]}`.
  - `dict`: `ValidationError({'name': ['Required.'], NON_FIELD_ERRORS: ['Clash.']})` gives
    `errors == {'name': [{'message': 'Required.'}], 'detail': [{'message': 'Clash.'}]}`.
  - Each also under DEBUG=True: same `errors`, no crash.
  - No item has a `code` key.
- [ ] **Step 2:** `python3 -m pytest tests/test_endpoint.py -v` fails: bare string, or a crash
  under DEBUG.
- [ ] **Step 3:** Build `data` with `hasattr(err, 'error_dict')`: per field, from
  `err.message_dict`, with `NON_FIELD_ERRORS` mapped to `detail`. Otherwise `{'detail': …}`
  from `err.messages`. Each item is `{'message': str(m)}`. Return `http.Http400(data)`, but
  first wrap it as `{'errors': data}`, because `JSONErrorResponse` only wraps strings.
- [ ] **Step 4:** `python3 -m pytest tests/ -v` passes.
- [ ] **Step 5: Commit** `ValidationError 400: fill in params, keep every message, use the errors shape`.

### Task 8: resticus PR

- [ ] **Step 1:** Push `fix/lookup-not-found` to `origin` (the fork) and open a PR to
  `dmpayton/django-resticus` `develop`. Write a detailed description:
  - The problem, with before and after responses for DEBUG on and off.
  - History: the lookup catch dates from 2015; 1c95246 (2019) added the view-level catch-all.
  - Why a single 404 leaks less, and that Django REST Framework does the same.
  - One section per commit, so the owner can take them separately.
  - The client check from the spec (the `errors` shape is unchanged elsewhere, and there's no
    `code` key).
  - The tests.
  - That it's independent of #25/#26.

  No attribution.
- [ ] **Step 2:** Tell the coordinator the PR number. Fill it into the `DEFERRED.md`
  malformed-id entry. Ask the coordinator to note that sjvair.com picks the change up at its
  next build after the upstream merge.

## Later (not this plan)

After the resticus merge and an image rebuild: sjvair.com tests for `hms/smoke/<bad>/` and
`hms/fire/<bad>/` → 404 `Resource not found`, and the malformed-id entry leaves `DEFERRED.md`.
