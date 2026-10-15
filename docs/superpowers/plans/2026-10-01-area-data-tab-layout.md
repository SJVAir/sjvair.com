# Area Data Tabs: One Layout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every area data tab puts its filters (and extra boxes) beside the map, the table full width below, and paginates long lists; the pesticides Notices tab becomes the notice list narrowed to its place.

**Architecture:** `regions/area-tab.html` gains a fixed filters row (left `.tab-side` column = `tab-filters` + `tab-aside`; right column = chips from `active_filters` + `tab-map`), hidden by CSS when the side column is empty. Records and Schools move into those blocks; Schools paginates in the view with Django's `Paginator`; Notices moves onto `NoticeList` the way Records sits on `RecordsBrowser`.

**Tech Stack:** Django templates, django-vanilla-views ListView, Bulma, libsass (`invoke styles`), htmx.

**Spec:** `docs/superpowers/specs/2026-10-01-area-data-tab-layout-design.md`

## Global Constraints

- Work in `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer`, branch `feature/pesticides-explorer`. Verify every commit lands there, not the main checkout.
- Block names `tab-filters` and `tab-table` keep their names (emissions fills them); new block is `tab-aside`. `tab_has_filters` is removed.
- Tests: `django.test.TestCase`, plain `assert`, fixtures `pesticides-explorer`. Run with `docker compose run --rm test pytest <paths> -n 4 --dist loadscope -q`.
- Never `git add -A`; list files. Commit locally per task; never push. No AI attribution in commit messages.
- Styles: after sass changes, `docker exec sjvair-web-run-9fa08fbbbf15 sh -c 'invoke styles && python manage.py collectstatic --noinput -v0'` (the 8002 dev container).
- Products before chemicals wherever both appear.
- Page size: 50 for notices (existing `NoticeList.paginate_by`) and schools (`SCHOOLS_PER_PAGE = 50`).

## Review Focus

1. Near-me Notices tab after a filter change or "Clear filters" — must keep `lat`/`lng`/`radius`/`label`, never bounce to the finder (Task 3 test `test_near_me_filters_keep_the_point`).
2. Schools `?page=` out of range or junk — last/first page, not a 500 (Task 2 test `test_bad_page_is_not_a_500`).
3. Notices tab in past mode — stat row still counts what's upcoming, archive months count only the place (Task 3 tests).
4. Year scope survives a Notices filter submit (the tab links keep `year=`) (Task 3 test `test_filter_form_carries_year_and_label`).
5. A tab with no filters/aside (Community overrides `tab-body`; any future tab) — map full width, no empty bordered box (Task 1 CSS + test on `.tab-side` emptiness).

---

### Task 1: Skeleton filters row; Records and Schools move into it

**Files:**
- Modify: `camp/templates/regions/area-tab.html`
- Modify: `assets/sass/sjvair/components/area-pages.sass`
- Modify: `camp/templates/pesticides/area-records.html`
- Modify: `camp/templates/pesticides/area-schools.html`
- Modify: `camp/apps/pesticides/views.py` (`AreaSchoolsMixin.get_context_data`: drop `tab_has_filters=True`)
- Test: `camp/apps/pesticides/tests/test_area_layout.py` (create)

**Interfaces:**
- Produces: blocks `tab-filters`, `tab-aside` (in `.tab-side`), `tab-map`, `tab-table`; skeleton renders chips from context `active_filters` [{label, clear_url}].

- [ ] **Step 1: Failing tests** — `camp/apps/pesticides/tests/test_area_layout.py`:

```python
import re

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


def side(html):
    """The skeleton's left column's inner HTML."""
    match = re.search(r'<div class="column is-3-desktop tab-side">(.*?)</div>\s*<div class="column tab-map">', html, re.S)
    assert match, 'no filters row'
    return match.group(1)


class AreaTabLayoutTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(pk=9001)

    def get(self, tab, **params):
        return self.client.get(self.fresno.get_pesticides_tab_url(tab), params).content.decode()

    def test_records_filters_beside_the_map_table_below(self):
        html = self.get('records')
        assert 'records-filters' in side(html)
        assert html.index('tab-side') < html.index('class="column tab-map"') < html.index('class="tab-table')
        assert 'records-filters' not in html[html.index('class="tab-table'):]

    def test_no_filters_beside_the_table(self):
        html = self.get('records')
        assert 'tab_has_filters' not in html
        table = html[html.index('class="tab-table'):]
        assert 'is-3-desktop' not in table.split('tab-charts')[0]
```

Add to `camp/apps/pesticides/tests/test_places.py`'s schools test class (the one with `self.url` = Selma Unified schools, around line 309) — the district page has no districts box, so assert the filters:

```python
    def test_filters_sit_beside_the_map(self):
        from camp.apps.pesticides.tests.test_area_layout import side
        html = self.client.get(self.url).content.decode()
        assert 'schools-filters' in side(html)
        assert html.index('class="column tab-map"') < html.index('schools-table')
```

- [ ] **Step 2: Run, expect FAIL** (`no filters row`):
`docker compose run --rm test pytest camp/apps/pesticides/tests/test_area_layout.py -q`

- [ ] **Step 3: Skeleton** — replace the body of `{% block explorer-content %}` in `camp/templates/regions/area-tab.html` and its comment:

```django
{% comment %}
The skeleton an explorer's area data tabs share, so they read alike however
different their data: under the header and tab row, a stat row; then the
filters (`tab-filters`) and any other boxes (`tab-aside`) in a column beside
the map, with the active-filter chips (`active_filters` [{label, clear_url}])
above it; the table the page's full width under them; then the charts, the
tab's related sections, and its notes. A tab fills the blocks it has; with
nothing beside the map the side column hides itself (area-pages.sass) and
the map takes the row. `tab-body` wraps the lot, for a tab with nothing to
show to replace in one go.

Context: `explorer_base` (the explorer's base template), `area_crumbs`
[{label, url}] for the breadcrumb before the tab, `tab_label`, and what
regions/includes/area-header.html takes.
{% endcomment %}
```

```django
{% block explorer-content %}
{% include 'regions/includes/area-header.html' %}
{% block tab-body %}
{% block tab-notices %}{% endblock %}
<div class="tab-stats">{% block tab-stats %}{% endblock %}</div>
<div class="columns tab-filters-row">
<div class="column is-3-desktop tab-side">{% block tab-filters %}{% endblock %}{% block tab-aside %}{% endblock %}</div>
<div class="column tab-map">
{% if active_filters %}<div class="tags">{% for f in active_filters %}<span class="tag is-info is-light is-medium">{{ f.label }} <a class="delete is-small ml-1" href="{{ f.clear_url }}" aria-label="Remove filter"></a></span>{% endfor %}</div>{% endif %}
{% block tab-map %}{% endblock %}
</div>
</div>
<div class="tab-table mt-4">{% block tab-table %}{% endblock %}</div>
<div class="tab-charts">{% block tab-charts %}{% endblock %}</div>
{% block tab-related %}{% endblock %}
{% block tab-notes %}{% endblock %}
{% endblock %}
{% block tab-after %}{% endblock %}
{% endblock %}
```

- [ ] **Step 4: CSS** — append to `assets/sass/sjvair/components/area-pages.sass` after the `.tab-stats` rule:

```sass
// Nothing beside the map (a tab without filters): the side column goes and
// the map takes the row.
.tab-side:not(:has(*))
  display: none
```

- [ ] **Step 5: Records tab** — in `camp/templates/pesticides/area-records.html` replace the `tab-map` block (filters + chips + map) with:

```django
{% block tab-filters %}{% include 'pesticides/includes/records-filters.html' %}{% endblock %}

{% block tab-map %}{% include 'pesticides/includes/section-map.html' %}{% endblock %}
```

and update its comment's last sentence to: "Laid out like the Records page: the filters beside the map, the nine-column table the page's full width under them."

- [ ] **Step 6: Schools tab** — in `camp/templates/pesticides/area-schools.html` split the `tab-filters` block:

```django
{% block tab-filters %}{% include 'pesticides/includes/schools-filters.html' %}{% endblock %}
{% block tab-aside %}{% include 'pesticides/includes/school-districts-box.html' %}{% endblock %}
```

In `AreaSchoolsMixin.get_context_data` delete `tab_has_filters=True,`. Update `schools-filters.html`'s comment "in a box beside it like the other data browsers'" → "in a box beside the map like the other data browsers'".

- [ ] **Step 7: Run tests + styles**

```
docker compose run --rm test pytest camp/apps/pesticides camp/apps/regions -n 4 --dist loadscope -q
docker exec sjvair-web-run-9fa08fbbbf15 sh -c 'invoke styles && python manage.py collectstatic --noinput -v0'
```
Expected: all pass. Load `http://localhost:8002` Fresno County Records and Schools tabs and the Community tab; Records unchanged, Schools filters beside the map, Community unaffected.

- [ ] **Step 8: Commit**

```bash
git add camp/templates/regions/area-tab.html assets/sass/sjvair/components/area-pages.sass camp/templates/pesticides/area-records.html camp/templates/pesticides/area-schools.html camp/templates/pesticides/includes/schools-filters.html camp/apps/pesticides/views.py camp/apps/pesticides/tests/test_area_layout.py camp/apps/pesticides/tests/test_places.py
git commit -m "feat(regions): area tabs put their filters beside the map, the table full width below"
```

---

### Task 2: Schools table paginates

**Files:**
- Modify: `camp/apps/pesticides/places.py` (`SCHOOLS_VISIBLE` → `SCHOOLS_PER_PAGE = 50`; `schools_panel` drops `is_collapsed`/`hidden`)
- Modify: `camp/apps/pesticides/views.py` (`AreaSchoolsMixin`)
- Modify: `camp/templates/pesticides/includes/schools-table.html`, `camp/templates/pesticides/area-schools.html`
- Modify: `assets/js/pesticides/explorer.js`, `assets/sass/sjvair/pages/pesticides.sass`
- Test: `camp/apps/pesticides/tests/test_places.py`

**Interfaces:**
- Consumes: Task 1's `tab-table` (full width).
- Produces: context `page_obj`, `is_paginated` on the Schools tab; `schools['rows']` is the current page only; `schools['matched']` still counts all filtered rows.

- [ ] **Step 1: Failing tests** — in `test_places.py` replace `test_rows_past_the_cap_render_collapsed` and `test_no_toggle_when_everything_fits` with:

```python
    def make_many(self, count):
        for index in range(count):
            self.make_location(f'EXTRA CARE {index:02d}')
        cache.clear()

    def test_rows_past_a_page_go_to_the_next(self):
        self.make_many(50)  # 52 sites with the fixture's two
        response = self.client.get(self.url, {'schools_sort': 'name'})
        assert len(response.context['schools']['rows']) == 50
        assert response.context['is_paginated'] is True
        assert response.context['schools']['matched'] == 52
        html = response.content.decode()
        assert 'is-collapsed' not in html and 'Show the other' not in html
        assert 'page=2' in html and 'schools_sort=name' in html.split('page=2')[0].rsplit('href="', 1)[1]

        second = self.client.get(self.url, {'schools_sort': 'name', 'page': 2})
        assert len(second.context['schools']['rows']) == 2

    def test_filtering_resets_to_page_one(self):
        self.make_many(50)
        html = self.client.get(self.url, {'page': 2}).content.decode()
        form = html[html.index('schools-filters'):html.index('</form>', html.index('schools-filters'))]
        assert 'name="page"' not in form

    def test_bad_page_is_not_a_500(self):
        self.make_many(50)
        for page in ('99', 'nope', '-1'):
            response = self.client.get(self.url, {'page': page})
            assert response.status_code == 200, page
            assert response.context['schools']['rows'], page

    def test_one_page_has_no_pagination(self):
        response = self.client.get(self.url)
        assert response.context['is_paginated'] is False
        assert 'pagination' not in response.content.decode()
```

(`make_location` exists in that test class; if it takes different arguments, follow its signature.)

- [ ] **Step 2: Run, expect FAIL** (`KeyError: 'is_paginated'`):
`docker compose run --rm test pytest camp/apps/pesticides/tests/test_places.py -q -k "page or filtering_resets"`

- [ ] **Step 3: `places.py`** — replace `SCHOOLS_VISIBLE = 15` with `SCHOOLS_PER_PAGE = 50`. In `schools_panel`, replace the docstring's last paragraph with "`params` is the request's GET. Paging is the view's: this returns every matching row, sorted.", and in the return dict use `'rows': rows,` and delete the `'hidden': ...` line.

- [ ] **Step 4: View** — in `AreaSchoolsMixin.get_context_data`, after `schools = places.schools_panel(...)`:

```python
        # A page of the table at a time, like the other browsers; get_page
        # turns a junk or out-of-range ?page= into the first or last page.
        page_obj = Paginator(schools['rows'], places.SCHOOLS_PER_PAGE).get_page(self.request.GET.get('page'))
        schools['rows'] = page_obj.object_list
```

and pass `page_obj=page_obj, is_paginated=page_obj.has_other_pages(),` to `super().get_context_data(...)`. Import `from django.core.paginator import Paginator` at the top if absent.

- [ ] **Step 5: Templates** — `schools-table.html`: change `<tr{% if row.is_collapsed %} class="is-collapsed"{% endif %}>` to `<tr>`; delete the `{% if schools.hidden %}…{% endif %}` button block; reword the comment ("every matching row is in the one <tbody>, and the rows past the first fifteen carry `is_collapsed`…") to "`schools` is places.schools_panel(), its rows the current page (the view pages them)." After the table's `</div>`, before `{% endwith %}`, add `{% include 'pesticides/includes/pagination.html' %}`. In `area-schools.html` change `<section class="schools-nearby" data-reveal-scope>` to `<section class="schools-nearby">`.

- [ ] **Step 6: JS/Sass** — `explorer.js`: the reveal handler's selector becomes `'[data-reveal-toggle]'` and the scope line `var scope = button.closest('[data-reveal-scope]');`; its comment's list becomes "(`.is-collapsed`: the school districts box past five, the "In and around" lists past a dozen)". `pesticides.sass` `.schools-table`: delete the `tbody tr.is-collapsed` rule (and its `&.is-revealed`), delete the `.schools-toggle` rule, and drop "and everything past the first fifteen rows is hidden until the toggle reveals it" from the comment above `.district-demographics`.

- [ ] **Step 7: Run** — `docker compose run --rm test pytest camp/apps/pesticides camp/apps/regions -n 4 --dist loadscope -q` (all pass); rebuild styles; `grep -rn "SCHOOLS_VISIBLE\|data-schools-toggle\|schools.hidden" camp assets` → nothing.

- [ ] **Step 8: Commit**

```bash
git add camp/apps/pesticides/places.py camp/apps/pesticides/views.py camp/templates/pesticides/includes/schools-table.html camp/templates/pesticides/area-schools.html assets/js/pesticides/explorer.js assets/sass/sjvair/pages/pesticides.sass camp/apps/pesticides/tests/test_places.py
git commit -m "feat(pesticides): the schools table pages like the other browsers"
```

---

### Task 3: Notices tab is the notice list, narrowed to its place

**Files:**
- Create: `camp/templates/pesticides/includes/notice-filters.html`, `camp/templates/pesticides/includes/notice-archive-months.html`
- Modify: `camp/templates/pesticides/notice-list.html`, `camp/templates/pesticides/area-notices.html`
- Modify: `camp/apps/pesticides/views.py` (`NoticeList.get_context_data` adds `clear_filters_url`; `AreaNoticesMixin`; `NearMeNotices`/`RegionNotices` bases)
- Test: `camp/apps/pesticides/tests/test_notices.py`

**Interfaces:**
- Consumes: Task 1's blocks and skeleton chips.
- Produces: `NoticeList.get_clear_filters_url()` (overridable); context `clear_filters_url`.

- [ ] **Step 1: Failing tests** — append to `test_notices.py`:

```python
class AreaNoticesTabTests(TestCase):
    """The Notices tab: the notice list, narrowed to its place."""
    fixtures = ['pesticides-explorer']
    POINT = {'lat': 36.71, 'lng': -119.79, 'radius': 3, 'label': 'near Selma'}

    def setUp(self):
        cache.clear()
        self.archived = PesticideNotice.objects.get(pk=1)
        self.county = self.archived.county
        self.url = self.county.get_pesticides_tab_url('notices')

    def test_lists_only_the_place(self):
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        here = [n.county_id for n in self.client.get(kern.get_pesticides_tab_url('notices')).context['object_list']]
        assert here and set(here) == {kern.pk}

    def test_past_mode_lists_the_archive_and_counts_only_the_place(self):
        response = self.client.get(self.url, {'past': 1})
        assert [n.pk for n in response.context['object_list']] == [1]
        assert [(m['year'], m['month'], m['count']) for m in response.context['archive_months']] == [(2020, 1, 1)]
        # The stat row is what's scheduled now, whatever the mode.
        assert response.context['upcoming_count'] == self.client.get(self.url).context['upcoming_count']

    def test_chemical_filter_and_own_chip(self):
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        chem = Chemical.objects.get(pk=1)
        response = self.client.get(kern.get_pesticides_tab_url('notices'), {'chemical': chem.sqid})
        assert [n.pk for n in response.context['object_list']] == [3]
        labels = [f['label'] for f in response.context['active_filters']]
        assert labels == [chem.display_name]

    def test_layout(self):
        from camp.apps.pesticides.tests.test_area_layout import side
        html = self.client.get(self.url, {'past': 1}).content.decode()
        panel = side(html)
        assert 'notice-filters' in panel and 'archive-months' in panel and 'spraydays' in panel.lower()
        assert 'Day by day' not in html and 'Past notices here' not in html
        assert html.index('class="column tab-map"') < html.index('summary-sentence')

    def test_near_me_filters_keep_the_point(self):
        response = self.client.get(reverse('pesticides:near-me-notices'), self.POINT)
        assert response.status_code == 200
        html = response.content.decode()
        form = html[html.index('notice-filters'):html.index('</form>', html.index('notice-filters'))]
        for name, value in (('lat', '36.71'), ('lng', '-119.79'), ('radius', '3'), ('label', 'near Selma')):
            assert f'name="{name}"' in form and value in form, name
        clear = response.context['clear_filters_url']
        assert clear.startswith(reverse('pesticides:near-me-notices')) and 'lat=36.71' in clear and 'label=near+Selma' in clear
        assert not [f for f in response.context['active_filters'] if f['label'].startswith('Within ')]

    def test_filter_form_carries_year_and_label(self):
        html = self.client.get(self.url, {'year': 2022}).content.decode()
        form = html[html.index('notice-filters'):html.index('</form>', html.index('notice-filters'))]
        assert '<input type="hidden" name="year" value="2022">' in form

    def test_paginates(self):
        assert self.client.get(self.url).context['paginator'].per_page == 50
```

- [ ] **Step 2: Run, expect FAIL**: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_notices.py -q -k AreaNoticesTab`

- [ ] **Step 3: Extract includes** — move the `<form class="notice-filters box" …>…</form>` from `notice-list.html` into `includes/notice-filters.html` (with `{% load pesticides_explorer %}`), and change it as follows: after `{{ form.radius }}` add

```django
    {# A near-me place's name, and the page's year for its nav links, ride along. #}
    {% if request.GET.label %}<input type="hidden" name="label" value="{{ request.GET.label }}">{% endif %}
    {% if request.GET.year %}<input type="hidden" name="year" value="{{ request.GET.year }}">{% endif %}
```

and the clear link becomes `<p class="filters-clear"><a href="{{ clear_filters_url }}">Clear filters</a></p>`. Put the Active/Archive `<div class="tabs is-toggle is-small mb-4">…</div>` at the top of the same include (above the form), so both pages get it beside the map. Move the `{% if mode == 'past' and archive_months %}<div class="box archive-months">…</div>{% endif %}` into `includes/notice-archive-months.html`. In `notice-list.html` the left column becomes:

```django
    <div class="column is-3-desktop">
        {% include 'pesticides/includes/notice-filters.html' %}
        {% include 'pesticides/includes/notice-archive-months.html' %}
        {% include 'pesticides/includes/spraydays-signup.html' %}
    </div>
```

(remove the toggle `div.tabs` that sat above `.columns`).

- [ ] **Step 4: `NoticeList`** — add:

```python
    def get_clear_filters_url(self):
        """Where "Clear filters" goes: the list in its mode, nothing else."""
        return self.request.path + ('?past=1' if self.mode == 'past' else '')
```

and `clear_filters_url=self.get_clear_filters_url(),` in its `get_context_data` kwargs.

- [ ] **Step 5: `AreaNoticesMixin`** — replace the class with:

```python
class AreaNoticesMixin:
    """
    A place page's Notices tab: the notice list (NoticeList) narrowed to the
    place -- its filters, archive, map and rows -- under the place's header
    and tabs, with the stat row always on what's scheduled now. The place's
    own filter is added to the request before the list reads it, and isn't
    offered as a chip to clear: the tab is the place.
    """
    template_name = 'pesticides/area-notices.html'

    def dispatch(self, request, *args, **kwargs):
        params = request.GET.copy()
        for key, value in self.area.area_params().items():
            params[key] = value
        request.GET = params
        return super().dispatch(request, *args, **kwargs)

    def get_active_filters(self):
        region = self.area.region
        own = {region.name, getattr(region, 'display_name', region.name)} if region is not None else set()
        return [chip for chip in super().get_active_filters()
            if chip['label'] not in own and not chip['label'].startswith('Within ')]

    def get_clear_filters_url(self):
        url = self.area_tab_url('notices')
        if self.mode == 'past':
            url += ('&' if '?' in url else '?') + 'past=1'
        return url

    def get_map_config(self):
        year, all_years, concern = self.scope
        chemical = self.related.get('chemical')
        product = self.related.get('product')
        return section_map_config(
            year, all_years=all_years, concern=concern,
            chemical=chemical if chemical and chemical is not MISSING else None,
            product=product if product and product is not MISSING else None,
            **self.area.map_kwargs(),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year, all_years, concern = self.scope
        context.update(
            section=None,
            area=self.area,
            tab_label='Notices',
            **places.upcoming_context(self.area, concern),
            spraydays_url=places.SPRAYDAYS_URL,
            **self.header_context(),
            **self.tab_scope_context(),
        )
        return context
```

Check `area_tab_url('notices')` for a near-me area includes the point and label (it does for the tab row — `test_every_near_me_tab_renders_and_keeps_its_point`). `section_map_config` already accepts `chemical`/`product` (NoticeList passes them); if `map_kwargs()` and the explicit kwargs collide, drop the explicit one. Change the views:

```python
class NearMeNotices(NearMeAreaMixin, AreaNoticesMixin, NoticeList):
class RegionNotices(RegionAreaMixin, AreaNoticesMixin, NoticeList):
```

- [ ] **Step 6: `area-notices.html`** — keep `tab-stats` and `tab-notes`; replace `tab-map`/`tab-table` with:

```django
{% block tab-filters %}{% include 'pesticides/includes/notice-filters.html' %}{% endblock %}
{% block tab-aside %}
{% include 'pesticides/includes/notice-archive-months.html' %}
{% include 'pesticides/includes/spraydays-signup.html' %}
{% endblock %}

{% block tab-map %}{% include 'pesticides/includes/section-map.html' %}{% endblock %}

{% block tab-table %}
<p class="summary-sentence mb-3">
    {{ count }} notice{{ count|pluralize }} {% if mode == 'active' %}currently scheduled{% else %}in the archive{% endif %} here.
</p>
{% include 'pesticides/includes/notice-rows.html' %}
{% include 'pesticides/includes/pagination.html' %}
{% endblock %}
```

Update the comment: "A place page's Notices tab: the notice list narrowed to the place — what SprayDays has scheduled there now, or its archive — with the filters beside the map." In `tab-notes`, drop the trailing "Sign up for SprayDays notices" paragraph (the signup box is beside the map now).

- [ ] **Step 7: Run** — `docker compose run --rm test pytest camp/apps/pesticides camp/apps/regions camp/api/v2/pesticides -n 4 --dist loadscope -q`. Fix any older test asserting the Day-by-day markup or `archive_url`; `UpcomingNoticeLinkTests` must still pass (active rows link each notice). Then smoke the maps:

```
docker exec sjvair-web-run-9fa08fbbbf15 python scripts/pesticides_map_smoke.py /tools/pesticides/<fresno-county-path>/notices/ /tools/pesticides/<fresno-county-path>/schools/
```
(use the Fresno County tab URLs from `Region.get_pesticides_tab_url`; if the script must run on the host, follow its docstring). Expected: no failures.

- [ ] **Step 8: Commit**

```bash
git add camp/templates/pesticides/includes/notice-filters.html camp/templates/pesticides/includes/notice-archive-months.html camp/templates/pesticides/notice-list.html camp/templates/pesticides/area-notices.html camp/apps/pesticides/views.py camp/apps/pesticides/tests/test_notices.py
git commit -m "feat(pesticides): a place's Notices tab is the notice list, narrowed to it"
```

---

## After the tasks

- Full suite: `docker compose run --rm test pytest -n 4 --dist loadscope -q`.
- Tell `sjvair-com-6a` the skeleton commit (Task 1) so emissions can drop its `tab_has_filters` lines and move boxes into `tab-aside`.
