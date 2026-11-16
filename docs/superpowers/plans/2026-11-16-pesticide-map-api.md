# Pesticide Map API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the server pieces the dashboard's Map widget needs: notices by day, `category`/`iarc_group` filters, valley-wide class breaks, and the meta text, badges, links, years and ramp.

**Architecture:** Every addition is an opt-in parameter or a new field on existing endpoints in `camp/api/v2/pesticides/` (`sections.py`, `meta.py`). The logic goes in small helpers in `camp/apps/pesticides/` beside the existing ones, which are left unchanged. Caching reuses `stats.cached` / `all_years_key` (use data) plus a new notices version (`|g:` key segment, the way `emissions/methane.py` does it).

**Tech Stack:** Django, PostGIS, django-resticus, Memcached, Huey.

**Spec:** `docs/superpowers/specs/2026-11-16-pesticide-map-api-design.md`

## Global Constraints

- The Pesticides and Facility Emissions explorers must not change behavior. A request without the new parameters returns exactly today's response. `maps.quantile_classes`, `maps.RAMP`, `maps.NO_DATA`, `stats.by_township` and `apply_filters`' existing branches keep their behavior.
- Filter names and values match `pesticides/place/`: `category` (`CategoryListField`: repeated or comma-separated, OR) and `iarc_group` (`Chemical.IARCGroup` values).
- Errors on `sections/`, `townships/` and `notices/*` use those endpoints' shape: 400 `{"error": "<message>"}`.
- Pacific day boundaries are built as `datetime(y, m, d, tzinfo=settings.DEFAULT_TIMEZONE)`, never with `timedelta(days=…)` across days (`stats.local_month_bounds` is the pattern).
- `NOTICE_GRACE_DAYS = 4`. Settled-day TTL is 24 h (`60 * 60 * 24`); other notice responses keep `NOTICE_CACHE_TTL` (300).
- Branches come from `origin/develop`, and PRs go into `develop`. No AI attribution in commits or PRs. Merging needs the user's explicit yes for that PR.
- Tests: `podman-compose --profile test run --rm test pytest <path> -v` (serial for single files). Full suite: `podman-compose --profile test run --rm test pytest -n 4 --dist loadscope`. Tee output to a log in the scratchpad before filtering.
- The local stack is shared. Timing measurements are read-only (`podman exec sjvaircom_web_1 python manage.py shell`).

## Review Focus

1. **A `date=` around a DST change** (Mar 8 and Nov 1, 2026): a notice at 23:30 Pacific on D is in, and one at 00:00 on D+1 is out. Pinned in Task 1.
2. **`category=` given twice and comma-joined** (`category=a&category=b,c`) behaves as one OR set and shares a cache key with the same set in another order. Pinned in Tasks 4 and 7.
3. **`classes=1` combined with `bbox`, `county` or `region`** still ranks the whole valley, and its key doesn't change with them. Pinned in Task 8.
4. **A notice with two chemicals, both matching the category**, appears once (`distinct`). Pinned in Task 4.
5. **No data for the year or month** (an empty month, or no years loaded): `classes` gives `{"breaks": [], "min": null}` for each figure, and the endpoints don't 500. Pinned in Task 8.

---

# PR 1: notices (branch `feature/pesticide-notices-day`, worktree `.worktrees/pesticide-notices-day`)

### Task 1: Notice day window and notices version (stats)

**Files:**
- Modify: `camp/apps/pesticides/stats.py` (next to `NOTICE_GRACE_DAYS`, line ~1064)
- Test: `camp/apps/pesticides/tests/test_notice_days.py` (new)

**Interfaces:**
- Produces:
  - `notice_day_bounds(day: date) -> tuple[datetime, datetime]`: `(start(D-4), start(D+1))`, both Pacific-aware.
  - `notices_on(notices: QuerySet, day: date) -> QuerySet`: `scheduled_application__gte=start(D-4), __lt=start(D+1)`.
  - `notice_day_settled_at(day: date) -> datetime`: `max(start(D+5), start(D+1) + timedelta(days=NOTICE_GRACE_DAYS))`.
  - `NOTICES_VERSION_KEY = 'pesticides:notices-version'`, `notices_version() -> str`, `bump_notices_version() -> str`, mirroring `data_version` / `bump_data_version` (`time.time_ns()`, no expiry, a missing value starts a new one).

- [ ] **Step 1: Write the failing tests** in a `NoticeDayTests(TestCase)` class:
  - `test_bounds_are_pacific_midnights`: for `date(2026, 6, 15)`, start == `datetime(2026, 6, 11, tzinfo=PACIFIC)`, end == `datetime(2026, 6, 16, tzinfo=PACIFIC)`.
  - `test_window_edges`: create notices at `start(D-4)` (in), `start(D+1) - 1 s` (in), `start(D+1)` (out), `start(D-4) - 1 s` (out). `notices_on(...)` returns the first two.
  - `test_dst_spring_forward_day`: D = `date(2026, 3, 8)`. A notice at 23:30 Pacific on Mar 8 is in, and one at 00:00 Pacific on Mar 9 is out.
  - `test_settled_at_normal_week`: D = `date(2026, 6, 15)` → `datetime(2026, 6, 20, tzinfo=PACIFIC)`.
  - `test_settled_at_dst_week`: D = `date(2026, 3, 5)`. `start(D+1)` is Mar 6 00:00 PST, and +96 h is Mar 10 01:00 PDT, which is later than `start(D+5)` (Mar 10 00:00 PDT). Assert the result is `datetime(2026, 3, 6, tzinfo=PACIFIC) + timedelta(days=4)`.
  - `test_notices_version_bumps`: `v = notices_version()`; `bump_notices_version()`; `notices_version() != v`; after `cache.delete(NOTICES_VERSION_KEY)`, `notices_version()` returns a fresh non-empty value.

- [ ] **Step 2: Run, and confirm it fails** with ImportError: `podman-compose --profile test run --rm test pytest camp/apps/pesticides/tests/test_notice_days.py -v`
- [ ] **Step 3: Implement the five helpers** in `stats.py`, with day starts built as in `local_month_bounds` (`date + timedelta(days=n)` on the *date*, then `datetime(..., tzinfo=settings.DEFAULT_TIMEZONE)`).
- [ ] **Step 4: Run, and confirm it passes.**
- [ ] **Step 5: Commit** `Pesticide notices: day window, settle instant, notices version`

### Task 2: The SprayDays fetch bumps the notices version

**Files:**
- Modify: `camp/apps/pesticides/tasks.py:6-9` (`fetch_pesticide_notices`)
- Test: `camp/apps/pesticides/tests/test_notice_days.py`

**Interfaces:** Consumes `stats.bump_notices_version()` (Task 1).

- [ ] **Step 1: Write failing tests**:
  - `test_fetch_bumps_version`: patch `camp.apps.pesticides.spraydays.fetch_applications`, call `tasks.fetch_pesticide_notices.call_local()`, and assert the version changed.
  - `test_failed_fetch_still_bumps`: make the patched fetch raise `RuntimeError`, then `pytest.raises(RuntimeError)`, and assert the version still changed.
- [ ] **Step 2: Run, and confirm both fail.**
- [ ] **Step 3: Wrap `fetch_applications()`** in `try/finally: stats.bump_notices_version()`, inside the lock.
- [ ] **Step 4: Run, and confirm it passes.**
- [ ] **Step 5: Commit** `Pesticide notices: the daily fetch retires cached notice answers`

### Task 3: Per-request cache timeout hook on CachedEndpointMixin

**Files:**
- Modify: `camp/utils/views.py:108` (the `cache.set(..., self.cache_timeout)` call)
- Test: `camp/utils/tests/test_cached_endpoint.py`

**Interfaces:** Produces `CachedEndpointMixin.get_cache_timeout(self, response) -> int`. By default it returns `self.cache_timeout`, and `get()` passes its result to `cache.set`. It's called after the response is built, so a subclass can read the request.

- [ ] **Step 1: Write failing tests**, following the file's existing pattern (a test endpoint subclass):
  - `test_default_timeout_is_class_attribute`: patch `cache.set`, and assert it's called with `cache_timeout`.
  - `test_get_cache_timeout_override_is_used`: a subclass returns 7, and `cache.set` gets 7.
- [ ] **Step 2: Run, and confirm they fail.** `podman-compose --profile test run --rm test pytest camp/utils/tests/test_cached_endpoint.py -v`
- [ ] **Step 3: Add the method and use it.**
- [ ] **Step 4: Run the file and confirm it passes.** Then run `camp/api/v2/emissions` and `camp/api/v2/pesticides/tests.py` and confirm they're unchanged.
- [ ] **Step 5: Commit** `CachedEndpointMixin: per-request cache timeout hook`

### Task 4: `notices/active/` and `notices/archive/`: `date=`, `past`, `category`, `iarc_group`, cache

**Files:**
- Modify: `camp/api/v2/pesticides/sections.py` (`ActiveNoticeListBase`, `ActiveNoticeList`, `ArchivedNoticeList`, plus a shared form)
- Test: `camp/api/v2/pesticides/tests.py` (`ActiveNoticeEndpointTests`, and a new `NoticeDayEndpointTests`)

**Interfaces:**
- Consumes `stats.notices_on`, `stats.notice_day_settled_at` and `stats.notices_version` (Task 1), and `get_cache_timeout` (Task 3). Consumes `CategoryListField` and `PlaceChoiceField` from `camp/api/v2/pesticides/endpoints.py`.
- Produces, in `sections.py`:
  - `class MapFilterForm(forms.Form)`: `category = CategoryListField()`, `iarc_group = PlaceChoiceField(choices=Chemical.IARCGroup.choices)`.
  - `parse_map_filters(params) -> tuple[dict, str | None]`: cleaned non-blank values, or the first field error's message. Tasks 7 and 8 reuse it.
  - `parse_day(params) -> tuple[date | None, str | None]`: error message `'date must be YYYY-MM-DD'`. `date.fromisoformat` is strict, so any ValueError or a year outside `stats.MIN_FILTER_YEAR..MAX_FILTER_YEAR` is that error.

Behaviour:
- `notices()` on the active endpoint: with a date, `stats.notices_on(PesticideNotice.objects.all(), day)`; without one, today's `_upcoming`. Archive: its own queryset, then `notices_on` when a date is given.
- Filters: `chemicals__categories__overlap=<list>` and `chemicals__iarc_group=<value>`. Duplicates are already handled by `.distinct()`.
- `past`: with a date, `scheduled_application < now - timedelta(days=NOTICE_GRACE_DAYS)` per feature. Archive keeps `True`. Without a date the property is absent (the existing archive test pins this).
- The cache key is `f'{super().get_view_cache_key()}|g:{stats.notices_version()}'` on both endpoints.
- `get_cache_timeout`: 24 h when a valid `date` is given and `timezone.now() >= notice_day_settled_at(day)`, else `NOTICE_CACHE_TTL`.

- [ ] **Step 1: Write failing tests** (`NoticeDayEndpointTests`, fixture `pesticides-explorer`, `cache.clear()` in setUp). Fixture facts: notice 2 has chemical 2 (CHLORPYRIFOS: `toxic_air_contaminant`, `california_restricted`, no IARC), and notice 3 has chemicals 1 (GLYPHOSATE: `carcinogen`, IARC `2A`) and 2.
  - `test_date_window`: set notice 2 to Pacific 2026-06-12 10:00 and notice 3 to 2026-06-16 00:00. `?date=2026-06-15` → [2], and `?date=2026-06-16` → [2, 3].
  - `test_date_includes_archived_notice`: notice 1 (2020-01-15 08:00 UTC) with `?date=2020-01-17` → [1], `past is True`.
  - `test_past_flag_only_with_date`: with a date, every feature has a boolean `past`; without one, no feature has it.
  - `test_bad_date`: `2026-13-01`, `nope` and `2026-6-1` are each 400 `{'error': 'date must be YYYY-MM-DD'}`.
  - `test_category_any_chemical`: `?category=carcinogen` → [3]. `?category=toxic_air_contaminant` → [2, 3] with notice 3 listed once. `?category=carcinogen&category=oil` and `?category=oil,carcinogen` → [3].
  - `test_iarc_group`: `?iarc_group=2A` → [3]. `?iarc_group=9` → 400, and `error` contains `9`.
  - `test_unknown_category`: `?category=foo` → 400 `{'error': 'Unknown category: foo.'}`.
  - `test_settled_day_cached_for_a_day`: patch `cache.set` and `timezone.now`. `?date=` 10 days back → timeout `86400`; `?date=` today → `300`.
  - `test_fetch_version_retires_cached_day`: GET `?date=2026-06-15`, move notice 2 out of the window, `stats.bump_notices_version()`, GET again → notice 2 is gone. Without the bump, the second GET is a cache HIT (`X-Cache-Status`).
  - `test_archive_takes_date_and_filters`: archive with `?date=2020-01-17&category=toxic_air_contaminant` → [1].
  - Explorer guard, `test_no_new_params_unchanged`: the active and archive responses without the new params have the same feature ids, order and property keys as before (assert the exact key set from `test_returns_active_notices_as_geojson`).
- [ ] **Step 2: Run, and confirm they fail.** `... pytest camp/api/v2/pesticides/tests.py -k "NoticeDay or ActiveNotice or ArchivedNotice" -v`
- [ ] **Step 3: Implement** as described above. Update both endpoint docstrings to name `date`, `category`, `iarc_group` and `past`.
- [ ] **Step 4: Run the notice tests and the whole `camp/api/v2/pesticides/tests.py`, and confirm they pass.**
- [ ] **Step 5: Commit** `Pesticide notices API: active on a day, category and IARC filters, past flag, settled-day cache`

### Task 5: Badges helper and `pesticides/meta/` notes, badges, links

**Files:**
- Create: `camp/apps/pesticides/badges.py`
- Modify: `camp/api/v2/pesticides/meta.py`
- Test: `camp/apps/pesticides/tests/test_badges.py` (new), `camp/api/v2/pesticides/tests.py` (`PesticidesMetaTests`)

**Interfaces:**
- Produces in `badges.py`:
  - `BADGES: list[dict]`, in this order: `{'key': 'prop65', 'label': 'Prop 65', 'note': 'prop65'}`, `{'key': 'carb_tac', 'label': 'CARB TAC', 'note': 'carb_tac'}`, `iarc_1` "IARC 1", `iarc_2a` "IARC 2A", `iarc_2b` "IARC 2B", `iarc_3` "IARC 3" (each `note` is the same key), `{'key': 'california_restricted', 'label': 'Restricted', 'note': 'california_restricted'}`.
  - `chemical_badges(chemical: Chemical) -> list[str]`, in BADGES order: `prop65` if `is_prop65`, `carb_tac` if `is_tac`, `f'iarc_{iarc_group.lower()}'` if `iarc_group`, `california_restricted` if `is_california_restricted`. Task 9 uses it.
- Meta adds `notes` (`{k: v for k, v in notes.all_notes().items()}`, with each value `{key, title, summary, detail, source_url}`), `badges` (`BADGES`) and `links` (`{'spraydays_signup': places.SPRAYDAYS_URL}`).

- [ ] **Step 1: Write failing tests**:
  - `test_badges.py`:
    - fixture GLYPHOSATE → `['prop65', 'iarc_2a']` (`carcinogen` makes it Prop 65; check `is_prop65` in `models.py:177` and adjust the expectation to the model's real rule);
    - CHLORPYRIFOS → `['carb_tac', 'california_restricted']`;
    - SULFUR → `[]`;
    - every `BADGES` `note` is a key of `notes.all_notes()`.
  - `PesticidesMetaTests.test_shape`: extend the key-set assertion to include `notes`, `badges` and `links`. Otherwise it's unchanged.
  - `test_notes_served`:
    - `data['notes']['noi_meaning'] == notes.all_notes()['noi_meaning']` (as JSON);
    - `pur_lag`, `badges`, `prop65`, `carb_tac`, `iarc_2a` and `california_restricted` are present.
  - `test_badges_and_links`: `[b['key'] for b in data['badges']]` equals the BADGES order, and `data['links'] == {'spraydays_signup': 'https://spraydays.cdpr.ca.gov/'}`.
- [ ] **Step 2: Run, and confirm they fail.**
- [ ] **Step 3: Implement.** Update the `PesticidesMeta` docstring.
- [ ] **Step 4: Run, and confirm they pass.** Also run `camp/apps/pesticides/tests/test_notes.py` and `camp/api/v2/meta/tests/test_catalog.py`.
- [ ] **Step 5: Commit** `Pesticides meta: notes, badges and the SprayDays link`

### Task 5b: The charts' filter values on the map endpoints (`*_id`, `aerial_ground`, commodity on notices)

Spec: "The charts' filter values on the map endpoints".

**Files:**
- Modify: `camp/api/v2/pesticides/fields.py` (move `SqidChoiceField` here from `endpoints.py`; re-export it from `endpoints.py` as Task 4 did for the others)
- Modify: `camp/api/v2/pesticides/sections.py` (`MapFilterForm`, `apply_filters`, `section_totals_available`, the notices filter block)
- Modify: `camp/api/v2/pesticides/meta.py` (`notice_filters`)
- Test: `camp/api/v2/pesticides/tests.py` (new `MapIdFilterTests(RollupTestMixin, TestCase)`)

**Interfaces:**
- `MapFilterForm` gains `chemical_id = SqidChoiceField(Chemical)`, `product_id = SqidChoiceField(Product)`, `commodity_id = SqidChoiceField(Commodity)` and `aerial_ground` (choices `G`, `A`, `F`, `O`, `none`; the same choices as `PesticidePlaceForm.aerial_ground`). `parse_map_filters(params)` also returns the "both forms" error: `'give chemical or chemical_id, not both'` (and likewise for product and commodity). Cleaned values are model instances for the ids.
- `NOTICE_METHOD_FOR_CODE = {'G': 'Ground', 'A': 'Aircraft', 'F': 'Fumigation'}` lives in `stats.py` beside `NOTICE_METHOD_LABELS`.
- Produces `NOTICE_VALUE_FILTERS = ('chemical_id', 'product_id', 'category', 'iarc_group', 'narrow', 'aerial_ground')`, served as meta `notice_filters`.

Behaviour:
- **Sections and townships.** `chemical_id` filters `chemical=obj`, `product_id` filters `product=obj`, `commodity_id` filters `commodity=obj`, and `aerial_ground` filters like `method`.
  - Counting: `chemical_id` sets `chemical_scoped` exactly as `chemical` does.
  - Any of them makes `section_totals_available` false.
- **Notices.**
  - `chemical_id` and `product_id` join the single `lookups` filter (`chemicals=obj`, `products=obj`).
  - `aerial_ground` uses the mapping. `O` is `~Q(application_method__iexact__in…)` over the three, excluding blank; `none` is `application_method=''`.
  - `commodity_id` gives 400 `"notices don't record a commodity"`.
- Without the new params, every response is unchanged.

- [ ] **Step 1: Write failing tests** (fixture `pesticides-explorer`):
  - `test_chemical_id_equals_code`: sections and townships with `chemical_id=<GLYPHOSATE sqid>` equal the response with `chemical=1855`, apart from nothing. Compare the features' properties.
  - `test_product_and_commodity_ids`: the same equality for `product_id` vs `product=<prodno>` and `commodity_id` vs `commodity=<site_code>`.
  - `test_both_forms_400`: `chemical=1855&chemical_id=<sqid>` gives 400 `{'error': 'give chemical or chemical_id, not both'}`.
  - `test_bad_id_400`: `chemical_id=zzzz` gives 400 with `'error'` equal to `'Not a chemical id.'`.
  - `test_aerial_ground_sections`: `aerial_ground=G` equals `method=G`, and `aerial_ground=none` equals `method=none`. `aerial_ground=X` gives 400.
  - `test_aerial_ground_notices`: set notice 2 to `Aircraft` and notice 3 to `Ground`. `A` gives [2] and `G` gives [3]. A notice set to `Hand` matches `O`. A blank one matches `none`.
  - `test_notice_chemical_id_same_chemical`: `chemical_id=<CHLORPYRIFOS sqid>&iarc_group=2A` gives [], and `chemical_id=<GLYPHOSATE sqid>&iarc_group=2A` gives [3].
  - `test_notice_commodity_id_400`: 400 `{'error': "notices don't record a commodity"}` on active and on archive.
  - `test_meta_notice_filters`: `data['notice_filters'] == list(NOTICE_VALUE_FILTERS)`. Extend `test_shape`'s key set.
- [ ] **Step 2: Run, and confirm they fail.**
- [ ] **Step 3: Implement.** Update the endpoint docstrings.
- [ ] **Step 4: Run all of `camp/api/v2/pesticides/tests.py` and `camp/apps/pesticides/tests/`, and confirm they pass.**
- [ ] **Step 5: Commit** `Pesticide map endpoints: the charts' filter values (ids, aerial_ground; no commodity on notices)`

### Task 6: Docs and PR 1

**Files:** `CLAUDE.md` (Metadata Endpoints, the `pesticides/meta/` bullet, plus a new "Pesticide notices by day" bullet)

- [ ] **Step 1: Update CLAUDE.md.**
  - In the meta bullet: `notes` (every health note, keyed), `badges` (`{key, label, note}`, keys permanent) and `links.spraydays_signup`.
  - New bullet: `notices/active/?date=` (the window rule `start(D-4) <= scheduled < start(D+1)` Pacific); `past` with date; `category`/`iarc_group` on both notice endpoints (any chemical matches); the settle instant; the 24 h vs 5 min TTL; the notices version bumped by `fetch_pesticide_notices` in `finally`.
- [ ] **Step 2: Run the full suite** and confirm it's green (tee to a log).
- [ ] **Step 3: Commit** `CLAUDE.md: pesticide notices by day and meta additions`, then push `feature/pesticide-notices-day` and open a PR into `develop`. The body covers:
  - what's added and the response shapes;
  - that the explorers are unchanged, and how that's tested;
  - **Deploy: none** (no migration; the new cache keys start empty; the notices version starts on first read).
- [ ] **Step 4:** Check `gh pr checks <n>` until it's green. Send the coordinator the PR number and final shapes. Don't merge without the user's explicit yes.

---

# PR 2: use (branch `feature/pesticide-map-classes` from `origin/develop` after PR 1 merges; worktree `.worktrees/pesticide-map-classes`)

### Task 7: `category` / `iarc_group` on `sections/` and `townships/`, counted like `place/`

**Files:**
- Modify: `camp/api/v2/pesticides/sections.py` (`SECTION_FILTER_PARAMS` / `section_totals_available`, `apply_filters`, `SectionListBase.get`, `TownshipListBase.get`)
- Modify: `camp/apps/pesticides/stats.py` (new helpers beside `by_township`)
- Test: `camp/api/v2/pesticides/tests.py` (new `MapCategoryFilterTests(RollupTestMixin, TestCase)`)

**Interfaces:**
- Consumes `parse_map_filters` (Task 4) and `places._RECORD_KEY`.
- Produces in `stats.py`:
  - `section_totals_by_record(rows: QuerySet) -> dict[int, dict]`: `{mtrs_pk: {'lbs_chemical', 'lbs_product', 'acres_treated', 'applications'}}`. An inner `values(*_RECORD_KEY).annotate(p=Sum('lbs_chemical'), pp=Max('lbs_product'), a=Max('acres_treated'), n=Max('applications'))`, wrapped in raw SQL `SELECT g.mtrs, SUM(g.p), SUM(g.pp), SUM(g.a), SUM(g.n) FROM (...) g WHERE g.mtrs IS NOT NULL GROUP BY g.mtrs`. Catch `EmptyResultSet` as `places.monthly_use` does.
  - `fold_townships(by_section: dict[int, dict]) -> dict[str, dict]`: sums through `township_index()`, with the same fields as `by_township`.
- Produces in `sections.py`: `section_figures(rows, params, filters) -> dict[int, dict]`. It picks the path: with `chemical`, today's `totals_aggregates(True)`; with `category` or `iarc_group` and no `chemical`, `section_totals_by_record`; otherwise today's `totals_aggregates(False)`. Task 8 uses it valley-wide.

Behaviour:
- `apply_filters` gains two branches, `chemical__categories__overlap` and `chemical__iarc_group`, which run only when the cleaned filters carry them.
- `section_totals_available` is false when either is present.
- Townships with those filters: `fold_townships(section_figures(...))`.

- [ ] **Step 1: Write failing tests**:
  - `test_section_matches_place`: for fixture section 9101 and the latest year, `sections/?bbox=<section bbox>&category=carcinogen` gives `lbs_chemical`, `acres_treated` and `applications` equal to `pesticides/place/?region_type=mtrs&region=<external_id>&category=carcinogen`'s year totals. Repeat for `iarc_group=2A`, and for `month=` with the place's month row.
  - `test_township_matches_place`: the same for a township, comparing against the sum of `place/` over its sections, or the fixture's single section if the township has one.
  - `test_two_ingredients_count_once`: a record with GLYPHOSATE and another `carcinogen` chemical counts once for acres and applications under `category=carcinogen`, and pounds are the sum of both.
  - `test_unknown_category_400`: `{'error': 'Unknown category: foo.'}` on both endpoints.
  - `test_order_independent_cache`: `category=a,b` and `category=b&category=a` give equal bodies.
  - Explorer guard, `test_no_new_params_unchanged`: the existing section and township responses (no category/iarc) are equal before and after. Use the existing test classes as they are; they must still pass unchanged.
- [ ] **Step 2: Run, and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `camp/api/v2/pesticides/tests.py` and `camp/apps/pesticides/tests/` and confirm they pass.**
- [ ] **Step 5: Commit** `Pesticide sections and townships: category and IARC filters, counted like place/`

### Task 8: `classes=1`: valley-wide breaks

**Files:**
- Create: `camp/apps/pesticides/classes.py`
- Modify: `camp/api/v2/pesticides/sections.py` (both list endpoints)
- Test: `camp/apps/pesticides/tests/test_classes.py` (new); `camp/api/v2/pesticides/tests.py`

**Interfaces:**
- Consumes `section_figures` and `parse_map_filters` (Task 7), `fold_townships`, `stats.cached`, `stats.all_years_key`, `maps.quantile_classes`, `section_totals` (unfiltered fast path).
- Produces in `classes.py`:
  - `FIGURES = ('lbs_chemical', 'acres_treated', 'applications')`;
  - `VALUE_PARAMS = ('month', 'chemical', 'product', 'commodity', 'chemical_id', 'product_id', 'commodity_id', 'method', 'aerial_ground', 'narrow', 'concern', 'category', 'iarc_group')` (ids hash by pk);
  - `breaks_for(values: dict) -> dict`: `{'breaks': quantile_classes(values).breaks, 'min': min(positive) or None}`;
  - `valley_classes(level: str, year, all_years: bool, params) -> dict`. `level` is `'section'` or `'township'`. Returns `{figure: breaks_for(...)}`, cached under `stats.all_years_key('classes', level, year_value, md5(json of the sorted cleaned VALUE_PARAMS))`. Category lists are sorted (as `CategoryListField` returns them), so spellings share a key.
- The endpoints add `classes` to the returned dict when `params.get('classes') == '1'`, built over the scope year (also under `compare=`).

- [ ] **Step 1: Write failing tests**:
  - `test_breaks_for`:
    - `{1: 0, 2: 5, 3: 10}` → breaks == `quantile_classes({2: 5, 3: 10}).breaks`, min == 5;
    - all zero → `{'breaks': [], 'min': None}`.
  - `test_valley_not_bbox`: a `sections/?bbox=<tiny box>&classes=1` response's classes equal `valley_classes('section', ...)` computed over every section with data.
  - `test_spatial_params_ignored`: the same classes with `county=fresno`, `region=<sqid>` or a different bbox. Patch the builder and assert it ran once across those calls (cache hit).
  - `test_month_ranked_alone`: `month=6` classes == breaks over June-only figures.
  - `test_filters_change_classes`: `category=carcinogen` gives different classes from unfiltered, equal to breaks over Task 7's filtered figures.
  - `test_import_retires`: after `stats.bump_data_version()`, the builder runs again.
  - `test_no_classes_without_param`: `'classes' not in` the response, for `classes` absent or `classes=0`.
  - `test_empty_month`: a month with no rows → every figure `{'breaks': [], 'min': None}`, status 200.
  - `test_township_level`: `townships/?classes=1` classes are computed over township totals (`fold_townships`).
  - `test_feature_values_fall_in_classes`: every feature's positive `lbs_chemical` is `<= breaks[-1]`.
- [ ] **Step 2: Run, and confirm they fail.**
- [ ] **Step 3: Implement.** The unfiltered fast path (`section_totals_available`) reads `PesticideSectionTotal` for the whole valley (no `mtrs__in`). The filtered path runs the rollup over all rows of the year.
- [ ] **Step 4: Run, and confirm they pass.**
- [ ] **Step 5: Commit** `Pesticide sections and townships: valley-wide class breaks (classes=1)`

### Task 9: Meta years, ramp, `shades_valley`; `top_chemicals` badges; township id

**Files:**
- Modify: `camp/api/v2/pesticides/meta.py`, `datafiles/pesticide-health-notes.yaml`, `camp/api/v2/pesticides/sections.py` (`SectionDetailBase.top`, `SectionDetail.cache_key_version = 1`, the `TownshipList` docstring)
- Test: `camp/api/v2/pesticides/tests.py`

**Interfaces:** Consumes `badges.chemical_badges` (Task 5).

- [ ] **Step 1: Write failing tests**:
  - `test_meta_years_and_ramp`:
    - `data['years'] == list(reversed(stats.available_years()))`;
    - `data['ramp'] == {'colors': maps.RAMP, 'no_data': maps.NO_DATA}`;
    - `data['notes']['shades_valley']['summary']` equals the spec's text exactly;
    - `data['notes']['shades']` is unchanged.
  - `test_top_chemicals_badges`: `sections/<9101 sqid>/` `top_chemicals` rows each have `badges == chemical_badges(<that chemical>)`, and `is_of_concern` is still present.
  - Update `test_shape`'s key set for `years` and `ramp`.
- [ ] **Step 2: Run, and confirm they fail.**
- [ ] **Step 3: Implement.** The YAML entry `shades_valley`:
  - title "What the shades mean";
  - summary verbatim from the spec;
  - `source_url` copied from `shades`.
- [ ] **Step 4: Run, and confirm they pass.** Also run `test_notes.py` and the templatetag tests (the explorer's notes must be unaffected).
- [ ] **Step 5: Commit** `Pesticides meta: years, ramp, valley shades note; section badges; township id documented`

### Task 10: Timings, docs, PR 2

- [ ] **Step 1: Measure** read-only on the shared stack with a scratchpad script run by `podman exec sjvaircom_web_1 python manage.py shell -c ...`. Time `valley_classes` cold (after `cache.delete` of its key) and cached, for the latest year, `month=6`, `category=carcinogen`, and `month=6&category=carcinogen`, at section and township level. Also time a `sections/?bbox=…&classes=1` request end to end. Record a table.
- [ ] **Step 2: Update CLAUDE.md** with a "Pesticide map" bullet:
  - `classes=1` (shape, population, value-vs-spatial params, cache under the data version);
  - `category`/`iarc_group` counting on sections and townships;
  - meta `years`/`ramp`/`shades_valley`;
  - `top_chemicals[].badges`;
  - the township id is the PLSS name and is permanent.
- [ ] **Step 3: Run the full suite** and confirm it's green (tee to a log). Commit, push, and open a PR into `develop`. The body has:
  - the shapes;
  - the timings table;
  - the explorer guards;
  - **Deploy: none** (no migration; the classes cache starts empty and fills on request; the `SectionDetail` key version means old cached rows aren't served).
- [ ] **Step 4:** Check `gh pr checks <n>`. Send the coordinator the PR, the shapes and the timings. Don't merge without the user's explicit yes.
