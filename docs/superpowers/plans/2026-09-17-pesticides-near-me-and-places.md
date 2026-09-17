# Pesticides Near Me and Place Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The resident tier: a "Find your area" block on the landing page (address search via MapTiler in the browser, "Use my location", county/city/ZIP pickers), a near-me page for a point + radius, and a region page for counties, cities, ZIPs, and places, all rendering one shared place-page layout from the rollup; county names across the explorer become links to county pages.

**Architecture:** One module `camp/apps/pesticides/places.py` resolves an *area* (a point+radius or a Region) to its MTRS section pks and builds the place-page context from `PesticideUseRollup` + `stats` helpers; two thin `vanilla` views (`NearMe`, `RegionPage`) render `pesticides/place.html`. The landing page gains a form + a small script (`assets/js/pesticides/find-area.js`) that calls MapTiler geocoding from the browser and redirects to the near-me or region URL; the server never geocodes. Reuses `area_filter` (sub-project 3 T1), `includes/month-bars.html` (sub-project 3 T2), `section_map_config` and the section-map include (sub-project 2).

**Tech Stack:** Django 5.2, PostGIS, `django-vanilla-views`, Bulma 0.9, plain Leaflet, MapTiler Geocoding API (browser-side, `settings.MAPTILER_API_KEY`, which already ships to browsers in tile URLs).

**Spec:** `docs/superpowers/specs/2026-09-16-pesticides-explorer-v2-design.md`, section "4. Near me and place pages" and "Cross-cutting".

## Global Constraints

- Commands from the worktree root inside Docker: `docker compose run --rm test pytest <path> -q`; `docker compose run --rm web invoke styles` after sass edits (commit `dist/css/style.css` with the sass).
- Tests: `django.test.TestCase`, fixtures (`pesticides-explorer`), plain `assert`; aggregate-reading classes use `RollupTestMixin`. Fixture: counties 9001 Fresno (square lon −120.5..−119.0, lat 36.0..37.0, slug `fresno`) / 9002 Kern (lon −120.0..−118.0, lat 35.0..35.9, slug `kern`); MTRS 9101 (lon −119.80..−119.78, lat 36.70..36.72, inside Fresno) / 9102 (lon −119.05..−119.03, lat 35.35..35.37, inside Kern); uses 1,2,4,6 (2023 Fresno/9101: 100+50+20+500 lbs, months 3,4,6,8), 3,5 (2023 Kern/9102), 7,9 (2022 Fresno), 8 (2022 Kern); notices 1 (past, Fresno), 2 (2099, Fresno), 3 (2099, Kern). Fixture notices have no `point`/`mtrs`; tests set them with `update()`.
- `SqidsField` is not a DB column: resolve sqids only via `Model.objects.filter(sqid=...)`.
- Notices: "active" = `stats._upcoming` (scheduled ≥ now − 4 days). Never a "next N days" window. Every place page links to SprayDays sign-up (`https://spraydays.cdpr.ca.gov/`). No alert features of our own.
- **Privacy:** the server never geocodes and never stores a location; near-me state lives only in the URL, and the page says so in one sentence.
- Explorer pages never link to raw API endpoints (docs links only). URLs are the only state.
- Never `git add -A`; commit trailer exactly `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; no other AI attribution.
- Shared db; a dev server for this worktree runs on port 8002 (do not start/stop servers).

---

## File map

| File | Responsibility |
|---|---|
| `camp/apps/pesticides/places.py` | `Area` resolution (point+radius or Region → section pks, cached per region), `place_context()` |
| `camp/apps/pesticides/views.py` | + `NearMe`, `RegionPage`; landing `Home` gains `find_area` context |
| `camp/apps/pesticides/forms.py` | + `FindAreaForm` (pickers) |
| `camp/apps/pesticides/urls.py` | + `near/`, `region/<sqid>/<slug>/` |
| `camp/apps/pesticides/templatetags/pesticides_explorer.py` | + `region_url` simple tag |
| `camp/apps/pesticides/stats.py` | `by_county` rows gain `county_sqid` |
| `camp/templates/pesticides/place.html`, `includes/find-area.html`, `includes/how-to-read.html` | pages / blocks |
| `camp/templates/pesticides/home.html`, `includes/by-county-table.html`, `includes/upcoming-notices.html`, `includes/records-table.html`, `includes/notice-rows.html` | landing reorder; county names → links |
| `assets/js/pesticides/find-area.js`, `assets/sass/sjvair/pages/pesticides.sass` | search box + geolocation + pickers; styles |
| `camp/apps/pesticides/tests/test_places.py`, `tests/test_find_area.py` | tests |

---

### Task 1: Area resolution, the place-page context, and the two views

**Files:** Create `camp/apps/pesticides/places.py`, `camp/templates/pesticides/place.html`, `camp/apps/pesticides/tests/test_places.py`. Modify `views.py`, `urls.py`, `templatetags/pesticides_explorer.py`, `stats.py`, `pesticides.sass`.

**Interfaces:**
- Consumes: `views.area_filter(queryset, *, county=None, region=None, section=None, point=None, radius=None)` (sub-project 3 T1), `views.section_map_config(year, *, center, zoom, radius, chemical, product, commodity, county)`, `views.year_context(year)`, `includes/month-bars.html` (expects `by_month`, `year`), `includes/related-card.html`, `includes/upcoming-notices.html`, `includes/section-map.html`, `stats.year_totals/by_month/top_related/_upcoming`, `camp.api.v2.pesticides.sections.radius_bbox`.
- Produces:

```python
# camp/apps/pesticides/places.py
PLACE_REGION_TYPES = (Region.Type.COUNTY, Region.Type.CITY, Region.Type.ZIPCODE, Region.Type.PLACE)
RADIUS_CHOICES = (1, 3, 5)
AREA_SECTIONS_TTL = 60 * 60 * 24

@dataclass
class Area:
    label: str                 # "near Selma, Fresno County" | "Fresno County" | "ZIP 93725"
    kind: str                  # 'point' | 'region'
    region: Region | None = None
    point: Point | None = None # SRID 4326
    radius: int | None = None  # miles
    section_pks: list[int] = field(default_factory=list)

    @property
    def county(self):          # Region or None — the county FK filter when kind == 'region' and region.type == COUNTY
    def rollup_rows(self):     # PesticideUseRollup filtered to the area (county FK for county regions, else mtrs__in=section_pks)
    def notices(self):         # PesticideNotice via views.area_filter with the same semantics
    def records_url(self, year):   # reverse('pesticides:records') + '?' + urlencode(area params + year)
    def notices_url(self):         # reverse('pesticides:notice-list') + '?' + urlencode(area params)
    def map_kwargs(self):          # dict(center='lat,lng', zoom=int, radius=..., county=slug or None)

def point_area(lat, lng, radius, label='') -> Area   # section pks via boundary__geometry__distance_lte=(point, D(mi=radius)) with the radius_bbox prefilter
def region_area(region) -> Area                      # county → MTRS whose boundary intersects the county boundary; other types the same; cached 1 day under f'pesticides:area-sections:{region.pk}'
def place_context(area, year) -> dict                # see below
```

  `place_context` returns: `area`, `totals` = `{'lbs', 'applications', 'sections_used', 'sections_total', 'chemicals'}` (sections_used = distinct `mtrs` in `rows.filter(year=year)`; sections_total = `len(area.section_pks)`; chemicals = distinct chemical count that year), `by_month` (12 rows), `peak_month` (`calendar.month_name[...]` or `None`), `top_chemicals`, `top_commodities`, `top_products` (`stats.top_related`, limit 10; products by `lbs_product`), `upcoming` (active notices in the area, `select_related('county').prefetch_related('chemicals', 'products')`, ordered by `scheduled_application`, up to 20), `upcoming_count`, `records_url`, `notices_url`, `map_config` (`section_map_config(year, **area.map_kwargs())`), `spraydays_url`.

  Map kwargs: point → `center=f'{lat:.4f},{lng:.4f}'`, `zoom=12`, `radius=radius`; county → boundary centroid, `zoom=9`, `county=slug`; other regions → centroid, `zoom=11`. (`centroid.y` is lat, `.x` is lng.)

- `NearMe(vanilla.TemplateView)` at `near/` (`pesticides:near-me`): reads `lat`, `lng` (floats; must be finite, −90..90 / −180..180), `radius` (int in `RADIUS_CHOICES`, default 1), `label` (str, ≤ 120 chars, HTML-escaped by the template), `year`. Invalid/missing lat/lng → redirect to the landing page with `?find=1` (the landing form focuses). Label default: `f'{lat:.3f}, {lng:.3f}'`. Context: `place_context(...)`, `year_context(year)`, `privacy_note=True`, `radius_options` = `[{'miles': m, 'url': ...}]` (same lat/lng/label/year, other radius).
- `RegionPage(vanilla.TemplateView)` at `region/<str:sqid>/<slug:slug>/` (`pesticides:region`): `Region.objects.filter(sqid=sqid, type__in=PLACE_REGION_TYPES).select_related('boundary').first()` else 404; if `slug` mismatches → 301 to the canonical URL; no boundary → 404. Context as above with `area=region_area(region)`.
- `{% region_url region %}` template tag → `reverse('pesticides:region', kwargs={'sqid': region.sqid, 'slug': region.slug})`; returns `''` for `None`.
- `stats.by_county` rows gain `county_sqid` via one `Region.objects.in_bulk(ids)` lookup after the aggregate (eight rows; sqid is not a DB column). `by-county-table.html` renders the name as a link to `{% url 'pesticides:region' sqid=row.county_sqid slug=row.county_slug %}` with `?year=` preserved (`year_qs`).

Page (`place.html`, extends `pesticides/base.html`):
1. Header: `area.label` as h1; subtitle "Within N miles" / region type label; year picker.
2. "Right now" box (`class="box right-now"`): "N notices scheduled nearby" (0 → "No notices of intent are currently scheduled here."), the `upcoming-notices.html` table when non-empty, and the SprayDays sign-up link. Visually separated from the year-binned blocks (same `notice-callout` treatment as the landing).
3. Stat row: Lbs applied in {year}, Applications, "Sections with use" as `used / total`, Chemicals used.
4. `section-map.html` include (centered on the area; the script already draws the radius circle when `data-radius` is set).
5. "By month": `month-bars.html` + sentence "Spraying peaks in {peak_month} here." when `peak_month`.
6. "What's applied here": three `related-card.html` (`show_lbs=True`, `complete=False`, `show_all_url=records_url`), products by `lbs_product`.
7. Links: "Browse all records for this area" → `records_url`; "See notices here" → `notices_url`.
8. Near-me only: `<p class="is-size-7 has-text-grey">Your location is only in this page's address bar; we don't store it.</p>`
9. Sources footer (same as other pages).

- [ ] **Step 1: Tests (RED)** — `tests/test_places.py`:

```python
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides import places
from camp.apps.pesticides.models import PesticideNotice
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


class AreaTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_point_area_finds_sections_in_radius(self):
        area = places.point_area(36.71, -119.79, 1, label='near Fresno')
        assert area.kind == 'point' and area.section_pks == [9101]
        assert area.map_kwargs() == {'center': '36.7100,-119.7900', 'zoom': 12, 'radius': 1, 'county': None}

    def test_region_area_county_uses_fk_and_caches_sections(self):
        fresno = Region.objects.get(pk=9001)
        area = places.region_area(fresno)
        assert area.section_pks == [9101]
        assert list(area.rollup_rows().values_list('county', flat=True).distinct()) == [9001]
        assert cache.get('pesticides:area-sections:9001') == [9101]
        assert area.map_kwargs()['zoom'] == 9 and area.map_kwargs()['county'] == 'fresno'

    def test_place_context_totals_and_peak(self):
        ctx = places.place_context(places.region_area(Region.objects.get(pk=9001)), 2023)
        assert ctx['totals'] == {'lbs': 670.0, 'applications': 4, 'sections_used': 1, 'sections_total': 1, 'chemicals': 3}
        assert ctx['peak_month'] == 'August'
        assert [r.obj.name for r in ctx['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert ctx['records_url'].startswith(reverse('pesticides:records') + '?')
        assert 'county=fresno' in ctx['records_url'] and 'year=2023' in ctx['records_url']

    def test_place_context_active_notices(self):
        PesticideNotice.objects.filter(pk=2).update(point=Point(-119.79, 36.71, srid=4326), mtrs_id=9101)
        ctx = places.place_context(places.point_area(36.71, -119.79, 1), 2023)
        assert [n.pk for n in ctx['upcoming']] == [2] and ctx['upcoming_count'] == 1
        assert 'lat=36.71' in ctx['notices_url'] and 'radius=1' in ctx['notices_url']


class NearMeTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:near-me')

    def test_renders(self):
        response = self.client.get(self.url, {'lat': 36.71, 'lng': -119.79, 'radius': 3, 'label': 'near Selma, Fresno County'})
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/place.html')
        html = response.content.decode()
        assert 'near Selma, Fresno County' in html and 'Within 3 miles' in html
        assert 'only in this page' in html and 'spraydays.cdpr.ca.gov' in html
        assert response.context['map_config']['radius'] == 3
        assert [o['miles'] for o in response.context['radius_options']] == [1, 5]

    def test_label_is_escaped_and_truncated(self):
        html = self.client.get(self.url, {'lat': 36.71, 'lng': -119.79, 'label': '<b>x</b>' + 'y' * 200}).content.decode()
        assert '<b>x</b>' not in html and '&lt;b&gt;x&lt;/b&gt;' in html
        assert 'y' * 121 not in html

    def test_bad_or_missing_coordinates_redirect_home(self):
        for params in ({}, {'lat': 'nan', 'lng': -119.79}, {'lat': 95, 'lng': -119.79}, {'lat': 36.71, 'lng': -119.79, 'radius': 7}):
            response = self.client.get(self.url, params)
            assert response.status_code == 302, params
            assert response['Location'] == reverse('pesticides:home') + '?find=1'


class RegionPageTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(pk=9001)
        self.url = reverse('pesticides:region', kwargs={'sqid': self.fresno.sqid, 'slug': 'fresno'})

    def test_renders(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.context['totals']['lbs'] == 670.0
        html = response.content.decode()
        assert 'Fresno County' in html and 'Spraying peaks in August here' in html and 'month-bars' in html
        assert 'only in this page' not in html

    def test_slug_redirect_and_404s(self):
        response = self.client.get(reverse('pesticides:region', kwargs={'sqid': self.fresno.sqid, 'slug': 'wrong'}))
        assert response.status_code == 301 and response['Location'] == self.url
        section = Region.objects.get(pk=9101)
        assert self.client.get(reverse('pesticides:region', kwargs={'sqid': section.sqid, 'slug': section.slug})).status_code == 404
        assert self.client.get(reverse('pesticides:region', kwargs={'sqid': 'nope', 'slug': 'x'})).status_code == 404

    def test_by_county_table_links_to_county_pages(self):
        html = self.client.get(reverse('pesticides:home')).content.decode()
        assert self.url in html
```

`landing_stats` caches `by_county` rows per year, so the new `county_sqid` key is missing from any already-cached entry: bump the `LANDING_KEY` string in `stats.py` (e.g. append `:v2`) so old entries are ignored.

- [ ] **Step 2: Run** `docker compose run --rm test pytest camp/apps/pesticides/tests/test_places.py -q` → fails on import.
- [ ] **Step 3: Implement** `places.py`, the views, URLs (`path('near/', NearMe.as_view(), name='near-me')`, `path('region/<str:sqid>/<slug:slug>/', RegionPage.as_view(), name='region')`), the tag, `by_county` sqids, `place.html`, sass (`.right-now` box with a left border in `$info`; `.stat-row .fraction` tabular-nums). Read `MapPage`, `SectionDetail`, and `RecordsBrowser` in `views.py` first and follow their conventions.
- [ ] **Step 4: GREEN** on `tests/test_places.py`, then `camp/apps/pesticides`; `invoke styles`.
- [ ] **Step 5: Commit** — `feat(pesticides): add near-me and region place pages` + trailer.

---

### Task 2: "Find your area" on the landing page, county links everywhere, and the how-to-read panel

**Files:** Create `camp/templates/pesticides/includes/find-area.html`, `includes/how-to-read.html`, `assets/js/pesticides/find-area.js`, `tests/test_find_area.py`. Modify `forms.py`, `views.py` (`Home`), `home.html`, `base.html` (script tag), `includes/upcoming-notices.html`, `includes/records-table.html`, `includes/notice-rows.html`, `pesticides.sass`.

**Interfaces:**
- `FindAreaForm(forms.Form)`: `county` (ChoiceField of `('sqid:slug', name)` built from `Region.objects.filter(type=COUNTY).order_by('name')`), `city` (same over `type=CITY`), `zipcode` (same over `type=ZIPCODE`, label = name), all optional with an empty first choice. No `POST`; the form is a GET form whose `action` is `pesticides:home`; `Home.get()` redirects when exactly one picker is set: `region/<sqid>/<slug>/?year=` (302). The pickers are rendered as Bulma `select`s with an "Go" button; JS-free operation must work.
- `Home` context adds `find_area_form`, `maptiler_key` (`settings.MAPTILER_API_KEY`), `focus_find` (`request.GET.get('find') == '1'`).
- `includes/find-area.html`:

```html
<section class="box find-area" id="find" data-maptiler-key="{{ maptiler_key }}" data-near-url="{% url 'pesticides:near-me' %}" data-year="{{ year }}">
    <h2 class="title is-5">Find your area</h2>
    <div class="field has-addons">
        <div class="control is-expanded has-icons-left">
            <input class="input" type="search" id="find-area-query" placeholder="Address, city, or ZIP in the San Joaquin Valley" autocomplete="off" aria-label="Address, city, or ZIP"{% if focus_find %} autofocus{% endif %}>
            <span class="icon is-left"><span class="fa-regular fa-magnifying-glass"></span></span>
        </div>
        <div class="control"><button type="button" class="button is-primary" id="find-area-locate"><span class="icon"><span class="fa-regular fa-location-crosshairs"></span></span><span>Use my location</span></button></div>
    </div>
    <ul class="find-area-results" id="find-area-results" hidden></ul>
    <p class="help" id="find-area-status"></p>
    <form method="get" action="{% url 'pesticides:home' %}" class="find-area-pickers">
        {% if year %}<input type="hidden" name="year" value="{{ year }}">{% endif %}
        <div class="field is-grouped is-grouped-multiline">
            <div class="control"><div class="select">{{ find_area_form.county }}</div></div>
            {% if find_area_form.fields.city.choices|length > 1 %}<div class="control"><div class="select">{{ find_area_form.city }}</div></div>{% endif %}
            <div class="control"><div class="select">{{ find_area_form.zipcode }}</div></div>
            <div class="control"><button class="button" type="submit">Go</button></div>
        </div>
    </form>
    <p class="is-size-7 has-text-grey">Searching sends your text to MapTiler to find coordinates; the result is only in the link we open. We don't store locations.</p>
</section>
```

- `find-area.js` (plain ES2017 IIFE, initialised for `.find-area`): on input (debounced 300 ms, ≥ 3 chars) `GET https://api.maptiler.com/geocoding/{encodeURIComponent(q)}.json?key=…&country=us&bbox=-121.9,34.8,-117.5,38.4&limit=5&language=en`; render `feature.place_name` rows into `#find-area-results`; Enter/click on a row → `location.assign(nearUrl + '?lat=' + lat.toFixed(4) + '&lng=' + lng.toFixed(4) + '&radius=1&label=' + encodeURIComponent('near ' + feature.text) + (year ? '&year=' + year : ''))` using `feature.center` (`[lng, lat]`). Escape all text with `textContent`. "Use my location" → `navigator.geolocation.getCurrentPosition` → reverse geocode `GET https://api.maptiler.com/geocoding/{lng},{lat}.json?key=…&limit=1` for the label (fall back to "near you" on failure) → same redirect. Errors (denied geolocation, network, empty results) go to `#find-area-status` in plain words; no alerts. Arrow-key navigation of results (`aria-activedescendant`) and Escape to close. No request when the key attribute is empty (show "Search is unavailable" status).
- County links: `upcoming-notices.html`, `notice-rows.html`, `records-table.html` render `notice.county.name` / `use.county.name` as `<a href="{% region_url notice.county %}">` when the county is set.
- `includes/how-to-read.html`: a `<details class="how-to-read">` with summary "How to read this page" and four short paragraphs (PUR and its lag; what an NOI is; what the shades/sections mean; what the badges mean — wording lives here now; sub-project 5 swaps in datafile notes). Included on `home.html` (right after the stat row) and `place.html` (after the stat row).
- Landing reorder (`home.html`): intro → `find-area.html` → `notice-callout` → stat row → `how-to-read.html` → county map → cards → leaderboards → explainer. The callout's count links to `pesticides:notice-list`.
- `base.html`: load `find-area.js` after `section-map.js`.

- [ ] **Step 1: Tests (RED)** — `tests/test_find_area.py`:

```python
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


@override_settings(MAPTILER_API_KEY='test-key')
class FindAreaTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:home')

    def test_landing_has_find_area_block(self):
        response = self.client.get(self.url)
        html = response.content.decode()
        assert 'data-maptiler-key="test-key"' in html
        assert reverse('pesticides:near-me') in html
        assert 'find-area.js' in html
        assert 'How to read this page' in html
        fresno = Region.objects.get(pk=9001)
        assert f'<option value="{fresno.sqid}:fresno">Fresno County</option>' in html
        assert html.index('id="find"') < html.index('stat-row')

    def test_picker_redirects_to_region_page(self):
        fresno = Region.objects.get(pk=9001)
        response = self.client.get(self.url, {'county': f'{fresno.sqid}:fresno', 'year': 2022})
        assert response.status_code == 302
        assert response['Location'] == reverse('pesticides:region', kwargs={'sqid': fresno.sqid, 'slug': 'fresno'}) + '?year=2022'

    def test_bad_picker_value_renders_landing(self):
        assert self.client.get(self.url, {'county': 'nope:x'}).status_code == 200

    def test_focus_flag(self):
        assert 'autofocus' in self.client.get(self.url, {'find': 1}).content.decode()

    def test_county_names_link_to_region_pages(self):
        from camp.apps.pesticides.models import Chemical
        chem = Chemical.objects.get(pk=2)  # chlorpyrifos: on notices 2 and 3
        html = self.client.get(chem.get_absolute_url()).content.decode()
        kern = Region.objects.get(pk=9002)
        assert reverse('pesticides:region', kwargs={'sqid': kern.sqid, 'slug': 'kern'}) in html
```

- [ ] **Step 2: Run** → fails (no block, no redirect).
- [ ] **Step 3: Implement** form, view changes, templates, script, sass (`.find-area-results` as an absolutely positioned dropdown list under the input: `position:relative` on `.find-area .field`, `.find-area-results { position:absolute; z-index:30; left:0; right:0; background:$white; border:1px solid $grey-lighter; border-radius:4px; box-shadow: 0 4px 12px rgba($black,.12); list-style:none; margin:0; padding:.25rem 0 } li { padding:.4rem .75rem; cursor:pointer } li[aria-selected=true], li:hover { background:$grey-lightest }`).
- [ ] **Step 4: GREEN** on `camp/apps/pesticides`; `invoke styles`. Syntax-check the script with `node --check assets/js/pesticides/find-area.js`.
- [ ] **Step 5: Commit** — `feat(pesticides): add "Find your area" to the landing page and link county names to county pages` + trailer.

---

### Task 3: Browser check and wrap-up (controller)

Chrome against port 8002: landing (search "Selma" → dropdown → near-me page; "Use my location" status text; county picker → county page), near-me page at `?lat=36.71&lng=-119.79&radius=3&label=near%20Selma` (right-now box, stat row, map with circle, month bars, cards, links), Fresno county page, a ZIP page, county links from the by-county table and a notice row. Timings: near-me and county pages under one second warm (record in the ledger). One fix dispatch + scoped re-review for anything found. Ledger. No push.
