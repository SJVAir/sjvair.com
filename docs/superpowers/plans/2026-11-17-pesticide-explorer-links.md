# Pesticide Explorer Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the explorer's section and chemical page links in `pesticides/meta/` (`links` +
`link_params`). Add the map's value filters and `month` to `pesticides/sections/<id>/`, opt-in.
Reword `notes.shades_valley`.

**Architecture:**
- A new `camp/apps/pesticides/links.py` holds the path templates. The explorer's
  `section_map_config` and the meta endpoint both read them.
- The value-filter half of `sections.apply_filters` and its `month` parsing become helpers, which
  the section-detail endpoint reuses.
- The record-key MAX counting in `stats.section_totals_by_record` is generalized to any group
  column (section, year, month, product).

**Tech Stack:** Django, django-resticus, PostGIS, pytest under podman.

**Spec:** `docs/superpowers/specs/2026-11-17-pesticide-explorer-links-design.md`

## Global Constraints

- The explorers must not change behaviour. `section_map_config` output stays identical.
  `sections/<id>/` responses with none of the new params stay byte-for-byte the same.
- Link keys (permanent): `section_page`, `section_records`, `section_notices`,
  `section_notices_past`, `chemical_page`. `spraydays_signup` is unchanged.
- Explorer paths are under `/tools/pesticides/` (from `reverse()`, never hand-written).
- Absolute URLs: `request.build_absolute_uri('/').rstrip('/')` + path. Never pass a `{id}`
  template to `build_absolute_uri`, which percent-encodes the braces.
- New `shades_valley` last sentence, verbatim: `An outline with no shading means nothing was reported.`
- No `county` in any link. `category`/`iarc_group` are on no link. `aerial_ground` and
  `commodity_id` are not on the notices links.
- `cache_key_version` of `SectionDetail` stays 1.
- No Claude/AI attribution in commits.

**Running tests (from the worktree; podman-compose doesn't work there).** First, once:
`cp ../../.env.test .` (gitignored; check with `git status` that it doesn't show).

```bash
podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 \
  -e TWILIO_AUTH_TOKEN=test-token -v "$PWD":/app:z -w /app sjvair-com-test:latest \
  pytest <path>[::<test>] -v 2>&1 | tee /tmp/claude-1000/-home-alex-workspace-sjvair-sjvair-com/316e03fa-bc62-41e5-92d7-c2e8669bd6e8/scratchpad/explorer-links-test.log
```

resticus hides tracebacks in tests (a bare `Http500`). When one appears, patch the view's
`server_error` to print the exception.

## Review Focus

1. **A `sections/<id>/` request that sends only `year`/`narrow`** (the explorer popup) must return
   exactly today's JSON. Task 3 pins it with a before/after equality test.
2. **`category` with several matching ingredients in one record** must not double-count acres,
   applications or product pounds in `years`, `months` or `top_products`. Task 3 checks them
   against `place/` and `sections/`.
3. **`month` must not narrow `months`.** It stays the year's 12 rows, while the top lists narrow.
   This is a Task 3 test.
4. **A bad value** (`month=13`, `chemical_id=zzz`, `category=nope`) must return 400
   `{"error": …}`, never a 500 or a silently unfiltered answer. These are Task 3 tests.
5. **`{id}` must stay literal braces in the absolute URLs**, not `%7Bid%7D`. This is a Task 1 test.

---

### Task 1: Link templates and `links`/`link_params` in meta

**Files:**
- Create: `camp/apps/pesticides/links.py`
- Modify: `camp/apps/pesticides/views.py` (`page_url_pattern` ~line 1199 moves out, and the 4
  template lines in `section_map_config` ~1266-1280)
- Modify: `camp/api/v2/pesticides/meta.py`
- Test: `camp/api/v2/pesticides/tests.py` (`PesticidesMetaTests`),
  `camp/apps/pesticides/tests/test_views.py`

**Interfaces:**
- Produces (in `links.py`):
  - `page_url_pattern(name: str) -> str`, moved verbatim from views. `views.py` imports it back
    so existing callers and tests keep working.
  - `SECTION_PAGE()`, `SECTION_RECORDS()`, `SECTION_NOTICES()`, `SECTION_NOTICES_PAST()`,
    `CHEMICAL_PAGE()`: zero-arg functions returning site-relative templates. `reverse()` needs the
    URLconf loaded, so these can't be module constants.
  - `LINK_PARAMS: dict[str, list[dict]]`, exactly the spec's `link_params` table.
  - `explorer_links(request) -> dict[str, str]`: the five keys mapped to absolute URLs.

- [ ] **Step 1: Write the failing tests**

In `test_views.py`, add `test_section_map_config_links_unchanged`. It pins today's values as
literals, before any refactor:

```python
config = views.section_map_config(2023, concern='concern', section_notices_extra='past=1&archive_year=2026&month=3')
assert config['section_page_url'] == '/tools/pesticides/sections/{id}/'
assert config['section_records_url'] == '/tools/pesticides/records/?section={id}&year=2023&narrow=concern'
assert config['section_notices_url'] == '/tools/pesticides/notices/?section={id}&year=2023&narrow=concern&past=1&archive_year=2026&month=3'
assert config['chemical_page_url'] == '/tools/pesticides/chemicals/{id}/'
assert views.section_map_config(2023)['section_records_url'].startswith('/tools/pesticides/records/?section={id}')
```

Run it first against the unmodified code and adjust the literals to what it actually returns.
`year=2023` appears only when 2023 isn't the fixture's default year. The test pins today's
behaviour; it does not define new behaviour.

In `PesticidesMetaTests`:
- `test_shape` gains `'link_params'` in the key set.
- Add `test_meta_explorer_links`:

```python
data = self.get()
origin = 'http://testserver'
assert data['links'] == {
    'spraydays_signup': SPRAYDAYS_URL,
    'section_page': f'{origin}/tools/pesticides/sections/{{id}}/',
    'section_records': f'{origin}/tools/pesticides/records/?section={{id}}',
    'section_notices': f'{origin}/tools/pesticides/notices/?section={{id}}',
    'section_notices_past': f'{origin}/tools/pesticides/notices/?section={{id}}&past=1',
    'chemical_page': f'{origin}/tools/pesticides/chemicals/{{id}}/',
}
assert set(data['link_params']) == set(data['links']) - {'spraydays_signup'}
assert data['link_params']['section_records'] == [
    {'param': 'year', 'from': 'year'}, {'param': 'start', 'from': 'month_start'},
    {'param': 'end', 'from': 'month_end'}, {'param': 'chemical', 'from': 'chemical_id'},
    {'param': 'product', 'from': 'product_id'}, {'param': 'commodity', 'from': 'commodity_id'},
    {'param': 'method', 'from': 'aerial_ground'}, {'param': 'narrow', 'from': 'narrow'}]
assert data['link_params']['section_notices_past'][:2] == [
    {'param': 'archive_year', 'from': 'notices_year'}, {'param': 'month', 'from': 'notices_month'}]
for entries in data['link_params'].values():
    assert not {e['from'] for e in entries} & {'county', 'category', 'iarc_group'}
```

- Add `test_meta_links_open_the_pages`: fill `section_records` with a fixture section's sqid and
  `section_page` with the same sqid. GET their paths with a beta-tools user and assert 200. Follow
  the explorer views' own tests to see how they log in a beta user. Also fill `chemical_page` and
  assert a 301 to the chemical's slugged URL, with the query string carried along.

- [ ] **Step 2: Run them to verify the meta ones fail** (the `test_views` one passes: it pins today)

- [ ] **Step 3: Implement `links.py`, then switch `section_map_config` and meta to it**

In `section_map_config`:
- `section_page_url` = `SECTION_PAGE()`.
- `section_records_url` = `SECTION_RECORDS() + scope_suffix`.
- `section_notices_url` = `SECTION_NOTICES() + scope_suffix + extra`.
- `chemical_page_url` = `CHEMICAL_PAGE()`.

`SECTION_NOTICES_PAST()` = `SECTION_NOTICES() + '&past=1'`.

In meta:
- `'links': {'spraydays_signup': SPRAYDAYS_URL, **explorer_links(request)}`, plus
  `'link_params': LINK_PARAMS`.
- Extend the docstring: the five keys, `{id}` = sqid, the fill rule, the `from` values, which
  notices link to use, and what's left off. Keep it to the spec's wording.

- [ ] **Step 4: Run `camp/api/v2/pesticides/tests.py::PesticidesMetaTests` and `camp/apps/pesticides/tests/test_views.py`; expect all PASS**

- [ ] **Step 5: Commit** `Meta links: explorer section and chemical page templates with link_params`

### Task 2: Shared filter helpers and record-key counting

**Files:**
- Modify: `camp/api/v2/pesticides/sections.py` (`apply_filters` ~line 94)
- Modify: `camp/apps/pesticides/stats.py` (`section_totals_by_record` ~line 949)
- Test: `camp/apps/pesticides/tests/test_stats.py`

**Interfaces:**
- Produces:
  - `sections.parse_month(params) -> tuple[int | None, str | None]`: `(month, None)`,
    `(None, None)` when absent, or `(None, 'month must be 1-12')`.
  - `sections.apply_map_filters(rows, filters: dict) -> QuerySet`: the `*_id`, `aerial_ground`,
    `category` and `iarc_group` part of `apply_filters`, moved out unchanged.
    `apply_filters` calls both helpers.
  - `stats.totals_by_record(rows, group: str) -> dict`, with `{group value: {'lbs_chemical',
    'lbs_product', 'acres_treated', 'applications'}}`. It runs the same SQL as today's
    `section_totals_by_record`, with `g.<group>` in place of `g.mtrs`. `group` must be one of
    `_RECORD_KEY`; assert it, because it's interpolated into SQL.
    `section_totals_by_record(rows)` becomes `totals_by_record(rows, 'mtrs')`.

- [ ] **Step 1: Write the failing test** `test_totals_by_record_groups`. On the
  `pesticides-explorer` fixture with `RollupTestMixin`, the rows narrowed to `category=carcinogen`:
  - `totals_by_record(rows, 'mtrs') == section_totals_by_record(rows)`
  - the `'year'` group's latest-year entry equals `place/`'s figures for that year, as
    `MapCategoryFilterTests.place()` reads them.
- [ ] **Step 2: Run it; expect FAIL** (`totals_by_record` is not defined)
- [ ] **Step 3: Implement the three helpers**
- [ ] **Step 4: Run `test_stats.py`, `MapCategoryFilterTests`, `MapIdFilterTests` and `SectionEndpointTests`; expect all PASS** (they cover the old behaviour)
- [ ] **Step 5: Commit** `Sections: month and map-filter helpers; record-key totals by any group`

### Task 3: Filters on `sections/<id>/`

**Files:**
- Modify: `camp/api/v2/pesticides/sections.py` (`SectionDetailBase.get` ~line 475, the
  `SectionDetail` docstring)
- Test: `camp/api/v2/pesticides/tests.py`, in a new `SectionDetailFilterTests(RollupTestMixin,
  TestCase)` with `fixtures = ['pesticides-explorer']` and section pk 9101

**Interfaces:**
- Consumes: `parse_month`, `apply_map_filters`, `parse_map_filters(params, ROLLUP_MAP_FILTERS)`,
  `chemical_scoped`, `counts_by_record`, and `stats.totals_by_record` (Task 2).

**Behaviour in `get`, in order:**
1. `filters, error = parse_map_filters(...)`, then `month, error = parse_month(...)`. Either error
   returns `bad_request(error)`.
2. `rows = apply_map_filters(rows, filters)`, after the existing narrow.
3. Pick the counting mode:
   - **No filters:** today's code exactly (`TOTALS`, `by_month(rows, year, …)`, today's `top`
     calls). The explorer depends on this.
   - **`chemical_id` given:** `years` uses `totals_aggregates(True)`. `months` uses
     `by_month(..., apps_field='applications')`. Top products use `lbs_field='lbs_product'`.
   - **Category or IARC group without a chemical:** use `counts_by_record`. `years` comes from
     `totals_by_record(rows, 'year')`, newest first. `months` comes from
     `totals_by_record(in_year(rows), 'month')`, zero-filled for 1-12, with month 0 left out (as
     `by_month` does). Top products rank `totals_by_record(in_year(rows), 'product')` by
     `lbs_product`, with limit 5 and the same entry shape. Load the products with
     `Product.objects.with_restricted().in_bulk`.
   - **Any other filter:** today's columns.
4. `month`: the top lists read `rows.filter(month=month)`. `years` and `months` don't.

`years` rows keep today's keys (`year`, `lbs_chemical`, `lbs_product`, `acres_treated`,
`applications`). `months` rows keep `month`, `lbs_chemical`, `acres_treated`, `applications`.

- [ ] **Step 1: Write the failing tests**
  - `test_unfiltered_unchanged`: for `{}`, `{'year': <latest>}`, `{'year': 'all'}` and
    `{'narrow': 'concern'}`, `response.content` is byte-equal to a pinned copy. **Before touching
    the view**, run these four requests once against the unmodified code. Save each
    `response.content.decode()` to
    `camp/api/v2/pesticides/testdata/section-detail-unfiltered.json` (one key per param set; the
    fixture data is deterministic). The test compares against that file. Commit the file with the
    test. Call `cache.clear()` between requests.
  - `test_category_matches_place`: with `category=carcinogen`, the latest year's `years` entry
    and each month's `months` entry equal `place/`'s figures for section 9101 (`pounds`→
    `lbs_chemical`, `acres`→`acres_treated`, `applications`).
  - `test_category_top_products_count_once`: with `category=carcinogen`, the sum of
    `top_products[].lbs` equals the `sections/` feature's `lbs_product` for the same filter,
    when fewer than 5 products come back.
  - `test_chemical_id_matches_sections`: the `years` entry equals the `sections/` feature's
    figures for `chemical_id=<sqid>`.
  - `test_month_narrows_top_lists_only`: with `month=m` (a fixture month with use), `months` has
    12 rows equal to the no-month response's, and `top_chemicals` equals the explorer list ranked
    on that month's rows.
  - `test_bad_values_400`: `month=13` gives `month must be 1-12`. `chemical_id=zzz` gives
    `Not a chemical id.`. An unknown `category` returns 400. `chemical=1&chemical_id=<sqid>` gives
    `give chemical or chemical_id, not both`.
  - `test_cache_keys_by_filter`: GET without filters, then with `category=carcinogen`. The second
    answer differs (`top_chemicals` narrowed), so the cache didn't serve the first.
- [ ] **Step 2: Run them; expect FAIL** (filters ignored)
- [ ] **Step 3: Implement**, then update the `SectionDetail` docstring with the new params, the
  counting rule and "month narrows the top lists only".
- [ ] **Step 4: Run `SectionDetailFilterTests`, `ConcernScopeEndpointTests`,
  `NarrowEndpointTests`, `SectionEndpointTests`; expect all PASS**
- [ ] **Step 5: Commit** `Section detail takes the map's value filters and month, opt-in`

### Task 4: `shades_valley` wording and docs

**Files:**
- Modify: `datafiles/pesticide-health-notes.yaml:77`, `camp/api/v2/pesticides/tests.py:2402`,
  `CLAUDE.md` (the `pesticides/meta/` text in Metadata Endpoints, and the `sections/<id>/`
  mention in the Pesticide map bullet)

- [ ] **Step 1: Change the test's expected last sentence** to `An outline with no shading means nothing was reported.`. Run `test_meta_years_and_ramp` and expect FAIL.
- [ ] **Step 2: Change the YAML's last sentence the same way.** Run it and expect PASS.
  `notes.shades` is untouched; the existing assertion on it still holds.
- [ ] **Step 3: CLAUDE.md.**
  - In the `pesticides/meta/` text, `links` becomes: `spraydays_signup` plus the five absolute
    explorer templates (`{id}` = sqid, the keys), and `link_params` (`[{param, from}]` per link).
    Add the fill rule, the `from` values, the notices rule (past template when the notices layer
    is on and showing a past day) and what's left off. Wrap at the file's width.
  - In the Pesticide map bullet, add: `sections/<id>/` takes the `*_id`, `category`,
    `iarc_group`, `aerial_ground` and `month` filters, counted like `sections/`. `month` narrows
    the top lists only. A request without them is unchanged.
- [ ] **Step 4: Full suite**
  `pytest -n 4 --dist loadscope` (same podman command). Expect all pass. Tee the output and record
  the pass count.
- [ ] **Step 5: Commit** `shades_valley without a colour; docs for explorer links and section-detail filters`
