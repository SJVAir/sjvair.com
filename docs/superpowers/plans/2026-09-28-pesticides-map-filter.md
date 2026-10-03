# Pesticides map-as-filter Implementation Plan

> **Shelved 2026-09-28** -- see the note at the top of the spec. Built in beb3def5 and taken back out in the next commit.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking one square-mile section on the Map page or a chemical / product / commodity page narrows that page to the section.

**Architecture:** A click in "filter mode" navigates to the same URL plus `?section=<sqid>` via the explorer's boosted htmx swap. The server re-renders the page narrowed to the section; the running map is adopted in place (not rebuilt) and keeps its camera. Narrowing is one more filter (`mtrs=`) on the rollup the pages already aggregate; the Map page gains a panel built from the section detail page's own (now shared) aggregation and markup.

**Tech Stack:** Django 5 / PostGIS, django-vanilla-views, htmx 2 (boosted `#explorer`), MapTiler SDK (MapLibre) in `assets/js/pesticides/section-map.js`, Bulma.

**Spec:** `docs/superpowers/specs/2026-09-28-pesticides-map-filter-design.md`

## Global Constraints

- Worktree: `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer`, branch `feature/pesticides-explorer`. Every command and edit happens there, never in the main checkout.
- **Do not commit or push.** Derek commits when he says so. (The "Commit" steps of the standard template are replaced by "leave uncommitted".)
- Tests: Django `TestCase`, plain `assert`, fixture `pesticides-explorer`, `RollupTestMixin`. Run with the worktree harness:
  ```
  docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml \
    --project-directory /home/derek/dev/ccac/sjvair.com \
    run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_mapfilter \
    -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer:/app \
    test pytest <paths> -q -p no:cacheprovider --create-db
  ```
  (Below, `HARNESS <paths>` means exactly this command.)
- One section at a time; townships never filter. Filter mode only where `section_map_config(..., select='filter')` is passed: the Map page and the three entity detail views. Every other map keeps today's popup.
- The section belongs to the page (not `scope_qs`, not the scope bar). The scope bar's `qs_replace` links keep it on a year/county change for free.
- Products before chemicals wherever both appear.
- The dev server for this worktree is on port 8002; static JS is not cache-busted (hard-refresh after JS edits).
- No AI-authorship attribution anywhere.

## Review Focus

1. **A grid rebuild must never re-navigate.** `reopenGridPopup` / `reopenSelectedSection` call `showSectionPopup`; in filter mode that navigates. The label popup uses its own key (`openFilterId`) and the selection state (`selectedSectionId`) is never set in filter mode, so neither reopen path fires. Covered by the smoke check (a filter click is followed by a settle with no further URL change).
2. **Clicking the selected section again clears it**, rather than re-requesting the same URL. Covered in Task 4's smoke check.
3. **A section and a county scope that don't intersect** (Kern section, `?county=fresno`) render the empty states, not an error. Covered in Task 2's tests.
4. **An unknown / non-MTRS `?section=`** (a county sqid) gives the "no matches" notice and no unfiltered numbers, on both the entity pages and the Map page. Covered in Tasks 2 and 3.
5. **Back / forward** across selections restores a live, single map instance with the right outline. Covered in Task 4's smoke check.

---

## File Structure

- `camp/apps/pesticides/views.py`: `section_map_config(select=)`; new `section_county_name()`, `section_summary()`, `section_filter_context()`; `SectionDetail` uses the shared summary; `ExplorerDetailMixin` learns `?section=`; `MapPage` gains the section panel.
- `camp/templates/pesticides/includes/section-stats.html` (new): the section stat row.
- `camp/templates/pesticides/includes/section-summary.html` (new): month bars through the records button, lifted out of `section-detail.html`.
- `camp/templates/pesticides/section-detail.html`: uses the two includes.
- `camp/templates/pesticides/detail-base.html`: the "Narrowed to Section …" banner.
- `camp/templates/pesticides/map.html`: the section panel.
- `camp/templates/pesticides/includes/map-toolbar.html`: carries `section` through the entity pickers.
- `assets/js/pesticides/section-map.js`: filter mode.
- `scripts/pesticides_map_smoke.py`: a filter-click check; popup checks skip filter-mode maps.
- Tests: `camp/apps/pesticides/tests/test_views.py` (new `SectionFilterDetailTests`, `SectionFilterMapPageTests`), `camp/apps/pesticides/tests/test_sections.py` (unchanged; the regression guard for the refactor).

---

### Task 1: Shared section summary + `select` on the map config

**Files:**
- Modify: `camp/apps/pesticides/views.py` (`section_map_config` ~l.1119; `SectionDetail` ~l.1688)
- Create: `camp/templates/pesticides/includes/section-stats.html`, `camp/templates/pesticides/includes/section-summary.html`
- Modify: `camp/templates/pesticides/section-detail.html`
- Test: `camp/apps/pesticides/tests/test_views.py`, `camp/apps/pesticides/tests/test_sections.py`

**Interfaces:**
- Produces:
  - `section_map_config(year, *, ..., select=None)`; `config['select']` is `'filter'` or `''`, emitted as `data-select`.
  - `section_county_name(section) -> str | None`: the section's county name, from its rollup rows.
  - `section_summary(rows, year, all_years, records_url, lbs_field='lbs_chemical') -> dict` with keys `totals, chemical_count, by_year, by_month, by_year_month, peak_month, top_chemicals, top_products, top_commodities, chemicals_card, products_card, commodities_card, records_url, years`.
  - Includes `section-stats.html` (needs `totals`, `chemical_count`, `year_label`) and `section-summary.html` (needs the summary keys plus `upcoming`, `upcoming_days`, `upcoming_count`, `year`, `year_label`).

- [ ] **Step 1: Write the failing test**

Add to `camp/apps/pesticides/tests/test_views.py` (a new class at the end of the file):

```python
class SectionMapSelectTests(RollupTestMixin, TestCase):
    """`select='filter'` is how a page opts its section map into click-to-filter."""
    fixtures = ['pesticides-explorer']

    def test_select_defaults_off_and_is_emitted(self):
        assert views.section_map_config(2023)['select'] == ''
        config = views.section_map_config(2023, select='filter')
        assert config['select'] == 'filter'
        assert config['map']['data']['select'] == 'filter'

    def test_section_summary_matches_the_section_page(self):
        section = Region.objects.get(pk=9101)
        rows = PesticideUseRollup.objects.filter(mtrs=section)
        summary = views.section_summary(rows, 2023, False, '/records/')
        assert summary['totals']['lbs'] == 670.0
        assert [r.obj.name for r in summary['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert summary['peak_month'] == 'August'
        assert summary['products_card']['show_all_url'] == '/records/'
        assert views.section_county_name(section) == 'Fresno County'
```

(If `config['map']['data']` isn't how `mapconfig.map_config` exposes the data dict, assert on the rendered container instead: `'data-select="filter"' in` the HTML of a page that passes it. Check `camp/utils/mapconfig.py` first.)

- [ ] **Step 2: Run to verify it fails**

Run: `HARNESS camp/apps/pesticides/tests/test_views.py::SectionMapSelectTests`
Expected: FAIL: `KeyError: 'select'` / `AttributeError: ... 'section_summary'`.

- [ ] **Step 3: Implement**

In `section_map_config`, add the keyword `select=None` to the signature and this entry to `config` (after `'highlight'`):

```python
        # 'filter': a click on a section narrows the page to it (the map
        # page and the entity pages) instead of opening its popup.
        'select': select or '',
```

Add near `_section_card` (before it):

```python
def section_county_name(section):
    """The county a section's use was reported in, off its rollup rows."""
    return (
        PesticideUseRollup.objects.filter(mtrs=section)
        .exclude(county__isnull=True)
        .order_by('county__name')
        .values_list('county__name', flat=True)
        .first()
    )


def section_summary(rows, year, all_years, records_url, lbs_field='lbs_chemical'):
    """
    The section page's numbers for `rows`: rollup rows already narrowed to
    one section, and on the map page to its entity filter and scope too.
    SectionDetail and the map page's section panel both render them, through
    includes/section-stats.html and includes/section-summary.html.
    A single section is at most a few thousand rollup rows even across every
    loaded year, so these stay live aggregates.
    """
    if year or all_years:
        totals = stats.year_totals(rows, year, lbs_field, all_years=all_years)
        by_month = stats.by_month(rows, year, lbs_field, all_years=all_years)
        chemical_count = (
            stats.real_chemicals(stats.in_year(rows, year, all_years))
            .filter(chemical__isnull=False).values('chemical').distinct().count()
        )
    else:
        totals = {'lbs': 0, 'applications': 0, 'counties': 0}
        by_month = []
        chemical_count = 0

    peak_month = None
    if by_month and any(month['lbs'] for month in by_month):
        peak = max(by_month, key=lambda month: month['lbs'])
        peak_month = calendar.month_name[peak['month']]

    top_chemicals = stats.top_related(rows, year, 'chemical', limit=stats.RELATED_LIMIT, all_years=all_years)
    top_products = stats.top_related(rows, year, 'product', lbs_field='lbs_product', limit=stats.RELATED_LIMIT, all_years=all_years)
    top_commodities = stats.top_related(rows, year, 'commodity', limit=stats.RELATED_LIMIT, all_years=all_years)
    return {
        'totals': totals,
        'chemical_count': chemical_count,
        'years': stats.years_loaded(),
        'by_year': stats.by_year(rows, lbs_field),
        'by_month': by_month,
        'by_year_month': stats.by_year_month(rows, lbs_field),
        'peak_month': peak_month,
        'top_chemicals': top_chemicals,
        'top_products': top_products,
        'top_commodities': top_commodities,
        'chemicals_card': _section_card('Top chemicals', 'chemicals', top_chemicals, records_url),
        'products_card': _section_card('Top products', 'products', top_products, records_url),
        'commodities_card': _section_card('Top commodities', 'commodities', top_commodities, records_url),
        'records_url': records_url,
    }
```

Rewrite `SectionDetail.get_context_data` to use it (behaviour identical; `county_name` now comes from `section_county_name`, which ignores the concern narrowing, which is correct since the county is a fact about the square):

```python
    def get_context_data(self, **kwargs):
        section = self.object
        year, all_years = stats.resolve_year_param(self.request.GET.get('year'))
        concern = scope_concern(self.request)
        rows = PesticideUseRollup.objects.filter(mtrs=section)
        if concern:
            rows = stats.narrow_rows(rows, concern)

        notices = PesticideNotice.objects.filter(mtrs=section)
        upcoming_days = stats.upcoming_by_day(notices)

        year_param = stats.year_param(year, all_years)
        records_url = reverse('pesticides:records') + f'?section={section.sqid}' + (
            f'&{year_param}' if year_param else ''
        ) + (f'&{stats.CONCERN_PARAM}=1' if concern else '')

        center = zoom = None
        if section.boundary_id:
            center, zoom = centroid(section), 13
        map_config = section_map_config(
            year, center=center, zoom=zoom, highlight=section.sqid, all_years=all_years, concern=concern,
        )

        return super().get_context_data(
            section='sections',
            county_name=section_county_name(section),
            **year_context(year, all_years, scope_county(self.request), county_scope=False, concern=concern),
            **section_summary(rows, year, all_years, records_url),
            upcoming=stats.notices_in_days(upcoming_days),
            upcoming_days=upcoming_days,
            upcoming_count=stats.upcoming_count(notices),
            map_config=map_config,
            api_docs_url=API_DOCS_URL,
            client_docs_url=CLIENT_DOCS_URL,
            **kwargs,
        )
```

Templates: cut from `section-detail.html` the `<div class="level stat-row box">…</div>` block into `includes/section-stats.html` verbatim, and everything from `<section class="month-bars-section mt-6">` through the closing `</div>` of `<div class="buttons mt-6 explorer-actions">` into `includes/section-summary.html` verbatim (it needs `{% load pesticides_explorer %}` at its top for `month_chart`/`month_heatmap`/`lbs`). Put a short `{% comment %}` at the top of each: "Shared by the section page and the map page's section panel; context from views.section_summary() plus upcoming/upcoming_days/upcoming_count and year_label." `section-detail.html` becomes:

```django
<div class="content detail-header">…unchanged…</div>

{% include 'pesticides/includes/section-stats.html' %}

{% include 'pesticides/includes/section-map.html' %}

{% include 'pesticides/includes/section-summary.html' %}

<footer class="sources mt-6 …">…unchanged…</footer>
```

- [ ] **Step 4: Run to verify it passes, plus the section page's own tests**

Run: `HARNESS camp/apps/pesticides/tests/test_views.py::SectionMapSelectTests camp/apps/pesticides/tests/test_sections.py`
Expected: all PASS (the section tests are the refactor's regression guard; none may change).

- [ ] **Step 5: Leave uncommitted.**

---

### Task 2: Entity detail pages narrow to `?section=`

**Files:**
- Modify: `camp/apps/pesticides/views.py` (`ExplorerDetailMixin` ~l.777–990)
- Modify: `camp/templates/pesticides/detail-base.html`
- Test: `camp/apps/pesticides/tests/test_views.py`

**Interfaces:**
- Consumes: `section_map_config(select=)`, `section_county_name()` (Task 1); existing `resolve_related`, `SECTION_REGIONS`, `MISSING`, `clear_url`, `centroid`.
- Produces: `section_filter_context(request, section, scope) -> dict` with keys `sqid, external_id, county, page_url, clear_url` (used by Task 3 too). Context keys on entity pages: `section_filter` (that dict or None), `section_missing` (bool).

- [ ] **Step 1: Write the failing tests**

```python
class SectionFilterDetailTests(RollupTestMixin, TestCase):
    """`?section=` narrows a chemical/product/commodity page to one square mile."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.section = Region.objects.get(pk=9101)          # Fresno
        self.kern_section = Region.objects.get(pk=9102)     # Kern
        self.chemical = Chemical.objects.get(pk=1)

    def lbs(self, **filters):
        return PesticideUseRollup.objects.filter(year=2023, **filters).aggregate(n=Sum('lbs_chemical'))['n'] or 0

    def get(self, obj, **params):
        return self.client.get(obj.get_absolute_url(), params)

    def test_chemical_page_narrows_to_the_section(self):
        ctx = self.get(self.chemical, section=self.section.sqid).context
        assert ctx['totals']['lbs'] == self.lbs(chemical=self.chemical, mtrs=self.section)
        assert ctx['totals']['lbs'] < self.lbs(chemical=self.chemical)
        assert ctx['section_filter']['sqid'] == self.section.sqid
        assert ctx['section_filter']['county'] == 'Fresno County'
        assert ctx['summary_sentence'].startswith(f'Applied in Section {self.section.external_id} in ')

    def test_product_and_commodity_pages_narrow_too(self):
        for obj, field, lbs_field in (
            (Product.objects.filter(pesticideuserollup__mtrs=self.section).distinct().first(), 'product', 'lbs_product'),
            (Commodity.objects.filter(pesticideuserollup__mtrs=self.section).distinct().first(), 'commodity', 'lbs_chemical'),
        ):
            expected = PesticideUseRollup.objects.filter(
                year=2023, mtrs=self.section, **{field: obj},
            ).aggregate(n=Sum(lbs_field))['n']
            assert self.get(obj, section=self.section.sqid).context['totals']['lbs'] == expected

    def test_county_blocks_are_hidden(self):
        response = self.get(self.chemical, section=self.section.sqid)
        assert response.context['by_county'] == []
        assert response.context['movers'] is None
        assert response.context['county_map'] is None
        assert 'by-county-table' not in response.content.decode()

    def test_links_out_carry_the_section(self):
        ctx = self.get(self.chemical, section=self.section.sqid, year=2022).context
        suffix = f'section={self.section.sqid}'
        for url in (ctx['records_url'], ctx['notices_url'], ctx['full_map_url']):
            assert suffix in url
        # "Show all" goes to the records browser: the list pages don't take a section.
        for card in (ctx['related_a'], ctx['related_b']):
            if not card['complete']:
                assert card['show_all_url'].startswith(reverse('pesticides:records'))
                assert suffix in card['show_all_url'] and 'year=2022' in card['show_all_url']

    def test_map_is_in_filter_mode_and_framed_on_the_section(self):
        cfg = self.get(self.chemical, section=self.section.sqid).context['map_config']
        assert cfg['select'] == 'filter'
        assert cfg['highlight'] == self.section.sqid
        assert cfg['zoom'] == 13 and cfg['center'] == views.centroid(self.section)
        # Unnarrowed, still filter mode, framed on the valley.
        cfg = self.get(self.chemical).context['map_config']
        assert cfg['select'] == 'filter' and cfg['highlight'] == '' and cfg['fit'] == 'valley'

    def test_banner_and_clear_link(self):
        html = self.get(self.chemical, section=self.section.sqid, year=2022).content.decode()
        assert 'section-filter-banner' in html
        assert f'Section {self.section.external_id}' in html
        # Clear keeps the scope and drops only the section.
        assert f'href="{self.chemical.get_absolute_url()}?year=2022"' in html

    def test_bad_section_is_no_match_not_unfiltered(self):
        county = Region.objects.get(pk=9001)
        for value in (county.sqid, 'nope'):
            response = self.get(self.chemical, section=value)
            assert response.status_code == 200
            assert response.context['section_missing'] is True
            assert response.context['totals']['lbs'] in (0, None)
            assert 'No section matches that link' in response.content.decode()

    def test_section_outside_the_county_scope_is_empty_not_an_error(self):
        response = self.get(self.chemical, section=self.kern_section.sqid, county='fresno')
        assert response.status_code == 200
        assert not response.context['totals']['applications']

    def test_no_section_is_unchanged(self):
        ctx = self.get(self.chemical).context
        assert ctx['section_filter'] is None and ctx['section_missing'] is False
        assert ctx['by_county']
```

(If `Product`/`Commodity` have a different reverse name to the rollup than `pesticideuserollup`, find it with `PesticideUseRollup._meta.get_field('product').related_query_name()` and use that. If the fixture's chemical 1 has no use outside 9101 in 2023, swap the `<` assertion for a chemical that does; check `self.lbs(chemical=...)` in a shell first.)

- [ ] **Step 2: Run to verify they fail**

Run: `HARNESS camp/apps/pesticides/tests/test_views.py::SectionFilterDetailTests`
Expected: FAIL: `KeyError: 'section_filter'` and unnarrowed totals.

- [ ] **Step 3: Implement**

Module-level helper (next to `section_county_name`):

```python
def section_filter_context(request, section, scope=''):
    """What a page narrowed to one section says about it: the banner (entity
    pages) and the panel heading (map page)."""
    return {
        'sqid': section.sqid,
        'external_id': section.external_id,
        'county': section_county_name(section),
        'page_url': reverse('pesticides:section-detail', kwargs={'sqid': section.sqid}) + (f'?{scope}' if scope else ''),
        'clear_url': clear_url(request, 'section'),
    }
```

`ExplorerDetailMixin` changes:

1. Class attribute beside `concern = False`:
   ```python
       # The one square-mile section a map click narrowed the page to
       # (?section=): None, a Region, or MISSING for a sqid that isn't one.
       mtrs = None
   ```
2. `get_rollup()`: first thing after building `rows`:
   ```python
        if self.mtrs is MISSING:
            return rows.none()
        if self.mtrs is not None:
            rows = rows.filter(mtrs=self.mtrs)
   ```
3. A helper:
   ```python
    def section_param(self):
        """'section=<sqid>' when the page is narrowed to a section, else ''."""
        return f'section={self.mtrs.sqid}' if self.mtrs not in (None, MISSING) else ''
   ```
4. `cached_stat`: a narrowed page aggregates live (at most a few thousand rows). First line:
   ```python
        if self.mtrs is not None:
            return build()
   ```
5. `related_card`: after computing `scope`, replace the `show_all_url` value with:
   ```python
        if self.section_param():
            # The list pages don't take a section; the records browser does.
            show_all_url = reverse('pesticides:records') + f'?{self.use_field}={self.object.sqid}&{self.section_param()}'
        else:
            show_all_url = reverse(list_url_name) + f'?{param}={self.object.sqid}'
        show_all_url += f'&{scope}' if scope else ''
   ```
   and use `'show_all_url': show_all_url` in the returned dict.
6. `get_summary_sentence`: the first branch becomes
   ```python
        if self.mtrs not in (None, MISSING):
            sentence = f'Applied in Section {self.mtrs.external_id} in {label}'
        elif self.county is not None:
   ```
7. `get_context_data`:
   - Right after `self.county = scope_county(self.request)`:
     ```python
        self.mtrs = resolve_related(self.request.GET, {'section': SECTION_REGIONS}).get('section')
        narrowed = self.mtrs is not None
     ```
   - After `notices = self.get_notices()`:
     ```python
        if self.mtrs is MISSING:
            notices = notices.none()
        elif narrowed:
            notices = notices.filter(mtrs=self.mtrs)
        section_qs = f'&{self.section_param()}' if self.section_param() else ''
     ```
   - `by_county=` becomes `[] if narrowed else self.cached_stat('by_county', ...)` (a section lies in one county; there is nothing to compare).
   - `records_url=` gains `+ section_qs` after the entity param; the `notices_url` expression gains `+ section_qs` after the entity param; `full_map_url` gains `+ section_qs` after the entity param.
   - After the `super().get_context_data(...)` call:
     ```python
        context['section_filter'] = section_filter_context(self.request, self.mtrs, scope) if self.mtrs not in (None, MISSING) else None
        context['section_missing'] = self.mtrs is MISSING
     ```
   - The `section_map_config(...)` call gains `select='filter'` and `**self.section_map_kwargs()`, with:
     ```python
    def section_map_kwargs(self):
        """Frame a fresh load of a narrowed page on its section, outlined."""
        if self.mtrs in (None, MISSING):
            return {}
        kwargs = {'highlight': self.mtrs.sqid}
        if self.mtrs.boundary_id:
            kwargs['center'], kwargs['zoom'] = centroid(self.mtrs), 13
        return kwargs
     ```
   - `context['movers'] = None if narrowed else movers_context(...)`.

`detail-base.html`: directly after the closing `</div>` of `.detail-header`:

```django
{% if section_filter %}
<div class="notification is-info is-light section-filter-banner">
    Narrowed to <strong>Section {{ section_filter.external_id }}</strong>{% if section_filter.county %} ({{ section_filter.county }}){% endif %}
    &middot; <a href="{{ section_filter.page_url }}">Section details</a>
    &middot; <a href="{{ section_filter.clear_url }}">Clear</a>
</div>
{% elif section_missing %}
<p class="notification is-warning is-light">No section matches that link.</p>
{% endif %}
```

- [ ] **Step 4: Run to verify they pass, plus every existing view test**

Run: `HARNESS camp/apps/pesticides/tests/test_views.py camp/apps/pesticides/tests/test_sections.py`
Expected: all PASS.

- [ ] **Step 5: Leave uncommitted.**

---

### Task 3: Map page section panel

**Files:**
- Modify: `camp/apps/pesticides/views.py` (`MapPage` ~l.1196)
- Modify: `camp/templates/pesticides/map.html`, `camp/templates/pesticides/includes/map-toolbar.html`
- Test: `camp/apps/pesticides/tests/test_views.py`

**Interfaces:**
- Consumes: `section_summary`, `section_filter_context`, `section_map_config(select=)` (Tasks 1–2).
- Produces: context keys on the Map page: `selected_section` (dict from `section_filter_context` or None), plus the `section_summary` keys and `upcoming`/`upcoming_days`/`upcoming_count` when a section is selected.

- [ ] **Step 1: Write the failing tests**

```python
class SectionFilterMapPageTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:map')
        self.section = Region.objects.get(pk=9101)
        self.chemical = Chemical.objects.get(pk=1)

    def test_no_section_no_panel(self):
        response = self.client.get(self.url)
        assert response.context['selected_section'] is None
        assert 'id="section-panel"' not in response.content.decode()
        assert response.context['map_config']['select'] == 'filter'

    def test_section_renders_the_panel(self):
        response = self.client.get(self.url, {'section': self.section.sqid})
        ctx = response.context
        assert ctx['selected_section']['sqid'] == self.section.sqid
        assert ctx['totals']['lbs'] == 670.0
        assert [r.obj.name for r in ctx['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert ctx['map_config']['highlight'] == self.section.sqid
        html = response.content.decode()
        assert 'id="section-panel"' in html and f'Section {self.section.external_id}' in html
        # Products before chemicals.
        assert html.index('Top products') < html.index('Top chemicals')

    def test_panel_honours_the_entity_filter(self):
        ctx = self.client.get(self.url, {'section': self.section.sqid, 'chemical': self.chemical.sqid}).context
        expected = PesticideUseRollup.objects.filter(
            year=2023, mtrs=self.section, chemical=self.chemical,
        ).aggregate(n=Sum('lbs_chemical'))['n']
        assert ctx['totals']['lbs'] == expected
        assert f'chemical={self.chemical.sqid}' in ctx['records_url']
        assert f'section={self.section.sqid}' in ctx['records_url']

    def test_section_chip_and_toolbar_keep_the_section(self):
        html = self.client.get(self.url, {'section': self.section.sqid}).content.decode()
        assert f'<input type="hidden" name="section" value="{self.section.sqid}">' in html
        chips = self.client.get(self.url, {'section': self.section.sqid}).context['filters']
        assert any(chip['label'] == f'Section {self.section.external_id}' for chip in chips)

    def test_bad_section_is_no_match(self):
        county = Region.objects.get(pk=9001)
        response = self.client.get(self.url, {'section': county.sqid})
        assert response.context['no_matches'] is True
        assert response.context['selected_section'] is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `HARNESS camp/apps/pesticides/tests/test_views.py::SectionFilterMapPageTests`
Expected: FAIL: `KeyError: 'selected_section'`.

- [ ] **Step 3: Implement**

In `MapPage.get_context_data`, after `resolved = …`:

```python
        section = resolve_related(request.GET, {'section': SECTION_REGIONS}).get('section')
        no_matches = no_matches or section is MISSING
        selected = section if section not in (None, MISSING) else None
```

Move `county = …` / `concern = …` above this block if needed. The `section_map_config(...)` call gains:

```python
            select='filter',
            highlight=selected.sqid if selected else None,
            center=centroid(selected) if selected and selected.boundary_id else None,
            zoom=13 if selected and selected.boundary_id else None,
```

The chip loop: after it, add

```python
        if selected:
            filters.append({
                'label': f'Section {selected.external_id}',
                'clear_url': clear_url(request, 'section'),
            })
```

The panel, before the `return`:

```python
        panel = {}
        if selected:
            rows = PesticideUseRollup.objects.filter(mtrs=selected, **resolved)
            if county is not None:
                rows = rows.filter(county=county)
            if concern:
                rows = stats.narrow_rows(rows, concern)
            scope = stats.scope_param(year, all_years, county, concern)
            entity_qs = ''.join(f'&{param}={obj.sqid}' for param, obj in resolved.items())
            records_url = reverse('pesticides:records') + f'?section={selected.sqid}' + entity_qs + (
                f'&{scope}' if scope else '')
            notices = PesticideNotice.objects.filter(mtrs=selected)
            if resolved.get('chemical'):
                notices = notices.filter(chemicals=resolved['chemical'])
            if resolved.get('product'):
                notices = notices.filter(products=resolved['product'])
            upcoming_days = stats.upcoming_by_day(notices)
            panel = {
                **section_summary(rows, year, all_years, records_url,
                    lbs_field='lbs_product' if resolved.get('product') else 'lbs_chemical'),
                'upcoming': stats.notices_in_days(upcoming_days),
                'upcoming_days': upcoming_days,
                'upcoming_count': stats.upcoming_count(notices),
            }
```

(`resolved` keys are exactly `chemical`/`product`/`commodity`, the rollup's FK names, so `filter(**resolved)` is correct. A commodity filter leaves notices unfiltered, since notices carry no commodity.)

Return: add `selected_section=section_filter_context(request, selected, stats.scope_param(year, all_years, county, concern)) if selected else None,` and `**panel,` to the `super().get_context_data(...)` call.

`map.html`, after the `{% include 'pesticides/includes/section-map.html' %}` line:

```django
{% if selected_section %}
<section class="section-panel mt-5" id="section-panel">
    <h2 class="title is-4 mb-2">
        Section {{ selected_section.external_id }}{% if selected_section.county %} <small class="has-text-grey is-size-6">{{ selected_section.county }}</small>{% endif %}
        {% if related.product %}<small class="is-size-6">&middot; {{ related.product.display_name }}</small>{% endif %}
        {% if related.chemical %}<small class="is-size-6">&middot; {{ related.chemical.display_name }}</small>{% endif %}
        {% if related.commodity %}<small class="is-size-6">&middot; {{ related.commodity.display_name }}</small>{% endif %}
    </h2>
    <p class="mb-4"><a href="{{ selected_section.page_url }}">Section details</a> &middot; <a href="{{ selected_section.clear_url }}">Clear</a></p>
    {% include 'pesticides/includes/section-stats.html' %}
    {% include 'pesticides/includes/section-summary.html' %}
</section>
{% endif %}
```

Update the intro paragraph's "click a section for its top chemicals" to "click a section to see its use below".

`map-toolbar.html`: after the `scope-hidden.html` include:

```django
    {% if selected_section %}<input type="hidden" name="section" value="{{ selected_section.sqid }}">{% endif %}
```

- [ ] **Step 4: Run to verify they pass, plus the existing map-page tests**

Run: `HARNESS camp/apps/pesticides/tests/test_views.py`
Expected: all PASS.

- [ ] **Step 5: Leave uncommitted.**

---

### Task 4: Filter mode in the section map + smoke check

**Files:**
- Modify: `assets/js/pesticides/section-map.js`
- Modify: `scripts/pesticides_map_smoke.py`

**Interfaces:**
- Consumes: `data-select="filter"` and `data-highlight` on the map container (Tasks 1–3); the page's `#explorer-body` (boosted by `#explorer`).
- Produces (JS): `SectionMap.prototype.isFilterMap()`, `filterToSection(feature)`, `navigateWithSection(id|null)`, `showFilterLabel()`; popup key `openFilterId`; instance fields `filterFeature`, `filterNavigating`, `filterLabelShownFor`.

- [ ] **Step 1: Add the failing smoke check**

In `scripts/pesticides_map_smoke.py`, add after `check_popup_clear`:

```python
def check_filter_click(page):
    """Filter-mode maps (the map page, entity pages): a section click narrows
    the page to it over htmx. Same map instance, camera unmoved, the URL and
    the outline carry the section, the label popup is up; its Clear drops the
    section; the back button brings it back."""
    if page.instance_js('return inst.data.select') != 'filter':
        return None, 'not a filter-mode map (skipped)'
    ok, _ = page.wait_grid('section', 10)
    if not ok:
        return False, 'not at the section grid'
    target = page.pick('inst.sourceData.grid.features')
    if not target:
        return False, 'no section with data on bare canvas to click'
    page.js("window.__smokeInstance = (function () { %s })();" % JS_INSTANCE)
    camera = page.instance_js('var c = inst.map.getCenter(); return [c.lng, c.lat, inst.map.getZoom()];')
    page.click_map(target['dx'], target['dy'], settle=0.5)
    problems = []
    narrowed = page.wait_for("""
        var inst = (function () { %s })();
        return location.search.indexOf('section=' + arguments[0]) !== -1 && !!inst && inst.data.highlight === arguments[0];
    """ % JS_INSTANCE, SWAP_TIMEOUT, target['id'])
    if not narrowed:
        return False, 'URL/highlight never carried section %s' % target['id']
    time.sleep(1.5)  # a grid rebuild after the swap must not navigate again
    state = page.instance_js("""
        var c = inst.map.getCenter();
        return {
            same: inst === window.__smokeInstance,
            camera: [c.lng, c.lat, inst.map.getZoom()],
            key: inst.popupKey,
            search: location.search,
            narrowed: !!document.querySelector('.section-filter-banner, #section-panel'),
        };
    """)
    if not state['same']:
        problems.append('a new map instance on the swap')
    if any(abs(a - b) > 1e-6 for a, b in zip(camera, state['camera'])):
        problems.append('camera moved %s -> %s' % (camera, state['camera']))
    if state['key'] != 'openFilterId':
        problems.append('label popup not open (popupKey %r)' % state['key'])
    if not state['narrowed']:
        problems.append('no banner / section panel on the page')
    if state['search'].count('section=') != 1:
        problems.append('URL %r' % state['search'])
    page.js("var b = document.querySelector('.section-filter-clear'); if (b) b.click();")
    cleared = page.wait_for("""
        var inst = (function () { %s })();
        return location.search.indexOf('section=') === -1 && !!inst && !inst.data.highlight;
    """ % JS_INSTANCE, SWAP_TIMEOUT)
    if not cleared:
        problems.append('Clear did not drop the section')
    page.js('window.history.back();')
    back = page.wait_for("""
        var inst = (function () { %s })();
        return location.search.indexOf('section=' + arguments[0]) !== -1 && !!inst && inst.data.highlight === arguments[0];
    """ % JS_INSTANCE, SWAP_TIMEOUT, target['id'])
    if not back:
        problems.append('back did not restore the section')
    count = page.js("var mod = window.PesticidesSectionMap; return mod ? mod.instances().length : null;")
    if count != 1:
        problems.append('%s live instance(s) after back' % count)
    detail = 'section %s: narrowed in place, cleared, restored by back' % target['id']
    return (not problems), (detail if not problems else '; '.join(problems))
```

Register it in `CHECKS` right after `('popup clear', check_popup_clear),` as `('filter click', check_filter_click),`. Give every check that clicks a section expecting today's popup (`check_lens_popup`, `check_section_popup`, `check_selection_survives_metric`, `check_popup_clear`, and any other `click_map` on a section layer; grep for `click_map`) this first line:

```python
    if page.instance_js('return inst.data.select') == 'filter':
        return None, 'filter-mode map: a click filters (skipped)'
```

The dev server on :8002 already serves the Task 1–3 markup, so run:
`.venv/bin/python scripts/pesticides_map_smoke.py --base http://localhost:8002 /tools/pesticides/map/`
(create the venv first if it's missing: `python3 -m venv .venv && .venv/bin/pip install selenium`).
Expected: `filter click` FAILs (the click opens today's popup; the URL never carries the section).

- [ ] **Step 2: Implement filter mode in `section-map.js`**

a. Near `isMarkerPopup`:

```javascript
  // A map whose page narrows to a clicked section (the map page, the entity
  // pages): a section click navigates instead of opening the popup.
  SectionMap.prototype.isFilterMap = function () {
    return this.data.select === 'filter';
  };
```

b. First lines of `showSectionPopup` (every section click, the lens's and "all sections"' included, and the locate button, arrives here):

```javascript
    if (this.isFilterMap()) {
      this.filterToSection(feature);
      return;
    }
```

c. New methods after `showSectionPopup`:

```javascript
  // Clicking the section the page is already narrowed to lets it go.
  SectionMap.prototype.filterToSection = function (feature) {
    var id = feature.properties.id;
    this.filterFeature = feature;
    this.navigateWithSection(id === this.data.highlight ? null : id);
  };

  // The same page with `section` set (or dropped), through the explorer's
  // boosted swap so it's indistinguishable from following a link: the URL
  // is pushed, #explorer-body swapped, and this map adopted in place. The
  // flag tells onAdopt the camera stays where the reader is.
  SectionMap.prototype.navigateWithSection = function (id) {
    var url = new URL(window.location.href);
    if (id) url.searchParams.set('section', id); else url.searchParams.delete('section');
    url.searchParams.delete('page');
    var href = url.pathname + url.search;
    var body = document.getElementById('explorer-body');
    if (!window.htmx || !body) {
      window.location.assign(href);
      return;
    }
    this.filterNavigating = true;
    var link = document.createElement('a');
    link.href = href;
    link.hidden = true;
    body.appendChild(link);
    window.htmx.process(link);
    link.click();
  };

  // The narrowed page's section wears a one-line label: its name, its page,
  // and Clear. Shown once per selection; closing it doesn't clear.
  SectionMap.prototype.showFilterLabel = function () {
    var id = this.data.highlight;
    if (!this.isFilterMap() || !id || this.filterLabelShownFor === id) return;
    var feature = this.gridById[id] ||
      (this.filterFeature && this.filterFeature.properties.id === id ? this.filterFeature : null);
    if (!feature) return;
    this.filterLabelShownFor = id;
    var props = feature.properties;
    var url = this.sectionUrl(id);
    var html = '<div class="section-popup section-filter-label">' +
      '<h4>' + escapeHtml(props.mtrs || id) + '</h4>' +
      '<div class="section-popup-actions">' +
      (url ? '<a class="section-popup-action" href="' + escapeHtml(url) + '"><span class="fa-regular fa-fw fa-circle-info"></span> Section details</a>' : '') +
      '<button type="button" class="section-popup-action section-filter-clear"><span class="fa-regular fa-fw fa-xmark"></span> Clear</button>' +
      '</div></div>';
    this.openPopup(boundsCenter(featureBounds(feature)), html, 'openFilterId', id);
  };
```

d. `bindPopupButtons`: at the top of its click listener:

```javascript
      if (click.target.closest && click.target.closest('.section-filter-clear')) {
        self.navigateWithSection(null);
        return;
      }
```

e. `updateHighlight`: the outline also follows a lens / all-sections selection on a filter map (the grid holds only townships then):

```javascript
  SectionMap.prototype.updateHighlight = function () {
    var id = this.data.highlight;
    var feature = null;
    if (id && this.level === 'section') {
      feature = this.gridById[id] || null;
    } else if (id && this.isFilterMap() && this.filterFeature && this.filterFeature.properties.id === id) {
      feature = this.filterFeature;
    }
    this.setSourceData('highlight', feature || EMPTY);
    this.showFilterLabel();
  };
```

f. `reopenGridPopup`'s `else if`: keep the label through a grid rebuild:

```javascript
    } else if (this.popup && !this.isMarkerPopup() && this.popupKey !== 'openFilterId') {
```

g. `onAdopt`:
   - Replace `var viewChanged = has('center') || has('zoom');` with:
     ```javascript
    // A selection made on this map never moves it: the reader clicked
    // something they can already see. (A back/forward to a narrowed page
    // isn't one, and frames it as a fresh load would.)
    var viewChanged = !this.filterNavigating && (has('center') || has('zoom'));
    this.filterNavigating = false;
     ```
   - Before `this.syncControls();`:
     ```javascript
    if (has('highlight')) {
      this.filterLabelShownFor = null;
      if (!this.data.highlight && this.popup && this.popupKey === 'openFilterId') this.closePopup();
      this.updateHighlight();
    }
     ```

- [ ] **Step 3: Run the smoke check to verify it passes**

Hard-refresh isn't needed for headless Chrome (fresh profile). Run:
`.venv/bin/python scripts/pesticides_map_smoke.py --base http://localhost:8002 /tools/pesticides/map/ "/tools/pesticides/chemicals/<sqid>/<slug>/"` (take a chemical URL from `/tools/pesticides/chemicals/`) plus one non-filter page, `/tools/pesticides/region/hez8v/fresno/`.
Expected: `filter click` PASS on the two filter pages, skipped on the region page; every previously-passing check still passes (popup checks skipped on filter pages); `console` clean.

- [ ] **Step 4: Leave uncommitted.**

---

### Task 5: Verify in the browser and run the full suite

- [ ] **Step 1:** In Chrome on `http://localhost:8002` (hard-refresh first; focus the tab, since a blank map in an unfocused tab is MapLibre throttling):
  - Map page zoomed out: hover a township, click a lens section → panel appears below, map doesn't move, outline + label on the section.
  - Zoom in, click another section → panel changes; click it again → cleared.
  - Label "Clear", panel "Clear", chip ×: all drop the section.
  - Pick a chemical in the toolbar with a section selected → panel narrows to that chemical in that section.
  - A chemical page: click a section → banner, stat row, trend, by-year, heatmap, related cards narrow; county table/map/movers gone; "Browse … records" and "Show all" land on the records browser filtered to the entity + section; year change in the scope bar keeps the section.
  - Back/forward through two selections; paste a narrowed URL into a new tab (opens framed on the section).
  - Phone width (resize to ~390px): the label popup fits; panel stacks.
- [ ] **Step 2:** Full suite: `HARNESS camp` (whole tree, as CI does). Expected: all green (1,964 + the new tests).
- [ ] **Step 3:** Report results to Derek; leave everything uncommitted.
