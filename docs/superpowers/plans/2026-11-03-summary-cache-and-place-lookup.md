# Summary Cache Headers and Place Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rollups run on Pacific periods. Summary responses carry `Cache-Control`/`ETag`
keyed on whether their periods are settled. `regions/places/lookup/` answers a rounded
point (POST) or a public monitor with its containing regions, and sdk-js wraps both.

**Architecture:** One new module, `camp/apps/summaries/schedule.py`, owns "when does a
rollup run" (a Pacific-hour guard the UTC crontabs call) and "when is a period settled".
The summary endpoints read the settle time from it and set headers in one mixin. The
lookup builds on `camp/apps/regions/resolve.py` and caches serialized answers.

**Tech Stack:** Django 5 / PostGIS, django-resticus, Huey 3.3 (django-huey), Sentry, Scout;
Deno 2 + Zod for sdk-js.

**Spec:** `docs/superpowers/specs/2026-11-03-summary-cache-and-place-lookup-design.md`
(evidence: `docs/superpowers/reports/2026-11-03-summary-rollups.md`).

## Global Constraints

- Settled responses: `Cache-Control: private, max-age=86400`. Others: `private, max-age=60`. Both send an `ETag`. Non-200 responses: `Cache-Control: no-cache`.
- Crontabs stay on UTC; nothing depends on the dyno's `TZ`.
- Seasons are Dec–Feb, Mar–May, Jun–Aug, Sep–Nov.
- Coordinates: 3 decimals, rounded by the server too. They come only in a POST body and never appear in a log, Sentry event, Scout trace or error response.
- Lookup default types: every `Region.Type` except `land_use` and `mtrs`. `land_use` asked for explicitly is a 400.
- The monitor lookup and spec 1's place endpoints answer only for `get_public()` monitors.
- Cache keys are memcached-safe: no spaces, under 250 characters.
- Tests: `django.test.TestCase`, pytest-style `assert`. Run inside the test image (command below).
- No Claude/AI attribution in commits or PRs. No merges into `develop` or `release/4.8.0`, and no sdk-js release, tag or beta, without the user's yes for that one.
- Management commands run scoped (`--region`/`--monitor`, a tight date range), with the blast radius checked first.

**Test command** (from the worktree root; one suite at a time on the shared stack):

```bash
podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 \
  -e TWILIO_AUTH_TOKEN=test-token -v "$PWD":/app:z \
  -v ~/workspace/django-resticus/.worktrees/session-csrf/resticus:/usr/local/lib/python3.14/site-packages/resticus:ro,z \
  -w /app sjvair-com-test:latest pytest <path> -v
```

The worktree needs `.env` and `.env.test` copied from the main checkout first.
Baseline on `develop`: 4096 passed, 4 skipped.

## Review Focus

1. **Fall-back night (first Sunday of November):** 01:xx Pacific happens twice. Each rollup must still run once (Task 1, `test_fall_back_runs_once`).
2. **A bulk request whose `end` is in the future, or today:** not settled, so 60 s (Task 3, `test_bulk_range_ending_today_is_short`).
3. **A revalidation through `GZipMiddleware`:** the gzip middleware turns the ETag into a weak one. A matching `If-None-Match` must still get a 304 (Task 3, `test_if_none_match_returns_304_through_gzip`).
4. **Malformed coordinates** (strings, `NaN`, out of range, missing one): a 400 that doesn't echo the value (Task 4, `test_bad_coordinates_400_without_echo`).
5. **A point on a shared ZIP edge:** both ZIPs come back, not one (Task 4, `test_point_on_shared_edge_returns_both`).

---

### Task 1: Rollups fire on Pacific time

**Files:**
- Create: `camp/apps/summaries/schedule.py`
- Modify: `camp/apps/summaries/tasks.py:307-383` (the 10 daily-through-yearly periodic tasks)
- Test: `camp/apps/summaries/tests.py` (new class `PacificScheduleTests`; update the existing `*_when_called_without_args` tests to patch `now` to 01:xx Pacific)

**Interfaces:**
- Produces: `schedule.is_pacific_hour(hour: int, now: datetime | None = None) -> bool`. True when `now` (default `timezone.now()`) is in `hour` Pacific time **and** `localtime(now).fold == 0`, so a repeated fall-back hour counts once. Also produces `schedule.ROLLUP_UTC_HOURS = {1: '8,9', 2: '9,10'}`: the UTC hours that contain a given Pacific hour in PDT or PST.

- [ ] **Step 1: Write the failing tests** in `PacificScheduleTests`:
  - `test_true_at_0115_pst`: `now = 2026-01-02 09:15 UTC` → `is_pacific_hour(1)` is True.
  - `test_true_at_0115_pdt`: `2026-07-02 08:15 UTC` → True.
  - `test_false_at_other_utc_candidate`: `2026-01-02 08:15 UTC` (00:15 PST) → False. `2026-07-02 09:15 UTC` (02:15 PDT) → False.
  - `test_fall_back_runs_once`: on 2026-11-01, `08:15 UTC` (01:15 PDT, fold 0) → True and `09:15 UTC` (01:15 PST, fold 1) → False.
  - `test_spring_forward`: on 2026-03-08, `09:15 UTC` (01:15 PST) → True.
  - `test_daily_task_skips_outside_pacific_hour`: patch `now` to `2026-01-02 08:00 UTC`, call `daily_monitor_summaries()`, and assert `rollup_monitor_summaries` (patched) was not called. At `09:00 UTC` it is called once, with window Jan 1 → Jan 2 Pacific.
  - `test_seasonal_task_rolls_real_season`: patch `now` to `2026-03-01 09:45 UTC` (01:45 PST, Mar 1), call `seasonal_monitor_summaries()`, and assert the window is Dec 1 2025 → Mar 1 2026 Pacific.
  - `test_monthly_task_rolls_month_just_ended`: `2026-11-01 08:15 UTC` (01:15 PDT, Nov 1, fold 0) → window Oct 1 → Nov 1.
  - `test_explicit_args_bypass_guard`: `daily_monitor_summaries(day=<aware Jan 5>)` at any hour runs.

- [ ] **Step 2: Run them; expect failures** (`ImportError` for `schedule`, wrong windows).

Run: `<test command> camp/apps/summaries/tests.py::PacificScheduleTests`

- [ ] **Step 3: Implement.** Create `schedule.py` with `is_pacific_hour` and `ROLLUP_UTC_HOURS`. In `tasks.py`, change each daily, monthly, quarterly, seasonal and yearly crontab's `hour=` to `ROLLUP_UTC_HOURS[1]` (yearly: `[2]`), keeping `month`, `day` and `minute`. On those days the Pacific 1st is the same UTC date at 08–10 UTC. At the top of each task, return early when it's called with no period argument and `not is_pacific_hour(1)` (yearly: `2`). Replace the "01:00" comment block above the hourly tasks with one that names the guard and why: Huey's `utc=True` default.

- [ ] **Step 4: Run the class plus the whole `camp/apps/summaries/` suite; expect PASS.** Existing `CalendarHelperTests` stay unchanged. They already assert the right windows for a Pacific `now`.

- [ ] **Step 5: Commit** — `git commit -m "Run the summary rollups on Pacific time"`

### Task 2: Settle times

**Files:**
- Modify: `camp/apps/summaries/schedule.py`
- Test: `camp/apps/summaries/tests.py` (new class `SettleTimeTests`)

**Interfaces:**
- Consumes: `BaseSummary.Resolution` values (`hour`, `day`, `month`, `quarter`, `season`, `year`).
- Produces:
  - `schedule.period_end(resolution: str, ts: datetime) -> datetime`: the end of the period containing `ts`, as an aware datetime. For day and coarser it's a Pacific boundary built with `make_aware(datetime(...), DEFAULT_TIMEZONE)`, never `timedelta` arithmetic across DST.
  - `schedule.SETTLE_MARGIN: dict[str, timedelta]` = hour 2h, day 3h, month/quarter/season 4h, year 5h.
  - `schedule.ROLLUP_LOCAL_TIME: dict[str, time]`, the latest scheduled Pacific time of each rollup after its period ends: day 01:10, month 01:25, quarter 01:35, season 01:55, year 02:05, all measured from the period's end. Hour is 50 minutes after the hour ends (the region task at H+1:50).
  - `schedule.is_settled(resolution: str, range_end: datetime | None, now: datetime | None = None) -> bool`. False when `range_end` is None. Otherwise `now >= period_end(resolution, range_end - 1µs) + SETTLE_MARGIN[resolution]`.

- [ ] **Step 1: Write failing tests:**
  - `test_period_end_each_resolution`: for `ts = 2026-10-15 12:00 Pacific`, the period ends are hour 13:00, day Oct 16, month Nov 1, quarter Jan 1 2027, season Dec 1, year Jan 1 2027 (all Pacific).
  - `test_period_end_season_winter_crosses_year`: `2026-01-10` → Mar 1 2026, and `2026-12-10` → Mar 1 2027.
  - `test_month_settles_4h_after_end`: `range_end = Nov 1 00:00 Pacific`. At Nov 1 03:59 it's False; at 04:00 it's True.
  - `test_open_range_never_settled`: `is_settled('year', None)` is False.
  - `test_margin_covers_schedule`: for each resolution, the scheduled rollup time after the period ends (`ROLLUP_LOCAL_TIME`, or 50 min for hour) plus 1 hour is ≤ `SETTLE_MARGIN`. This is the guard against the schedule drifting past the settle time.

- [ ] **Step 2: Run; expect failures.**
- [ ] **Step 3: Implement** the four names above in `schedule.py`.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "Add settle times for summary periods"`

### Task 3: Cache headers on the summary endpoints

**Files:**
- Modify: `camp/api/v2/summaries/endpoints.py` (`SummaryMixin`)
- Test: `camp/api/v2/summaries/tests.py` (new class `SummaryCacheHeaderTests`)

**Interfaces:**
- Consumes: `schedule.is_settled` (Task 2). The range end is `self.get_date_filter().get('timestamp__lt')`, which already covers both the path endpoints and the bulk ones (`end_exclusive`).
- Produces: `SummaryMixin.dispatch(request, *args, **kwargs)`, wrapping `super().dispatch`. It sets the headers, sets the ETag with `django.utils.cache.set_response_etag` when there isn't one, and returns `get_conditional_response(request, etag=response['ETag'], response=response)` so a match becomes a 304.

- [ ] **Step 1: Write failing tests** (freeze `now` with `patch('django.utils.timezone.now')`; use the module's existing fixtures and helpers for a monitor, a region and rows):
  - `test_settled_month_path_is_long`: `GET monitors/<id>/summaries/pm25/daily/2026/9/` at Oct 5 → `Cache-Control` has `private` and `max-age=86400`, plus an `ETag`.
  - `test_current_month_path_is_short`: same URL for October, at Oct 5 → `max-age=60`.
  - `test_day_inside_margin_is_short`: the `daily/2026/9/` path at Oct 1 02:00 Pacific → `max-age=60`.
  - `test_yearly_without_year_is_short`: `…/yearly/` → `max-age=60`.
  - `test_bulk_range_ending_today_is_short`: bulk daily with `end=` today → 60. With `end=` a month ago → 86400.
  - `test_region_path_and_bulk_get_headers`: the same two cases for the region path and region bulk endpoints.
  - `test_if_none_match_returns_304_through_gzip`: request with `HTTP_ACCEPT_ENCODING='gzip'`, then repeat with `HTTP_IF_NONE_MATCH=<that ETag>` → 304 with no body.
  - `test_errors_are_no_cache`: an unknown entry type (404) and a bulk call missing `start` (400) → `Cache-Control: no-cache` and no `max-age`.
  - `test_page_two_gets_same_rule`: `?page=2` of a settled bulk response → 86400.
- [ ] **Step 2: Run; expect failures.**
- [ ] **Step 3: Implement `SummaryMixin.dispatch`** with `patch_cache_control(response, private=True, max_age=…)` for 200s and `no_cache=True` otherwise. A body-hash ETag (Django's) is the agreed choice.
- [ ] **Step 4: Run the class and the whole `camp/api/v2/summaries/` suite; expect PASS.** Then curl one settled and one unsettled URL on the local stack and note the `Vary` header in the PR (Cookie/Origin).
- [ ] **Step 5: Commit** — `git commit -m "Send cache headers on summary responses"`

### Task 4: Lookup by point or monitor

**Files:**
- Modify: `camp/apps/regions/resolve.py` (new `regions_containing`, plus `resolve_place` limited to public monitors)
- Modify: `camp/api/v2/regions/endpoints.py` (`PlaceLookup`: a `post` method, monitor mode in `get`, new `PointLookupForm`)
- Test: `camp/api/v2/regions/tests.py` (new class `PlaceLookupPointTests`), plus the spec 1 place-endpoint tests for hidden monitors (`camp/api/v2/calheatscore/tests.py`, `camp/api/v2/forecasts/tests.py`; find them with `grep -rln "place/" camp/api/v2/*/tests.py`)

**Interfaces:**
- Produces:
  - `resolve.DEFAULT_LOOKUP_TYPES: tuple[str, ...]`: every `Region.Type` value except `land_use` and `mtrs`.
  - `resolve.parse_lookup_types(raw: str) -> tuple[str, ...]`: splits on commas, strips, sorts and de-duplicates. An empty value gives the defaults. An unknown type raises `PlaceError('Unknown region type: <t>.')`, and `land_use` raises `PlaceError("Land-use regions can't be looked up.")`.
  - `resolve.round_point(lat: float, lon: float) -> tuple[float, float]`: rounds to 3 decimals.
  - `resolve.regions_containing(geometry: Point, types: tuple[str, ...], key: str) -> list[dict]`: current regions whose boundary intersects `geometry`, filtered by type **in the same query**, ordered by `type`, `external_id`, and serialized with `RegionListSerializer`. The list of dicts is cached for `CACHE_TIMEOUT` under `key`. Dicts, not models, because the serializer reads `boundary.geometry.extent`.
  - Point key: `f'regions_containing:point:{lat:.3f}:{lon:.3f}:{",".join(types)}'`. Monitor key: `_place_key('regions_containing', monitor) + ':' + ",".join(types)`.
  - `resolve_place` looks monitors up in `Monitor.objects.get_queryset().get_public()`. A hidden monitor raises the same `PlaceNotFound` as an unknown one.
  - HTTP:
    - `POST regions/places/lookup/` with JSON `{lat, lon, type?}` → `{"data": [...]}`.
    - `GET ?monitor=&type=` → the same shape.
    - `GET ?q=` unchanged.
    - `q` with `monitor`, or `lat`/`lon` in a GET query, → 400 (`'Send coordinates in a POST body.'`).
    - A POST with `q` → 400.
- [ ] **Step 1: Write failing tests** (build small square ZIP, city and county boundaries in `setUp`, with two ZIPs sharing an edge):
  - `test_point_returns_containing_regions_sorted`
  - `test_point_rounded_before_lookup`: `36.73749` and `36.7371` give the same cache key and the same answer.
  - `test_type_list_filters` and `test_default_excludes_land_use_and_mtrs` (create one of each that contains the point).
  - `test_explicit_land_use_400`, `test_unknown_type_400`, `test_mtrs_allowed_when_asked`.
  - `test_point_outside_everything_empty_list`.
  - `test_point_on_shared_edge_returns_both`.
  - `test_retired_region_excluded`.
  - `test_bad_coordinates_400_without_echo`: `"abc"`, `NaN`, `lat=91`, `lon=-181`, and a missing `lon`. Each gives a 400 whose body doesn't contain the sent value.
  - `test_coordinates_in_query_string_400`.
  - `test_monitor_mode` (public → its regions); `test_hidden_monitor_404`; `test_monitor_without_position_400`.
  - `test_name_mode_unchanged` (`?q=` still returns one region or `null`).
  - `test_anonymous_post_without_csrf_token_200` (use `Client(enforce_csrf_checks=True)`); `test_signed_in_post_without_csrf_token_403`.
  - `test_warm_lookup_no_queries` (`assertNumQueries(0)` on the second identical POST).
  - Hidden-monitor tests on `calheatscore/place/?monitor=` and `forecasts/place/?monitor=` → 404.
- [ ] **Step 2: Run; expect failures.**
- [ ] **Step 3: Implement** the resolver functions and the endpoint. `PointLookupForm` has `lat = FloatField(min_value=-90, max_value=90)` and `lon = FloatField(min_value=-180, max_value=180)`, rejects non-finite values, and has an optional `type`. Override the error messages so none of them include the input. Wrap `post` with `method_decorator(sensitive_post_parameters('lat', 'lon'))`.
- [ ] **Step 4: Run `camp/api/v2/regions/` and the two place suites; expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "Look up a place's regions by point or monitor"`

### Task 5: Keep coordinates out of Sentry, Scout and logs

**Files:**
- Create: `camp/utils/sentry.py` (`scrub_event`)
- Modify: `camp/apps/documents/sentry.py` (keep `is_documents_event` and `stacktraces`; `scrub_documents` stays importable for its tests), `camp/settings/base.py:548-554` (`before_send=scrub_event`) and `:578-590` (`SCOUT_URI_REPORTING = 'path'`)
- Test: `camp/utils/tests/test_sentry.py` (or next to the existing documents scrubber tests; find them with `grep -rln scrub_documents camp`)

**Interfaces:**
- Produces: `camp.utils.sentry.scrub_event(event, hint=None) -> dict`. For documents paths it does what `scrub_documents` does today. For `/api/2.0/regions/places/lookup/` it drops `request.data`, `request.query_string` and every frame's `vars`. Every other event comes back unchanged. No Django imports, because settings load it.
- [ ] **Step 1: Write failing tests:** `test_lookup_event_drops_body_query_and_vars`, `test_documents_event_still_scrubbed`, `test_other_event_untouched`.
- [ ] **Step 2: Run; expect failures.**
- [ ] **Step 3: Implement**, and point settings at `scrub_event`. Set `SCOUT_URI_REPORTING = 'path'`, so Scout never records query strings. That costs query params in every trace; note it in the PR. Grep `LOGGING` and `camp/` for anything that logs `request.body` or `request.data`, and record "none found" or the fix in the PR.
- [ ] **Step 4: Run the new tests and the documents suite; expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "Scrub lookup coordinates from Sentry and Scout"`

### Task 6: Verify on real data, document, open the sjvair.com PR

**Files:**
- Modify: `CLAUDE.md` → "Metadata Endpoints": add the lookup modes, the summary cache rule and `schedule.py`. Also note the rollup timing under the summaries section (create a short one if none exists).

- [ ] **Step 1: Performance.** Run `EXPLAIN ANALYZE` for the Task 4 query through `podman exec sjvaircom_web_1 python manage.py shell`. Use three points: central Fresno (36.737, -119.787), a rural point (36.3, -120.3) and one outside the valley (34.05, -118.25). Run each with the default types and with `type=zipcode`. Expect a GiST index scan on the boundary geometry and the type filter in the same plan. Record cold and warm timings. Also time one settled bulk summary request with and without `If-None-Match`.
- [ ] **Step 2: Hand check on the stack.** Message `map-sdk-e7` and `data-dashboard-26` before swapping the web container to this worktree (recipe: the brief's "Serving a worktree"). Then:
  - curl a settled and an unsettled summary URL and check the headers, then a 304;
  - POST a lookup anonymously;
  - send a lookup with `lat` in the query string → 400;
  - restart the summaries worker and confirm it registers the new crontabs (`hour='8,9'`).

  Restore the stack and message both sessions again.
- [ ] **Step 3: Full suite.** Run `<test command> -n 4 --dist loadscope`. Expect the baseline plus the new tests, with no failures. Tee the output to a log (`| tee …/scratchpad/full-suite.log`).
- [ ] **Step 4: Push and open the PR into `develop`.** The description needs:
  - **Deploy notes, catch-up section:** after the deploy, roll up the periods the late schedule hasn't reached. Today that's October 2026 monthly and Q3 2026 quarterly; recompute from the deploy date. Show the exact `rebuild_summaries` invocations with scope (one `--region`/`--monitor` first as a check, then a dry-run count of affected rows). The blast radius is checked before any wider run, and that run needs the user's yes.
  - **What's left for follow-up:** the misaligned seasonal rows and the other two report findings.
  - The ETag/`Vary` notes, the Scout trade-off, and the perf numbers.
- [ ] **Step 5: Ask the user** for review; don't merge.

### Task 7: sdk-js `lookupRegionPlace` point and monitor modes

**Files** (in `/home/alex/workspace/sjvair/sdk-js`, branch `feature/lookup-point-monitor` from `origin/release/4.8.0`, in a worktree under its `.worktrees/`):
- Modify: `lib/regions/get_region_places.ts`, `lib/regions/mod_test.ts`, `api-urls.md`
- Modify: `lib/regions/schemas/*` if no list-item schema fits the lookup's list response (`regionListItemSchema` should).

**Interfaces:**
- Consumes: Task 4's HTTP contract.
- Produces (overloads; the existing name call keeps working unchanged):
  - `lookupRegionPlace(q: string, type?: RegionType, options?: RequestOptions): Promise<RegionData | null>` (unchanged).
  - `lookupRegionPlace(place: { lat: number; lon: number; type?: RegionType | RegionType[] }, options?: RequestOptions): Promise<RegionListItem[]>`: rounds each coordinate with `Math.round(x * 1000) / 1000`, then POSTs a JSON body (`type` comma-joined), like `account/login`'s `init`.
  - `lookupRegionPlace(place: { monitor: string; type?: RegionType | RegionType[] }, options?: RequestOptions): Promise<RegionListItem[]>`: a GET with `searchParams`.
- [ ] **Step 1: Write failing tests** in `mod_test.ts` against the local API (served from the Task 4 branch):
  - `"POST regions/places/lookup/ (point)"`: a Fresno point gives a list containing a `county` named Fresno County, and each item validates against `regionListItemSchema`.
  - `"…(point, rounds)"`: stub `fetch` and assert the sent body has `36.737` for an input of `36.73749`.
  - `"GET regions/places/lookup/ (monitor)"`: uses `TEST_MONITOR_ID` and skips with a note when it's unset.
  - `"…(type array)"`: `["zipcode","county"]` returns only those types.
- [ ] **Step 2: Run; expect failures.** Run `deno test --allow-net --allow-env --allow-read --env-file=.env lib/regions/mod_test.ts`.
- [ ] **Step 3: Implement** the overloads and update the JSDoc and `api-urls.md`.
- [ ] **Step 4: Run `deno fmt --check && deno lint && deno check mod.ts` and the regions tests; expect PASS.** Don't run the account tests (they send a real SMS).
- [ ] **Step 5: Commit, push, and open a PR into `release/4.8.0`.** No beta. Ask the user before any release. Tell `data-dashboard-26` the PR exists.

### Task 8: data-dashboard docs (docs-only, straight to `main`, after both PRs are open)

- [ ] **Step 1:** Run `git -C /home/alex/workspace/sjvair/data-dashboard fetch origin`, then `git -C … worktree add .worktrees/docs-step3 origin/main`. Re-read each file right before editing it.
- [ ] **Step 2: Edit:**
  - `TODO.md` → "Release 1, step 3": mark the cache headers and the lookup done (with PR numbers), plus this track's "Start here" row. Ask the user whether to drop the production data-check items (the "(addition)" block) and record the answer.
  - `ROADMAP.md` item 3: progress.
  - `ARCHITECTURE.md` → "Data resolution & live refresh": the settle rule, the max-ages and the stable-URL heads-up.
  - `ARCHITECTURE.md` → "Widget data selection" → the lookup bullet and "Location privacy": the `type` list, the defaults and the server-side rounding.
  - `DEFERRED.md`, each entry with why and a revisit trigger:
    - the hour-early period starts;
    - the missing production region summaries;
    - the misaligned seasonal rows;
    - hidden monitors' summaries readable by id;
    - the lookup's 24 h cache after a boundary re-import.
- [ ] **Step 3:** Run `../../node_modules/.bin/prettier --write` on the edited files from the worktree. Commit (`docs: step 3 spec 2 status`), then `git push origin HEAD:main` (fetch and rebase first if `main` moved).
