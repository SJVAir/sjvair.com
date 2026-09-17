# Pesticides Interactive Section Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reusable, interactive Leaflet map of MTRS sections shaded by pesticide use for a year and filters, with active SprayDays notices as markers, click popups, and a static fallback; proven on a new `/tools/pesticides/map/` page.

**Architecture:** A plain-Leaflet script (`assets/js/pesticides/section-map.js`) reads a container's data attributes, fetches `/api/2.0/pesticides/sections/` for the viewport and `/api/2.0/pesticides/notices/active/` (new, GeoJSON, unpaginated) for markers, shades sections with the same five-step quantile ramp the county map uses, and opens popups fed by `sections/<sqid>/`. A Django include emits the container plus the existing static county map as the no-JS fallback. A new `MapPage` view renders the include full-width with the year picker and entity/county filters carried in the query string.

**Tech Stack:** Django 5.2, resticus, Leaflet 1.9.4 (already bundled at `assets/js/admin/leaflet/`), Bulma 0.9, no bundler.

**Spec:** `docs/superpowers/specs/2026-09-16-pesticides-explorer-v2-design.md`, section "2. Interactive section map" (as amended: feature properties carry totals only; popups fetch section detail).

## Global Constraints

- Commands run from the worktree root inside Docker: `docker compose run --rm test pytest <path> -q`; `docker compose run --rm web invoke styles` rebuilds CSS.
- Tests: `django.test.TestCase`, fixtures, plain `assert`. The `pesticides-explorer` fixture plus `RollupTestMixin` (`camp/apps/pesticides/tests/rollup_mixin.py`) provide rollup rows.
- `SqidsField` is not a DB column.
- No new JS dependencies; no build step. Static files live under `assets/` and are served by `STATICFILES_DIRS`; reference them with `{% static 'js/pesticides/section-map.js' %}`.
- The sections API caps at 2,500 sections and returns 400 with `{"error": "... zoom in"}` beyond that; a near-cap response is ~2.2 MB. The map must not request below zoom 9 and should keep the viewport small enough at zoom 9–10 (Fresno-county scale ≈ 1,500 sections).
- Never `git add -A`; list files. Commit trailer exactly `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; no other AI attribution.
- Shared db container; re-run once before treating an unrelated failure as real. Do not restart other people's dev servers; port 8001 belongs to another worktree. Use port 8002 for this worktree when a server is needed: `docker compose run --rm -p 8002:8000 web python manage.py runserver 0:8000`.
- Notice timing: "active" means `scheduled_application >= now - 4 days` (`stats.NOTICE_GRACE_DAYS`).

---

## File map

| File | Responsibility |
|---|---|
| `camp/api/v2/pesticides/sections.py` | + `ActiveNoticeList` (GeoJSON, optional bbox, cached 5 min) |
| `camp/api/v2/pesticides/urls.py` | + `notices/active/` |
| `camp/api/v2/pesticides/tests.py` | + endpoint tests |
| `assets/js/pesticides/section-map.js` | the map behavior |
| `assets/css/pesticides/section-map.css` | popup/legend/control styles (plain CSS, loaded with the script) |
| `camp/templates/pesticides/includes/section-map.html` | container + static fallback + legend/controls |
| `camp/templates/pesticides/map.html` | the Map page |
| `camp/templates/pesticides/base.html` | sub-nav "Map" tab; load the script + css |
| `camp/apps/pesticides/views.py` | `MapPage`, `section_map_config()` helper |
| `camp/apps/pesticides/urls.py` | `map/` |
| `camp/apps/pesticides/tests/test_views.py` | Map page tests |

---

### Task 1: Active notices GeoJSON endpoint

**Files:** `camp/api/v2/pesticides/sections.py`, `camp/api/v2/pesticides/urls.py`, `camp/api/v2/pesticides/tests.py`, `camp/api/v2/tests/test_openapi.py`

**Interfaces:**
- `GET /api/2.0/pesticides/notices/active/[?bbox=w,s,e,n][&chemical=&product=&county=]` → `{"type": "FeatureCollection", "as_of": <iso>, "features": [...]}`; each feature: `id` = notice sqid, `geometry` = Point (4326) or null, `properties = {id, scheduled_application (iso), scheduled_end (iso, +4 days), county, application_method, treated_amount, treated_units, products: [{id, name}], chemicals: [{id, name, is_of_concern}], section: <mtrs external_id or null>}`. Unpaginated (active notices are tens of rows). Cached 5 minutes via `CachedEndpointMixin` (`cache_timeout = 300`), same `*Base` + cached subclass pattern as the section endpoints.
- Filters reuse `apply_filters`-style casting: `chemical` (chem code, via `chemicals__chem_code`), `product` (prodno), `county` (slug). `bbox` uses `point__bboverlaps=Polygon.from_bbox(...)`; invalid bbox → 400.

- [ ] **Step 1: Tests (RED)** — add to `camp/api/v2/pesticides/tests.py`:

```python
class ActiveNoticeEndpointTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.url = reverse('api:v2:pesticides:notice-active')

    def test_returns_active_notices_as_geojson(self):
        from camp.apps.pesticides.models import PesticideNotice
        from django.contrib.gis.geos import Point
        PesticideNotice.objects.filter(pk=2).update(point=Point(-119.79, 36.71, srid=4326))
        data = self.client.get(self.url).json()
        assert data['type'] == 'FeatureCollection'
        ids = {f['properties']['id'] for f in data['features']}
        assert ids == {PesticideNotice.objects.get(pk=2).sqid, PesticideNotice.objects.get(pk=3).sqid}
        two = next(f for f in data['features'] if f['properties']['id'] == PesticideNotice.objects.get(pk=2).sqid)
        assert two['geometry'] == {'type': 'Point', 'coordinates': [-119.79, 36.71]}
        assert two['properties']['county'] == 'Fresno County'
        assert two['properties']['scheduled_end'] > two['properties']['scheduled_application']
        assert [c['name'] for c in two['properties']['chemicals']] == ['CHLORPYRIFOS']
        assert two['properties']['chemicals'][0]['is_of_concern'] is True
        assert [p['name'] for p in two['properties']['products']] == ['LORSBAN 4E']

    def test_past_notice_excluded(self):
        from camp.apps.pesticides.models import PesticideNotice
        data = self.client.get(self.url).json()
        assert PesticideNotice.objects.get(pk=1).sqid not in {f['properties']['id'] for f in data['features']}

    def test_bbox_and_filters(self):
        from camp.apps.pesticides.models import PesticideNotice
        from django.contrib.gis.geos import Point
        PesticideNotice.objects.filter(pk=2).update(point=Point(-119.79, 36.71, srid=4326))
        PesticideNotice.objects.filter(pk=3).update(point=Point(-119.04, 35.36, srid=4326))
        data = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8'}).json()
        assert [f['properties']['county'] for f in data['features']] == ['Fresno County']
        data = self.client.get(self.url, {'chemical': 1855}).json()   # glyphosate: only notice 3
        assert [f['properties']['id'] for f in data['features']] == [PesticideNotice.objects.get(pk=3).sqid]
        assert self.client.get(self.url, {'bbox': 'nope'}).status_code == 400

    def test_notice_without_point_has_null_geometry(self):
        data = self.client.get(self.url).json()
        assert all(f['geometry'] is None or f['geometry']['type'] == 'Point' for f in data['features'])
```

And in `test_openapi.py`'s pesticides test: `assert any('pesticides' in p and p.endswith('notices/active/') for p in self.paths)`.

- [ ] **Step 2: Implement** in `sections.py`:

```python
NOTICE_CACHE_TTL = 300

class ActiveNoticeListBase(generics.Endpoint):
    def get(self, request):
        params = request.GET
        notices = stats._upcoming(PesticideNotice.objects.all()).select_related('county', 'mtrs').prefetch_related('chemicals', 'products').order_by('scheduled_application', 'pk')
        if params.get('bbox'):
            try:
                west, south, east, north = (float(v) for v in params['bbox'].split(','))
            except ValueError:
                return bad_request('bbox must be west,south,east,north')
            if not (west < east and south < north):
                return bad_request('bbox must be west,south,east,north')
            notices = notices.filter(point__bboverlaps=Polygon.from_bbox((west, south, east, north)))
        for param, lookup, cast in (('chemical', 'chemicals__chem_code', int), ('product', 'products__prodno', int), ('county', 'county__slug', str)):
            value = params.get(param)
            if value:
                try:
                    notices = notices.filter(**{lookup: cast(value)})
                except ValueError:
                    return bad_request(f'{param} is invalid')
        grace = timedelta(days=stats.NOTICE_GRACE_DAYS)
        features = [{
            'type': 'Feature',
            'id': n.sqid,
            'geometry': json.loads(n.point.geojson) if n.point else None,
            'properties': {
                'id': n.sqid,
                'scheduled_application': n.scheduled_application.isoformat(),
                'scheduled_end': (n.scheduled_application + grace).isoformat(),
                'county': n.county.name if n.county else None,
                'application_method': n.application_method,
                'treated_amount': n.treated_amount,
                'treated_units': n.treated_units,
                'section': n.mtrs.external_id if n.mtrs else None,
                'products': [{'id': p.sqid, 'name': p.name} for p in n.products.all()],
                'chemicals': [{'id': c.sqid, 'name': c.name, 'is_of_concern': c.is_of_concern} for c in n.chemicals.all()],
            },
        } for n in notices.distinct()]
        return {'type': 'FeatureCollection', 'as_of': timezone.now().isoformat(), 'features': features}


class ActiveNoticeList(CachedEndpointMixin, ActiveNoticeListBase):
    """Active SprayDays notices of intent (scheduled from four days ago onward) as GeoJSON points. Optional `bbox=west,south,east,north`, `chemical` (chem code), `product` (prodno), `county` (slug)."""
    cache_timeout = NOTICE_CACHE_TTL
```

`.distinct()` matters because the M2M filters can duplicate rows. URL: `path('notices/active/', sections.ActiveNoticeList.as_view(), name='notice-active')` — place it **before** `notice/<str:notice_id>/` isn't needed (different prefix), but keep it above any catch-all.

- [ ] **Step 3: GREEN** — `docker compose run --rm test pytest camp/api/v2/pesticides/tests.py camp/api/v2/tests/test_openapi.py -q`.
- [ ] **Step 4: Commit** — `feat(api): add active pesticide notices as GeoJSON` + trailer.

---

### Task 2: The map script, styles, include, and Map page

**Files:** `assets/js/pesticides/section-map.js`, `assets/css/pesticides/section-map.css`, `camp/templates/pesticides/includes/section-map.html`, `camp/templates/pesticides/map.html`, `camp/templates/pesticides/base.html`, `camp/apps/pesticides/views.py`, `camp/apps/pesticides/urls.py`, `camp/apps/pesticides/tests/test_views.py`, `assets/sass/sjvair/pages/pesticides.sass`

**Interfaces:**
- `views.section_map_config(year, *, center=None, zoom=None, radius=None, chemical=None, product=None, commodity=None, county=None) -> dict` with keys `sections_url`, `notices_url`, `year`, `center` ("lat,lng" or ""), `zoom`, `radius` ("" or int), `chemical`, `product`, `commodity`, `county` (identifier strings or ""), `section_url_pattern` (`/api/2.0/pesticides/sections/{id}/`). Default center is the SJV centroid `36.75,-119.80` at zoom 8 when nothing is given.
- Include `pesticides/includes/section-map.html` expects `map_config` (the dict) and optionally `county_map` (static fallback HTML) and `year`. Renders:

```html
<div class="section-map-wrap">
  <div class="section-map" id="section-map-{{ map_config.year }}"
       data-sections-url="…" data-notices-url="…" data-section-url-pattern="…"
       data-year="…" data-chemical="…" data-product="…" data-commodity="…" data-county="…"
       data-center="…" data-zoom="…" data-radius="…"></div>
  <div class="section-map-controls" hidden>
    <label><input type="radio" name="metric" value="lbs_chemical" checked> Pounds</label>
    <label><input type="radio" name="metric" value="applications"> Applications</label>
    <span class="section-map-status" aria-live="polite"></span>
  </div>
  <ul class="county-legend section-map-legend" hidden></ul>
  <noscript>{% if county_map %}{% include 'pesticides/includes/county-map.html' %}{% endif %}</noscript>
</div>
```

  (The static fallback goes inside `<noscript>` so it renders only without JS; the script reveals the controls/legend.)
- `MapPage` (`vanilla.TemplateView`, `pesticides/map.html`, URL name `pesticides:map`, path `map/`): reads `year` (via `stats.resolve_year`), optional `chemical`/`product`/`commodity` sqids (resolved to objects, shown as a "Showing: <name> ×" tag; unknown sqid → ignored), `county` slug; context: `map_config` (with chem_code/prodno/site_code/slug as the API identifiers), `filters` (list of `{label, clear_url}`), plus `year_context`. The page: hero with sub-nav "Map" active; a full-width map (height 70vh, min 480px); the year picker above; the filter tags; a short caption and the SprayDays note.
- `base.html`: add `<li>` "Map" to the sub-nav (before Records/Notices which come later); load `section-map.css` in `extra-head` and `section-map.js` in `javascripts` after `leaflet-maps.js`.

- [ ] **Step 1: Tests (RED)** — add to `test_views.py`:

```python
class MapPageTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:map')

    def test_renders_with_defaults(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/map.html')
        cfg = response.context['map_config']
        assert cfg['year'] == 2023
        assert cfg['center'] == '36.75,-119.80' and cfg['zoom'] == 8
        assert cfg['sections_url'] == '/api/2.0/pesticides/sections/'
        assert cfg['notices_url'] == '/api/2.0/pesticides/notices/active/'
        html = response.content.decode()
        assert 'class="section-map"' in html and 'data-year="2023"' in html
        assert 'section-map.js' in html
        assert '<noscript>' in html and 'admin-leaflet-map' in html   # static fallback

    def test_entity_filters_resolve_to_api_identifiers(self):
        chem = Chemical.objects.get(pk=1)
        response = self.client.get(self.url, {'chemical': chem.sqid, 'year': 2022, 'county': 'fresno'})
        cfg = response.context['map_config']
        assert cfg['chemical'] == '1855' and cfg['county'] == 'fresno' and cfg['year'] == 2022
        assert [f['label'] for f in response.context['filters']] == ['GLYPHOSATE', 'Fresno County']
        assert 'year=2022' in response.context['filters'][0]['clear_url']

    def test_unknown_filter_ignored(self):
        response = self.client.get(self.url, {'product': 'nope'})
        assert response.status_code == 200
        assert response.context['map_config']['product'] == ''

    def test_nav_has_map_tab(self):
        assert 'pesticides:map' or True
        html = self.client.get(reverse('pesticides:chemical-list')).content.decode()
        assert reverse('pesticides:map') in html
```

(Drop the vacuous `assert 'pesticides:map' or True` line when writing the file; keep the real assertion.)

- [ ] **Step 2: Implement views + templates** per the interfaces. In `views.py`:

```python
SJV_CENTER = '36.75,-119.80'
SJV_ZOOM = 8

def section_map_config(year, center=None, zoom=None, radius=None, chemical=None, product=None, commodity=None, county=None):
    return {
        'sections_url': '/api/2.0/pesticides/sections/',
        'notices_url': '/api/2.0/pesticides/notices/active/',
        'section_url_pattern': '/api/2.0/pesticides/sections/{id}/',
        'year': year or '',
        'center': center or SJV_CENTER,
        'zoom': zoom or SJV_ZOOM,
        'radius': radius or '',
        'chemical': str(chemical.chem_code) if chemical else '',
        'product': str(product.prodno) if product else '',
        'commodity': commodity.site_code if commodity else '',
        'county': county or '',
    }
```

`MapPage.get_context_data` resolves `chemical`/`product`/`commodity` sqids with `Model.objects.filter(sqid=...).first()`, validates `county` against `Region.objects.filter(type=COUNTY, slug=...)`, builds `filters` with `clear_url = qs_replace(...)`-equivalent (compute with `QueryDict.copy()`; drop the param; keep the rest), and passes `county_map=maps.county_map(stats.by_county(PesticideUseRollup.objects.all(), year))` for the fallback (only when year).

- [ ] **Step 3: Write the script** `assets/js/pesticides/section-map.js` (plain ES2017, IIFE, no globals except `L`):

Behavior contract (implement all of it):
1. `init()` on DOMContentLoaded: for each `.section-map` without `data-rendered`, build the map: `L.map(el, {zoomControl: true, scrollWheelZoom: true})`, tiles from the same MapTiler URL the static maps use (read from the first `.admin-leaflet-map`'s `data-tiles` if present, else from `el.dataset.tiles` which the include sets from `leaflet.TILE_URL` — add `tile_url` to `map_config` via `leaflet.TILE_URL.format(key=settings.MAPTILER_API_KEY, z='{z}', x='{x}', y='{y}')` and `attribution`), `setView(center, zoom)`; if `data-radius`, draw `L.circle` (miles→meters) and `fitBounds` to it.
2. Reveal `.section-map-controls` and `.section-map-legend` (remove `hidden`).
3. `loadSections()` on `moveend`/`zoomend`, debounced 300 ms, with an in-flight `AbortController`: if `map.getZoom() < 9` → clear the layer, status "Zoom in to see square-mile sections", return. Else GET `sections_url?bbox=w,s,e,n&year=&chemical=&product=&commodity=&county=` (omit empty params). On 400 with `error` → status shows the message. On success → replace the `L.geoJSON` layer.
4. Shading: compute five quantile classes over features with metric > 0 in the current response (same algorithm as `maps.quantile_classes`: distinct sorted values, cut at ceil(i·n/k)); colors `['#deebf7','#9ecae1','#6baed6','#3182bd','#08519c']`, no-data `#f0f0f0` with `fillOpacity 0.25`; borders `#555` weight 0.5. Render the legend `<li>` items exactly like `county-legend.html` (swatch + range with `toLocaleString()` + unit), plus "No data".
5. Metric radio changes re-style without refetching.
6. Section click → popup: header `MTRS <mtrs>` + county; totals for the metric; "Loading…" then fetch `section_url_pattern.replace('{id}', id) + '?year='` and list top 3 chemicals as links to `/tools/pesticides/chemicals/<id>/` (slug not needed: `/chemicals/<sqid>/` 301s to the slugged URL) with an "of concern" dot when `is_of_concern` is present in future; for now name + lbs. Include a "This section" link to `/tools/pesticides/sections/<id>/` (sub-project 3 creates it; acceptable to 404 until then — say so in a code comment).
7. Notices: on the same moveend, GET `notices_url?bbox=…` (plus chemical/product/county). Draw `L.circleMarker` (radius 7, `#d35400` fill, white stroke) for features with geometry; popup: "Notice of intent", scheduled date/time (local), "may begin through <end date>", county, method, treated amount+units, products and chemicals lists (names; chemical names link to their pages), and a "Sign up with SprayDays" link `https://spraydays.cdpr.ca.gov/`.
8. `prefers-reduced-motion`: pass `{animate: false}` to setView/fitBounds when the media query matches.
9. Errors (network) → status "Couldn't load sections; try again" and console.error; never throw.

CSS (`assets/css/pesticides/section-map.css`): `.section-map { width: 100%; height: 70vh; min-height: 480px; border: 1px solid #dbdbdb; border-radius: 4px }`, `.section-map-controls` as a small flex row with the status text muted, `.leaflet-popup .section-popup h4 { margin: 0 0 .25rem }`, `.notice-popup`, and marker styles. Keep the legend classes shared with `county-legend` (already styled in sass under `.county-map`; add a sass rule so `.section-map-legend` gets the same look: in `pesticides.sass`, extend the `.county-legend` block selector to `.county-legend, .section-map-legend`).

- [ ] **Step 4: Wire base.html and the sub-nav**, add `map.html`:

```django
{% extends 'pesticides/base.html' %}
{% load pesticides_explorer %}
{% block title %}Map | {{ block.super }}{% endblock %}
{% block body-class %}{{ block.super }} map-page{% endblock %}
{% block breadcrumb-list %}<li class="is-active"><a aria-current="page">Map</a></li>{% endblock %}
{% block explorer-content %}
<div class="content">
    <h1 class="title is-4 mb-2">Pesticide use by square mile{% if year %}, {{ year }}{% endif %}</h1>
    <p class="has-text-grey">Each square is one MTRS section. Shades are quantile classes over the sections in view; click a section for its top chemicals. Orange dots are SprayDays notices of intent currently scheduled.</p>
    {% if filters %}
    <div class="tags">
        {% for f in filters %}<span class="tag is-info is-light is-medium">{{ f.label }} <a class="delete is-small ml-1" href="{{ f.clear_url }}" aria-label="Remove filter"></a></span>{% endfor %}
    </div>
    {% endif %}
</div>
{% include 'pesticides/includes/section-map.html' %}
<p class="is-size-7 has-text-grey mt-3">Sections with no reported use in {{ year }} are outlined only. Want to be told about notices near you? <a href="https://spraydays.cdpr.ca.gov/" target="_blank" rel="noopener">Sign up with SprayDays</a>.</p>
{% endblock %}
```

- [ ] **Step 5: GREEN** — `docker compose run --rm test pytest camp/apps/pesticides/tests/ -q`; rebuild sass (`invoke styles`); `node -e "new Function(require('fs').readFileSync('assets/js/pesticides/section-map.js','utf8'))"` to syntax-check.
- [ ] **Step 6: Commit** — `feat(pesticides): add the interactive section map and Map page` + trailer.

---

### Task 3: Browser check (controller)

Done by the controller with the Chrome extension against a server on port 8002: landing → Map tab; zoom < 9 message; zoom in over Fresno → sections shade, legend appears; metric toggle; click a section → popup with top chemicals; a notice marker popup; `?chemical=<sqid>` filter narrows shading; radius mode via a hand-built URL is exercised in sub-project 4. Fixes found here go through one fix dispatch + scoped re-review.

### Task 4: Wrap up

Full suite; commit any fixes; ledger; no push.
