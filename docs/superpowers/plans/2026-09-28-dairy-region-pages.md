# Dairy Region Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every emissions area (county, community, ZIP, school district, tract, near-me point) its own dairy page, laid out like the Dairies tab but scoped to the area; shrink the emissions region page's Dairies block to a one-line summary that links there; and redirect the Dairies tab's `?region=` and near-me filters to the new pages.

**Architecture:**
- **Lookups.** `views.RegionPage` / `views.NearMe` lose their region and point lookups to two small mixins (`RegionLookupMixin`, `NearLookupMixin`) that the new dairy pages share, so the 404/redirect/bounce rules can't drift. `RegionRedirect` gets a `url_method` so the dairy short-URL redirect is a one-line subclass.
- **Pages.** `dairy_views.py` grows a `DairyScopeMixin` (the tab's scope resolution, canonical query and disabled scope-bar options, pulled out of `DairyList`), a `DairyAreaPage` base and two concrete pages, `RegionDairies` and `NearMeDairies`, on one template `emissions/dairy-area.html`. The tab and the pages share the stat tiles (`includes/dairy-stats.html`), the charts (`includes/dairy-charts.html`) and the table (`includes/dairy-table.html`, gaining `hide_county`).
- **Map.** `dairy_map_config()` takes area params for the GeoJSON URL and the facility map's `outline_url` / `center` / `zoom` / `radius`; `dairy-map.js` gains the facility map's outline, mask and circle handling. The dairy GeoJSON endpoint accepts `region=` and `lat`/`lng`/`radius`, so the map's points and the table's rows come from the same `dairy_q()`.
- **Region page.** `views.dairy_block()` slims to a summary with a `page_url`; `includes/dairy-block.html` becomes `includes/dairy-summary.html`.
- **Tab.** `DairyList` 301s `?region=` / `?lat=&lng=` to the pages, and its sidebar's region picker becomes the Find-your-area box wired to dairy URLs.

**Tech Stack:** Django/GeoDjango + PostGIS, django-vanilla-views, django-resticus (`CachedEndpointMixin`), htmx boosted swaps, MapTiler SDK on the map core (`window.SJVAirMaps`, `assets/js/maps/`), uPlot charts via `emissions_explorer` template tags, Bulma + bulma-tooltip, Selenium smoke script.

**Spec:** `docs/superpowers/specs/2026-09-28-dairy-region-pages-design.md` (read it before any task; it names every page section, URL and edge case).

## Global Constraints

- **Where to work.** Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer`, branch `feature/ceidars-explorer` (`<worktree>` below). Use absolute paths, and `git -C <worktree>` for every git command. Never edit or commit in `/home/derek/dev/ccac/sjvair.com` (the main checkout) or any other worktree. After each commit, verify it with `git -C <worktree> log --oneline -1`.
- **Tests** use `django.test.TestCase` with plain `assert`; fixtures `regions.yaml`, `emissions.yaml`; helpers in `camp/apps/emissions/tests` (`make_dairies`, `make_dairy`, `make`, `AROUND_PLANT`, `IN_KERN`, `dairy_inventory`, `dairy_map_data`, `map_data`).
- **Test command** (`$TEST <paths>` below):
  `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_dairypages -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer:/app test pytest <paths> -q -p no:cacheprovider --create-db`
  `fatal: not a git repository` in its output is harmless.
- **Asset rebuild:** the same prefix without `-e`, service `web`, `invoke vendor bundle styles`:
  `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer:/app web invoke vendor bundle styles`
  Run `node --check` on any JS touched.
- **Smoke:** `/home/derek/.claude/jobs/d44a9b36/tmp/venv/bin/python scripts/emissions_map_smoke.py --base http://localhost:8003`. The dev server is on :8003; never stop its container.
- **Commits:** explicit paths only (`git -C <worktree> add <new files>`, then `git -C <worktree> commit -m "…" -- <every path>`). Never `git add -A`, never `git stash`, never push, no AI attribution or Co-Authored-By trailers. Message style: `feat(dairies): …`, `refactor(emissions): …`, `test(emissions): …`.
- **Style:** match the surrounding code's comment density and naming. Verbose names use `_()`; don't align `=`. JS is plain ES2017 IIFE, `var`, `'use strict'`.
- **Copy, verbatim from the spec.** Summary line: `N dairies · N mature dairy cows · N Large CAFOs · N with digesters`. Link: `Dairies in <name> →`. Out of range: `See 2023 →`. Empty area (region page): `No dairies in CARB's dairy database here.` Empty dairy page: `No dairies in CARB's dairy database in <name> for <year>.` No CADD data: `No dairy data has been loaded yet.` County link line on a non-county dairy page: `CARB estimates dairy emissions by county: <County> dairies →`. County tile heading: `Dairy cattle, CARB estimate`. Footer: the tab's `These are CARB's counts…` sentence.
- **Pollutants.** `dairies.POLLUTANT_KEYS = ('rog', 'pm', 'pm10', 'tog')`; everything else falls back to ROG with `dairies.resolve_scope()`'s note. `toxics`/`minor` are dropped from the dairy pages' query by `dairy_views.canonical_query`.
- **Refinements made while planning** (the spec is otherwise followed as written):
  1. `find_area_places()` takes a URL *name* (`'emissions:region'` / `'emissions:region-dairies'`) rather than a `Region` method name: it builds URLs from `values_list('sqid', 'slug')` and never instantiates regions. Cached under its own key per name.
  2. The dairy GeoJSON endpoint validates `region=` against `views.AREA_PAGE_TYPES` (the spec's "`FILTER_TYPES` plus counties" is exactly that set); `dairy_views.FILTER_TYPES` is deleted in Task 7 rather than moved.
  3. The near-me breadcrumb's middle crumb carries the point *and* the page's scope (`year`, `pollutant`) after it, the same as the region crumb carries `scope_qs`.
  4. The dairy page's `<h1>` is the area's plain name (the region page's header, as the spec says); the heading line under it starts with `Dairies ·`, and the `<title>` is `Dairies in <title>`.

## Review Focus

- **A dairy page for an area with no dairies this year but a herd in an earlier year** (a closed dairy). The page must show the empty line, no stat row/map/table, and still the herd chart. Pinned by `test_no_dairies_this_year_keeps_the_charts` (Task 4).
- **`?county=` on a dairy page** (a link built from the tab's scope bar). It must be dropped before the scope resolves, so the county picker stays hidden and no link carries it. Pinned by `test_county_is_dropped` (Task 4).
- **A community dairy page whose only dairies count by mailing city** (their points sit outside the boundary). The table and the GeoJSON must agree because both use `RegionArea.dairy_q()`. Pinned by `test_region_narrows_by_the_same_rule_as_the_table` (Task 2) and the community smoke check (Task 8).
- **The tab's `?region=<unknown>`** (a stale bookmark, a retired tract). It must render unfiltered with a 200, not 404 or loop. Pinned by `test_an_unknown_region_renders_unfiltered` (Task 7).
- **A boosted year change on a dairy region page** (adopt, not rebuild). The outline must survive the swap and the map must reload the new year's points with the same outline. Pinned by `onAdopt`'s reload key list (Task 5) and the Tulare smoke check (Task 8).

---

### Task 1: Lookup mixins for region and near-me pages

**Files:**
- Modify: `camp/apps/emissions/views.py` (lines 563–588 `RegionRedirect`/`RegionPage.get`, 663–716 `NearMe`)
- Test: `camp/apps/emissions/tests/test_areas_pages.py` (existing tests must keep passing; one new test)

**Interfaces:**
- Consumes: nothing new.
- Produces (all in `camp.apps.emissions.views`):
  - `get_page_region(sqid) -> Region | None` — a region with a page (`AREA_PAGE_TYPES`, a boundary, current tract vintage), `select_related('boundary')`.
  - `class RegionLookupMixin` with `region_url(self, region) -> str` (default `region.get_emissions_url()`) and `lookup_region(self, request, sqid, slug) -> HttpResponse | None` (sets `self.region`; raises `Http404`; returns a 301 for a wrong slug, else `None`).
  - `class RegionRedirect(vanilla.View)` with class attr `url_method = 'get_emissions_url'`.
  - `class NearLookupMixin` with `lookup_near(self, request) -> HttpResponse | None` (sets `self.near`, `self.county`; returns the bounce, else `None`), `bounce()`, `near_title() -> str`, `near_params() -> dict`, `radius_url(miles)`, `radius_options() -> list[dict]`.
  - `RegionPage(RegionLookupMixin, AreaPage)` and `NearMe(NearLookupMixin, AreaPage)` behave exactly as before. `NearMe.dairy_link_params()` now returns `self.near_params()`.

- [ ] **Step 1: Write the failing test**

Add to the end of `camp/apps/emissions/tests/test_areas_pages.py`:

```python
class LookupMixinTests(TestCase):
    """The region and point lookups the emissions and dairy pages share."""
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')

    def test_get_page_region(self):
        assert views.get_page_region(self.fresno.sqid) == self.fresno
        retired = make(Region.Type.TRACT, '06019000199', AROUND_PLANT, version='2010')
        assert views.get_page_region(retired.sqid) is None
        assert views.get_page_region('nope') is None

    def test_region_redirect_uses_its_url_method(self):
        class DairyRedirect(views.RegionRedirect):
            url_method = 'get_emissions_url'
        request = RequestFactory().get('/x/', {'year': '2023'})
        response = DairyRedirect.as_view()(request, sqid=self.fresno.sqid)
        assert response.status_code == 301
        assert response['Location'] == f'{self.fresno.get_emissions_url()}?year=2023'

    def test_near_lookup(self):
        mixin = views.NearLookupMixin()
        request = RequestFactory().get('/x/', {'lat': '36.737', 'lng': '-119.787', 'radius': '3', 'label': 'x' * 500})
        mixin.request = request
        assert mixin.lookup_near(request) is None
        assert mixin.county == self.fresno and mixin.near.radius == 3
        assert len(request.GET['label']) == views.MAX_LABEL
        assert mixin.near_params() == {'lat': '36.7370', 'lng': '-119.7870', 'radius': 3, 'label': 'x' * views.MAX_LABEL}
        assert mixin.near_title().startswith('Within 3 miles of xxx')
        assert [option['miles'] for option in mixin.radius_options()] == [1, 3, 5]
        bounced = views.NearLookupMixin()
        response = bounced.lookup_near(RequestFactory().get('/x/', {'lat': '47.6', 'lng': '-122.3'}))
        assert response.status_code == 302 and response['Location'].endswith('?find=1')
```

Add `from django.test import RequestFactory, TestCase` to the imports (replacing the existing `TestCase` import).

- [ ] **Step 2: Run it to verify it fails**

Run: `$TEST camp/apps/emissions/tests/test_areas_pages.py::LookupMixinTests`
Expected: FAIL with `AttributeError: module ... has no attribute 'get_page_region'`.

- [ ] **Step 3: Refactor `views.py`**

Replace `RegionRedirect` and `RegionPage.get` (lines 563–588) with:

```python
def get_page_region(sqid):
    """A region with a page (AREA_PAGE_TYPES, a boundary, the current tract vintage), or None."""
    return (
        Region.objects.filter(sqid=sqid, type__in=AREA_PAGE_TYPES, boundary__isnull=False)
        .current_vintage().select_related('boundary').first()
    )


class RegionRedirect(vanilla.View):
    """`region/<sqid>/` -> the slugged URL, keeping the query string (the map's popups link here)."""

    # The Region method that builds the slugged URL; the dairy pages' redirect overrides it.
    url_method = 'get_emissions_url'

    def get(self, request, sqid):
        region = get_page_region(sqid)
        if region is None:
            raise Http404('No such region.')
        query = request.GET.urlencode()
        return redirect(getattr(region, self.url_method)() + (f'?{query}' if query else ''), permanent=True)


class RegionLookupMixin:
    """
    `region/<sqid>/<slug>/` for a page about one region: a page type with a
    boundary and a current vintage (get_page_region), else a 404; a wrong
    slug redirected to the right one with the query kept. The emissions
    region page and the dairy region page share it so the rules can't drift.
    """

    def region_url(self, region):
        return region.get_emissions_url()

    def lookup_region(self, request, sqid, slug):
        """Sets self.region; None when the URL is right, else the redirect. Raises Http404."""
        self.region = get_page_region(sqid)
        if self.region is None:
            raise Http404('No such region.')
        if slug != self.region.slug:
            query = request.GET.urlencode()
            return redirect(self.region_url(self.region) + (f'?{query}' if query else ''), permanent=True)
        return None


class RegionPage(RegionLookupMixin, AreaPage):
    def get(self, request, sqid, slug):
        response = self.lookup_region(request, sqid, slug)
        if response is not None:
            return response
        return super().get(request, sqid=sqid, slug=slug)
```

Replace `NearMe` (lines 663–736) with:

```python
class NearLookupMixin:
    """
    ?lat=&lng=&radius=&label= for a page about a point and a 1, 3 or 5 mile
    radius, from the address bar, never stored: `self.near` (a RadiusArea)
    and `self.county` (the covered county the point is in). Anything invalid,
    or a point outside the covered counties, bounces to the home page's find
    form. The emissions near-me page and the dairy near-me page share it.
    """

    def lookup_near(self, request):
        """Sets self.near and self.county; None when the point is good, else the bounce."""
        self.near = radius_area(request.GET)
        if self.near is None:
            return self.bounce()
        self.county = Region.objects.counties().filter(boundary__geometry__intersects=self.near.point).first()
        if self.county is None:
            return self.bounce()
        # Cut an over-long label in the query itself, so the links built from
        # it (the scope picker, the radius buttons) don't carry it either.
        label = request.GET.get('label') or ''
        if len(label) > MAX_LABEL:
            params = request.GET.copy()
            params['label'] = label[:MAX_LABEL]
            request.GET = params
        return None

    def bounce(self):
        return redirect(reverse('emissions:home') + '?find=1')

    def near_title(self):
        """'Within 3 miles of <label>' -- find-area.js labels read "near X"; the title already says "of"."""
        label = radius_label(self.request.GET, self.near.lat, self.near.lng)
        return f'Within {self.near.radius} mile{"s" if self.near.radius != 1 else ""} of {label}'

    def near_params(self):
        """The point as query parameters, for links to the other near-me page."""
        params = {'lat': f'{self.near.lat:.4f}', 'lng': f'{self.near.lng:.4f}', 'radius': self.near.radius}
        label = (self.request.GET.get('label') or '')[:MAX_LABEL]
        if label:
            params['label'] = label
        return params

    def radius_url(self, miles):
        params = self.request.GET.copy()
        params['radius'] = miles
        return f'{self.request.path}?{params.urlencode()}'

    def radius_options(self):
        return [
            {'miles': miles, 'url': self.radius_url(miles), 'current': miles == self.near.radius}
            for miles in RADIUS_CHOICES
        ]


class NearMe(NearLookupMixin, AreaPage):
    """The area page for a point and a 1, 3 or 5 mile radius (NearLookupMixin)."""

    def get(self, request, *args, **kwargs):
        response = self.lookup_near(request)
        if response is not None:
            return response
        return super().get(request, *args, **kwargs)

    def get_area(self):
        return self.near

    def get_county(self):
        return self.county

    def get_map_config(self, scope):
        return facility_map_config(
            scope, mode='compact', params=scope.params(county=None),
            areas_view=map_view(self.request.GET, Region.Type.TRACT, year=scope.year),
            center=f'{self.near.lat:.4f},{self.near.lng:.4f}', zoom=RADIUS_ZOOMS[self.near.radius],
            radius=self.near.radius,
        )

    def dairy_link_params(self):
        return self.near_params()

    def dairy_county(self):
        return None

    def get_context_data(self, **kwargs):
        # Not a region, so nothing to disambiguate with a type -- `name`
        # (the h1) and `title` (the <title> tag and breadcrumb) are the same.
        title = self.near_title()
        return super().get_context_data(
            name=title,
            title=title,
            kind='Near me',
            population=None,
            context_bar=None,
            radius_options=self.radius_options(),
            privacy_note=True,
            **kwargs,
        )
```

Note: `NearLookupMixin.near_title()` and `near_params()` read `self.request`, which vanilla views set in `dispatch()`; the unit test sets it by hand.

- [ ] **Step 4: Run the area page tests**

Run: `$TEST camp/apps/emissions/tests/test_areas_pages.py camp/apps/emissions/tests/test_dairies_pages.py`
Expected: all PASS (the refactor changes no behaviour; `LookupMixinTests` now passes).

- [ ] **Step 5: Commit**

```bash
git -C <worktree> commit -m "refactor(emissions): pull the region and near-me lookups into mixins" -- camp/apps/emissions/views.py camp/apps/emissions/tests/test_areas_pages.py
```

---

### Task 2: The dairy GeoJSON endpoint narrows to an area

**Files:**
- Modify: `camp/api/v2/emissions/dairies.py` (lines 1–80)
- Test: `camp/api/v2/emissions/tests.py` (`DairyEndpointTests`)

**Interfaces:**
- Consumes: `views.get_filter_region(sqid, types)`, `views.AREA_PAGE_TYPES`, `views.radius_area(get)`, `areas.RegionArea`, `dairies.table(year, area=…)`.
- Produces: `GET /api/2.0/emissions/dairies/geojson/?year=&region=<sqid>` and `?year=&lat=&lng=&radius=` — features narrowed by `RegionArea.dairy_q()` / `RadiusArea.dairy_q()`; unknown region or bad point → 400 `{'error': …}`; `get_area(request) -> (area | None, error | None)`.

- [ ] **Step 1: Write the failing tests**

Add to `DairyEndpointTests` in `camp/api/v2/emissions/tests.py` (imports: `from camp.apps.emissions import areas, dairies`, `from camp.apps.emissions.tests.test_areas import AROUND_PLANT, make`, `from camp.apps.emissions.tests.test_dairies import dairy_inventory, make_dairies, set_city`):

```python
    def test_region_narrows_by_the_same_rule_as_the_table(self):
        # Plantville's boundary holds BIG DAIRY by point; SMALL DAIRY (Kern)
        # counts in it by mailing city, though its point is far outside.
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        set_city(self.small, 'Plantville')
        dairies.clear_caches()
        names = [f['properties']['name'] for f in self.get('dairy-geojson', {'region': cdp.sqid}).json()['features']]
        assert names == [herd.dairy.name for herd in dairies.table(2023, area=areas.RegionArea(cdp))]
        assert set(names) == {'BIG DAIRY', 'SMALL DAIRY'}
        county = self.get('dairy-geojson', {'region': self.fresno.sqid}).json()['features']
        assert [f['properties']['name'] for f in county] == ['BIG DAIRY']

    def test_a_point_narrows_to_its_radius(self):
        near = self.get('dairy-geojson', {'lat': '36.737', 'lng': '-119.787', 'radius': '1'}).json()['features']
        assert [f['properties']['name'] for f in near] == ['BIG DAIRY']

    def test_unknown_region_and_bad_point_are_400(self):
        retired = make(Region.Type.TRACT, '06019000199', AROUND_PLANT, version='2010')
        for params in ({'region': 'nope'}, {'region': retired.sqid}, {'lat': 'x', 'lng': '1'},
                       {'lat': '36.7', 'lng': '-119.7', 'radius': '2'}, {'lat': '91', 'lng': '0'}):
            response = self.get('dairy-geojson', params)
            assert response.status_code == 400 and 'error' in response.json(), params

    def test_area_responses_are_cached_apart(self):
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        assert self.get('dairy-geojson', {'region': cdp.sqid})['X-Cache-Status'] == 'MISS'
        assert self.get('dairy-geojson', {'region': cdp.sqid})['X-Cache-Status'] == 'HIT'
        assert self.get('dairy-geojson')['X-Cache-Status'] == 'MISS'
        dairies.clear_caches()
        assert self.get('dairy-geojson', {'region': cdp.sqid})['X-Cache-Status'] == 'MISS'
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/api/v2/emissions/tests.py::DairyEndpointTests`
Expected: the four new tests FAIL (features unfiltered; 200 instead of 400).

- [ ] **Step 3: Implement `get_area` and use it**

In `camp/api/v2/emissions/dairies.py`, change the imports and add `get_area`:

```python
from camp.apps.emissions import areas, dairies
from camp.apps.emissions.models import Dairy
from camp.apps.emissions.pollutants import POLLUTANTS
from camp.apps.emissions.views import AREA_PAGE_TYPES, area_links, get_filter_region, radius_area
from camp.utils.views import CachedEndpointMixin
```

```python
def get_area(request):
    """
    (area, error): a RegionArea for ?region= (any region page type with a
    boundary: the dairy region pages' map), a RadiusArea for
    ?lat=&lng=&radius= (the near-me dairy page's), (None, None) with neither;
    an unknown region or a bad point is an error message.
    """
    sqid = (request.GET.get('region') or '').strip()
    if sqid:
        region = get_filter_region(sqid, types=AREA_PAGE_TYPES)
        if region is None:
            return None, 'region must be the id of a county, community, ZIP code, school district or census tract with a page.'
        return areas.RegionArea(region), None
    if 'lat' in request.GET or 'lng' in request.GET:
        near = radius_area(request.GET)
        if near is None:
            return None, 'lat and lng must be a point, and radius 1, 3 or 5 (miles).'
        return near, None
    return None, None
```

In `DairyGeoJSONBase.get`, after the year check:

```python
        area, error = get_area(request)
        if error:
            return http.Http400({'error': error})
        features = []
        for herd in dairies.table(year, area=area):
```

Update `DairyGeoJSON`'s docstring to mention `?region=<sqid>` and `?lat=&lng=&radius=` ("the area's dairies only, by the region pages' membership rule"), and bump `cache_key_version = 3` (a response cached under `?region=` before this change was unfiltered).

- [ ] **Step 4: Run the API tests**

Run: `$TEST camp/api/v2/emissions/tests.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git -C <worktree> commit -m "feat(dairies): the dairy GeoJSON narrows to a region or a radius" -- camp/api/v2/emissions/dairies.py camp/api/v2/emissions/tests.py
```

---

### Task 3: Shared stat tiles, charts and a `hide_county` table

**Files:**
- Create: `camp/templates/emissions/includes/dairy-stats.html`
- Create: `camp/templates/emissions/includes/dairy-charts.html`
- Modify: `camp/templates/emissions/includes/dairy-table.html` (lines 14, 27)
- Modify: `camp/templates/emissions/dairy-list.html` (lines 12–29, 68–72)
- Test: `camp/apps/emissions/tests/test_dairies_pages.py` (new `DairyIncludeTests`; existing tests keep passing)

**Interfaces:**
- Produces:
  - `emissions/includes/dairy-stats.html` — context: `summary` (`dairies.summary()`), `year`, optional `carb_estimate` = `{'tons': float, 'share': float | None, 'place': str}` (renders a fifth tile), `pollutant`.
  - `emissions/includes/dairy-charts.html` — context: `trend`, `emissions_trend` (`[]` for no CARB chart), `digester_trend` (`[]` for none), `pollutant`, `year`, `chart_place` (the CARB chart's place name, may be `None`).
  - `dairy-table.html` — new flag `hide_county` (hides the County column; `compact` still hides it too).

- [ ] **Step 1: Write the failing tests**

Add to `camp/apps/emissions/tests/test_dairies_pages.py` (import `from django.template.loader import render_to_string`):

```python
class DairyIncludeTests(DairyPageTestCase):
    """The tiles, charts and table the Dairies tab and the dairy region pages share."""

    def test_stats_include_with_and_without_the_carb_tile(self):
        summary = dairies.summary(2023)
        html = render_to_string('emissions/includes/dairy-stats.html', {'summary': summary, 'year': 2023})
        assert '<p class="heading">Total dairies</p><p class="title">2</p>' in html
        assert 'CARB estimate' not in html
        html = render_to_string('emissions/includes/dairy-stats.html', {
            'summary': summary, 'year': 2023, 'pollutant': POLLUTANTS['rog'],
            'carb_estimate': {'tons': 730.0, 'share': 0.25, 'place': 'Fresno County'},
        })
        assert '<p class="heading">Dairy cattle, CARB estimate</p><p class="title">730 <span class="is-size-5">tons/yr ROG</span></p>' in html
        assert '25% of Fresno County ROG' in html

    def test_table_hides_the_county_column(self):
        html = render_to_string('emissions/includes/dairy-table.html', {'rows': [], 'hide_county': True})
        assert '<th>County</th>' not in html
        html = render_to_string('emissions/includes/dairy-table.html', {'rows': []})
        assert '<th>County</th>' in html
```

Add `from camp.apps.emissions.pollutants import POLLUTANTS` and `from django.template.loader import render_to_string` to the file's imports.

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/emissions/tests/test_dairies_pages.py::DairyIncludeTests`
Expected: FAIL with `TemplateDoesNotExist: emissions/includes/dairy-stats.html`.

- [ ] **Step 3: Create the includes**

`camp/templates/emissions/includes/dairy-stats.html`:

```django
{% load humanize emissions_explorer %}
{% comment %}
The dairy headline tiles (dairies.summary), on the Dairies tab and a dairy
region page: the counted dairies with the Large CAFOs, digesters with their
share, milk cows with their share of cattle, and all cattle. `carb_estimate`
({tons, share, place}; county dairy pages only) adds CARB's county estimate
of dairy-cattle emissions in the scope pollutant, with dairy cattle's share
of the county's all-sources total.
{% endcomment %}
<div class="level is-mobile stat-row box is-grid-mobile">
    <div class="level-item has-text-centered"><div>
        <p class="heading">Total dairies</p><p class="title">{{ summary.dairies|intcomma }}</p>
        <p class="is-size-7 has-text-grey">{{ summary.large|intcomma }} large dair{{ summary.large|pluralize:"y,ies" }}</p>
    </div></div>
    <div class="level-item has-text-centered"><div>
        <p class="heading">With a digester</p><p class="title">{{ summary.digesters|intcomma }}</p>
        {% if summary.digester_share is not None %}<p class="is-size-7 has-text-grey">{{ summary.digester_share|percent }} of dairies</p>{% endif %}
    </div></div>
    <div class="level-item has-text-centered"><div>
        <p class="heading">Milk cows</p><p class="title">{{ summary.milk_cows|whole }}</p>
        {% if summary.milk_share is not None %}<p class="is-size-7 has-text-grey">{{ summary.milk_share|percent }} of cattle</p>{% endif %}
    </div></div>
    <div class="level-item has-text-centered"><div>
        <p class="heading">Total cattle</p><p class="title">{{ summary.cattle|whole }}</p>
        <p class="is-size-7 has-text-grey">cows, heifers, calves &amp; beef</p>
    </div></div>
    {% if carb_estimate %}
    <div class="level-item has-text-centered"><div>
        <p class="heading">Dairy cattle, CARB estimate</p><p class="title">{{ carb_estimate.tons|whole }} <span class="is-size-5">tons/yr {{ pollutant.label }}</span></p>
        {% if carb_estimate.share is not None %}<p class="is-size-7 has-text-grey">{{ carb_estimate.share|percent }} of {{ carb_estimate.place }} {{ pollutant.label }}</p>{% endif %}
    </div></div>
    {% endif %}
</div>
```

`camp/templates/emissions/includes/dairy-charts.html`:

```django
{% load emissions_explorer %}
{% comment %}
The dairy charts, on the Dairies tab and a dairy region page: the herd
trend, CARB's county dairy-cattle estimate where there is one
(`emissions_trend`, [] elsewhere) and the digester trend where any year had
one. `chart_place` names the place in the CARB chart's caption.
{% endcomment %}
<div class="columns is-desktop is-multiline mt-5 dairy-charts">
    <div class="column is-half-desktop">{% dairy_trend_chart trend year %}</div>
    {% if emissions_trend %}<div class="column is-half-desktop">{% dairy_emissions_chart emissions_trend pollutant year chart_place %}</div>{% endif %}
    {% if digester_trend %}<div class="column is-half-desktop">{% digester_trend_chart digester_trend year %}</div>{% endif %}
</div>
```

In `dairy-table.html`, line 14 becomes `{% if not compact and not hide_county %}<th>…County…</th>{% endif %}` and line 27 `{% if not compact and not hide_county %}<td>…</td>{% endif %}`; add `hide_county` to the comment block ("a county dairy page hides the County column").

In `dairy-list.html`: replace lines 12–29 (the stat row) with `{% include 'emissions/includes/dairy-stats.html' %}` and lines 68–72 (the charts) with `{% include 'emissions/includes/dairy-charts.html' with chart_place=scope.county.name %}`.

- [ ] **Step 4: Run the tab tests**

Run: `$TEST camp/apps/emissions/tests/test_dairies_pages.py`
Expected: all PASS (the tab renders the same markup through the includes).

- [ ] **Step 5: Commit**

```bash
git -C <worktree> add camp/templates/emissions/includes/dairy-stats.html camp/templates/emissions/includes/dairy-charts.html
git -C <worktree> commit -m "refactor(dairies): share the stat tiles, charts and table between the tab and the coming area pages" -- camp/templates/emissions/includes/dairy-stats.html camp/templates/emissions/includes/dairy-charts.html camp/templates/emissions/includes/dairy-table.html camp/templates/emissions/dairy-list.html camp/apps/emissions/tests/test_dairies_pages.py
```

---

### Task 4: The dairy region and near-me pages

**Files:**
- Modify: `camp/apps/regions/models.py` (after `get_emissions_url`, line 130)
- Modify: `camp/apps/emissions/urls.py`
- Modify: `camp/apps/emissions/views.py` (`WITHIN_KEY` block, line 23–31)
- Modify: `camp/apps/emissions/dairy_views.py` (most of it)
- Modify: `camp/templates/emissions/includes/dairy-map-toolbar.html` (lines 10–14, 43–54)
- Create: `camp/templates/emissions/dairy-area.html`
- Test: `camp/apps/emissions/tests/test_dairy_area_pages.py` (new), `camp/apps/regions/tests/test_models.py` if it exists else add to `camp/apps/emissions/tests/test_dairy_area_pages.py`

**Interfaces:**
- Consumes: Task 1's `RegionLookupMixin`, `NearLookupMixin`, `RegionRedirect.url_method`, `views.RADIUS_ZOOMS`, `views.region_title/region_page_title`; Task 2's `?region=`/point on the GeoJSON; Task 3's includes.
- Produces:
  - `Region.get_emissions_dairies_url()` → `reverse('emissions:region-dairies', kwargs={'sqid', 'slug'})`.
  - URL names `emissions:region-dairies`, `emissions:region-dairies-redirect`, `emissions:near-me-dairies`.
  - `views.WITHIN_DAIRIES_KEY = 'emissions:within-dairies:v1'`, `views.region_within_dairies(region)`.
  - `dairy_views.DairyScopeMixin(ScopeMixin)` with `resolve(request)` and the scope-bar context; `dairy_views.search_filters(get) -> {'q', 'sort'}`; `dairy_views.csv_response(rows, filename)`; `dairy_views.dairy_map_config(scope, view, *, area_params=None, outline_url='', center='', zoom='', radius='')`; `dairy_views.DairyAreaPage`, `RegionDairies`, `RegionDairiesRedirect`, `NearMeDairies`.
  - Template context on the pages (Tasks 5, 8 rely on the map's `data-*`): `map_config['map']['data']` carries `outline-url`, `center`, `zoom`, `radius`, `view="dairies"`, and `geojson-url` with `region=` or `lat/lng/radius`; `view_options` is `()` on area pages so the toolbar has no view switch.

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_dairy_area_pages.py`:

```python
import csv
import io
import re

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions import areas, dairies, dairy_views, views
from camp.apps.emissions.models import DairyHerd
from camp.apps.emissions.tests.test_areas import AROUND_PLANT, make
from camp.apps.emissions.tests.test_dairies import dairy_inventory, make_dairies, make_dairy
from camp.apps.emissions.tests.test_dairies_pages import dairy_map_data
from camp.apps.regions.models import Region

FARAWAY = 'MULTIPOLYGON(((-118.2 35.0, -118.1 35.0, -118.1 35.1, -118.2 35.1, -118.2 35.0)))'
HERD_TITLE = 'Mature dairy cows (solid) and other cattle (dashed) by year'
EMISSIONS_TITLE = 'Dairy cattle ROG, CARB estimate'
DIGESTER_TITLE = 'Dairies with an operating digester'


class DairyAreaTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.fresno_city = Region.objects.get(type=Region.Type.CITY, slug='fresno')
        self.big, self.small, self.closed = make_dairies()

    def get(self, region, params=None, status=200):
        response = self.client.get(region.get_emissions_dairies_url(), params or {})
        assert response.status_code == status, response.status_code
        return response

    def near(self, params=None, status=200):
        response = self.client.get(reverse('emissions:near-me-dairies'), params or {})
        assert response.status_code == status, response.status_code
        return response


class RouteTests(DairyAreaTestCase):
    def test_region_url(self):
        # The fixture's county slug is 'fresno'.
        assert self.fresno.get_emissions_dairies_url() == f'/tools/emissions/region/{self.fresno.sqid}/{self.fresno.slug}/dairies/'

    def test_every_page_type_renders(self):
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        zipcode = make(Region.Type.ZIPCODE, '93656', AROUND_PLANT)
        tract = make(Region.Type.TRACT, '06019000100', AROUND_PLANT)
        for region in (self.fresno, self.fresno_city, cdp, zipcode, tract):
            content = self.get(region, {'year': '2023'}).content.decode()
            assert 'BIG DAIRY' in content, region
            assert 'SMALL DAIRY' not in content, region
        assert self.get(self.fresno).context['section'] == 'dairies'

    def test_other_types_and_retired_tracts_404(self):
        retired = make(Region.Type.TRACT, '06019000199', AROUND_PLANT, version='2010')
        self.get(retired, status=404)
        other_type = next(region_type for region_type in Region.Type if region_type not in views.AREA_PAGE_TYPES)
        other = make(other_type, 'Other', AROUND_PLANT)
        assert self.client.get(reverse('emissions:region-dairies', kwargs={'sqid': other.sqid, 'slug': other.slug})).status_code == 404
        assert self.client.get(reverse('emissions:region-dairies-redirect', args=['nope'])).status_code == 404

    def test_short_url_and_wrong_slug_redirect_with_the_query(self):
        target = f'{self.fresno.get_emissions_dairies_url()}?year=2023'
        response = self.client.get(reverse('emissions:region-dairies-redirect', args=[self.fresno.sqid]), {'year': '2023'})
        assert response.status_code == 301 and response['Location'] == target
        response = self.client.get(reverse('emissions:region-dairies', kwargs={'sqid': self.fresno.sqid, 'slug': 'wrong'}), {'year': '2023'})
        assert response.status_code == 301 and response['Location'] == target

    def test_near_me(self):
        content = self.near({'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'label': 'near Home', 'year': '2023'}).content.decode()
        assert 'Within 1 mile of Home' in content and 'BIG DAIRY' in content
        assert 'class="within' not in content
        assert '3 mi</a>' in content
        home = reverse('emissions:home') + '?find=1'
        for params in ({}, {'lat': 'x', 'lng': '1'}, {'lat': '36.7', 'lng': '-119.7', 'radius': '2'}, {'lat': '47.6', 'lng': '-122.3'}):
            response = self.client.get(reverse('emissions:near-me-dairies'), params)
            assert response.status_code == 302 and response['Location'] == home, params
        long = self.near({'lat': '36.737', 'lng': '-119.787', 'label': 'x' * 500}).content.decode()
        assert 'x' * 121 not in long


class ScopeTests(DairyAreaTestCase):
    def test_a_year_outside_cadd_falls_back_with_a_note(self):
        content = self.get(self.fresno, {'year': '2024'}).content.decode()
        assert 'CADD has herd data for 2022–2023; showing 2023.' in content
        assert 'year=2023' in content and 'year=2024' not in content

    def test_nox_falls_back_to_rog_with_a_note(self):
        content = self.get(self.fresno, {'year': '2023', 'pollutant': 'nox'}).content.decode()
        assert 'Dairies report no NOx; showing ROG.' in content
        assert 'pollutant=rog' in content

    def test_county_is_dropped(self):
        response = self.get(self.fresno_city, {'year': '2023', 'county': 'kern'})
        content = response.content.decode()
        assert 'county=' not in content
        assert 'data-scope="county"' not in content
        assert response.context['county_options'] == []

    def test_disabled_options_have_the_tabs_tooltips(self):
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        assert 'data-tooltip="CADD has herd data for 2022–2023">2024</span>' in content
        assert 'data-tooltip="CARB reports no NOx from dairy cattle"' in content
        assert 'CARB reports no toxic air contaminants for dairy cattle' in content


class ContentTests(DairyAreaTestCase):
    def test_stat_tiles_match_the_summary(self):
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        summary = dairies.summary(2023, area=areas.RegionArea(self.fresno))
        assert f'<p class="heading">Total dairies</p><p class="title">{summary["dairies"]}</p>' in content
        assert '<p class="heading">Total cattle</p><p class="title">1,600</p>' in content
        assert '<h1 class="title is-3 mb-1">Fresno County</h1>' in content
        assert '<title>Dairies in Fresno County | ' in content

    def test_county_page_has_the_carb_tile_and_chart_and_no_county_column(self):
        dairy_inventory(self.fresno, rog=2.0)
        content = self.get(self.fresno, {'year': '2023', 'pollutant': 'rog'}).content.decode()
        assert '<p class="heading">Dairy cattle, CARB estimate</p><p class="title">730 <span class="is-size-5">tons/yr ROG</span></p>' in content
        assert '25% of Fresno County ROG' in content
        assert EMISSIONS_TITLE in content and HERD_TITLE in content and DIGESTER_TITLE in content
        assert '<th>County</th>' not in content and 'Other cattle' in content
        assert 'CARB estimates dairy emissions by county' not in content

    def test_city_page_has_no_carb_figure_and_links_the_county(self):
        dairy_inventory(self.fresno, rog=2.0)
        content = self.get(self.fresno_city, {'year': '2023', 'pollutant': 'rog'}).content.decode()
        assert 'CARB estimate' not in content and EMISSIONS_TITLE not in content
        assert HERD_TITLE in content and DIGESTER_TITLE in content
        assert f'CARB estimates dairy emissions by county: <a href="{self.fresno.get_emissions_dairies_url()}?year=2023&amp;pollutant=rog">Fresno County dairies →</a>' in content
        assert '<th>County</th>' in content

    def test_summary_and_digester_chart_count_the_same_dairies(self):
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        context = self.get(cdp, {'year': '2023'}).context
        assert context['summary']['dairies'] == 1 and context['summary']['digesters'] == 1
        by_year = {row['year']: row['digesters'] for row in context['digester_trend']}
        assert by_year[2023] == 1
        assert context['trend'] == dairies.trend(area=areas.RegionArea(cdp))

    def test_table_sorts_searches_and_pages(self):
        # cadd_ids 1-3 are make_dairies()'s; 60 more Fresno dairies make two pages.
        for n in range(10, 70):
            make_dairy(n, f'DAIRY {n}', (-119.786, 36.736), self.fresno, herds={2023: {'milk_cows': n}})
        dairies.clear_caches()
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        assert content.index('BIG DAIRY') < content.index('DAIRY 69')
        assert 'page=2' in content and 'sort=-mature_cows' in content
        assert f'class="dairy-zoom" data-dairy="{self.big.sqid}"' in content
        content = self.get(self.fresno, {'year': '2023', 'sort': 'name'}).content.decode()
        assert content.index('BIG DAIRY') < content.index('DAIRY 10')
        content = self.get(self.fresno, {'year': '2023', 'q': 'big'}).content.decode()
        assert 'BIG DAIRY' in content and 'DAIRY 10' not in content
        assert 'entity-picker' not in content and 'Remove the distance filter' not in content

    def test_csv(self):
        response = self.get(self.fresno, {'year': '2023', 'format': 'csv'})
        assert response['Content-Type'] == 'text/csv'
        assert f'dairies-{self.fresno.slug}-2023.csv' in response['Content-Disposition']
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        assert [row['dairy'] for row in rows] == ['BIG DAIRY']
        response = self.near({'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'year': '2023', 'format': 'csv'})
        assert 'dairies-near-36.7370--119.7870-1-2023.csv' in response['Content-Disposition']

    def test_no_dairies_this_year_keeps_the_charts(self):
        # CLOSED DAIRY only ever has empty herds; give it one counted year, then none in 2023.
        DairyHerd.objects.filter(dairy=self.closed, year=2021).update(milk_cows=10, mature_cows=10)
        west = make(Region.Type.CDP, 'Westside', 'MULTIPOLYGON(((-119.79 36.738, -119.77 36.738, -119.77 36.75, -119.79 36.75, -119.79 36.738)))')
        dairies.clear_caches()
        content = self.get(west, {'year': '2023'}).content.decode()
        assert "No dairies in CARB's dairy database in Westside for 2023." in content
        assert 'stat-row' not in content and 'dairy-table' not in content and 'dairy-map' not in content
        assert HERD_TITLE in content

    def test_no_dairies_ever_has_no_charts(self):
        urban = make(Region.Type.URBAN_AREA, 'Faraway', FARAWAY)
        content = self.get(urban, {'year': '2023'}).content.decode()
        assert "No dairies in CARB's dairy database in Faraway for 2023." in content
        assert HERD_TITLE not in content

    def test_no_cadd_data_at_all(self):
        DairyHerd.objects.all().delete()
        dairies.clear_caches()
        content = self.get(self.fresno).content.decode()
        assert 'No dairy data has been loaded yet.' in content
        assert 'stat-row' not in content

    def test_in_and_around_links_dairy_pages_and_is_cached_apart(self):
        # scope_qs is the dairies scope: the year always, and the (fallen-back) pollutant.
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        section = re.search(r'<section class="within mt-6" id="in-and-around">(.*?)</section>', content, re.S).group(1)
        assert f'href="{self.fresno_city.get_emissions_dairies_url()}?year=2023&amp;pollutant=rog"' in section
        assert '/tools/emissions/region/' in section and '/dairies/' in section
        assert cache.get(f'{views.WITHIN_DAIRIES_KEY}:{self.fresno.pk}') is not None
        assert cache.get(f'{views.WITHIN_KEY}:{self.fresno.pk}') is None

    def test_breadcrumbs(self):
        content = self.get(self.fresno_city, {'year': '2023'}).content.decode()
        crumbs = re.search(r'<nav class="breadcrumb"[^>]*>(.*?)</nav>', content, re.S).group(1)
        assert f'<a href="{self.fresno.get_emissions_url()}?year=2023&amp;pollutant=rog">Fresno County</a>' in crumbs
        assert f'<a href="{self.fresno_city.get_emissions_url()}?year=2023&amp;pollutant=rog">Fresno (City)</a>' in crumbs
        assert '<li class="is-active"><a aria-current="page">Dairies</a></li>' in crumbs
        county = self.get(self.fresno, {'year': '2023'}).content.decode()
        crumbs = re.search(r'<nav class="breadcrumb"[^>]*>(.*?)</nav>', county, re.S).group(1)
        assert crumbs.count('Fresno County') == 1
        near = self.near({'lat': '36.737', 'lng': '-119.787', 'radius': '3', 'label': 'near Home', 'year': '2023'}).content.decode()
        crumbs = re.search(r'<nav class="breadcrumb"[^>]*>(.*?)</nav>', near, re.S).group(1)
        assert f'<a href="{reverse("emissions:near-me")}?lat=36.7370&amp;lng=-119.7870&amp;radius=3&amp;label=near+Home&amp;year=2023&amp;pollutant=rog">Within 3 miles of Home</a>' in crumbs


class MapConfigTests(DairyAreaTestCase):
    def test_region_page_map(self):
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        assert dairy_map_data(content, 'view') == 'dairies'
        assert 'data-view="counties"' not in content
        assert dairy_map_data(content, 'outline-url') == reverse('api:v2:regions:region-detail', args=[self.fresno.sqid])
        assert dairy_map_data(content, 'geojson-url') == f'/api/2.0/emissions/dairies/geojson/?year=2023&amp;region={self.fresno.sqid}'
        assert dairy_map_data(content, 'county') in ('', None)
        assert 'data-size="large"' in content and 'data-digester="yes"' in content

    def test_near_me_map(self):
        content = self.near({'lat': '36.737', 'lng': '-119.787', 'radius': '3', 'year': '2023'}).content.decode()
        assert dairy_map_data(content, 'center') == '36.7370,-119.7870'
        assert dairy_map_data(content, 'zoom') == '12'
        assert dairy_map_data(content, 'radius') == '3'
        assert dairy_map_data(content, 'geojson-url') == '/api/2.0/emissions/dairies/geojson/?year=2023&amp;lat=36.7370&amp;lng=-119.7870&amp;radius=3'

    def test_config(self):
        scope, _ = dairies.resolve_scope({'year': '2023'})
        config = dairy_views.dairy_map_config(scope, dairy_views.dairy_map_view({}), area_params={'region': 'abc'}, outline_url='/o/')
        assert config['view'] == 'dairies' and config['view_options'] == ()
        assert config['map']['data']['outline-url'] == '/o/'
        tab = dairy_views.dairy_map_config(scope, dairy_views.dairy_map_view({'view': 'counties'}))
        assert tab['view'] == 'counties' and tab['view_options'] == dairy_views.VIEW_OPTIONS
```

Notes for the implementer: `make_dairies()` puts BIG DAIRY (1,300 mature cows + 300 other = 1,600 cattle, Fresno) and SMALL DAIRY (Kern); `dairy_inventory(fresno, rog=2.0)` gives 730 tons/yr dairy ROG out of 8.0 × 365 total → 25%. The Fresno city fixture's boundary contains BIG DAIRY's point. If `Region.objects.filter(type=AIR_DISTRICT)` is empty in the fixture, replace that assertion with a `SCHOOL_DISTRICT`-free type such as `Region.Type.FORECAST_ZONE` made with `make(...)`, or drop that line.

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/emissions/tests/test_dairy_area_pages.py`
Expected: FAIL with `AttributeError: 'Region' object has no attribute 'get_emissions_dairies_url'` / `NoReverseMatch`.

- [ ] **Step 3: `Region.get_emissions_dairies_url()` and the routes**

In `camp/apps/regions/models.py`, after `get_emissions_url` (line 132):

```python
    def get_emissions_dairies_url(self):
        """This region's dairies page in the emissions explorer."""
        return reverse('emissions:region-dairies', kwargs={'sqid': self.sqid, 'slug': self.slug})
```

`camp/apps/emissions/urls.py` — the short dairy URL **must come before** `region/<sqid>/<slug>/`, or `/region/X/dairies/` is taken as slug `dairies`:

```python
urlpatterns = [
    path('', views.Home.as_view(), name='home'),
    path('about/', views.About.as_view(), name='about'),
    path('map/', views.MapPage.as_view(), name='map'),
    path('near/', views.NearMe.as_view(), name='near-me'),
    path('near/dairies/', dairy_views.NearMeDairies.as_view(), name='near-me-dairies'),
    path('region/<str:sqid>/', views.RegionRedirect.as_view(), name='region-redirect'),
    # Before the slugged region page: `region/<sqid>/dairies/` isn't a slug.
    path('region/<str:sqid>/dairies/', dairy_views.RegionDairiesRedirect.as_view(), name='region-dairies-redirect'),
    path('region/<str:sqid>/<slug:slug>/', views.RegionPage.as_view(), name='region'),
    path('region/<str:sqid>/<slug:slug>/dairies/', dairy_views.RegionDairies.as_view(), name='region-dairies'),
    path('facilities/', views.FacilityList.as_view(), name='facility-list'),
    ...unchanged...
    path('dairies/', dairy_views.DairyList.as_view(), name='dairy-list'),
]
```

In `camp/apps/emissions/views.py`, after `region_within` (line 31):

```python
# The dairy region pages' own lists, linking other areas' dairy pages.
WITHIN_DAIRIES_KEY = 'emissions:within-dairies:v1'


def region_within_dairies(region):
    return nearby.regions_within(region, url_method='get_emissions_dairies_url', cache_prefix=WITHIN_DAIRIES_KEY)
```

- [ ] **Step 4: `dairy_views.py` — the scope mixin, shared helpers and map config**

Rewrite `dairy_views.py` so `DairyList` keeps its behaviour and the new pages share its parts. Full new module (keep the existing module docstring, constants `PAGE_SIZE`, `FILTER_TYPES`, `NEAR_KEYS`, `VIEW_OPTIONS`, `MEASURE_OPTIONS`, `SIZE_*`, `DIGESTER_*`, and the functions `table_filters`, `near_label`, `page_params`, `canonical_query`, `dairy_map_view` as they are, except where shown):

```python
import csv
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.urls import reverse

import vanilla

from camp.apps.emissions import areas, dairies, stats, views
from camp.apps.emissions.models import HERD_FIELDS
from camp.apps.emissions.pollutants import CRITERIA
from camp.apps.emissions.views import AREA_PAGE_TYPES, ScopeMixin, radius_area, radius_label, region_page_title, region_title
from camp.apps.regions.models import Region
from camp.utils import mapconfig


def search_filters(get):
    """The table's own filters, validated: a name search and the sort."""
    sort = get.get('sort')
    return {
        'q': (get.get('q') or '').strip() or None,
        'sort': sort if sort in dairies.TABLE_SORTS else dairies.DEFAULT_SORT,
    }


def table_filters(get):
    """The Dairies tab's filters: search_filters() plus a region (by point) or else near-me's radius."""
    region = views.get_filter_region(get.get('region'), types=FILTER_TYPES)
    return {
        **search_filters(get),
        'area': areas.RegionArea(region) if region else radius_area(get),
    }
```

`csv_response`, replacing `DairyList.csv_response`'s body:

```python
def csv_response(rows, filename):
    """The dairy table (dairies.table rows) as CSV, one row per herd."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(
        ['cadd_id', 'dairy', 'id', 'street', 'city', 'zipcode', 'county', 'year']
        + list(HERD_FIELDS)
        + ['mature_cows', 'other_cattle', 'size_class']
        + ['milk_cows_ref_code', 'non_milking_ref_code', 'digester_operating', 'digester_since']
    )
    for herd in rows:
        dairy = herd.dairy
        writer.writerow(
            [dairy.cadd_id, dairy.name, dairy.sqid, dairy.address.get('street', ''), dairy.address.get('city', ''),
             dairy.address.get('zipcode', ''), dairy.county.name, herd.year]
            + ['' if getattr(herd, field) is None else getattr(herd, field) for field in HERD_FIELDS]
            + [herd.mature_cows, herd.other_cattle, herd.size_class]
            + [herd.milk_cows_ref_code, herd.non_milking_ref_code,
               'yes' if herd.digester else 'no', herd.digester_since or '']
        )
    return response
```

`dairy_map_config` gains the area arguments:

```python
def dairy_map_config(scope, view, *, area_params=None, outline_url='', center='', zoom='', radius=''):
    """
    The data-* attributes of a `.dairy-map` (see assets/js/emissions/dairy-map.js):
    the Dairies tab's, or a dairy area page's with `area_params` (the GeoJSON
    endpoint's region= or lat/lng/radius, so the points are the area's
    dairies) and the area's frame -- `outline_url` (a region's boundary,
    outlined and masked) or `center`/`zoom`/`radius` (near-me's circle). An
    area page has the Dairies view only: no view switch, no Counties.
    """
    area = area_params is not None
    year_qs = urlencode({'year': scope.year})
    config = {
        'geojson_url': f"{reverse('api:v2:emissions:dairy-geojson')}?{urlencode({'year': scope.year, **(area_params or {})})}",
        'counties_url': f"{reverse('api:v2:emissions:dairy-counties')}?{urlencode({'year': scope.year, 'pollutant': scope.pollutant.key})}",
        'shapes_url': f"{reverse('api:v2:regions:region-geojson')}?type=county&simplify=1",
        'popup_url': reverse('api:v2:emissions:dairy-detail', args=['__id__']).replace('__id__', '{id}') + f'?{year_qs}',
        'region_url': reverse('emissions:region-redirect', args=['__id__']).replace('__id__', '{id}'),
        # What the popups' links to region pages carry: the scope, less the county.
        'query': urlencode(scope.params(county=None)),
        'county': scope.county.slug if scope.county else '',
        'year': scope.year,
        'label': scope.pollutant.label,
        'unit': scope.pollutant.unit,
        'view': 'dairies' if area else view['view'],
        'measure': view['measure'],
        'source_note': dairies.CEPAM_NOTE,
        # The region or circle the page is about (dairy region pages, near-me).
        'outline_url': outline_url,
        'center': center,
        'zoom': zoom,
        'radius': radius,
        'view_options': () if area else VIEW_OPTIONS,
        'measure_options': MEASURE_OPTIONS,
        ...the sizes/digester keys, unchanged...
    }
```

The rest of the function (labels, `template_only`, `mapconfig.map_config(...)`) is unchanged.

In `dairy-map-toolbar.html`, wrap the view switch (lines 10–14) in `{% if map_config.view_options %} … {% endif %}` and the measure dropdown (lines 43–54) in the same test, and note it in the comment ("an area page has no view switch and no measure: Dairies only").

The scope mixin and pages:

```python
class DairyScopeMixin(ScopeMixin):
    """
    A page on the dairies scope: dairies.resolve_scope() (CADD's years, the
    pollutants dairies report, with a note for each fallback), the request's
    GET rewritten to the canonical query so every link built from it carries
    the fallbacks, and the scope bar showing what doesn't apply, disabled.
    """
    section = 'dairies'

    def resolve(self, request):
        self._scope, self.notes = dairies.resolve_scope(request.GET)
        request.GET = canonical_query(request.GET, self._scope)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        known = dairies.years()
        # No CADD years at all yet (before any import): the no-data state
        # covers the page, and the scope bar's year picker has nothing of
        # its own to offer, so it's hidden rather than showing every
        # explorer year as a dead "None" fallback.
        year_options = sorted(set(stats.available_years()) | set(known)) if known else []
        span = f'{known[0]}–{known[-1]}' if known else ''
        params = page_params(scope)
        context = {
            'notes': self.notes,
            'has_data': bool(known),
            'coverage_note': scope.year is not None and scope.year < dairies.COVERAGE_CHANGE_YEAR,
            'coverage_year': dairies.COVERAGE_CHANGE_YEAR,
            'scope_params': params,
            'scope_qs': f'?{urlencode(params)}' if params else '',
            'year_options': year_options,
            'disabled_years': {year: f'CADD has herd data for {span}' for year in year_options if year not in known},
            'pollutant_options': CRITERIA,
            'disabled_pollutants': {
                pollutant.key: f'CARB reports no {pollutant.label} from dairy cattle'
                for pollutant in CRITERIA if pollutant.key not in dairies.POLLUTANT_KEYS
            },
            'disabled_toggles': {
                'toxics': 'CARB reports no toxic air contaminants for dairy cattle',
                'minor': 'Minor sources are small permitted facilities; dairies have none',
            },
        }
        context.update(kwargs)
        return super().get_context_data(**context)


class DairyList(DairyScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/dairy-list.html'

    def get(self, request, *args, **kwargs):
        self.resolve(request)
        if request.GET.get('format') == 'csv':
            scope = self.get_scope()
            return csv_response(dairies.table(scope.year, county=scope.county, **table_filters(request.GET)), f'dairies-{scope.year}.csv')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        filters = table_filters(self.request.GET)
        area = filters['area']
        rows = dairies.table(scope.year, county=scope.county, **filters)
        page = Paginator(rows, PAGE_SIZE).get_page(self.request.GET.get('page'))
        near = isinstance(area, areas.RadiusArea)
        return super().get_context_data(
            summary=dairies.summary(scope.year, county=scope.county, area=area),
            rows=page.object_list,
            page_obj=page,
            is_paginated=page.has_other_pages(),
            sort=filters['sort'],
            filters=filters,
            region={'sqid': area.region.sqid, 'name': region_title(area.region)} if isinstance(area, areas.RegionArea) else None,
            near=near_label(self.request.GET, area),
            near_params={key: self.request.GET[key] for key in NEAR_KEYS if key in self.request.GET} if near else {},
            trend=dairies.trend(county=scope.county, area=area),
            # CARB's estimate is by county: the scope's county, else all of them.
            emissions_trend=dairies.emissions_trend(scope.pollutant, county=scope.county),
            digester_trend=dairies.digester_chart_points(county=scope.county, area=area),
            map_config=dairy_map_config(scope, dairy_map_view(self.request.GET)) if dairies.years() else None,
            **kwargs,
        )


class DairyAreaPage(DairyScopeMixin, vanilla.TemplateView):
    """
    What a region's and a near-me dairy page share: one area's dairies for
    the resolved year -- the tiles, the map framed on the area, the table
    with its search, sort, pages and CSV, and the charts.
    """
    template_name = 'emissions/dairy-area.html'

    def get(self, request, *args, **kwargs):
        # The page is the area: a stray ?county= would ride along on every
        # link built from request.GET, so drop it before the scope resolves.
        if 'county' in request.GET:
            params = request.GET.copy()
            params.pop('county')
            request.GET = params
        self.resolve(request)
        if request.GET.get('format') == 'csv':
            return csv_response(self.rows(), self.csv_name(self.get_scope().year))
        return super().get(request, *args, **kwargs)

    def get_area(self):
        raise NotImplementedError

    def carb_county(self):
        """The county whose CARB dairy-cattle estimate the page shows (county pages), else None."""
        raise NotImplementedError

    def get_map_config(self, scope):
        raise NotImplementedError

    def csv_name(self, year):
        raise NotImplementedError

    def rows(self):
        return dairies.table(self.get_scope().year, area=self.get_area(), **search_filters(self.request.GET))

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        area = self.get_area()
        county = self.carb_county()
        filters = search_filters(self.request.GET)
        page = Paginator(self.rows(), PAGE_SIZE).get_page(self.request.GET.get('page'))
        summary = dairies.summary(scope.year, area=area)
        trend = dairies.trend(area=area)
        # [] off county pages and for a pollutant CARB doesn't report (the
        # scope has already fallen back to one it does, so a county page
        # always has the chart when CEPAM has the county).
        emissions_trend = dairies.emissions_trend(scope.pollutant, county=county) if county is not None else []
        this_year = next((row for row in emissions_trend if row['year'] == scope.year), None)
        # A region page overrides this with its own "In and around" lists;
        # a near-me page (a point, not a region) has none.
        kwargs.setdefault('within', None)
        return super().get_context_data(
            area=area,
            summary=summary,
            has_dairies=bool(summary['dairies']),
            # The charts stay while any CADD year had a counted herd here (a dairy that closed).
            has_history=bool(trend),
            rows=page.object_list,
            page_obj=page,
            is_paginated=page.has_other_pages(),
            sort=filters['sort'],
            filters=filters,
            trend=trend,
            emissions_trend=emissions_trend,
            digester_trend=dairies.digester_chart_points(area=area),
            carb_estimate={'tons': this_year['value'], 'share': this_year['share'], 'place': county.name} if this_year else None,
            hide_county=county is not None,
            map_config=self.get_map_config(scope) if dairies.years() else None,
            # The page is the area: no county picker.
            county_options=[],
            **kwargs,
        )


class RegionDairiesRedirect(views.RegionRedirect):
    """`region/<sqid>/dairies/` -> the slugged dairy page, keeping the query string."""
    url_method = 'get_emissions_dairies_url'


class RegionDairies(views.RegionLookupMixin, DairyAreaPage):
    def region_url(self, region):
        return region.get_emissions_dairies_url()

    def get(self, request, sqid, slug):
        response = self.lookup_region(request, sqid, slug)
        if response is not None:
            return response
        return super().get(request, sqid=sqid, slug=slug)

    def get_area(self):
        return areas.RegionArea(self.region)

    def carb_county(self):
        return self.region if self.region.type == Region.Type.COUNTY else None

    def get_map_config(self, scope):
        return dairy_map_config(
            scope, dairy_map_view(self.request.GET), area_params={'region': self.region.sqid},
            outline_url=reverse('api:v2:regions:region-detail', args=[self.region.sqid]),
        )

    def csv_name(self, year):
        return f'dairies-{self.region.slug}-{year}.csv'

    def get_context_data(self, **kwargs):
        region = self.region
        county = region if region.type == Region.Type.COUNTY else Region.objects.get_county_region(region)
        return super().get_context_data(
            # `name` is the plain heading (h1); `title` (the <title> tag and
            # the breadcrumb) adds the type for a community region.
            name=region_title(region),
            title=region_page_title(region),
            kind=region.type_label,
            population=(region.metadata or {}).get('population'),
            county_region=county,
            region_page_url=region.get_emissions_url(),
            # Non-county pages point at the county's dairy page for CARB's estimate.
            county_dairies_url=county.get_emissions_dairies_url() if county is not None and county != region else None,
            within=views.region_within_dairies(region),
            **kwargs,
        )


class NearMeDairies(views.NearLookupMixin, DairyAreaPage):
    """The dairy page for a point and a 1, 3 or 5 mile radius (views.NearLookupMixin)."""

    def get(self, request, *args, **kwargs):
        response = self.lookup_near(request)
        if response is not None:
            return response
        return super().get(request, *args, **kwargs)

    def get_area(self):
        return self.near

    def carb_county(self):
        return None

    def get_map_config(self, scope):
        return dairy_map_config(
            scope, dairy_map_view(self.request.GET), area_params=self.near_params_for_api(),
            center=f'{self.near.lat:.4f},{self.near.lng:.4f}', zoom=views.RADIUS_ZOOMS[self.near.radius],
            radius=self.near.radius,
        )

    def near_params_for_api(self):
        """The point without its label: the GeoJSON endpoint doesn't take one."""
        return {key: value for key, value in self.near_params().items() if key != 'label'}

    def csv_name(self, year):
        return f'dairies-near-{self.near.lat:.4f}-{self.near.lng:.4f}-{self.near.radius}-{year}.csv'

    def get_context_data(self, **kwargs):
        title = self.near_title()
        scope = self.get_scope()
        return super().get_context_data(
            name=title,
            title=title,
            kind='Near me',
            population=None,
            county_region=None,
            radius_options=self.radius_options(),
            # The emissions near-me page for the breadcrumb: the point, then the page's scope.
            near_page_url=f"{reverse('emissions:near-me')}?{urlencode({**self.near_params(), **page_params(scope)})}",
            privacy_note=True,
            **kwargs,
        )
```

Delete the old `DairyList.csv_response` method; `test_csv` on the tab still expects `dairies-2023.csv`.

- [ ] **Step 5: The template**

Create `camp/templates/emissions/dairy-area.html`:

```django
{% extends 'emissions/base.html' %}
{% load humanize emissions_explorer pesticides_explorer %}
{% comment %}
One area's dairies (dairy_views.DairyAreaPage): a region's or a near-me
point's. The region page's header, the Dairies tab's tiles, map, table and
charts scoped to the area, and "In and around" linking other areas' dairy
pages. County pages add CARB's county estimate (a tile and a chart) and hide
the table's County column.
{% endcomment %}

{% block title %}Dairies in {{ title }} | {{ block.super }}{% endblock %}
{% block breadcrumb-list %}{% if county_region and county_region != area.region %}<li><a href="{{ county_region.get_emissions_url }}{{ scope_qs }}">{{ county_region.name }}</a></li>{% endif %}<li><a href="{% if region_page_url %}{{ region_page_url }}{{ scope_qs }}{% else %}{{ near_page_url }}{% endif %}">{{ title }}</a></li><li class="is-active"><a aria-current="page">Dairies</a></li>{% endblock %}

{% block explorer-content %}
<div class="content">
    <h1 class="title is-3 mb-1">{{ name }}</h1>
    <p class="heading">Dairies · {{ kind }}{% if county_region and county_region != area.region %} · {{ county_region.name }}{% endif %}{% if population %} · {{ population|whole }} people{% endif %}</p>
    {% if radius_options %}
    <div class="buttons has-addons explorer-scope">
        {% for option in radius_options %}<a class="button is-small{% if option.current %} is-link is-selected{% endif %}" href="{{ option.url }}">{{ option.miles }} mi</a>{% endfor %}
    </div>
    {% endif %}
</div>
{% for note in notes %}<p class="notification is-warning is-light py-2 px-3 dairy-note">{{ note }}</p>{% endfor %}
{% if not has_data %}
<p class="has-text-grey">No dairy data has been loaded yet.</p>
{% else %}
{% if has_dairies %}
{% include 'emissions/includes/dairy-stats.html' %}

{% include 'maps/includes/map.html' with map=map_config.map %}
<p class="is-size-7 mt-2">Each circle is a dairy in CARB's dairy database (CADD), sized by its mature dairy cows (other cattle where it has none) and coloured by its EPA size class; the Digester filter shows the dairies that ran an anaerobic digester in {{ year }}. <a href="{% url 'emissions:about' %}#dairies">About the dairy data</a>.</p>
{% if coverage_note %}<p class="is-size-7 has-text-grey dairy-coverage-note">CADD tracked fewer dairies before {{ coverage_year }}, so totals for {{ year }} aren't a like-for-like comparison with later years.</p>{% endif %}
<noscript><p>The map needs JavaScript; the table below lists the same dairies.</p></noscript>

<div class="columns mt-4">
    <div class="column is-3-desktop">
        <form method="get" class="explorer-filters box" hx-trigger="submit, change delay:250ms">
            {% for key, value in scope_params.items %}<input type="hidden" name="{{ key }}" value="{{ value }}">{% endfor %}
            <input type="hidden" name="sort" value="{{ sort }}">
            <div class="field">
                <label class="label" for="dairy-q">Search</label>
                <div class="control has-icons-left">
                    <input class="input" type="search" id="dairy-q" name="q" value="{{ filters.q|default:'' }}" placeholder="Dairy name"
                        hx-get="{{ request.path }}" hx-include="closest form" hx-trigger="keyup changed delay:500ms, search">
                    <span class="icon is-small is-left"><span class="fas fa-search"></span></span>
                </div>
            </div>
            <div class="field is-grouped">
                <div class="control"><button class="button is-link" type="submit">Apply</button></div>
                <div class="control"><a class="button is-light" href="{{ request.path }}{{ scope_qs }}">Clear</a></div>
            </div>
        </form>
    </div>
    <div class="column">
        {% include 'emissions/includes/dairy-table.html' with sortable=True zoom=True %}
        {% include 'pesticides/includes/pagination.html' %}
        <p class="mt-3"><a href="{% qs_replace format='csv' page=None %}" hx-boost="false" download>Download these dairies (CSV)</a></p>
    </div>
</div>
{% else %}
<p class="has-text-grey dairy-empty">No dairies in CARB's dairy database in {{ name }} for {{ year }}.</p>
{% if carb_estimate %}<p class="dairy-county-line">Dairy cattle, CARB estimate: <strong>{{ carb_estimate.tons|whole }} tons/yr {{ pollutant.label }}</strong></p>{% endif %}
{% endif %}
{% if has_history %}{% include 'emissions/includes/dairy-charts.html' with chart_place=county_region.name %}{% endif %}
{% if county_dairies_url %}<p class="mt-4">CARB estimates dairy emissions by county: <a href="{{ county_dairies_url }}{{ scope_qs }}">{{ county_region.name }} dairies →</a></p>{% endif %}
<p class="is-size-7">These are CARB's counts: herds, digesters, and CARB's county estimate of dairy cattle emissions. Nothing here estimates one dairy's emissions. <a href="{% url 'emissions:about' %}#dairies">How the dairy data works</a>.</p>
{% endif %}

{% include 'regions/includes/within.html' with within_name=name %}

{% if privacy_note %}<p class="is-size-7 has-text-grey">This page's location is only in its address; we don't store it.</p>{% endif %}
{% endblock %}
```

(`hide_county` is in the context, so the table include picks it up; `area.region` resolves to `''` on near-me, which is fine.)

- [ ] **Step 6: Run the new tests and the neighbours**

Run: `$TEST camp/apps/emissions/tests/test_dairy_area_pages.py camp/apps/emissions/tests/test_dairies_pages.py camp/apps/emissions/tests/test_areas_pages.py`
Expected: all PASS. The near-me crumb's order is what `urlencode({**near_params, **page_params})` produces (lat, lng, radius, label, year, pollutant); `page_params` keeps `pollutant=rog` because the dairies scope's pollutant is never the explorer default (NOx), which is why every `scope_qs` on these pages reads `?year=2023&pollutant=rog`.

- [ ] **Step 7: Check the page in the dev server**

Open `http://localhost:8003/tools/emissions/region/<tulare sqid>/tulare-county/dairies/?year=2023` (find the sqid from the home page's county jump links). The tiles, map container, table and charts render; the scope bar has no county picker. The map itself is not framed yet (Task 5).

- [ ] **Step 8: Commit**

```bash
git -C <worktree> add camp/templates/emissions/dairy-area.html camp/apps/emissions/tests/test_dairy_area_pages.py
git -C <worktree> commit -m "feat(dairies): a dairy page per emissions area, nested under the area's URL" -- camp/apps/regions/models.py camp/apps/emissions/urls.py camp/apps/emissions/views.py camp/apps/emissions/dairy_views.py camp/templates/emissions/dairy-area.html camp/templates/emissions/includes/dairy-map-toolbar.html camp/apps/emissions/tests/test_dairy_area_pages.py
```

---

### Task 5: The dairy map frames the area (JS)

**Files:**
- Modify: `assets/js/emissions/dairy-map.js`

**Interfaces:**
- Consumes: the container's `data-outline-url`, `data-center`, `data-zoom`, `data-radius` from Task 4; `M.parseCenter`, `M.geometryBounds`, `M.EMPTY`, `shell.ensureSource/ensureLayer/setSourceData/frame`; the regions API's `region-detail` JSON (`json.data.boundary.geometry`).
- Produces: `DairyMap.prototype.loadOutline()`, `showOutline(geometry)`, `outlineBounds` (read by the smoke script), sources `outline` / `outline-mask`, layers `outline-mask` / `outline-line` above `dairies`; `frame()`/`home()` prefer the outline; `onAdopt` reloads on `outlineUrl`, `center`, `radius` changes.

- [ ] **Step 1: Add the constants and helpers**

After `var ZOOM_TO = 12;` (line 55):

```js
  // The page's own area (a dairy region page's boundary, near-me's radius):
  // its outline's colour, the world ring the mask is cut from, and the
  // circle's resolution -- the same as the facility map's.
  var OUTLINE_COLOR = '#d35400';
  var WORLD_RING = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
  var CIRCLE_POINTS = 64;
  var METERS_PER_MILE = 1609.344;
```

After `digesterText` (before `popupHtml`):

```js
  // Everything outside `geometry` (a Polygon or MultiPolygon), as one polygon
  // with the geometry's outer rings as holes: the page's area stays clear,
  // the rest is washed out.
  function maskFor(geometry) {
    var rings = [];
    if (geometry.type === 'Polygon') rings = [geometry.coordinates[0]];
    if (geometry.type === 'MultiPolygon') rings = geometry.coordinates.map(function (part) { return part[0]; });
    if (!rings.length) return M.EMPTY;
    return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [WORLD_RING].concat(rings) } };
  }

  // A `miles` circle around [lng, lat] as a polygon (the SDK has no circles in metres).
  function circle(center, miles) {
    var meters = miles * METERS_PER_MILE;
    var dLat = meters / 111320;
    var dLng = meters / (111320 * Math.cos(center[1] * Math.PI / 180));
    var ring = [];
    for (var i = 0; i <= CIRCLE_POINTS; i++) {
      var angle = (i % CIRCLE_POINTS) * 2 * Math.PI / CIRCLE_POINTS;
      ring.push([center[0] + dLng * Math.cos(angle), center[1] + dLat * Math.sin(angle)]);
    }
    return { type: 'Polygon', coordinates: [ring] };
  }
```

- [ ] **Step 2: State, layers, loading**

In the constructor, after `this.countyAnchors = {};`:

```js
    // The page's outline (region JSON) has its own request counter and bounds.
    this.outlineRequest = 0;
    this.outlineBounds = null;
```

In `addLayers`, add the sources after `ensureSource('dairies')` and the two layers after the `dairies` layer (so the wash sits over the points, as on the facility map):

```js
    this.shell.ensureSource('outline');
    this.shell.ensureSource('outline-mask');
```

```js
    this.shell.ensureLayer({
      id: 'outline-mask', type: 'fill', source: 'outline-mask',
      paint: { 'fill-color': '#ffffff', 'fill-opacity': 0.55 },
    });
    this.shell.ensureLayer({
      id: 'outline-line', type: 'line', source: 'outline',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': OUTLINE_COLOR, 'line-width': 2.5, 'line-opacity': 0.9 },
    });
```

In `load()`, first line after `var ticket = this.shell.ticket();`: `this.loadOutline();`. Then add, after `load`:

```js
  // The page's own area: a region's boundary (dairy region pages) or the
  // radius (near-me), outlined, with everything outside washed out, and
  // framed. A dairy counted by its mailing city can sit outside the
  // boundary: it still draws, under the wash.
  DairyMap.prototype.loadOutline = function () {
    var self = this;
    var request = ++this.outlineRequest;
    var center = M.parseCenter(this.data.center);
    var radius = parseFloat(this.data.radius);
    if (center && radius > 0) {
      this.showOutline(circle(center, radius));
      return;
    }
    if (!this.data.outlineUrl) {
      this.showOutline(null);
      return;
    }
    getJson(this.data.outlineUrl)
      .then(function (json) {
        if (request !== self.outlineRequest || !self.map) return;
        var boundary = json && json.data && json.data.boundary;
        self.showOutline(boundary ? boundary.geometry : null);
      })
      .catch(function (err) {
        if (request !== self.outlineRequest || !self.map) return;
        logError('failed to load the outline', err);
      });
  };

  DairyMap.prototype.showOutline = function (geometry) {
    if (!geometry) {
      this.outlineBounds = null;
      this.shell.setSourceData('outline', M.EMPTY);
      this.shell.setSourceData('outline-mask', M.EMPTY);
      return;
    }
    this.shell.setSourceData('outline', { type: 'Feature', properties: {}, geometry: geometry });
    this.shell.setSourceData('outline-mask', maskFor(geometry));
    this.outlineBounds = M.geometryBounds(geometry);
    if (this.outlineBounds) this.map.fitBounds(this.outlineBounds, { padding: 24, duration: 0 });
  };
```

Replace `frame` and `home`:

```js
  // The page's area frames the map when it has one (fitted as the outline
  // arrives); else a county in scope does; otherwise the page's bounds.
  DairyMap.prototype.frame = function () {
    if (this.outlineBounds || this.data.outlineUrl || M.parseCenter(this.data.center)) return;
    var bounds = this.countyBounds();
    if (bounds) this.map.fitBounds(bounds, { padding: 24, duration: 0 });
  };

  DairyMap.prototype.home = function () {
    var bounds = this.outlineBounds || this.countyBounds();
    return bounds ? { bounds: bounds, padding: 24 } : null;
  };
```

In `onAdopt`, the reload list becomes `['geojsonUrl', 'countiesUrl', 'county', 'year', 'label', 'unit', 'outlineUrl', 'center', 'radius']`, and in the reload branch, before `this.load()`:

```js
    // An old page's outline still in flight must not land here; the new
    // page's own is fetched by load().
    this.outlineRequest++;
    this.outlineBounds = null;
    this.shell.setSourceData('outline', M.EMPTY);
    this.shell.setSourceData('outline-mask', M.EMPTY);
    if (!this.data.county && !this.data.outlineUrl) this.shell.frame();
```

(replacing the existing `if (!this.data.county) this.shell.frame();`). Update the module's header comment: add a line that on a dairy region or near-me page the map is Dairies only, framed on the area (outline or radius), the points already narrowed by the GeoJSON's `region=` / point.

- [ ] **Step 3: Syntax check and rebuild**

Run: `node --check /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer/assets/js/emissions/dairy-map.js`
Expected: no output.

Run the asset rebuild command from Global Constraints. Expected: exits 0.

- [ ] **Step 4: Check in the browser**

Hard-refresh `http://localhost:8003/tools/emissions/region/<tulare sqid>/tulare-county/dairies/?year=2023`: the county is outlined in orange, everything outside washed, only Tulare's dairies drawn, no Dairies|Counties switch in the toolbar, the Home control returns to the county. Then `http://localhost:8003/tools/emissions/near/dairies/?lat=36.3&lng=-119.3&radius=3`: a circle, dairies within it. Change the year from the scope bar: one map, outline kept, points reloaded. In the console: `window.EmissionsDairyMap.instances()[0].outlineBounds` is set on both pages; no errors.

- [ ] **Step 5: Run the tab's page tests (the tab's JS config is untouched, but the toolbar template changed in Task 4)**

Run: `$TEST camp/apps/emissions/tests/test_dairies_pages.py camp/apps/emissions/tests/test_dairy_area_pages.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C <worktree> commit -m "feat(dairies): the dairy map outlines a region page's area or near-me's radius" -- assets/js/emissions/dairy-map.js
```

---

### Task 6: The emissions region page keeps a one-line dairy summary

**Files:**
- Modify: `camp/apps/emissions/views.py` (`dairy_block`, lines 457–495; `AreaPage.dairy_link_params` → `dairy_url`; `RegionPage`, `NearMe`)
- Create: `camp/templates/emissions/includes/dairy-summary.html`
- Delete: `camp/templates/emissions/includes/dairy-block.html`
- Modify: `camp/templates/emissions/area.html` (line 53)
- Test: `camp/apps/emissions/tests/test_dairies_pages.py` (`DairyBlockTests`, `DairyChartPageTests`)

**Interfaces:**
- Consumes: `Region.get_emissions_dairies_url()`, `emissions:near-me-dairies`, `NearLookupMixin.near_params()`.
- Produces: `views.dairy_page_query(scope, year) -> str`; `views.dairy_block(scope, area, dairy_url, *, county=None)` where `dairy_url` is a callable `(query: str) -> str`; block keys `first_year`, `last_year`, `in_range`, `is_county`, `last_year_url`, and in range `summary`, `has_dairies`, `page_url`, `county_pollutant`, `county_tons`. `AreaPage.dairy_url(query)` replaces `dairy_link_params()`.

- [ ] **Step 1: Rewrite the tests**

In `test_dairies_pages.py`, replace `DairyBlockTests` with:

```python
class DairyBlockTests(DairyPageTestCase):
    """The one-line dairy summary on a region or near-me page, linking the area's dairy page."""

    def region_page(self, region, params=None):
        response = self.client.get(region.get_emissions_url(), params or {})
        assert response.status_code == 200, response.status_code
        return response.content.decode()

    def test_county_page(self):
        content = self.region_page(self.fresno, {'year': '2023'})
        block = content[content.index('id="dairies"'):block_end(content)]
        assert '1 dairy · 1,300 mature dairy cows · 1 Large CAFO · 1 with digesters' in block
        assert f'<a href="{self.fresno.get_emissions_dairies_url()}?year=2023">Dairies in Fresno County →</a>' in block
        assert 'BIG DAIRY' not in block and 'dairy-table' not in content and 'dairy-charts' not in content

    def test_county_dairy_emissions(self):
        dairy_inventory(self.fresno, rog=2.0)
        content = self.region_page(self.fresno, {'year': '2023', 'pollutant': 'rog'})
        assert 'Dairy cattle, CARB estimate: <strong>730 tons/yr ROG</strong>' in content
        assert f'href="{self.fresno.get_emissions_dairies_url()}?year=2023&amp;pollutant=rog"' in content
        # NOx (the default): CARB reports none for dairy cattle, and the link leaves the pollutant out.
        content = self.region_page(self.fresno, {'year': '2023'})
        assert '<p class="dairy-county-line is-greyed">No NOx data for dairies.</p>' in content
        assert 'CARB estimate' not in content
        assert f'href="{self.fresno.get_emissions_dairies_url()}?year=2023"' in content

    def test_a_year_outside_cadd_greys_the_block(self):
        content = self.region_page(self.fresno)  # 2024, the explorer's latest year
        assert 'class="dairy-block mt-5 is-greyed"' in content
        assert "No dairy data for 2024. CARB's dairy database covers 2022–2023." in content
        assert f'<a href="{self.fresno.get_emissions_dairies_url()}?year=2023">See 2023 →</a>' in content
        assert '1 dairy ·' not in content and 'Dairies in Fresno County' not in content

    def test_other_region_pages_have_no_county_figure(self):
        dairy_inventory(self.fresno, rog=2.0)
        city = make(Region.Type.CITY, 'Somewhere', AROUND_PLANT)
        content = self.region_page(city, {'year': '2023', 'pollutant': 'rog'})
        assert '1 dairy · 1,300 mature dairy cows · 1 Large CAFO' in content
        assert 'CARB estimate' not in content and 'data for dairies' not in content
        assert f'<a href="{city.get_emissions_dairies_url()}?year=2023&amp;pollutant=rog">Dairies in Somewhere →</a>' in content

    def test_an_area_without_dairies(self):
        urban = make(Region.Type.URBAN_AREA, 'Faraway', 'MULTIPOLYGON(((-118.2 35.0, -118.1 35.0, -118.1 35.1, -118.2 35.1, -118.2 35.0)))')
        content = self.region_page(urban, {'year': '2023'})
        assert "No dairies in CARB's dairy database here." in content
        assert 'Dairies in Faraway' not in content

    def test_near_me(self):
        params = {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'label': 'near Home', 'year': '2023'}
        content = self.client.get(reverse('emissions:near-me'), params).content.decode()
        assert '1 dairy · 1,300 mature dairy cows' in content
        assert f'href="{reverse("emissions:near-me-dairies")}?year=2023&amp;lat=36.7370&amp;lng=-119.7870&amp;radius=1&amp;label=near+Home"' in content
        assert 'CARB estimate' not in content

    def test_no_block_before_an_import(self):
        DairyHerd.objects.all().delete()
        dairies.clear_caches()
        assert 'id="dairies"' not in self.region_page(self.fresno, {'year': '2023'})
```

with a module-level helper above the class:

```python
def block_end(content):
    return content.index('</section>', content.index('id="dairies"'))
```

Replace `DairyChartPageTests` with a version that keeps `test_dairies_tab` and `test_dairies_tab_without_digesters` as they are and replaces the five region-page tests with one:

```python
    def test_region_and_near_me_pages_have_no_dairy_charts(self):
        # The charts live on the area's dairy page now (test_dairy_area_pages).
        dairy_inventory(self.fresno, year=2023, rog=2.0)
        city = make(Region.Type.CITY, 'Somewhere', AROUND_PLANT)
        for content in (
            self.region_page(self.fresno, {'year': '2023', 'pollutant': 'rog'}),
            self.region_page(city, {'year': '2023', 'pollutant': 'rog'}),
            self.client.get(reverse('emissions:near-me'), {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'year': '2023'}).content.decode(),
        ):
            assert self.HERD_TITLE not in content and self.EMISSIONS_TITLE not in content and self.DIGESTER_TITLE not in content
            assert 'id="dairies"' in content
```

`SectionNavTests` stays unchanged and must keep passing.

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/emissions/tests/test_dairies_pages.py::DairyBlockTests camp/apps/emissions/tests/test_dairies_pages.py::DairyChartPageTests`
Expected: FAIL (old links, top-ten table and charts still rendered).

- [ ] **Step 3: Slim `dairy_block()` and the `AreaPage` hooks**

In `views.py`, replace `dairy_block` (lines 457–495):

```python
def dairy_page_query(scope, year):
    """
    The area's dairy page's query from an emissions scope: the year, and the
    pollutant only when dairies report it (else the page falls back to ROG
    quietly, and the link needn't carry a pollutant it will drop).
    """
    params = {'year': year}
    if scope.pollutant.key in dairies.POLLUTANT_KEYS:
        params['pollutant'] = scope.pollutant.key
    return urlencode(params)


def dairy_block(scope, area, dairy_url, *, county=None):
    """
    The one-line Dairies summary on a region or near-me page, or None before
    CARB's dairy database is imported. `dairy_url(query)` builds the area's
    dairy page URL. Outside CADD's years it only says so (the template greys
    it) and links the dairy page at CADD's last year. `county` (county
    pages) adds CARB's county dairy-cattle emissions in the scope pollutant.
    """
    known = dairies.years()
    if not known:
        return None
    block = {
        'first_year': known[0],
        'last_year': known[-1],
        'in_range': scope.year in known,
        'is_county': county is not None,
        'last_year_url': dairy_url(dairy_page_query(scope, known[-1])),
    }
    if not block['in_range']:
        return block
    reported = scope.pollutant.key in dairies.POLLUTANT_KEYS
    summary = dairies.summary(scope.year, area=area)
    block.update(
        summary=summary,
        has_dairies=bool(summary['dairies']),
        page_url=dairy_url(dairy_page_query(scope, scope.year)),
        county_pollutant=reported,
        county_tons=dairies.county_emissions(scope.year, scope.pollutant).get(county.pk) if county is not None and reported else None,
    )
    return block
```

In `AreaPage`, replace `dairy_link_params` with:

```python
    def dairy_url(self, query):
        """The area's dairy page, with `query` (year, pollutant) on it."""
        raise NotImplementedError
```

and the `dairy_block(...)` call becomes `dairy_block=dairy_block(base, area, self.dairy_url, county=self.dairy_county())`.

In `RegionPage`:

```python
    def dairy_url(self, query):
        return f'{self.region.get_emissions_dairies_url()}?{query}'
```

In `NearMe`:

```python
    def dairy_url(self, query):
        return f"{reverse('emissions:near-me-dairies')}?{query}&{urlencode(self.near_params())}"
```

- [ ] **Step 4: The summary template**

Create `camp/templates/emissions/includes/dairy-summary.html` (and `git rm` `dairy-block.html`):

```django
{% load humanize emissions_explorer %}
{% comment %}
A region or near-me page's Dairies summary (views.dairy_block): one line on
the scope year's counted dairies here and a link to the area's dairy page,
which has the map, table and charts. On county pages, CARB's county
dairy-cattle emissions in the scope pollutant. Greyed outside CADD's years,
with a link to the dairy page at CADD's last year. Keeps `id="dairies"` and
the `dairy-block` class for the section nav and the greyed style.
{% endcomment %}
<section class="dairy-block mt-5{% if not dairy_block.in_range %} is-greyed{% endif %}" id="dairies">
    <h2 class="title is-4"><span class="icon"><span class="fa-duotone fa-fw fa-cow explorer-icon is-dairies" aria-hidden="true"></span></span> Dairies</h2>
    {% if not dairy_block.in_range %}
    <p>No dairy data for {{ year }}. CARB's dairy database covers {{ dairy_block.first_year }}–{{ dairy_block.last_year }}. <a href="{{ dairy_block.last_year_url }}">See {{ dairy_block.last_year }} →</a></p>
    {% else %}
    {% if dairy_block.is_county %}
    {% if not dairy_block.county_pollutant %}
    <p class="dairy-county-line is-greyed">No {{ pollutant.label }} data for dairies.</p>
    {% elif dairy_block.county_tons is not None %}
    <p class="dairy-county-line">Dairy cattle, CARB estimate: <strong>{{ dairy_block.county_tons|whole }} tons/yr {{ pollutant.label }}</strong> <a class="is-size-7" href="{% url 'emissions:about' %}#dairies">(animals and manure only)</a></p>
    {% endif %}
    {% endif %}
    {% with summary=dairy_block.summary %}
    {% if summary.dairies %}
    <p class="dairy-summary">{{ summary.dairies|intcomma }} dair{{ summary.dairies|pluralize:"y,ies" }} · {{ summary.mature_cows|whole }} mature dairy cows · {{ summary.large|intcomma }} Large CAFO{{ summary.large|pluralize }} · {{ summary.digesters|intcomma }} with digesters</p>
    <p><a href="{{ dairy_block.page_url }}">Dairies in {{ name }} →</a></p>
    {% else %}
    <p class="has-text-grey">No dairies in CARB's dairy database here.</p>
    {% endif %}
    {% endwith %}
    {% endif %}
</section>
```

In `area.html` line 53: `{% if dairy_block %}{% include 'emissions/includes/dairy-summary.html' %}{% endif %}`.

- [ ] **Step 5: Run the tests**

Run: `$TEST camp/apps/emissions/tests/test_dairies_pages.py camp/apps/emissions/tests/test_areas_pages.py camp/apps/emissions/tests/test_dairy_area_pages.py`
Expected: all PASS, `SectionNavTests` included.

- [ ] **Step 6: Commit**

```bash
git -C <worktree> add camp/templates/emissions/includes/dairy-summary.html
git -C <worktree> rm -q camp/templates/emissions/includes/dairy-block.html
git -C <worktree> commit -m "feat(emissions): the region page's Dairies block becomes a summary linking the dairy page" -- camp/apps/emissions/views.py camp/templates/emissions/includes/dairy-summary.html camp/templates/emissions/includes/dairy-block.html camp/templates/emissions/area.html camp/apps/emissions/tests/test_dairies_pages.py
```

---

### Task 7: The Dairies tab redirects its filters and gets the Find-your-area box

**Files:**
- Modify: `camp/apps/emissions/dairy_views.py` (`DairyList`, `table_filters`, drop `near_label`, `NEAR_KEYS`, `FILTER_TYPES`)
- Modify: `camp/apps/emissions/views.py` (`find_area_places`, line 409–423; `radius_label`'s docstring)
- Modify: `camp/templates/emissions/dairy-list.html` (lines 36–60)
- Modify: `camp/templates/emissions/includes/find-area.html` (line 1)
- Test: `camp/apps/emissions/tests/test_dairies_pages.py` (`DairyTabContentTests`), `camp/apps/emissions/tests/test_areas_pages.py` (`FindAreaTests`)

**Interfaces:**
- Consumes: `emissions:region-dairies`, `emissions:near-me-dairies`, `views.get_filter_region`, `views.radius_area`, Task 4's `search_filters`.
- Produces: `views.find_area_places(url_name='emissions:region')` (cache key `f'{FIND_AREA_PLACES_KEY}:{url_name}'`); `DairyList.redirect_to_area(request) -> HttpResponse | None`; the find-area include honours `find_near_url` (defaults to `emissions:near-me`).

- [ ] **Step 1: Rewrite the tests**

In `test_dairies_pages.py`, replace `test_region_filter`, `test_region_filter_scopes_the_headline_and_charts_alike`, `test_a_tract_from_its_region_page` and `test_near_me_filter_and_its_tag` with:

```python
    def test_a_region_redirects_to_its_dairy_page(self):
        cdp = make(Region.Type.CDP, 'Plantville', AROUND_PLANT)
        response = self.client.get(self.url, {'region': cdp.sqid, 'year': '2023', 'sort': 'name', 'view': 'counties', 'measure': 'mature_cows'})
        assert response.status_code == 301
        assert response['Location'] == f'{cdp.get_emissions_dairies_url()}?year=2023&sort=name&measure=mature_cows'
        tract = make(Region.Type.TRACT, '06019000100', AROUND_PLANT)
        assert self.client.get(self.url, {'region': tract.sqid})['Location'] == tract.get_emissions_dairies_url()
        assert self.client.get(self.url, {'region': self.fresno.sqid})['Location'] == self.fresno.get_emissions_dairies_url()

    def test_an_unknown_region_renders_unfiltered(self):
        retired = make(Region.Type.TRACT, '06019000199', AROUND_PLANT, version='2010')
        for sqid in ('nope', retired.sqid):
            content = self.get({'region': sqid}).content.decode()
            assert 'BIG DAIRY' in content and 'SMALL DAIRY' in content

    def test_a_point_redirects_to_the_near_me_dairy_page(self):
        params = {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'label': 'near Tower District', 'year': '2023'}
        response = self.client.get(self.url, params)
        assert response.status_code == 301
        assert response['Location'] == f"{reverse('emissions:near-me-dairies')}?lat=36.737&lng=-119.787&radius=1&label=near+Tower+District&year=2023"
        # A radius near-me doesn't offer is no filter at all: the tab renders.
        content = self.get({**params, 'radius': '2'}).content.decode()
        assert 'BIG DAIRY' in content and 'SMALL DAIRY' in content

    def test_find_box_points_at_dairy_pages(self):
        content = self.get({'county': 'kern', 'pollutant': 'pm10'}).content.decode()
        assert 'entity-picker' not in content
        assert f'data-near-url="{reverse("emissions:near-me-dairies")}"' in content
        places = json.loads(re.search(r'id="find-area-places"[^>]*>(.*?)</script>', content, re.S).group(1))
        fresno = next(place for place in places if place['name'] == 'Fresno County')
        assert fresno['url'] == self.fresno.get_emissions_dairies_url()
        jumps = re.search(r'<p class="find-area-counties">(.*?)</p>', content, re.S).group(1)
        hrefs = re.findall(r'href="([^"]*)"', jumps)
        assert hrefs and all('/dairies/?' in href and 'county=' not in href and 'pollutant=pm10' in href for href in hrefs)
```

(add `import json` to the file's imports). In `test_areas_pages.py`'s `FindAreaTests`, add:

```python
    def test_places_per_url_name_are_cached_apart(self):
        cache.clear()
        fresno = Region.objects.get(type='county', slug='fresno')
        assert next(p for p in views.find_area_places() if p['name'] == 'Fresno County')['url'] == fresno.get_emissions_url()
        assert next(p for p in views.find_area_places('emissions:region-dairies') if p['name'] == 'Fresno County')['url'] == fresno.get_emissions_dairies_url()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/emissions/tests/test_dairies_pages.py::DairyTabContentTests camp/apps/emissions/tests/test_areas_pages.py::FindAreaTests`
Expected: the new tests FAIL (200 instead of 301; `find_area_places()` takes no argument).

- [ ] **Step 3: `find_area_places(url_name)` and the include**

In `views.py`:

```python
def find_area_places(url_name='emissions:region'):
    """
    Every region page but tracts, as {name, type, type_label, short_name,
    url}, for the search box. `url_name` picks the page the box lands on:
    the emissions region pages (the home page) or the dairy pages (the
    Dairies tab); each is cached under its own key.
    """
    def compute():
        ...unchanged, except: 'url': reverse(url_name, kwargs={'sqid': sqid, 'slug': slug}),
    return cache.get_or_set(f'{FIND_AREA_PLACES_KEY}:{url_name}', compute, stats.CACHE_TIMEOUT)
```

In `includes/find-area.html`, line 1: `data-near-url="{% if find_near_url %}{{ find_near_url }}{% else %}{% url 'emissions:near-me' %}{% endif %}"`.

In `views.py`'s `radius_label` docstring, drop the "and the Dairies tab's near-me filter tag (dairy_views.near_label)" clause.

- [ ] **Step 4: The tab**

In `dairy_views.py`: delete `FILTER_TYPES`, `NEAR_KEYS`, `near_label` and the `table_filters` function; `DairyList` uses `search_filters`:

```python
class DairyList(DairyScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/dairy-list.html'

    def get(self, request, *args, **kwargs):
        response = self.redirect_to_area(request)
        if response is not None:
            return response
        self.resolve(request)
        if request.GET.get('format') == 'csv':
            scope = self.get_scope()
            return csv_response(dairies.table(scope.year, county=scope.county, **search_filters(request.GET)), f'dairies-{scope.year}.csv')
        return super().get(request, *args, **kwargs)

    def redirect_to_area(self, request):
        """
        ?region= and ?lat=&lng= were the tab's filters; each area has its own
        dairy page now. 301 there with the rest of the query (view=counties
        dropped: the pages have no Counties view). An unknown region or a bad
        point is ignored and the tab renders unfiltered, as it always did.
        """
        get = request.GET
        target = None
        if get.get('region'):
            region = views.get_filter_region(get['region'], types=AREA_PAGE_TYPES)
            if region is not None:
                target = region.get_emissions_dairies_url()
        elif 'lat' in get or 'lng' in get:
            if radius_area(get) is not None:
                target = reverse('emissions:near-me-dairies')
        if target is None:
            return None
        params = get.copy()
        params.pop('region', None)
        if params.get('view') == 'counties':
            params.pop('view')
        query = params.urlencode()
        return redirect(target + (f'?{query}' if query else ''), permanent=True)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        filters = search_filters(self.request.GET)
        page = Paginator(dairies.table(scope.year, county=scope.county, **filters), PAGE_SIZE).get_page(self.request.GET.get('page'))
        # The find box: every page type's dairy page, and the county jump
        # links; the links carry the scope less the county (the page is the
        # county), the same as the home page's.
        places = views.find_area_places('emissions:region-dairies')
        return super().get_context_data(
            summary=dairies.summary(scope.year, county=scope.county),
            rows=page.object_list,
            page_obj=page,
            is_paginated=page.has_other_pages(),
            sort=filters['sort'],
            filters=filters,
            trend=dairies.trend(county=scope.county),
            # CARB's estimate is by county: the scope's county, else all of them.
            emissions_trend=dairies.emissions_trend(scope.pollutant, county=scope.county),
            digester_trend=dairies.digester_chart_points(county=scope.county),
            map_config=dairy_map_config(scope, dairy_map_view(self.request.GET)) if dairies.years() else None,
            find_area_places=places,
            find_area_counties=[p for p in places if p['type'] == Region.Type.COUNTY],
            find_area_qs=scope.query(county=None),
            find_near_url=reverse('emissions:near-me-dairies'),
            maptiler_key=settings.MAPTILER_API_KEY,
            **kwargs,
        )
```

Add `from django.conf import settings` and `from django.shortcuts import redirect` to the imports; drop `region_title` from the `views` import if nothing else uses it. `scope.query(county=None)` here is the dairies scope (`self._scope`), so it carries `pollutant=pm10` and the year when it isn't the explorer's latest; `region_qs` (ScopeMixin, the same expression) is what the include reads for `data-query`.

In `dairy-list.html`, the sidebar column (lines 37–60) becomes:

```django
    <div class="column is-3-desktop">
        {% include 'emissions/includes/find-area.html' %}
        <form method="get" class="explorer-filters box" hx-trigger="submit, change delay:250ms">
            {% for key, value in scope_params.items %}<input type="hidden" name="{{ key }}" value="{{ value }}">{% endfor %}
            <input type="hidden" name="sort" value="{{ sort }}">
            <div class="field">
                ...the Search field, unchanged...
            </div>
            <div class="field is-grouped">
                <div class="control"><button class="button is-link" type="submit">Apply</button></div>
                <div class="control"><a class="button is-light" href="{{ request.path }}{{ scope_qs }}">Clear</a></div>
            </div>
        </form>
    </div>
```

(the `near_params` hidden inputs, the entity picker and the near tag go). `assets/js/pesticides/explorer.js` already re-inits `.find-area` after every swap, and `find-area.js` is already on the emissions base page, so no JS changes.

- [ ] **Step 5: Run the tests**

Run: `$TEST camp/apps/emissions/tests/test_dairies_pages.py camp/apps/emissions/tests/test_areas_pages.py camp/apps/emissions/tests/test_dairy_area_pages.py`
Expected: all PASS.

- [ ] **Step 6: Check the tab**

`http://localhost:8003/tools/emissions/dairies/?county=tulare`: the sidebar has the find box; typing "Visalia" and picking it lands on Visalia's dairy page with `?year=…&pollutant=…`; a county jump link lands on that county's dairy page. `http://localhost:8003/tools/emissions/dairies/?region=<any sqid>` 301s to the region's dairy page.

- [ ] **Step 7: Commit**

```bash
git -C <worktree> commit -m "feat(dairies): the Dairies tab redirects region and near-me filters to the dairy pages, with a find box" -- camp/apps/emissions/dairy_views.py camp/apps/emissions/views.py camp/templates/emissions/dairy-list.html camp/templates/emissions/includes/find-area.html camp/apps/emissions/tests/test_dairies_pages.py camp/apps/emissions/tests/test_areas_pages.py
```

---

### Task 8: Smoke checks and the full run

**Files:**
- Modify: `scripts/emissions_map_smoke.py` (docstring; the block from `driver.get(args.base + '/tools/emissions/dairies/?county=tulare')` at line ~590 to the end of the checks)

**Interfaces:**
- Consumes: `window.EmissionsDairyMap.instances()[0].outlineBounds` (Task 5), the pages' URLs (Task 4), the tab redirect and find box (Task 7), the region page's summary (Task 6).

- [ ] **Step 1: Add the dairy page checks**

Add a helper beside `CIRCLE_UNDER_WASH`:

```python
# A canvas pixel over a dairy circle that the wash outside the page's area
# also covers, clear of the chrome: [x, y] from the canvas centre, or null.
DAIRY_UNDER_WASH = """
var m = window.EmissionsDairyMap.instances()[0], map = m.map, c = map.getCanvas(), r = c.getBoundingClientRect();
for (var y = 60; y < r.height - 30; y += 5) for (var x = 20; x < r.width - 20; x += 5) {
  if (!map.queryRenderedFeatures([x, y], {layers: ['dairies']}).length) continue;
  if (!map.queryRenderedFeatures([x, y], {layers: ['outline-mask']}).length) continue;
  if (document.elementFromPoint(r.left + x, r.top + y) !== c) continue;
  return [x - r.width / 2, y - r.height / 2];
}
return null;
"""
```

Then, after the `'a county narrows the dairy map'` check, replace everything from `driver.get(args.base + '/tools/emissions/')` … `'a county page maps its facilities (2023)'` onward (keep those two facility checks and the `'the Dairies tab draws its herd, CARB estimate and digester charts'` check) so the Tulare block checks become dairy-page checks:

```python
        # Tulare County's dairy page: the dairy map framed on the county
        # (outlined), Dairies only (no view switch), the three charts, a
        # row's name zooming to its dairy, and a year change keeping one map.
        tulare = driver.execute_script(
            "var a = Array.prototype.find.call(document.querySelectorAll('.find-area-counties a'),"
            " function (a) { return a.textContent.indexOf('Tulare') !== -1; }); return a ? a.href.split('?')[0] : null;")
        driver.get(tulare + '?year=2023&pollutant=rog')
        outlined = wait_dairies(driver) and driver.execute_script(
            "var m = window.EmissionsDairyMap.instances()[0]; return !!m.outlineBounds;")
        check(results, "Tulare County's dairy page loads its dairy map, outlined", outlined, tulare)
        drawn = settled_count(driver, dairy_count)
        check(results, 'it draws dairies', drawn > 0, f'{drawn} dairies')
        legend = driver.execute_script("return document.querySelector('.dairy-map-legend').innerHTML;")
        check(results, 'its legend has the size key', 'legend-sizes' in legend and 'EPA size class' in legend)
        check(results, 'no view switch in its toolbar', driver.execute_script(
            "return !document.querySelector('.dairy-map-view') && !!document.querySelector('.dairy-map-sizes');"))
        titles = driver.execute_script(chart_titles % '.dairy-charts')
        check(results, "the county dairy page draws its herd, CARB estimate and digester charts",
              len(titles) == 3 and 'Dairy cattle ROG, CARB estimate' in titles, str(titles))
        check(results, 'no County column on a county dairy page', driver.execute_script(
            "return Array.prototype.every.call(document.querySelectorAll('.dairy-table th'), function (th) { return th.textContent.trim() !== 'County'; });"))
        driver.execute_script("document.querySelector('.dairy-zoom').click();")
        opened = False
        for _ in range(40):
            opened = driver.execute_script(
                "var p = document.querySelector('.maplibregl-popup .dairy-popup');"
                "return !!p && p.textContent.indexOf('Mature dairy cows') !== -1;")
            if opened:
                break
            time.sleep(0.25)
        check(results, "a table row's name zooms to its dairy with its popup", opened)
        driver.execute_script("var p = document.querySelector('.maplibregl-popup-close-button'); if (p) p.click();")
        pick_year(driver, 2)
        time.sleep(1)
        kept = wait_dairies(driver) and driver.execute_script(
            "var list = window.EmissionsDairyMap.instances(); return list.length === 1 && !!list[0].outlineBounds;")
        check(results, 'a year change (boosted swap) keeps one map, still outlined', kept, driver.current_url)

        # A community dairy page: outlined; every drawn dairy is in the
        # table's count; a dairy under the wash still opens its popup.
        community = driver.execute_script(
            "var a = document.querySelector('.within-list a'); return a ? a.href.split('?')[0] : null;")
        driver.get(community + '?year=2023')
        outlined = wait_dairies(driver) and driver.execute_script(
            "var m = window.EmissionsDairyMap.instances()[0]; return !!m.outlineBounds;")
        check(results, 'a community dairy page loads, outlined', outlined, community)
        drawn = settled_count(driver, dairy_count)
        total = driver.execute_script("return document.querySelector('.stat-row .title').textContent.replace(/,/g, '') | 0;")
        check(results, "every drawn dairy is in the page's count", 0 < drawn <= total, f'{drawn} drawn, {total} counted')
        driver.execute_script("document.querySelector('.dairy-map').scrollIntoView({block: 'center'});")
        time.sleep(0.5)
        hit = driver.execute_script(DAIRY_UNDER_WASH)
        if hit:
            canvas = driver.find_element(By.CSS_SELECTOR, '.dairy-map canvas')
            ActionChains(driver).move_to_element_with_offset(canvas, int(hit[0]), int(hit[1])).click().perform()
            time.sleep(1)
        opened = driver.execute_script("return !!document.querySelector('.maplibregl-popup .dairy-popup');")
        check(results, 'a dairy under the wash still opens its popup', (not hit) or opened, str(hit))

        # Near-me dairies: the circle, and a radius button keeping the page.
        driver.get(args.base + '/tools/emissions/near/dairies/?lat=36.3302&lng=-119.2921&radius=3')
        near = wait_dairies(driver) and driver.execute_script(
            "var m = window.EmissionsDairyMap.instances()[0]; return !!m.outlineBounds;")
        check(results, 'near-me dairy page loads, with its circle', near)
        driver.find_element(By.CSS_SELECTOR, '.buttons.explorer-scope a').click()
        time.sleep(1)
        stayed = wait_dairies(driver) and '/near/dairies/' in driver.current_url and 'radius=1' in driver.current_url
        check(results, 'a radius button keeps the page and redraws', stayed, driver.current_url)

        # The tab's old filters land on the pages; its find box goes to a county dairy page.
        sqid = tulare.rstrip('/').split('/')[-2]
        driver.get(args.base + '/tools/emissions/dairies/?region=' + sqid + '&year=2023')
        check(results, 'the tab with ?region= lands on the region dairy page',
              driver.current_url.split('?')[0] == tulare + 'dairies/', driver.current_url)
        driver.get(args.base + '/tools/emissions/dairies/')
        driver.find_element(By.CSS_SELECTOR, '.find-area-counties a').click()
        time.sleep(1)
        check(results, "the tab's find box takes you to a county dairy page", '/dairies/' in driver.current_url, driver.current_url)

        # Tulare County's emissions page: the Dairies section is the summary only.
        driver.get(tulare + '?year=2023&pollutant=rog')
        time.sleep(1)
        summary_only = driver.execute_script(
            "var s = document.getElementById('dairies'); return !!s && !s.querySelector('.dairy-table') && !s.querySelector('.dairy-charts')"
            " && !!s.querySelector('.dairy-summary');")
        check(results, "Tulare County's Dairies section is the summary only", summary_only)
        link = driver.execute_script(
            "var a = document.querySelector('#dairies a[href*=\"/dairies/\"]'); return a ? a.href : null;")
        check(results, "'Dairies in Tulare County →' goes to the dairy page", bool(link) and link.split('?')[0] == tulare + 'dairies/', str(link))
        nav = driver.execute_script(
            "return Array.prototype.map.call(document.querySelectorAll('.section-nav a'), function (a) { return a.getAttribute('href'); });")
        check(results, 'its section nav links Facilities, Dairies, In and around',
              nav == ['#facilities', '#dairies', '#in-and-around'], str(nav))
        ...keep the existing "jumps in place" check...
```

Delete the retired checks (`"Tulare County's Dairies block draws its three charts"` and `'with NOx, no CARB estimate chart …'`). The `tulare` URL from the find-area links ends in `/tulare-county/`, so `tulare + 'dairies/'` is the dairy page. Update the module docstring's last paragraph to describe the dairy pages (county, community, near-me), the tab redirect and the region page summary.

- [ ] **Step 2: Rebuild assets, run the smoke script**

Run the asset rebuild command (a no-op if Task 5's build is current), then:
`/home/derek/.claude/jobs/d44a9b36/tmp/venv/bin/python /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer/scripts/emissions_map_smoke.py --base http://localhost:8003`
Expected: `N/N checks passed`, `no console errors` PASS. If the community page's `.within-list a` is a school district with no dairies, pick the first `.within-panel` link whose page shows a `.dairy-map` instead (loop over the first few `.within-list a` hrefs until one loads a map).

- [ ] **Step 3: Run the full emissions, API and regions suites**

Run: `$TEST camp/apps/emissions camp/api/v2/emissions camp/apps/regions`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git -C <worktree> commit -m "test(emissions): smoke the dairy region pages, near-me dairies and the tab redirect" -- scripts/emissions_map_smoke.py
```

---

## Self-review

- **Spec coverage.** URLs and names (Task 4); `Region.get_emissions_dairies_url()` (4); mixins (1); scope handling, `county` dropped, disabled scope bar (4); header, tiles with the county fifth tile (3, 4); map Dairies-only, outline/radius, GeoJSON `region=`/point with 400s and generation-keyed cache (2, 4, 5); table with CSV name and `hide_county` (3, 4); charts include and the county link line (3, 4); "In and around" under its own cache key (4); footer line (4); breadcrumbs (4); region page summary, `page_url`, out-of-range link, no-dairies line, section nav unchanged (6); tab redirects with `view=counties` dropped, unknown region unfiltered, find box on dairy URLs, `near_label`/`NEAR_KEYS`/`FILTER_TYPES` removed (7); edge cases: no dairies this year with history, year outside CADD, no CADD data, county pages, NOx fallback, near-me outside coverage, mailing-city members (2, 4, 8); smoke (8).
- **Placeholders.** None: every step carries its code or exact command; "unchanged" refers only to lines the step names as kept.
- **Type consistency.** `dairy_url(query: str)` in `AreaPage`/`RegionPage`/`NearMe` (Task 6) matches `dairy_block(scope, area, dairy_url, county=)`; `search_filters` (Task 4) is what Task 7's `DairyList` and `csv_response` use; `find_area_places(url_name)` (Task 7) is called with a URL name in both places; `outlineBounds` (Task 5) is what Task 8 reads; `carb_estimate` keys `tons/share/place` match Task 3's include; `view_options == ()` on area pages (Task 4) is what the toolbar template and Task 8's "no view switch" check rely on.
- **Review Focus.** Each line names its test and task above.
