# Notices Mode, Consistent Paging, County Column — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scheduled/Past becomes a filter driving the notices list, stat row and map; every paginated list pages the same way; the County column hides on one-county pages; the Notices tab stops building data it never shows.

**Architecture:** A `NearestPageMixin` gives every ListView `Paginator.get_page` paging; the pager include moves after each table. A `past` mode on the shared active-notices endpoint base backs a new `notices/archive/` endpoint, and the page's `map_config` points the map at it in past mode. `stats.notice_summary(queryset)` feeds the Notices tab's stat row from the list's own filtered queryset.

**Tech Stack:** Django, django-vanilla-views, django-resticus endpoints (`camp/api/v2/pesticides/sections.py`), MapLibre section map (`assets/js/pesticides/section-map.js`), Bulma.

**Spec:** `docs/superpowers/specs/2026-10-01-notice-mode-paging-county-design.md`

## Global Constraints

- Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer`, branch `feature/pesticides-explorer`; absolute paths, `git -C <worktree>`; never the main checkout.
- Tests: `django.test.TestCase`, plain `assert`, fixtures `pesticides-explorer`. Run `docker compose run --rm test pytest <paths> -n 4 --dist loadscope -q` from the worktree.
- Commit locally per task, explicit file lists, no AI attribution, never push.
- Styles/JS: `docker exec sjvair-web-run-9fa08fbbbf15 sh -c 'invoke styles && python manage.py collectstatic --noinput -v0'` (8002 mounts this worktree). If JS is bundled by an invoke task, run that too (check `tasks.py`).
- Products before chemicals wherever both appear.
- Past mode with no month = all past notices. Switching modes drops `archive_year`, `month`, `page`.
- Out of scope: Overview, section, chemical and product pages' notices/maps.

## Review Focus

1. Switching Past → Scheduled must not carry `archive_year`/`month` (Task 4 test `test_switching_mode_drops_month_and_page`).
2. Past-mode map on a county with many notices — the archive endpoint's cap returns 400 and the map clears, never a 500 (Task 3 test `test_cap`).
3. A Records `?page=` past the end after a filter narrows the set — last page, not 404, and the hydration still runs (Task 1 test).
4. County column on a near-me tab spanning two counties stays (Task 2 test).
5. Stats in past mode with a month picked — count, acres and chemicals for that month only (Task 4 test).

---

### Task 1: Paging is the same everywhere

**Files:**
- Modify: `camp/apps/pesticides/views.py` (new `NearestPageMixin`; `ExplorerListMixin`, `RecordsBrowser`, `NoticeList` use it)
- Modify: `camp/templates/pesticides/includes/records-table.html` (drop the pager include), every template that includes `records-table.html` (add `{% include 'pesticides/includes/pagination.html' %}` right after it — `grep -rn "records-table.html" camp/templates`)
- Modify: `camp/templates/pesticides/includes/schools-table.html` (count line → `summary-sentence`)
- Test: `camp/apps/pesticides/tests/test_paging.py` (create)

**Interfaces:** Produces `NearestPageMixin` (mixin above vanilla ListView in the MRO).

- [ ] **Step 1: Failing tests** — `test_paging.py`:

```python
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


class NearestPageTests(RollupTestMixin, TestCase):
    """A junk or out-of-range ?page= lands on a real page on every list."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        fresno = Region.objects.get(pk=9001)
        self.urls = [
            reverse('pesticides:product-list'),
            reverse('pesticides:chemical-list'),
            reverse('pesticides:commodity-list'),
            reverse('pesticides:records'),
            reverse('pesticides:notice-list'),
            fresno.get_pesticides_tab_url('records'),
            fresno.get_pesticides_tab_url('notices'),
        ]

    def test_bad_pages_are_not_404s(self):
        for url in self.urls:
            for page in ('99', 'nope', '-1', '0'):
                response = self.client.get(url, {'page': page})
                assert response.status_code == 200, (url, page)

    def test_records_pager_sits_after_the_table(self):
        html = self.client.get(reverse('pesticides:records')).content.decode()
        assert html.index('records-table') < html.rindex('</table>')
        if 'class="pagination' in html:
            assert html.rindex('</table>') < html.index('class="pagination')
```

Add to the schools test class in `test_places.py` (the Selma Unified one):

```python
    def test_count_line_reads_like_the_other_browsers(self):
        html = self.client.get(self.url).content.decode()
        assert 'summary-sentence' in html[:html.index('schools-table')]
        assert 'schools-count' not in html
```

- [ ] **Step 2: Run, expect FAIL** (404s on Records/product lists).

- [ ] **Step 3: Mixin** — in `views.py`, above `ExplorerListMixin`:

```python
class NearestPageMixin:
    """
    A list's paging, the same on every browser: a junk or out-of-range
    `?page=` lands on the nearest real page (the first or the last) rather
    than a 404 -- a list shrinks under a bookmarked page as notices expire
    or a filter narrows it.
    """
    def paginate_queryset(self, queryset, page_size):
        return self.get_paginator(queryset, page_size).get_page(self.request.GET.get(self.page_kwarg))
```

- `ExplorerListMixin` inherits it (`class ExplorerListMixin(NearestPageMixin):`) — confirm each list class lists `ExplorerListMixin` before `vanilla.ListView`.
- `RecordsBrowser(NearestPageMixin, vanilla.ListView)`: its `paginate_queryset` keeps `super().paginate_queryset(...)` then hydrates — now `super()` is the mixin. Keep `get_paginator` (count reuse).
- `NoticeList(NearestPageMixin, vanilla.ListView)`: delete its own `paginate_queryset`.

- [ ] **Step 4: Pager placement** — remove the last line `{% include 'pesticides/includes/pagination.html' %}` from `records-table.html`; add it directly after each `{% include 'pesticides/includes/records-table.html' %}`.

- [ ] **Step 5: Schools count line** — in `schools-table.html` change `<p class="is-size-7 has-text-grey schools-count">` to `<p class="summary-sentence mb-3">`, keeping its content. Remove the `.schools-count` rule from `assets/sass/sjvair/pages/pesticides.sass` if present; rebuild styles.

- [ ] **Step 6: Run** `camp/apps/pesticides camp/apps/regions camp/api/v2/pesticides` — all pass.

- [ ] **Step 7: Commit** — `feat(pesticides): every list pages the same way`

---

### Task 2: County column only off one-county pages

**Files:**
- Modify: `camp/templates/pesticides/includes/notice-rows.html`, `camp/templates/pesticides/includes/records-table.html`
- Test: `camp/apps/pesticides/tests/test_notices.py`, `camp/apps/pesticides/tests/test_records.py` (or whichever file holds Records browser tests — `grep -ln "pesticides:records'" camp/apps/pesticides/tests`)

- [ ] **Step 1: Failing tests**

```python
class CountyColumnTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')

    def headers(self, html):
        return html[html.index('<thead>'):html.index('</thead>')]

    def test_hidden_on_one_county(self):
        for url, params in (
            (self.kern.get_pesticides_tab_url('notices'), {}),
            (self.kern.get_pesticides_tab_url('records'), {}),
            (reverse('pesticides:notice-list'), {'county': 'kern'}),
        ):
            html = self.client.get(url, params).content.decode()
            assert '<th>County</th>' not in self.headers(html), url

    def test_shown_valley_wide_and_near_me(self):
        for url, params in (
            (reverse('pesticides:notice-list'), {}),
            (reverse('pesticides:records'), {}),
            (reverse('pesticides:near-me-notices'), {'lat': 36.71, 'lng': -119.79, 'radius': 3}),
        ):
            html = self.client.get(url, params).content.decode()
            assert '<th>County</th>' in self.headers(html), url
```

(If the Records header cell renders as a sort link, match on the column's header text instead; if a page renders no table when empty, give it a fixture row or assert on the empty-table markup — keep the assertion meaningful.)

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Templates** — wrap the County `<th>` and `<td>` in `{% if not county %}…{% endif %}` in both includes, and fix any `colspan` on the empty row (`{% if county %}8{% else %}9{% endif %}` in records-table; the matching count in notice-rows). Add a comment line: `{# One county's page: every row is that county, so no County column. #}`.

- [ ] **Step 4: Run** pesticides + regions — pass. **Step 5: Commit** — `feat(pesticides): no County column on one county's pages`

---

### Task 3: Archived notices endpoint for the map

**Files:**
- Modify: `camp/api/v2/pesticides/sections.py` (`ActiveNoticeListBase` gains a `past` mode; new `ArchivedNoticeListBase`/`ArchivedNoticeList`), `camp/api/v2/pesticides/urls.py`
- Test: `camp/api/v2/pesticides/tests.py`

**Interfaces:** Produces `GET /api/2.0/pesticides/notices/archive/` (name `notice-archive`) — params `bbox`, `chemical`, `product`, `county`, `narrow`, optional `year` + `month`; features as `notices/active/` plus `properties.past = true`.

- [ ] **Step 1: Failing tests** — next to `ActiveNoticeEndpointTests`:

```python
class ArchivedNoticeEndpointTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('api:v2:pesticides:notice-archive')

    def ids(self, **params):
        return [f['properties']['id'] for f in self.client.get(self.url, params).json()['features']]

    def test_only_past_notices(self):
        past = PesticideNotice.objects.get(pk=1)
        assert self.ids() == [past.sqid]
        feature = self.client.get(self.url).json()['features'][0]
        assert feature['properties']['past'] is True
        active = self.client.get(reverse('api:v2:pesticides:notice-active')).json()['features'][0]
        assert set(active['properties']) <= set(feature['properties'])

    def test_month(self):
        past = PesticideNotice.objects.get(pk=1)
        assert self.ids(year=2020, month=1) == [past.sqid]
        assert self.ids(year=2020, month=2) == []

    def test_bad_month_is_a_400(self):
        assert self.client.get(self.url, {'year': 2020, 'month': 13}).status_code == 400

    def test_cap(self):
        from camp.api.v2.pesticides import sections
        with self.settings():
            original = sections.MAX_NOTICES
            sections.MAX_NOTICES = 0
            try:
                assert self.client.get(self.url).status_code == 400
            finally:
                sections.MAX_NOTICES = original
```

(Check the URL namespace in `camp/api/v2/pesticides/urls.py` and the active endpoint's tests for the exact `reverse` names, and match imports at the top of `tests.py`.)

- [ ] **Step 2: Run, expect FAIL** (NoReverseMatch).

- [ ] **Step 3: Endpoint** — refactor `ActiveNoticeListBase.get` so the notice selection is a method:

```python
class ActiveNoticeListBase(generics.Endpoint):
    past = False

    def notices(self, params):
        """The notices this endpoint serves before its filters, soonest first."""
        return stats._upcoming(PesticideNotice.objects.all()).order_by('scheduled_application', 'pk')
```

`get()` starts from `self.notices(params)` (returning a 400 tuple/response if it signals bad params — follow how `parse_bbox` errors return `bad_request`), keeps every filter, the `distinct()`, the cap, and adds `'past': self.past` to each feature's properties only when `self.past` (so the active features are unchanged).

```python
class ArchivedNoticeListBase(ActiveNoticeListBase):
    past = True

    def notices(self, params):
        """Notices past the grace period, newest first; one month with `year` + `month`."""
        cutoff = timezone.now() - timedelta(days=stats.NOTICE_GRACE_DAYS)
        notices = PesticideNotice.objects.filter(scheduled_application__lt=cutoff)
        ...month bounds via the same helper NoticeList uses (local_month_bounds in camp/apps/pesticides/views.py — move it to a shared module if importing views from the API would be circular)...
        return notices.order_by('-scheduled_application', '-pk')


class ArchivedNoticeList(CachedEndpointMixin, ArchivedNoticeListBase):
    """Past SprayDays notices of intent (past the four-day grace period) as GeoJSON points, newest first. Same parameters and cap as notices/active/, plus optional `year` + `month` for one month (America/Los_Angeles)."""
    cache_timeout = NOTICE_CACHE_TTL
```

A `month` without a valid `year`, or out of 1–12 → 400. Keep the existing `select_related`/`prefetch_related`. Add `path('notices/archive/', sections.ArchivedNoticeList.as_view(), name='notice-archive')` beside the active route. Make sure the cache key varies by `year`/`month` (check `CachedEndpointMixin`).

- [ ] **Step 4: Run** `camp/api/v2/pesticides` — pass. **Step 5: Commit** — `feat(api): archived notices as GeoJSON, for the map's past mode`

---

### Task 4: Scheduled / Past drives the whole page

**Files:**
- Modify: `camp/templates/pesticides/includes/notice-filters.html`, `camp/templates/pesticides/area-notices.html`
- Modify: `camp/apps/pesticides/stats.py` (`notice_summary`), `camp/apps/pesticides/views.py` (`NoticeList.get_map_config`, `AreaNoticesMixin`)
- Modify: `assets/js/pesticides/section-map.js` (past wording), `assets/sass/sjvair/pages/pesticides.sass` (toggle field style if needed)
- Test: `camp/apps/pesticides/tests/test_notices.py`, `camp/apps/pesticides/tests/test_stats.py` (or wherever stats tests live)

**Interfaces:** Consumes Task 3's `notice-archive` route. Produces `stats.notice_summary(queryset) -> {'count': int, 'acres': float|None, 'chemicals': [Chemical]}` (chemicals sorted by `display_name`).

- [ ] **Step 1: Failing tests** (append to `test_notices.py`):

```python
class NoticeModeTests(TestCase):
    """Scheduled / Past is a filter on the whole notices page."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.archived = PesticideNotice.objects.get(pk=1)
        self.tab = self.archived.county.get_pesticides_tab_url('notices')

    def form(self, html):
        start = html.index('notice-filters')
        return html[start:html.index('</form>', start)]

    def test_mode_is_a_field_in_the_filter_box(self):
        for url in (reverse('pesticides:notice-list'), self.tab):
            form = self.form(self.client.get(url).content.decode())
            assert 'name="past"' in form, url
            assert 'tabs is-toggle' not in self.client.get(url).content.decode().split('notice-filters')[0], url

    def test_switching_mode_drops_month_and_page(self):
        html = self.client.get(self.tab, {'past': 1, 'archive_year': 2020, 'month': 1, 'page': 2}).content.decode()
        form = self.form(html)
        # The month and page ride along only while Past stays chosen; the
        # Scheduled choice must not submit them.
        assert 'name="page"' not in form
        scheduled = re.search(r'<input[^>]*name="past"[^>]*value=""[^>]*>|<input[^>]*value=""[^>]*name="past"[^>]*>', form)
        assert scheduled, 'no Scheduled option'

    def test_stats_follow_the_mode(self):
        past = self.client.get(self.tab, {'past': 1}).context
        assert past['notice_stats']['count'] == 1
        month = self.client.get(self.tab, {'past': 1, 'archive_year': 2020, 'month': 2}).context
        assert month['notice_stats']['count'] == 0

    def test_stats_follow_a_chemical_filter(self):
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        chem = Chemical.objects.get(pk=1)
        url = kern.get_pesticides_tab_url('notices')
        assert self.client.get(url, {'chemical': chem.sqid}).context['notice_stats']['count'] == 1
        other = Chemical.objects.exclude(pk=1).first()
        assert self.client.get(url, {'chemical': other.sqid}).context['notice_stats']['count'] == 0

    def test_map_follows_the_mode(self):
        url = reverse('api:v2:pesticides:notice-archive')
        for page in (reverse('pesticides:notice-list'), self.tab):
            assert self.client.get(page).context['map_config']['notices_url'].startswith('/api/2.0/pesticides/notices/active/')
            assert self.client.get(page, {'past': 1}).context['map_config']['notices_url'] == url
            month = self.client.get(page, {'past': 1, 'archive_year': 2020, 'month': 1}).context['map_config']['notices_url']
            assert month.startswith(url + '?') and 'year=2020' in month and 'month=1' in month

    def test_tab_skips_the_upcoming_context(self):
        context = self.client.get(self.tab).context
        for key in ('upcoming_days', 'upcoming', 'upcoming_by_county'):
            assert key not in context, key
```

(`import re` at the top. If `notice_stats` collides with an existing key, pick another and use it consistently. The second filter test assumes chemical pk 1 is on notice 3 only, as `NoticeListTests.test_filters` shows; adjust to the fixture if not.)

`stats` test: `notice_summary` over a queryset with one acres notice and one non-acres → `acres` is the acres sum; none in acres → `None`; chemicals de-duplicated and sorted.

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: `stats.notice_summary`** — beside `upcoming_by_day`, same acres rule and `distinct()`/prefetch care:

```python
def notice_summary(notices):
    """
    What a list of notices adds up to: how many, the acres among those that
    give an amount in acres (None when none do), and the chemicals they list.
    The notices page's stat row, whichever notices it's showing.
    """
    notices = notices.distinct().prefetch_related('chemicals')
    count, acres, chemicals = 0, None, {}
    for notice in notices:
        count += 1
        if notice.treated_amount and (notice.treated_units or '').strip().lower() == ACRES:
            acres = (acres or 0) + notice.treated_amount
        for chemical in notice.chemicals.all():
            chemicals.setdefault(chemical.pk, chemical)
    return {'count': count, 'acres': acres, 'chemicals': sorted(chemicals.values(), key=lambda c: c.display_name)}
```

- [ ] **Step 4: Views**
  - `NoticeList`: a `get_notices_url()` returning `'/api/2.0/pesticides/notices/active/'` in active mode, else `reverse('api:v2:pesticides:notice-archive')` plus `?year=Y&month=M` when both are set (from `form.cleaned_data['archive_year']`/`['month']`). `get_map_config` passes it into the config (set `config['notices_url']` after `section_map_config(...)` returns, or add a `notices_url=` kwarg to `section_map_config` defaulting to the active URL — pick whichever touches less; `section_map_config` lives in views.py ~line 1208).
  - `AreaNoticesMixin.get_map_config` does the same.
  - `AreaNoticesMixin.get_context_data`: drop `**places.upcoming_context(...)`; add `notice_stats=stats.notice_summary(self.get_queryset())` — the list's own filtered, mode- and month-aware queryset (before pagination). Sweep the context it adds for keys no template it renders reads (`grep` the area-notices template and its includes) and drop them; do the same for `AreaRecordsMixin`, `AreaSchoolsMixin` and `NoticeList` — list what you removed in the report.

- [ ] **Step 5: Templates**
  - `notice-filters.html`: delete the `div.tabs.is-toggle` block. Inside the form, first field:

```django
    <div class="field notice-mode">
        <label class="label">Notices</label>
        <div class="control">
            <div class="buttons has-addons are-small">
                <label class="button{% if mode == 'active' %} is-selected is-primary{% endif %}"><input type="radio" name="past" value=""{% if mode == 'active' %} checked{% endif %} hidden> Scheduled</label>
                <label class="button{% if mode == 'past' %} is-selected is-primary{% endif %}"><input type="radio" name="past" value="1"{% if mode == 'past' %} checked{% endif %} hidden> Past</label>
            </div>
        </div>
    </div>
```

    Remove the `<input type="hidden" name="past" value="1">`. The `archive_year`/`month` hidden inputs stay inside `{% if mode == 'past' %}` — and, so choosing Scheduled drops them, mark them `data-past-only` and add to `explorer.js` a delegated `change` handler: when a `[name="past"]` radio changes to `""`, disable the form's `[data-past-only]` inputs before the htmx submit (disabled inputs aren't submitted). If that's awkward with htmx's `change delay:250ms` trigger, the alternative is to have `NoticeList` ignore `archive_year`/`month` when not in past mode (it already does for the list) and make the archive-months/map/stats code ignore them too — then a stale param is harmless; choose one, and the test above must still pass. Give `.notice-mode .button` a cursor and keep the radios visually hidden (`hidden` attribute is fine).
  - `area-notices.html` stat row: read `notice_stats` — headings "Scheduled now" / "Past notices" (`{% if filter_month %} in {{ month label }}{% endif %}` — use the archive month's label the view already builds for archive months, or `calendar.month_name` via a small context value `filter_month_label`), "Acres", "Chemicals"; notes "notices of intent" / "to be treated" (scheduled) or "treated" (past), "restricted materials".

- [ ] **Step 6: Map wording** — in `section-map.js`, `noticeEntryHtml` and the notice popup (~lines 3417, 3461-3464): when the feature has `past` true, the sub-heading reads "Past notice" instead of "Notice of intent", and `through` is empty (no "may begin through"); in `legendRows` (~3134) the notices row reads "Past notice (numbered: how many)" when `this.data.noticesUrl` is the archive (pass a `noticesPast` flag in `map_config` — `notices_past: True` — rather than sniffing the URL). The section popup's notices block (`sectionNoticesHtml`) labels "Past notice(s)" likewise. Rebuild static.

- [ ] **Step 7: Run** pesticides + regions + api — pass. Smoke `scripts/pesticides_map_smoke.py` on a county Notices tab and the same with `?past=1` (Kern or Fresno — `get_pesticides_tab_url('notices')`); report results (the Schools-tab "locations"/"all sections" smoke failures are known expectation gaps, not regressions).

- [ ] **Step 8: Commit** — `feat(pesticides): Scheduled / Past filters the whole notices page`
