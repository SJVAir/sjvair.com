# Hardcoded Values Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove sjvair.com's own copies of what its metadata provides, drop `monitors/meta/`'s
legacy `levels` dict, and serve the school activity guidelines as metadata.

**Architecture:** Everything reads the in-memory level sets in `camp/apps/entries/levels.py`
and the domain `scales.py` modules. A new `camp/apps/entries/guidelines.py` holds the school
activity guidelines; `monitors/meta/` serves it, and the `/guidelines/` pages render from it
through a small view and template filters. No new queries.

**Tech Stack:** Django, django-resticus, Sass (compiled by `invoke styles`), pytest with
`django.test.TestCase`.

**Spec:** `docs/superpowers/specs/2026-11-04-hardcoded-values-cleanup-design.md` (read it
first; the plan argues from it).

## Global Constraints

- Work in `/home/alex/workspace/sjvair/sjvair.com/.worktrees/hardcoded-cleanup`, branch
  `feature/hardcoded-cleanup`. PR into `develop`; never merge without the user's yes.
- No Claude or AI attribution in commits, PRs or docs (no `Co-Authored-By` trailer).
- Tests: `django.test.TestCase`, setup in `setUp` or the test, pytest-style `assert`.
- Ids and keys are permanent: activity keys `recess`, `pe`, `athletics`, `events`; level keys
  are the existing AQLevel keys.
- Guideline text is verbatim from today's templates ("let's not reword anything"): plain
  strings, `&amp;` → `&`, wrapped in `gettext_lazy`, served as `str`.
- `meta/datasets/` output must not change. `/tempo/products/` output must not change. Cleaned
  PM2.5 data (`lcs.py`) must not change.
- No new per-request queries. Cache keys, if any, must be memcached-safe.
- Shared stack: never swap or restart `sjvaircom_web_1` or the Huey workers. Use the
  throwaway `:8001` container. Never write to the local DB without asking the coordinator
  (data-dashboard-2c). Nothing touches production.
- The test command (run from the worktree; the "not a git repository" trailing line is
  noise), referred to below as **TEST**:
  ```bash
  podman run --rm --network sjvaircom_sjvair-net --env-file .env.test \
    -e DATABASE_URL=postgres://sjvair:<password from .env.test>@db:5432/sjvair_cleanup \
    -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token -v $PWD:/app:z \
    -v ~/workspace/django-resticus/.worktrees/session-csrf/resticus:/usr/local/lib/python3.14/site-packages/resticus:ro,z \
    -w /app sjvair-com-test:latest pytest <args>
  ```

## Review Focus

1. **A forecast with `aqi_value` above 500 or exactly on a breakpoint** should get the
   Hazardous label and color above 500, and the higher level exactly on a breakpoint
   (e.g. 51 → Moderate). Pinned in Task 5.
2. **An unknown or empty `burn_status`** should show the feed text, or nothing, in the admin
   panel, never crash. Pinned in Task 5.
3. **A level tag for `very_hazardous`, or a subscription at `good`**, should render with the
   level's color and readable text. Pinned in Task 3.
4. **Someone later edits `levels.PM25`** (adds or renames a level): the school guidelines must
   fail a test rather than silently serve a level with no text. Pinned in Task 1.
5. **Lazy translation strings leaking into JSON**: every `school_guidelines` value must be a
   plain `str` in the response. Pinned in Task 1.

---

### Task 0: Worktree setup and baseline

**Files:** none committed.

- [ ] **Step 1:** Copy `.env`, `.env.test` and `docker-compose.override.yml` from the main
  checkout into the worktree root (they're git-ignored).
- [ ] **Step 2:** Run the full suite with TEST `-n 4 --dist loadscope`. Expected: all pass
  (baseline after #302 was 4225; #303–#305 added more). Record the count.
- [ ] **Step 3: Baseline timings against the real local DB.** Start the throwaway server:
  ```bash
  podman run -d --name cleanup-web --network sjvaircom_sjvair-net --env-file .env \
    -e BAM_MIRROR_ENABLED=0 -p 8001:8000 -v $PWD:/app:z \
    -v $HOME/workspace/django-resticus/.worktrees/session-csrf/resticus:/usr/local/lib/python3.14/site-packages/resticus:ro,z \
    -w /app localhost/sjvaircom_web:latest python manage.py runserver 0:8000
  ```
  For each of `/guidelines/`, `/guidelines/schools/`, `/api/2.0/monitors/meta/`,
  `/api/2.0/meta/datasets/` and `/api/2.0/forecasts/`, record the median of 5
  `curl -s -o /dev/null -w '%{time_total}'` runs. Record each one's query count with a
  read-only `podman exec cleanup-web python manage.py shell -c` that uses `django.test.Client`
  inside `CaptureQueriesContext`. Save the results to the scratchpad. Keep the container
  running; it autoreloads.

---

### Task 1: School guidelines metadata; drop the legacy `levels` dict

**Files:**
- Create: `camp/apps/entries/guidelines.py`
- Modify: `camp/api/v2/monitors/endpoints.py` (`MonitorMetaEndpoint.get_entries`)
- Modify: `camp/apps/entries/levels.py` (delete `LevelSet.as_dict`)
- Modify: `camp/api/v2/accounts/endpoints.py` (stale comment saying levels come from `monitors/meta/`)
- Test: `camp/apps/entries/tests/test_guidelines.py` (new),
  `camp/api/v2/monitors/tests/test_meta_scales.py`,
  `camp/apps/entries/tests/test_levels.py`, `camp/apps/entries/tests/test_scales.py`,
  `camp/apps/entries/tests/test_aqi_breakpoints.py`

**Interfaces:**
- Produces: `camp.apps.entries.guidelines.SCHOOL_ACTIVITIES` (a tuple of `Activity`), where
  `Activity` is a frozen dataclass `key: str, label, duration (or None), levels: dict[str,
  tuple]` (level key → tuple of lazy sentences).
- Produces: `school_guidelines_json(request) -> dict`, the JSON block from the spec, with
  every string as `str`. `source.url` comes from
  `request.build_absolute_uri('/guidelines/schools/')`.
- Produces: `SCHOOL_GUIDELINES_LABEL = _('Outdoor Activity Guidelines for Schools')`.

- [ ] **Step 1: Write the failing tests**

  In `test_guidelines.py`:
  - `test_level_keys_match_pm25`: for each activity,
    `list(a.levels) == [l.key for l in levels.PM25]`.
  - `test_activity_order_and_labels`:
    - `[a.key for a in SCHOOL_ACTIVITIES] == ['recess', 'pe', 'athletics', 'events']`;
    - labels `['Recess', 'P.E.', 'Athletic Practice & Training', 'Scheduled Sporting Events']`;
    - durations `['15 minutes', '1 hour', '2-4 hours', None]`.
  - `test_text_verbatim`, spot checks:
    - recess `unhealthy` == `('Exercise indoors or avoid vigorous outdoor activities.', 'Sensitive individuals should remain indoors.')`;
    - pe `unhealthy` first sentence == `'Exercise indoors or limit vigorous outdoor activities to a maximum of 15 minutes.'`;
    - events `unhealthy_sensitive` first == `'Increase rest breaks and substitutions per CIF guidelines for extreme heat.'`;
    - every activity's `hazardous` == `('No outdoor or indoor activities.',)`.

  In `test_meta_scales.py`:
  - Replace `test_levels_dict_unchanged` with `test_levels_key_removed`:
    `all('levels' not in e for e in entries.values())`.
  - Add `test_school_guidelines_pm25_only`:
    - `entries['pm25']['school_guidelines']['resolution'] == 'hour'`;
    - its `source` == `{'name': 'SJVAir', 'url': 'http://testserver/guidelines/schools/'}`;
    - every other entry's `school_guidelines is None`.
  - Add `test_school_guidelines_plain_strings`: walk the block and assert every leaf is `str`
    or `None`; `json.dumps` succeeds.

- [ ] **Step 2: Run them.** TEST `camp/apps/entries/tests/test_guidelines.py camp/api/v2/monitors/tests/test_meta_scales.py -v`
  Expected: FAIL (module missing; `levels` key still present).
- [ ] **Step 3: Implement** `guidelines.py`, copying every cell of
  `camp/templates/pages/guidelines/schools.html` (lines 27–119) in page order.
  - In `get_entries`, drop `'levels'` and add `'school_guidelines'`: the block for `pm25`,
    `None` otherwise.
  - `get_entries` needs the request: pass `self.request`.
- [ ] **Step 4: Remove the legacy format.**
  - Delete `LevelSet.as_dict`.
  - Delete `test_as_dict` (`test_levels.py`) and `test_as_dict_keeps_shape_and_adds_tier`
    (`test_scales.py`).
  - Rewrite `test_served_ranges` to read `PM25.Levels.to_scale('pm25', 'PM2.5', 'µg/m³')`:
    the `unhealthy` level's `min == 55.5` and `max == 125.5`; `hazardous` `min == 225.5`,
    `max is None`.
  - Fix the stale comment in `accounts/endpoints.py` to point at `scale`.
- [ ] **Step 5: Run.** TEST `camp/apps/entries camp/api/v2/monitors camp/api/v2/accounts -n 4 --dist loadscope`. Expected: PASS.
- [ ] **Step 6: Commit.**
  `git commit -m "feat(meta): serve school activity guidelines; drop monitors/meta legacy levels"`

---

### Task 2: Level template filters

**Files:**
- Create: `camp/apps/entries/templatetags/__init__.py`, `camp/apps/entries/templatetags/level_tags.py`
- Test: `camp/apps/entries/tests/test_level_tags.py`

**Interfaces:**
- Produces: the filter `level_style(level) -> str`, for example
  `"background-color: #ff7e00; color: #fff"`.
  - Text is white when `level.tier >= 2`. Otherwise it is `#363636` (Bulma's `$text`), which
    keeps today's contrast.
  - It returns `''` for `None`.
- Produces: the filter `level_range(levelset, decimals) -> list[str]`, one string per level in
  scale order.
  - Each string is `"{min} – {next_min - step}"`, where step is `10 ** -decimals`, formatted
  to `decimals` places.
  - The top level is `"≥{min}"`.
  - The separator is an en dash with spaces.

- [ ] **Step 1: Write the failing tests**
  - `test_pm25_ranges`: `level_range(levels.PM25, 1) == ['0.0 – 9.0', '9.1 – 35.4', '35.5 – 55.4', '55.5 – 125.4', '125.5 – 225.4', '≥225.5']`.
  - `test_aqi_ranges`: `level_range(levels.AQI, 0) == ['0 – 50', '51 – 100', '101 – 150', '151 – 200', '201 – 300', '≥301']`.
  - `test_level_style_contrast`: dark text on `levels.PM25.GOOD` and `MODERATE`; white on
    `UNHEALTHY_SENSITIVE` and `levels.PM100.VERY_HAZARDOUS`; the background equals
    `level.color`; `None` gives `''`.
- [ ] **Step 2: Run them.** TEST `camp/apps/entries/tests/test_level_tags.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Use `Decimal` arithmetic for `next_min - step`, so float error
  can't produce `35.39999`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(entries): level_style and level_range template filters"`

---

### Task 3: Guidelines pages and account level tags

**Files:**
- Modify: `camp/utils/views.py` (add `GuidelinesPage(PageTemplate)`)
- Modify: `camp/urls.py`: add `path('guidelines/', …)` and `path('guidelines/schools/', …)`
  before the catch-all at line 104, using `template_name='pages/guidelines/index.html'` and
  `'pages/guidelines/schools.html'`.
- Modify: `camp/templates/pages/guidelines/index.html`, `camp/templates/pages/guidelines/schools.html`
- Modify: `camp/templates/account/alerts.html:28`, `camp/templates/account/subscriptions.html:23`
- Modify: `camp/apps/alerts/models.py` (add `Subscription.get_level()`)
- Modify: `assets/sass/sjvair/pages/guidelines.sass` (delete the `th.guidelines-level` `level-N`
  `@extend` rules, lines 27–44), `assets/sass/sjvair/global.sass` (delete the per-key
  `.tag.air.<key>` background and color rules; keep the `.tag.air` shape rules)
- Test: `camp/tests/test_guidelines_pages.py` (new), `camp/apps/alerts/tests/` (the existing
  account-page tests, or a new `test_level_tags.py` there)

**Interfaces:**
- Consumes: `SCHOOL_ACTIVITIES` and `SCHOOL_GUIDELINES_LABEL` (Task 1); `level_style` and
  `level_range` (Task 2).
- Produces: `GuidelinesPage` context with these keys:
  - `levels`: `list(levels.PM25)`;
  - `pm25_ranges`: `level_range(levels.PM25, 1)`;
  - `aqi_ranges`: `level_range(levels.AQI, 0)`;
  - `pm25_units`: `PM25.units`;
  - `activities`: `SCHOOL_ACTIVITIES`.
- Produces: `Subscription.get_level() -> Level`, which is `AQLevel.scale[self.level.upper()]`.

- [ ] **Step 1: Write the failing tests** (test client, no login for the guidelines pages).
  - `test_general_page_from_metadata`, on `/guidelines/`:
    - 200;
    - contains every PM2.5 level label;
    - contains `'0.0 – 9.0 µg/m³'` and `'0 – 50'`;
    - contains each level's `guidance` for Moderate through Hazardous;
    - contains `'background-color: #00e400'`;
    - does not contain `"It's a great day to be active outside"` or
      `'Consider reducing prolonged or heavy exertion'`;
    - still contains `'Guidelines are based on hourly PM2.5 concentration.'`.
  - `test_schools_page_from_metadata`, on `/guidelines/schools/`:
    - 200;
    - contains `'Athletic Practice &amp; Training'` (HTML-escaped) and `'2-4 hours'`;
    - contains `'Exercise indoors or limit vigorous outdoor activities to a maximum of 15 minutes.'`;
    - contains `'≥225.5'`.
  - `test_guidelines_pages_query_count`: each page renders in `assertNumQueries(N)`. N is
    the count measured on the old template at the start of this step (no growth).
  - `test_alert_tag_uses_level_color`: a signed-in user with an open alert at
    `very_hazardous` on PM10 sees `'background-color: #7e0023; color: #fff'` on
    `/account/alerts/` (or that page's existing URL name).
  - `test_subscription_tag_good`: a `good` subscription renders `level_style` of
    `AQLevel.scale.GOOD` on the subscriptions page.
- [ ] **Step 2: Run them.** TEST `camp/tests/test_guidelines_pages.py camp/apps/alerts -v`. Expected: the new ones FAIL.
- [ ] **Step 3: Implement the view and routes.** Rewrite both templates to loop over `levels` /
  `activities`.
  - Header cells take `style="{{ level|level_style }}"`.
  - Body cells keep their positional `level-{{ forloop.counter }}` classes for the light tints.
  - The general page's Guidance row shows `level.guidance`, which is empty for Good.
  - The range row shows `pm25_ranges[i] pm25_units` over `aqi_ranges[i]` (zip them in the view
    as `columns`).
  - Titles, tabs, footnote and table classes stay as they are.
- [ ] **Step 4: Change the account tags.** They become
  `<span class="tag air" style="{{ alert.latest.get_level|level_style }}">` and
  `… subscription.get_level|level_style …`, with `{% load level_tags %}`. Delete the Sass rules
  listed above.
- [ ] **Step 5: Run.** TEST `camp/tests camp/apps/alerts camp/api/v1/alerts -n 4 --dist loadscope`. Expected: PASS.
- [ ] **Step 6: Visual check.**
  - Run `podman exec cleanup-web invoke styles` (or the repo's Sass build) and check that it
    compiles.
  - Open `http://localhost:8001/guidelines/` and `/guidelines/schools/`.
  - Compare them with `http://localhost:8000/` (the shared server): same layout, header colors
    and tints, and the Good guidance cell blank.
- [ ] **Step 7: Commit.** `git commit -m "feat(pages): build guidelines pages and level tags from metadata"`

---

### Task 4: Retire `Subscription.LEVELS`

**Files:**
- Modify: `camp/apps/alerts/models.py` (delete `LEVELS` and its `Choices` import if it becomes unused)
- Modify: `camp/api/v1/alerts/tests.py` (lines 32, 65, 81, 92, 95: use `'unhealthy'` / `'hazardous'`)

- [ ] **Step 1: Make the edits.**
- [ ] **Step 2: Run.** TEST `camp/api/v1/alerts camp/apps/alerts -v`, then
  `grep -rn "Subscription.LEVELS" camp`. Expected: PASS, and no grep hits.
- [ ] **Step 3: Commit.** `git commit -m "chore(alerts): remove legacy Subscription.LEVELS"`

---

### Task 5: Forecasts read the AQI scale

**Files:**
- Delete: `camp/utils/aqi.py` (and its tests, if any: `grep -rn aqi_label camp`)
- Modify: `camp/apps/forecasts/tasks.py:15,158`, `camp/apps/forecasts/models.py` (`color`;
  add an internal `level` property, not served: the API gets no `aqi_level` key), `camp/api/v2/forecasts/serializers.py`,
  `camp/apps/forecasts/panels.py:33-37`, `camp/apps/forecasts/scales.py` (add
  `burn_status_label`), `camp/apps/entries/levels.py:320` (comment referencing `aqi_label`)
- Test: `camp/apps/forecasts/tests.py`, `camp/api/v2/forecasts/tests.py`

**Interfaces:**
- Produces: `Forecast.level -> Level`, which is `levels.AQI.get_level(self.aqi_value)`.
  `Forecast.color` returns `self.level.color`.
- Produces: `burn_status_label(value: str) -> str | None`, the burn scale level's label whose
  `value` matches, else `None`.

- [ ] **Step 1: Write the failing tests**
  - `test_forecast_color_is_discrete`: `aqi_value=75` → `color == '#ffff00'`; `51` →
    `'#ffff00'`; `50` → `'#00e400'`; `501` → `'#7e0023'`.
  - `test_api_aqi_category_from_scale`: a stored row with `aqi_category='Out of Range'`,
    `aqi_value=520` is served with `aqi_category == 'Hazardous'` and `color == '#7e0023'`; a
    `aqi_value=120` row → `'Unhealthy for Sensitive Groups'`.
  - `test_import_stores_scale_label`: the existing fetch-forecasts test (fixture XML) stores
    `aqi_category == levels.AQI.get_level(v).label` for each row.
  - `test_panel_burn_label`:
    - `burn_status='Discouraged'` → item `'burn' == 'Burning Discouraged'`;
    - an unknown value with feed text `'X'` → `'X'`;
    - empty status and text → `''`.
- [ ] **Step 2: Run them.** TEST `camp/apps/forecasts camp/api/v2/forecasts -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - The task uses `str(levels.AQI.get_level(aqi_value).label)`.
  - The serializer's `aqi_category` is a lambda `str(f.level.label)`.
  - The panel's `category` is `str(row.level.label)`, and its `burn` is
    `burn_status_label(row.burn_status) or row.burn_status_text or row.burn_status`.
  - Delete `aqi.py`.
- [ ] **Step 4: Run.** TEST `camp/apps/forecasts camp/api/v2/forecasts camp/apps/regions -n 4 --dist loadscope`. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(forecasts): color and category from the AQI scale"`

---

### Task 6: Catalog reads its labels and lists from their sources

**Files:**
- Modify: `camp/api/v2/meta/catalog.py`, `camp/api/v2/tempo/endpoints.py`, and the shared
  TEMPO units (builder's choice: `camp/apps/tempo/products.py` or similar)
- Test: `camp/api/v2/meta/tests/test_catalog.py`,
  `camp/api/v2/meta/tests/catalog_snapshot.json` (new)

**Interfaces:**
- Produces: `TEMPO_UNITS: dict[str, str]` holding the four products, `cldo4: 'fraction'`
  included. `TempoProducts` filters out `cldo4` explicitly, keeping its output identical.

- [ ] **Step 1: Pin the output before touching anything.**
  - Add `test_catalog_unchanged` to `DatasetCatalogTests` (which already loads
    `default-calibrations.yaml`). It compares `self.get()` with `catalog_snapshot.json`, and
    when the env var `WRITE_CATALOG_SNAPSHOT=1` is set it writes the snapshot instead
    (`json.dump(..., sort_keys=True, indent=1)`).
  - Run it once with TEST `-e WRITE_CATALOG_SNAPSHOT=1` (the flag goes before the image name)
    on the unchanged code, and commit the snapshot.
  - Add `test_tempo_products_unchanged`, which pins the current `/tempo/products/` keys and
    units (`no2`, `o3tot`, `hcho`).
  - Run them. Expected: PASS.
- [ ] **Step 2: Refactor.**
  - Smoke, fire, aqi-forecast, burn-status and heat-score entries take `label` and `units`
    from the scale functions.
  - The weather dataset's monitor models are the `Monitor.get_subclasses()` whose
    `monitor_type` maps to `'weather'` in `settings.MONITOR_OPT_IN_TYPES`. The `CIMIS` import
    goes.
  - `FACILITY_POLLUTANTS` comes from `pollutants.CRITERIA + pollutants.PRECURSORS`, keeping the
    order of today's list: nox, rog, pm, pm10, sox, co, tog, nh3. CRITERIA's order differs, so
    sort by that explicit key list or assert it.
  - The unit is `Pollutant.unit_label`.
  - TEMPO units come from `TEMPO_UNITS`.
- [ ] **Step 3: Run.** TEST `camp/api/v2/meta camp/api/v2/tempo -n 4 --dist loadscope`. Expected: PASS, with the snapshot unchanged.
- [ ] **Step 4: Commit.** `git commit -m "refactor(meta): catalog reads labels, units and lists from their sources"`

---

### Task 7: Smaller copies (group map, PM2.5 cleaning tiers)

**Files:**
- Modify: `camp/apps/monitors/management/commands/generate_group_map.py:35-43`
- Modify: `camp/apps/calibrations/core/processors/pm25/lcs.py:219-226`
- Test: the `lcs` processor tests (`grep -rln "lcs" camp/apps/calibrations/**/tests*`)

- [ ] **Step 1: Write the failing test** `test_cleaning_tier_bounds`:
  - the thresholds the cleaner uses equal
    `[Decimal('9.0'), Decimal('35.4'), Decimal('55.4'), Decimal('125.4'), Decimal('225.4'), Decimal('10000.0')]`
    with multipliers `[None, 5, 4, 3, 3, 3]`;
  - and a value of `Decimal('9.05')` takes the same branch as today (Moderate's multiplier 5).

  Extract the list into a module-level function `cleaning_thresholds()` so it is testable,
  then run the test. Expected: PASS on today's hardcoded list. It is the pin.
- [ ] **Step 2: Derive the bounds.** Compute `cleaning_thresholds()` from `levels.PM25`: each
  bound is the next level's `value` minus `Decimal('0.1')`; the last stays `10000.0`. Keep the
  multipliers keyed by level key. Run. Expected: PASS.
- [ ] **Step 3: Rebuild `pm_colors`.** In `generate_group_map.py`, build it from `levels.PM25`
  as `(level.value, next.value - 0.1 or 999999, hex_to_rgb(level.color))`. No test (management
  command for ad-hoc maps); check with `python -c "import …; print(pm_colors)"` in TEST.
- [ ] **Step 4: Commit.** `git commit -m "refactor: group map and PM2.5 cleaning tiers read levels.PM25"`

---

### Task 8: Docs, performance check, full suite, PR

**Files:**
- Modify: `CLAUDE.md` → "Metadata Endpoints"
- data-dashboard docs, in their own worktree

- [ ] **Step 1: CLAUDE.md.** In the "Domain meta endpoints" bullet, replace the "Its old `levels`
  dict … Don't change its shape." sentences with:
  - `monitors/meta/` no longer serves the legacy `levels` dict; `scale` is the only level
    format.
  - Each entry type has `school_guidelines` (null except `pm25`), defined in
    `camp/apps/entries/guidelines.py`. Activity keys are permanent, the text is verbatim from
    the old schools page, and the `/guidelines/` pages render from the same source.

  Add one line under the forecasts or place bullets: forecast `color` and `aqi_category` are
  the AQI scale level's color and label, computed from `aqi_value`; the stored `aqi_category`
  is only for the admin.
- [ ] **Step 2: Performance.** Repeat Task 0 Step 3 against `:8001`. Expected: the same
  query counts for every URL, and timings within noise (no more than about 10% slower, or say
  why). Put the before/after table in the PR description. No query changed, so no EXPLAIN is
  needed; say so.
- [ ] **Step 3: Full suite.** TEST `-n 4 --dist loadscope`, `tee`'d to a log in the scratchpad.
  Expected: all pass, with the count compared to Task 0.
- [ ] **Step 4: Push and open the PR into `develop`.**
  - Ask the user before pushing if they haven't already okayed it.
  - The PR body lists the response changes: `levels` removed; `school_guidelines` added;
    forecast `color` and `aqi_category`.
  - No attribution. Don't merge.
- [ ] **Step 5: Tell the coordinator** (data-dashboard-2c) that the PR is open, with its
  number and the response changes. Tell sdk-js-8c the same.
- [ ] **Step 6: data-dashboard docs.**
  - Work in `git -C /home/alex/workspace/sjvair/data-dashboard worktree add .worktrees/docs-hardcoded-cleanup origin/main`.
  - Follow its TODO.md "Docs rules": re-read before editing, run prettier, rebase, and push to
    `main`.
  - Changes:
    - DEFERRED.md → Mobile app → "Retire the old air-quality `levels` format": resolved by
      spec 5 (PR #N);
    - the TODO.md "Release 1, step 3" item: its status;
    - ARCHITECTURE.md → "Metadata as source of truth": the `school_guidelines` shape.
  - Tell the coordinator.
- [ ] **Step 7: Clean up.** `podman stop cleanup-web && podman rm cleanup-web`.
