# Region Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Region admin change page into a per-type dashboard: a tile row, an air quality trend chart, a county forecast panel, a tract CES indicator grid, an overlapping-communities panel, and the existing coverage/monitor panels with tiles, ordered sensibly.

**Architecture:** Extend the existing panel registry (`camp/apps/regions/panels.py`) with `order`, a cached `context`, and `tiles()`. New panels live in the app that owns their data (summaries, forecasts, reports, regions) and register on app `ready()`. Charts are server-rendered inline SVG from a small pure-Python helper. No JavaScript.

**Tech Stack:** Django 5.2 admin, PostGIS, pytest-django `TestCase`.

**Spec:** `docs/superpowers/specs/2026-09-18-region-dashboards-design.md`

## Global Constraints

- Worktree: `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+region-dashboards`, branch `feature/region-dashboards`. Never touch the main checkout. Confirm with `git rev-parse --show-toplevel` before committing.
- Tests use `django.test.TestCase` and plain `assert`; fixtures via `fixtures = [...]`.
- Never `git add -A`; list files explicitly. Commit messages are a plain conventional subject line with NO trailers and no AI attribution of any kind.
- Timezone `America/Los_Angeles`; daily summary timestamps are local midnight stored aware.
- No JavaScript, no chart libraries, no caching, no new models or migrations.
- Verbose names use `_()` as first positional arg. Don't align `=` in field definitions.
- Panel orders: forecast 5, trend 10, coverage/CES 20, overlapping communities 30, monitors 40.

## Running tests

```bash
docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml \
  --project-directory /home/derek/dev/ccac/sjvair.com \
  run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_dash \
  -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+region-dashboards:/app \
  test pytest camp/apps/regions/tests.py -v -p no:cacheprovider --create-db
```

`RUN_TESTS <args>` means that command with `<args>` in place of `camp/apps/regions/tests.py -v`.

## Reference facts (verified)

- `camp/apps/regions/panels.py` today: `PANELS`, `register`, `panels_for(region, request)`, `Panel` (`types`, `title`, `template_name`, `geometry`, `get_context()`, `render()`), helpers `admin_change_url`, `monitors_inside(geometry)` (rows with `name,type,status,last_seen,host,is_sjvair,position,admin_url`), `type_rows`, `status_counts` (`total,active,inactive,hidden,sjvair`), and panels `MonitorsPanel`, `TractPanel` (`records()` returning dicts with `label`, `headline`, `fields`; `field_value(record, field)`).
- `camp/apps/reports/panels.py`: `ScopedPanel` (`scope`, `scope_links()`), `CommunityCoveragePanel` (context keys include `tracts` dict with `population`, `monitors`, `per_10k`), `CountyCoveragePanel` (context `tiles` dict with `uncovered`, `uncovered_population`), `tract_stats(geometry)`. `CoverageCommunity.build_rows(scope, county='', place_type='', min_population=0)` in `camp/apps/reports/views.py` returns row dicts with `name,type,county,population,monitors,per_10k,nearest_km,detail_url`; `CoverageCommunity.place_queryset()` returns city/CDP regions with a boundary. `MonitorScope` in `camp/apps/reports/scope.py`.
- `camp/templates/admin/regions/region/change_form.html` overrides `after_field_sets` to render `panels` (from `RegionAdmin.change_view` extra context) and defines `.region-panel` styles.
- `RegionAdmin.fields = ['name', 'slug', 'external_id', 'type', 'boundary', 'get_metadata', 'get_overview_map', 'get_monitor_map']`; readonly admin via `ReadOnlyAdminMixin`; `LeafletMapMixin` provides map media.
- `RegionSummary` (`camp/apps/summaries/models.py`): `region` FK, `entry_type` (e.g. `pm25`), `resolution` (`BaseSummary.Resolution.DAILY == 'day'`), `timestamp` (aware, local midnight for daily), `count`, `expected_count`, `sum_value`, `sum_of_squares`, `tdigest` (JSON), `minimum`, `maximum`, `mean`, `stddev`, `p25`, `p75`, `station_count`, `weight`. Unique on `(region, entry_type, resolution, timestamp)`. Daily `maximum` carries raw spikes; use `mean`.
- Entry models: `camp.apps.entries.models` exports `PM25, O3, NO2, CO, SO2`; each has `entry_type` (model name), `label`, and `Levels` (a `LevelSet`; iterate for `Level` objects with `.key` (lowercase, e.g. `unhealthy_sensitive`), `.label`, `.value` (lower bound), `.color`). `PM25.Levels` values: good 0, moderate 9.1, unhealthy_sensitive 35.5, unhealthy 55.5, very_unhealthy 150.5, hazardous 250.5. `LevelSet.get_level(value)`, `LevelSet.get_color(value)`. Model map: `camp.apps.entries.fields.EntryTypeField.get_model_map()` → `{entry_type: Model}`.
- `Forecast` (`camp/apps/forecasts/models.py`): `region` FK (county Region), `zone_name`, `forecast_date`, `issued_date`, `published_at`, `aqi_value`, `aqi_category`, `pollutant` (`'O3'`/`'PM2.5'`), `burn_status`, `burn_status_text`, `air_alert`, `air_alert_start`, `air_alert_end`, property `color`. Ordering `('-issued_date', 'region__name')`.
- `Region.objects.counties()` = the 8 SJV county Regions (`Fresno County` …). `Region.Type` values: `county, city, zipcode, tract, cdp, congressional_district, state_assembly, state_senate, school_district, urban_area, land_use, protected, place, mtrs, custom`.
- Fixtures: `regions.yaml` (8 counties with real boundaries, a `Fresno` city pk 9, a `Fresno Unified` school district pk 10, a zip code), `calenviroscreen.yaml` (two fake Fresno tracts; tract `06019000101` has CES5 pop 4650, percentile 89.2, DAC, and CES4 2010+2020 records; boundary pk 1003 is its 2020 boundary), `purple-air.yaml`.
- `camp/apps/regions/tests.py` has `RegionPanelTests` with a superuser `self.user`, `self.request` (RequestFactory GET with user), `self.tract` (`06019000101`), `self.district`, and a `Downtown` PurpleAir at (−119.79, 36.74). `camp/apps/reports/tests.py` has `StaffClientMixin`, `touch()`, `make_place()`, and `CommunityPanelTests` / `CountyPanelTests` using `panels_for` + `isinstance`.
- `camp/utils/tests/` exists (`test_admin_maps.py`); pytest discovers `test_*.py`.

---

### Task 1: Panel plumbing, tile row, collapsed fields

**Files:**
- Modify: `camp/apps/regions/panels.py`, `camp/apps/regions/admin.py`, `camp/templates/admin/regions/region/change_form.html`, `camp/apps/reports/panels.py`, `camp/apps/regions/tests.py`, `camp/apps/reports/tests.py`

**Interfaces:**
- Produces: `Panel.order: int = 100`; `Panel.context` (cached property calling `get_context()` once); `Panel.tiles() -> list[tuple[str, str]]`; `Panel.render()` uses `self.context`; `panels_for()` returns panels sorted by `(order, registration index)`; template context `panels` plus `tiles` (flat list of `(label, value)`). Query-param link helper `Panel.param_links(name, choices)` returning `[(label, url, active)]` that keeps other params.

- [ ] **Step 1: Write the failing tests**

Append to `RegionPanelTests` in `camp/apps/regions/tests.py`:

```python
    def test_panels_are_ordered(self):
        from camp.apps.regions.panels import PANELS, Panel, panels_for

        class Late(Panel):
            types = (Region.Type.TRACT,)
            order = 200
            title = 'Late'

        class Early(Panel):
            types = (Region.Type.TRACT,)
            order = 1
            title = 'Early'

        PANELS.extend([Late, Early])
        try:
            titles = [p.title for p in panels_for(self.tract, self.request)]
            assert titles[0] == 'Early' and titles[-1] == 'Late'
        finally:
            PANELS.remove(Late)
            PANELS.remove(Early)

    def test_context_is_computed_once_and_feeds_tiles(self):
        panel = MonitorsPanel(self.district, self.request)
        calls = []
        original = panel.get_context

        def counting():
            calls.append(1)
            return original()
        panel.get_context = counting
        panel.render()
        panel.tiles()
        assert len(calls) == 1
        assert panel.tiles() == [('Active monitors', f"{panel.context['counts']['active']} / {panel.context['counts']['total']}")]

    def test_change_page_has_tile_row_and_collapsed_fields(self):
        content = self.client.get(reverse('admin:regions_region_change', args=[self.district.pk])).content.decode()
        assert 'class="region-tiles"' in content
        assert 'Active monitors' in content
        assert 'class="module aligned collapse' in content  # the Region fieldset is collapsed
        assert content.index('region-tiles') < content.index('region-panel')

    def test_param_links_keep_other_params(self):
        request = RequestFactory().get('/', {'range': '90d', 'pollutant': 'o3'})
        request.user = self.user
        panel = MonitorsPanel(self.district, request)
        links = {label: (url, active) for label, url, active in panel.param_links('range', [('30d', '30 days'), ('90d', '90 days')])}
        assert links['90 days'][1] is True
        assert 'pollutant=o3' in links['30 days'][0]
        assert 'range=30d' in links['30 days'][0]
```

Append to `CommunityPanelTests` and `CountyPanelTests` in `camp/apps/reports/tests.py`:

```python
    def test_tiles(self):  # in CommunityPanelTests
        request = RequestFactory().get('/')
        request.user = self.user
        panel = [p for p in panels_for(self.testville, request) if isinstance(p, CommunityCoveragePanel)][0]
        assert panel.tiles() == [('Population', '4,650'), ('Counted monitors', '1'), ('Per 10k', '2.15')]
```

```python
    def test_tiles(self):  # in CountyPanelTests
        request = RequestFactory().get('/')
        request.user = self.user
        panel = [p for p in panels_for(self.fresno, request) if isinstance(p, CountyCoveragePanel)][0]
        tiles = dict(panel.tiles())
        assert set(tiles) == {'Communities without a monitor', 'Population without a monitor'}
        assert tiles['Communities without a monitor'] == str(panel.context['tiles']['uncovered'])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/regions/tests.py camp/apps/reports/tests.py -v -k "ordered or computed_once or tile_row or param_links or test_tiles"`
Expected: FAIL (`AttributeError` on `order`/`tiles`/`param_links`, missing markup).

- [ ] **Step 3: Panel base**

In `camp/apps/regions/panels.py`, add `from django.utils.functional import cached_property` and replace `panels_for` and `Panel` with:

```python
def panels_for(region, request):
    """Every registered panel that applies to `region`, sorted by order then registration."""
    chosen = [(cls.order, index, cls) for index, cls in enumerate(PANELS) if cls.applies(region)]
    return [cls(region, request) for _order, _index, cls in sorted(chosen, key=lambda item: item[:2])]


class Panel:
    types = ()
    title = ''
    template_name = None
    order = 100

    def __init__(self, region, request):
        self.region = region
        self.request = request

    @classmethod
    def applies(cls, region):
        return region.type in cls.types and region.boundary_id is not None

    @property
    def geometry(self):
        return self.region.boundary.geometry

    def get_context(self):
        return {}

    @cached_property
    def context(self):
        """get_context() computed once per request; tiles() and render() both read it."""
        return self.get_context()

    def tiles(self):
        """(label, value) pairs for the dashboard header row. Values are preformatted strings."""
        return []

    def param_links(self, name, choices):
        """
        (label, url, active) for a query-param selector: each link sets `name`
        to that choice and keeps every other param.
        """
        current = self.request.GET.get(name)
        links = []
        for value, label in choices:
            query = self.request.GET.copy()
            query[name] = value
            links.append((label, '?' + query.urlencode(), value == current))
        return links

    def render(self):
        return render_to_string(self.template_name, {
            'panel': self,
            'region': self.region,
            **self.context,
        })
```

Give `MonitorsPanel` `order = 40` and:

```python
    def tiles(self):
        counts = self.context['counts']
        return [('Active monitors', f"{counts['active']} / {counts['total']}")]
```

Give `TractPanel` `order = 20`.

- [ ] **Step 4: Tiles on the coverage panels**

In `camp/apps/reports/panels.py`, add `from django.contrib.humanize.templatetags.humanize import intcomma` and:

- `CommunityCoveragePanel`: `order = 20` and

```python
    def tiles(self):
        context = self.context
        per_10k = context['per_10k']
        return [
            ('Population', intcomma(context['tracts']['population'])),
            ('Counted monitors', intcomma(context['monitors'])),
            ('Per 10k', '—' if per_10k is None else str(per_10k)),
        ]
```

- `CountyCoveragePanel`: `order = 20` and

```python
    def tiles(self):
        tiles = self.context['tiles']
        return [
            ('Communities without a monitor', str(tiles['uncovered'])),
            ('Population without a monitor', intcomma(tiles['uncovered_population'])),
        ]
```

- [ ] **Step 5: Admin and template**

In `camp/apps/regions/admin.py`, replace the `fields = [...]` line on `RegionAdmin` with:

```python
    fieldsets = [
        (None, {'fields': ['get_monitor_map']}),
        ('Region', {
            'classes': ['collapse'],
            'fields': ['name', 'slug', 'external_id', 'type', 'boundary', 'get_metadata', 'get_overview_map'],
        }),
    ]
```

and in `change_view` also pass the tiles:

```python
        panels = panels_for(region, request) if region is not None else []
        extra_context = {
            **(extra_context or {}),
            'panels': panels,
            'tiles': [tile for panel in panels for tile in panel.tiles()],
        }
```

In `camp/templates/admin/regions/region/change_form.html`, add before the `after_field_sets` block:

```django
{% block field_sets %}
{% if tiles %}
<div class="region-tiles">
    {% for label, value in tiles %}
    <div class="region-tile"><span class="region-tile-value">{{ value }}</span><span class="region-tile-label">{{ label }}</span></div>
    {% endfor %}
</div>
{% endif %}
{{ block.super }}
{% endblock %}
```

and these styles inside the existing `<style>`:

```css
    .region-tiles { display: flex; flex-wrap: wrap; gap: 12px; margin: 0 0 16px; }
    .region-tile { min-width: 140px; padding: 10px 14px; background: var(--darkened-bg); border: 1px solid var(--hairline-color); border-radius: 4px; }
    .region-tile-value { display: block; font-size: 1.4rem; font-weight: bold; }
    .region-tile-label { display: block; font-size: 0.75rem; color: var(--body-quiet-color); text-transform: uppercase; }
```

`render()` and the existing panel templates need no change: they read `self.context`. Check `CommunityPanelTests`/`CountyPanelTests` still pass (they call `get_context()` directly, which is fine).

- [ ] **Step 6: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/regions/tests.py camp/apps/reports/tests.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add camp/apps/regions/panels.py camp/apps/regions/admin.py camp/templates/admin/regions/region/change_form.html camp/apps/reports/panels.py camp/apps/regions/tests.py camp/apps/reports/tests.py
git commit -m "feat(regions): panel ordering, tile row, and collapsed region fields on the change page"
```

---

### Task 2: SVG line chart helper

**Files:**
- Create: `camp/utils/charts.py`, `camp/utils/tests/test_charts.py`

**Interfaces:**
- Produces: `line_chart(series, bands=(), width=720, height=240, y_label='') -> SafeString`. `series`: list of dicts `{'label': str, 'points': list[(date, float|None)], 'color': str, 'dashed': bool}`; `bands`: list of `(min_value: float, color: str)` ascending.

- [ ] **Step 1: Write the failing tests**

`camp/utils/tests/test_charts.py`:

```python
from datetime import date, timedelta

from django.test import SimpleTestCase

from camp.utils.charts import line_chart


def days(n, start=date(2026, 8, 1)):
    return [start + timedelta(days=i) for i in range(n)]


class LineChartTests(SimpleTestCase):
    def test_one_path_per_series_and_one_rect_per_band(self):
        svg = line_chart(
            [
                {'label': 'Fresno', 'points': list(zip(days(30), [10.0 + i for i in range(30)])), 'color': '#123456', 'dashed': False},
                {'label': 'County', 'points': list(zip(days(30), [12.0] * 30)), 'color': '#654321', 'dashed': True},
            ],
            bands=[(0, '#00e400'), (9.1, '#ffff00'), (35.5, '#ff7e00')],
        )
        assert svg.count('class="chart-line"') == 2
        assert svg.count('class="chart-band"') == 3
        assert 'stroke-dasharray' in svg
        assert '#123456' in svg and '#654321' in svg
        assert '<svg' in svg and svg.strip().endswith('</svg>')

    def test_gaps_break_the_line(self):
        points = list(zip(days(5), [1.0, 2.0, None, 4.0, 5.0]))
        svg = line_chart([{'label': 'x', 'points': points, 'color': '#000', 'dashed': False}])
        path = svg.split('class="chart-line"')[1].split('d="')[1].split('"')[0]
        assert path.count('M') == 2  # two segments

    def test_weekly_ticks_for_short_ranges_and_monthly_for_long(self):
        short = line_chart([{'label': 'x', 'points': list(zip(days(30), [1.0] * 30)), 'color': '#000', 'dashed': False}])
        assert short.count('class="chart-xtick"') == 5  # days 0, 7, 14, 21, 28
        long = line_chart([{'label': 'x', 'points': list(zip(days(120), [1.0] * 120)), 'color': '#000', 'dashed': False}])
        assert long.count('class="chart-xtick"') == 4  # Sep, Oct, Nov, and Aug 1 itself

    def test_empty_and_single_point(self):
        empty = line_chart([{'label': 'x', 'points': [], 'color': '#000', 'dashed': False}])
        assert '<svg' in empty and 'chart-line' not in empty
        single = line_chart([{'label': 'x', 'points': [(date(2026, 8, 1), 3.0)], 'color': '#000', 'dashed': False}])
        assert 'class="chart-point"' in single

    def test_y_axis_covers_data_and_first_band_above_it(self):
        svg = line_chart(
            [{'label': 'x', 'points': list(zip(days(3), [1.0, 2.0, 3.0])), 'color': '#000', 'dashed': False}],
            bands=[(0, '#0f0'), (9.1, '#ff0'), (35.5, '#f70')],
        )
        assert 'class="chart-ytick">10' in svg or 'class="chart-ytick">12' in svg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/utils/tests/test_charts.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

`camp/utils/charts.py`:

```python
"""
Server-rendered SVG charts for admin pages. Pure Python, no JavaScript:
the admin has no chart library and these pages are read, not explored.
"""

import math
from datetime import date, timedelta
from html import escape

from django.utils.safestring import mark_safe

MARGIN = {'top': 12, 'right': 16, 'bottom': 28, 'left': 44}


def nice_ceiling(value):
    """Round a positive number up to 1, 2, 2.5 or 5 times a power of ten."""
    if value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    base = 10 ** exponent
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * base:
            return step * base
    return 10 * base


def x_ticks(first, last):
    """Tick dates: every 7 days for ranges under 60 days, otherwise month starts (plus the first day)."""
    span = (last - first).days
    if span < 60:
        return [first + timedelta(days=i) for i in range(0, span + 1, 7)]
    ticks = [first]
    year, month = first.year, first.month
    while True:
        month += 1
        if month > 12:
            month, year = 1, year + 1
        tick = date(year, month, 1)
        if tick > last:
            break
        ticks.append(tick)
    return ticks


def line_chart(series, bands=(), width=720, height=240, y_label=''):
    points = [point for item in series for point in item['points']]
    dates = [d for d, _v in points]
    values = [v for _d, v in points if v is not None]

    inner_w = width - MARGIN['left'] - MARGIN['right']
    inner_h = height - MARGIN['top'] - MARGIN['bottom']
    first, last = (min(dates), max(dates)) if dates else (date.today(), date.today())
    span_days = max((last - first).days, 1)

    y_max = nice_ceiling(max(values) * 1.1) if values else 1.0
    # Show at least the first non-zero band so the scale reads the same across regions.
    first_band = next((minimum for minimum, _c in bands if minimum > 0), None)
    if first_band is not None and y_max < first_band * 1.2:
        y_max = nice_ceiling(first_band * 1.2)

    def sx(d):
        return MARGIN['left'] + (d - first).days / span_days * inner_w

    def sy(v):
        return MARGIN['top'] + inner_h - (min(v, y_max) / y_max) * inner_h

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img">']

    for index, (minimum, color) in enumerate(bands):
        if minimum >= y_max:
            break
        top = bands[index + 1][0] if index + 1 < len(bands) else y_max
        top = min(top, y_max)
        parts.append(
            f'<rect class="chart-band" x="{MARGIN["left"]}" y="{sy(top):.1f}" width="{inner_w}" '
            f'height="{sy(minimum) - sy(top):.1f}" fill="{escape(color)}" fill-opacity="0.12"/>'
        )

    # Axes and ticks
    parts.append(f'<line class="chart-axis" x1="{MARGIN["left"]}" y1="{MARGIN["top"] + inner_h}" x2="{width - MARGIN["right"]}" y2="{MARGIN["top"] + inner_h}" stroke="#999"/>')
    parts.append(f'<line class="chart-axis" x1="{MARGIN["left"]}" y1="{MARGIN["top"]}" x2="{MARGIN["left"]}" y2="{MARGIN["top"] + inner_h}" stroke="#999"/>')
    for fraction in (0, 0.25, 0.5, 0.75, 1):
        value = y_max * fraction
        label = f'{value:g}'
        parts.append(f'<text class="chart-ytick" x="{MARGIN["left"] - 6}" y="{sy(value) + 4:.1f}" text-anchor="end" font-size="11" fill="#666">{label}</text>')
    if dates:
        for tick in x_ticks(first, last):
            label = tick.strftime('%b %-d') if span_days < 60 else tick.strftime('%b')
            parts.append(f'<text class="chart-xtick" x="{sx(tick):.1f}" y="{height - 8}" text-anchor="middle" font-size="11" fill="#666">{label}</text>')
    if y_label:
        parts.append(f'<text class="chart-ylabel" x="{MARGIN["left"]}" y="{MARGIN["top"] - 2}" font-size="11" fill="#666">{escape(y_label)}</text>')

    for item in series:
        segments, current = [], []
        for d, v in item['points']:
            if v is None:
                if current:
                    segments.append(current)
                current = []
            else:
                current.append((sx(d), sy(v)))
        if current:
            segments.append(current)
        dash = ' stroke-dasharray="6 4"' if item.get('dashed') else ''
        color = escape(item['color'])
        for segment in segments:
            if len(segment) == 1:
                x, y = segment[0]
                parts.append(f'<circle class="chart-point" cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>')
                continue
            d_attr = ' '.join(f'{"M" if i == 0 else "L"}{x:.1f},{y:.1f}' for i, (x, y) in enumerate(segment))
            parts.append(f'<path class="chart-line" d="{d_attr}" fill="none" stroke="{color}" stroke-width="2"{dash}><title>{escape(item["label"])}</title></path>')

    parts.append('</svg>')
    return mark_safe(''.join(parts))
```

Note: `test_gaps_break_the_line` counts `M` in one path; with the gap, two segments become two `<path>` elements, each with one `M`. Adjust that test to `assert svg.count('class="chart-line"') == 2` instead of counting `M` inside a single path.

- [ ] **Step 4: Run tests to verify they pass**

Run: `RUN_TESTS camp/utils/tests/test_charts.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/utils/charts.py camp/utils/tests/test_charts.py
git commit -m "feat(utils): server-rendered SVG line chart helper"
```

---

### Task 3: Air quality trend panel

**Files:**
- Create: `camp/apps/summaries/panels.py`, `camp/templates/admin/regions/panels/trend.html`
- Modify: `camp/apps/summaries/apps.py` (ready imports panels), `camp/apps/summaries/tests.py`

**Interfaces:**
- Consumes: `Panel` (with `order`, `context`, `tiles`, `param_links`), `line_chart`, `EntryTypeField.get_model_map()`.
- Produces: `TrendPanel` registered for every region type; context keys `chart` (SVG or `''`), `range`, `range_links`, `pollutant`, `pollutant_links` (empty list when only one), `unit`, `stats` (`mean`, `worst_day`, `worst_mean`, `days_over`, `stations`, `over_label`), `has_data`, `comparison_label`. Test helper `daily_region_summary(region, day, mean, entry_type='pm25', station_count=1)`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/summaries/tests.py` (it already imports `datetime`, `timedelta`, `timezone`, `TestCase`; add `from django.test import RequestFactory`, `from camp.apps.accounts.models import User`, `from camp.apps.regions.models import Region`, `from camp.apps.regions.panels import panels_for`, `from camp.apps.summaries.models import RegionSummary`, `from camp.apps.summaries.panels import TrendPanel`):

```python
def daily_region_summary(region, day, mean, entry_type='pm25', station_count=1):
    timestamp = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    return RegionSummary.objects.create(
        region=region, entry_type=entry_type, resolution=RegionSummary.Resolution.DAILY, timestamp=timestamp,
        count=24, expected_count=24, sum_value=mean * 24, sum_of_squares=mean * mean * 24, tdigest={},
        minimum=mean, maximum=mean, mean=mean, stddev=0.0, p25=mean, p75=mean,
        station_count=station_count, weight=float(station_count),
    )


class TrendPanelTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.user = User.objects.create_superuser(email='admin@example.com', password='password', phone='+15595551234', full_name='Admin')
        self.city = Region.objects.get(pk=9)  # Fresno (city), inside Fresno County
        self.county = Region.objects.counties().get(name='Fresno County')
        self.kern = Region.objects.counties().get(name='Kern County')
        yesterday = timezone.localdate() - timedelta(days=1)
        for offset in range(10):
            day = yesterday - timedelta(days=offset)
            daily_region_summary(self.city, day, 40.0 if offset < 2 else 10.0, station_count=3)
            daily_region_summary(self.county, day, 20.0)
            daily_region_summary(self.kern, day, 30.0)
        # A stale row outside every range must be ignored.
        daily_region_summary(self.city, yesterday - timedelta(days=400), 999.0)

    def panel(self, region, **params):
        request = RequestFactory().get('/', params)
        request.user = self.user
        return [p for p in panels_for(region, request) if isinstance(p, TrendPanel)][0]

    def test_city_tiles_and_comparison(self):
        context = self.panel(self.city).context
        assert context['has_data'] is True
        assert context['pollutant'] == 'pm25'
        assert context['range'] == '30d'
        assert context['stats']['mean'] == 16.0   # (2*40 + 8*10) / 10
        assert context['stats']['days_over'] == 2  # 40 >= 35.5
        assert context['stats']['worst_mean'] == 40.0
        assert context['stats']['stations'] == 3
        assert context['comparison_label'] == 'Fresno County'
        assert context['chart'].count('class="chart-line"') == 2
        assert dict(self.panel(self.city).tiles())['Days unhealthy for sensitive groups'] == '2'

    def test_county_compares_to_all_counties(self):
        context = self.panel(self.county).context
        assert context['comparison_label'] == 'All SJV counties'
        # The comparison line is the mean of county means: (20 + 30) / 2 each day.
        assert context['comparison_points'][0][1] == 25.0

    def test_ranges_and_pollutants_are_validated(self):
        assert self.panel(self.city, range='12m').context['range'] == '12m'
        assert self.panel(self.city, range='nope').context['range'] == '30d'
        context = self.panel(self.city, pollutant='o3').context
        assert context['pollutant'] == 'pm25'  # no ozone rows for this region
        assert context['pollutant_links'] == []
        daily_region_summary(self.city, timezone.localdate() - timedelta(days=1), 0.05, entry_type='o3')
        context = self.panel(self.city, pollutant='o3').context
        assert context['pollutant'] == 'o3'
        assert [label for label, _url, _on in context['pollutant_links']] == ['PM2.5', 'Ozone']

    def test_no_data_message(self):
        context = self.panel(Region.objects.get(pk=10)).context  # school district, no rows
        assert context['has_data'] is False
        assert context['chart'] == ''
        assert self.panel(Region.objects.get(pk=10)).tiles() == []
```

If the `O3.label` is not `'Ozone'`, read `camp/apps/entries/models/gases.py` and use the real label in the last assertion.

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/summaries/tests.py -v -k TrendPanel`
Expected: ImportError for `camp.apps.summaries.panels`.

- [ ] **Step 3: Implement**

`camp/apps/summaries/panels.py`:

```python
"""
Air quality trend panel for the Region admin: daily region summaries as a
line chart with level bands, a comparison line, and headline tiles.
"""

from datetime import datetime, timedelta

from django.db.models import Avg
from django.utils import timezone

from camp.apps.entries.fields import EntryTypeField
from camp.apps.regions.models import Region
from camp.apps.regions.panels import Panel, register
from camp.utils.charts import line_chart

RANGES = [('30d', '30 days', 30), ('90d', '90 days', 90), ('ytd', 'Year to date', None), ('12m', '12 months', 365)]
DEFAULT_RANGE = '30d'
DEFAULT_POLLUTANT = 'pm25'
REGION_COLOR = '#1f4e79'
COMPARISON_COLOR = '#7f8c8d'


def range_window(key):
    """(start_date, end_date_exclusive) in local calendar days ending yesterday."""
    end = timezone.localdate()
    for value, _label, days in RANGES:
        if value == key:
            if days is None:
                return end.replace(month=1, day=1), end
            return end - timedelta(days=days), end
    raise KeyError(key)


def daily_means(region_ids, entry_type, start, end):
    """{region_id: {date: mean}} for daily summaries in [start, end)."""
    from camp.apps.summaries.models import RegionSummary
    start_dt = timezone.make_aware(datetime.combine(start, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(end, datetime.min.time()))
    rows = (RegionSummary.objects
        .filter(region_id__in=region_ids, entry_type=entry_type, resolution=RegionSummary.Resolution.DAILY,
                timestamp__gte=start_dt, timestamp__lt=end_dt)
        .values_list('region_id', 'timestamp', 'mean', 'station_count')
        .order_by('timestamp'))
    out = {}
    for region_id, timestamp, mean, stations in rows:
        out.setdefault(region_id, {})[timezone.localtime(timestamp).date()] = (mean, stations)
    return out


@register
class TrendPanel(Panel):
    """Daily mean of a pollutant over a range, against the parent county (or all counties)."""

    types = tuple(Region.Type.values)
    title = 'Air quality trend'
    template_name = 'admin/regions/panels/trend.html'
    order = 10

    @property
    def range(self):
        wanted = self.request.GET.get('range', DEFAULT_RANGE)
        return wanted if wanted in {value for value, _l, _d in RANGES} else DEFAULT_RANGE

    def available_pollutants(self):
        """entry types with any daily row for this region, in model-map order."""
        from camp.apps.summaries.models import RegionSummary
        present = set(RegionSummary.objects
            .filter(region=self.region, resolution=RegionSummary.Resolution.DAILY)
            .values_list('entry_type', flat=True).distinct())
        model_map = EntryTypeField.get_model_map()
        ordered = [DEFAULT_POLLUTANT] + sorted(key for key in model_map if key != DEFAULT_POLLUTANT)
        return [(key, str(model_map[key].label)) for key in ordered if key in present and key in model_map]

    @property
    def pollutant(self):
        available = {key for key, _label in self.available_pollutants()}
        wanted = self.request.GET.get('pollutant', DEFAULT_POLLUTANT)
        if wanted in available:
            return wanted
        return DEFAULT_POLLUTANT if DEFAULT_POLLUTANT in available else (next(iter(available)) if available else DEFAULT_POLLUTANT)

    def comparison(self):
        """(label, [region ids]) for the comparison line, or (None, [])."""
        if self.region.type == Region.Type.COUNTY:
            return 'All SJV counties', list(Region.objects.counties().values_list('pk', flat=True))
        county = (Region.objects.counties()
            .filter(boundary__geometry__contains=self.geometry.centroid)
            .first())
        return (county.name, [county.pk]) if county else (None, [])

    def get_context(self):
        start, end = range_window(self.range)
        pollutant = self.pollutant
        model = EntryTypeField.get_model_map().get(pollutant)
        levels = list(model.Levels) if model else []
        usg = next((level for level in levels if level.key == 'unhealthy_sensitive'), None)
        unit = model._meta.get_field('value').help_text if model else ''

        comparison_label, comparison_ids = self.comparison()
        means = daily_means([self.region.pk, *comparison_ids], pollutant, start, end)
        own = means.get(self.region.pk, {})
        days = [start + timedelta(days=i) for i in range((end - start).days)]

        region_points = [(day, own[day][0] if day in own else None) for day in days]
        comparison_points = []
        if comparison_ids:
            for day in days:
                values = [means[pk][day][0] for pk in comparison_ids if pk in means and day in means[pk]]
                comparison_points.append((day, sum(values) / len(values) if values else None))

        has_data = bool(own)
        stats = {}
        if has_data:
            values = [value for value, _stations in own.values()]
            worst_day = max(own, key=lambda day: own[day][0])
            latest = max(own)
            stats = {
                'mean': round(sum(values) / len(values), 1),
                'worst_day': worst_day,
                'worst_mean': round(own[worst_day][0], 1),
                'days_over': sum(1 for value in values if usg and value >= usg.value),
                'over_label': usg.label if usg else '',
                'stations': own[latest][1],
            }

        series = [{'label': self.region.name, 'points': region_points, 'color': REGION_COLOR, 'dashed': False}]
        if comparison_label and any(value is not None for _d, value in comparison_points):
            series.append({'label': comparison_label, 'points': comparison_points, 'color': COMPARISON_COLOR, 'dashed': True})
        bands = [(level.value, level.color) for level in levels]

        return {
            'has_data': has_data,
            'chart': line_chart(series, bands=bands, y_label=str(unit)) if has_data else '',
            'range': self.range,
            'range_links': self.param_links('range', [(value, label) for value, label, _days in RANGES]),
            'pollutant': pollutant,
            'pollutant_links': self.param_links('pollutant', self.available_pollutants()) if len(self.available_pollutants()) > 1 else [],
            'pollutant_label': str(model.label) if model else pollutant,
            'unit': str(unit),
            'stats': stats,
            'comparison_label': comparison_label if len(series) > 1 else None,
            'comparison_points': comparison_points,
            'start': start,
            'end': end - timedelta(days=1),
        }

    def tiles(self):
        context = self.context
        if not context['has_data']:
            return []
        stats = context['stats']
        return [
            (f"Mean {context['pollutant_label']}", f"{stats['mean']:g}"),
            ('Worst day', f"{stats['worst_mean']:g} on {stats['worst_day']:%b %-d}"),
            ('Days unhealthy for sensitive groups', str(stats['days_over'])),
        ]
```

`camp/templates/admin/regions/panels/trend.html`:

```django
{% load humanize %}
<p class="scope-links">Range:
    {% for label, url, on in range_links %}<a href="{{ url }}" class="{% if on %}is-on{% endif %}">{{ label }}</a>{% endfor %}
    {% if pollutant_links %}&nbsp; Pollutant:
    {% for label, url, on in pollutant_links %}<a href="{{ url }}" class="{% if on %}is-on{% endif %}">{{ label }}</a>{% endfor %}
    {% endif %}
</p>
{% if has_data %}
<div class="panel-stats">
    <table>
        <caption>{{ pollutant_label }}, {{ start|date:"M j" }} – {{ end|date:"M j, Y" }}</caption>
        <tr><th>Period mean</th><td>{{ stats.mean }} {{ unit }}</td></tr>
        <tr><th>Worst day</th><td>{{ stats.worst_mean }} on {{ stats.worst_day|date:"M j" }}</td></tr>
        <tr><th>Days at or above "{{ stats.over_label }}"</th><td>{{ stats.days_over }}</td></tr>
        <tr><th>Stations (latest day)</th><td>{{ stats.stations }}</td></tr>
        {% if comparison_label %}<tr><th>Dashed line</th><td>{{ comparison_label }}</td></tr>{% endif %}
    </table>
</div>
{{ chart }}
<p class="help">Daily means of the region summary. Shaded bands are the {{ pollutant_label }} AQI levels.</p>
{% else %}
<p>No daily {{ pollutant_label }} summaries for this region in the last {{ range }}. Region summaries need at least one monitor inside the boundary and the nightly rollup to have run.</p>
{% endif %}
```

`camp/apps/summaries/apps.py`:

```python
from django.apps import AppConfig


class SummariesConfig(AppConfig):
    name = 'camp.apps.summaries'

    def ready(self):
        from camp.apps.summaries import panels  # noqa: F401 -- registers the Region admin trend panel
```

Notes: the `%-d` strftime flag is Linux-only, which matches the container. `param_links` marks a choice active only when the param is present; make the template still show the default as active by having `get_context` pass `range_links` computed against `self.range` instead: replace the `param_links` call for range with a local loop that sets `active = value == self.range`, and likewise for pollutant. Concretely, write a small method:

```python
    def choice_links(self, name, choices, current):
        links = []
        for value, label in choices:
            query = self.request.GET.copy()
            query[name] = value
            links.append((label, '?' + query.urlencode(), value == current))
        return links
```

and use `self.choice_links('range', [...], self.range)` and `self.choice_links('pollutant', ..., pollutant)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/summaries/tests.py camp/apps/regions/tests.py -v -k "TrendPanel or RegionPanel"`
Expected: all PASS. If the `worst_mean` assertion sees `40.0` twice with the tie broken to a different day, that is fine since only the mean is asserted.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/summaries/panels.py camp/apps/summaries/apps.py camp/apps/summaries/tests.py camp/templates/admin/regions/panels/trend.html
git commit -m "feat(summaries): air quality trend panel on the Region admin"
```

---

### Task 4: County forecast panel

**Files:**
- Create: `camp/apps/forecasts/panels.py`, `camp/templates/admin/regions/panels/forecast.html`
- Modify: `camp/apps/forecasts/apps.py`, `camp/apps/forecasts/tests.py`

**Interfaces:**
- Produces: `ForecastPanel` (county, order 5); context `days`: list of `{'date', 'items': [{'pollutant', 'aqi', 'category', 'color', 'burn', 'alert'}]}`, `issued` (date or None). Tile: today's highest AQI category.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/forecasts/tests.py` (add imports `from datetime import timedelta`, `from django.test import RequestFactory`, `from django.utils import timezone`, `from camp.apps.accounts.models import User`, `from camp.apps.regions.panels import panels_for`, `from camp.apps.forecasts.panels import ForecastPanel`):

```python
class ForecastPanelTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.user = User.objects.create_superuser(email='admin@example.com', password='password', phone='+15595551234', full_name='Admin')
        self.county = Region.objects.counties().get(name='Fresno County')
        self.today = timezone.localdate()
        stale = self.today - timedelta(days=1)
        for issued, pm, o3 in ((stale, 120, 60), (self.today, 62, 48)):
            for pollutant, aqi in (('PM2.5', pm), ('O3', o3)):
                for offset in (0, 1):
                    Forecast.objects.create(
                        region=self.county, zone_name='Fresno', forecast_date=self.today + timedelta(days=offset),
                        issued_date=issued, published_at=timezone.now(), aqi_value=aqi + offset,
                        aqi_category='Moderate' if aqi + offset < 101 else 'Unhealthy for Sensitive Groups',
                        pollutant=pollutant, burn_status='burn' if offset else 'no-burn', burn_status_text='No burning',
                        air_alert=offset == 1, air_alert_start=self.today if offset else None,
                    )

    def panel(self):
        request = RequestFactory().get('/')
        request.user = self.user
        return [p for p in panels_for(self.county, request) if isinstance(p, ForecastPanel)][0]

    def test_latest_issue_grouped_by_day(self):
        context = self.panel().context
        assert context['issued'] == self.today
        assert [day['date'] for day in context['days']] == [self.today, self.today + timedelta(days=1)]
        today = {item['pollutant']: item for item in context['days'][0]['items']}
        assert today['PM2.5']['aqi'] == 62 and today['O3']['aqi'] == 48  # not the stale 120/60
        assert today['PM2.5']['color']
        assert context['days'][1]['items'][0]['alert'] is True

    def test_tile_is_todays_worst_category(self):
        assert self.panel().tiles() == [('Forecast today', 'Moderate (AQI 62)')]

    def test_no_forecast(self):
        Forecast.objects.all().delete()
        panel = self.panel()
        assert panel.context['days'] == []
        assert panel.tiles() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/forecasts/tests.py -v -k ForecastPanel`
Expected: ImportError.

- [ ] **Step 3: Implement**

`camp/apps/forecasts/panels.py`:

```python
"""Today's SJVAPCD forecast for a county, on its Region admin page."""

from django.utils import timezone

from camp.apps.forecasts.models import Forecast
from camp.apps.regions.models import Region
from camp.apps.regions.panels import Panel, register


@register
class ForecastPanel(Panel):
    types = (Region.Type.COUNTY,)
    title = "Today's forecast"
    template_name = 'admin/regions/panels/forecast.html'
    order = 5

    def get_context(self):
        today = timezone.localdate()
        latest = (Forecast.objects
            .filter(region=self.region, forecast_date__gte=today)
            .order_by('-issued_date')
            .values_list('issued_date', flat=True)
            .first())
        days = []
        if latest is not None:
            rows = (Forecast.objects
                .filter(region=self.region, forecast_date__gte=today, issued_date=latest)
                .order_by('forecast_date', 'pollutant'))
            by_date = {}
            for row in rows:
                by_date.setdefault(row.forecast_date, []).append({
                    'pollutant': row.get_pollutant_display(),
                    'aqi': row.aqi_value,
                    'category': row.aqi_category,
                    'color': row.color,
                    'burn': row.burn_status_text or row.burn_status,
                    'alert': row.air_alert,
                    'alert_start': row.air_alert_start,
                    'alert_end': row.air_alert_end,
                })
            days = [{'date': date, 'items': items} for date, items in sorted(by_date.items())]
        return {'issued': latest, 'days': days}

    def tiles(self):
        days = self.context['days']
        if not days or days[0]['date'] != timezone.localdate():
            return []
        worst = max(days[0]['items'], key=lambda item: item['aqi'])
        return [('Forecast today', f"{worst['category']} (AQI {worst['aqi']})")]
```

`camp/templates/admin/regions/panels/forecast.html`:

```django
{% if days %}
<p class="help">Issued {{ issued|date:"M j" }} by the San Joaquin Valley APCD.</p>
<div class="panel-stats">
{% for day in days %}
<table>
    <caption>{{ day.date|date:"l, M j" }}</caption>
    {% for item in day.items %}
    <tr><th>{{ item.pollutant }}</th>
        <td><span class="swatch" style="background: {{ item.color }};"></span>{{ item.category }} (AQI {{ item.aqi }})</td></tr>
    {% endfor %}
    {% with first=day.items.0 %}
    {% if first.burn %}<tr><th>Burning</th><td>{{ first.burn }}</td></tr>{% endif %}
    {% if first.alert %}<tr><th>Air alert</th><td>{{ first.alert_start|date:"M j" }}{% if first.alert_end %} – {{ first.alert_end|date:"M j" }}{% endif %}</td></tr>{% endif %}
    {% endwith %}
</table>
{% endfor %}
</div>
{% else %}
<p>No forecast on file for this county. The daily forecast task fills this in once the SJVAPCD zones are imported.</p>
{% endif %}
```

Add to the change form's `<style>`: `.region-panel .swatch { display: inline-block; width: 12px; height: 12px; margin-right: 6px; border: 1px solid #7f8c8d; vertical-align: middle; }`.

`camp/apps/forecasts/apps.py`:

```python
from django.apps import AppConfig


class ForecastsConfig(AppConfig):
    name = 'camp.apps.forecasts'

    def ready(self):
        from camp.apps.forecasts import panels  # noqa: F401 -- registers the Region admin forecast panel
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/forecasts/tests.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/forecasts/panels.py camp/apps/forecasts/apps.py camp/apps/forecasts/tests.py camp/templates/admin/regions/panels/forecast.html camp/templates/admin/regions/region/change_form.html
git commit -m "feat(forecasts): today's forecast panel on county admin pages"
```

---

### Task 5: Tract indicator grid and overlapping communities

**Files:**
- Modify: `camp/apps/regions/panels.py`, `camp/templates/admin/regions/panels/tract.html`, `camp/apps/regions/tests.py`
- Create: `camp/templates/admin/regions/panels/overlap.html`
- Modify: `camp/apps/reports/panels.py`, `camp/apps/reports/tests.py`

**Interfaces:**
- `TractPanel.context` gains `indicators`: `{'versions': ['CES5', 'CES4'], 'headline': [(label, ces5_value, ces4_value)], 'groups': [{'label', 'score': (label, ces5, ces5_p, ces4, ces4_p), 'rows': [(label, ces5, ces5_p, ces4, ces4_p)]}]}`; tiles `CES percentile`, `SB535 DAC`.
- `OverlapPanel` (reports app; school district, zip code, legislative districts; order 30): context `communities` (rows from `CoverageCommunity.build_rows` limited to places whose centroid is inside the region) and `tiles` `Communities inside`.
- `MonitorsPanel.types` drops nothing; both panels can apply to a district.

- [ ] **Step 1: Write the failing tests**

Append to `RegionPanelTests`:

```python
    def test_tract_indicator_grid(self):
        context = TractPanel(self.tract, self.request).context
        indicators = context['indicators']
        assert indicators['versions'] == ['CES5', 'CES4']
        headline = {label: values for label, *values in indicators['headline']}
        assert headline['Total Population'][0] == 4650
        assert headline['CES Score Percentile'][0] == 89.2
        assert headline['SB535 DAC'] == ['Yes', 'Yes']
        groups = {group['label']: group for group in indicators['groups']}
        assert set(groups) == {'Pollution burden', 'Population characteristics'}
        pollution = groups['Pollution burden']
        assert pollution['score'][0] == 'Pollution Burden Score'
        labels = [row[0] for row in pollution['rows']]
        assert 'PM2.5' in labels and 'Ozone' in labels
        assert all(len(row) == 5 for row in pollution['rows'])
        tiles = dict(TractPanel(self.tract, self.request).tiles())
        assert tiles == {'CES percentile': '89.2', 'SB535 DAC': 'Yes'}
```

Append to `camp/apps/reports/tests.py` (imports: `OverlapPanel` from `camp.apps.reports.panels`):

```python
class OverlapPanelTests(StaffClientMixin, TestCase):
    fixtures = ['regions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        super().setUp()
        self.testville = make_place('Testville', Region.Type.CDP, (-119.8, 36.7, -119.7, 36.8), '9001')
        self.faraway = make_place('Faraway', Region.Type.CITY, (-119.2, 35.3, -119.1, 35.4), '9002')  # Kern
        self.district = Region.objects.create(name='Square Unified', slug='square-unified', type=Region.Type.SCHOOL_DISTRICT, external_id='sq')
        self.district.boundary = Boundary.objects.create(region=self.district, version='latest',
            geometry=MultiPolygon(Polygon.from_bbox((-119.9, 36.6, -119.6, 36.9))))
        self.district.save()
        self.monitor = PurpleAir.objects.create(name='In Testville', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        touch(self.monitor, timezone.now() - timedelta(minutes=5))

    def test_lists_places_whose_centroid_is_inside(self):
        request = RequestFactory().get('/')
        request.user = self.user
        panels = panels_for(self.district, request)
        panel = [p for p in panels if isinstance(p, OverlapPanel)][0]
        names = {row['name']: row for row in panel.context['communities']}
        assert 'Testville' in names and 'Faraway' not in names
        assert names['Testville']['monitors'] == 1
        assert names['Testville']['detail_url'] == reverse('admin:regions_region_change', args=[self.testville.pk])
        assert panel.tiles() == [('Communities inside', str(len(names)))]
        assert [type(p).__name__ for p in panels][-1] == 'MonitorsPanel'  # overlap (30) sorts before monitors (40)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/regions/tests.py camp/apps/reports/tests.py -v -k "indicator_grid or OverlapPanel"`
Expected: FAIL (`KeyError: 'indicators'`, ImportError for `OverlapPanel`).

- [ ] **Step 3: Tract indicator grid**

In `TractPanel` (`camp/apps/regions/panels.py`) add:

```python
    HEADLINE = ('population', 'ci_score', 'ci_score_p', 'dac_sb535', 'dac_category')
    GROUPS = (('Pollution burden', 'pollution', 'pol_'), ('Population characteristics', 'popchar', 'char_'))

    def newest_records(self):
        """{'CES5': record, 'CES4': record} using the newest boundary that has each."""
        found = {}
        for boundary in self.region.boundaries.order_by('-version'):
            for attr, key in (('ces5', 'CES5'), ('ces4', 'CES4')):
                if key not in found:
                    record = getattr(boundary, attr, None)
                    if record is not None:
                        found[key] = record
        return found

    @staticmethod
    def display(record, name):
        if record is None:
            return None
        field = record._meta.get_field(name)
        value = TractPanel.field_value(record, field)
        if isinstance(value, bool):
            return 'Yes' if value else 'No'
        return value

    def indicators(self):
        records = self.newest_records()
        versions = [key for key in ('CES5', 'CES4') if key in records]
        if not versions:
            return {'versions': [], 'headline': [], 'groups': []}
        sample = records[versions[0]]

        def label_of(name):
            for record in records.values():
                try:
                    return record._meta.get_field(name).verbose_name
                except Exception:
                    continue
            return name

        def values(name):
            return [self.display(records.get(key), name) if records.get(key) and name in {f.name for f in records[key]._meta.fields} else None for key in versions]

        headline = [(label_of(name), *values(name)) for name in self.HEADLINE]
        groups = []
        for label, score_name, prefix in self.GROUPS:
            names = sorted({
                field.name for record in records.values() for field in record._meta.fields
                if field.name.startswith(prefix) and not field.name.endswith('_p')
            })
            rows = []
            for name in names:
                row = [label_of(name)]
                for key in versions:
                    row.append(self.display(records.get(key), name) if key in records and name in {f.name for f in records[key]._meta.fields} else None)
                    row.append(self.display(records.get(key), f'{name}_p') if key in records and f'{name}_p' in {f.name for f in records[key]._meta.fields} else None)
                rows.append(tuple(row))
            score = [label_of(score_name)]
            for key in versions:
                score.append(self.display(records.get(key), score_name))
                score.append(self.display(records.get(key), f'{score_name}_p'))
            groups.append({'label': label, 'score': tuple(score), 'rows': rows})
        return {'versions': versions, 'headline': headline, 'groups': groups}

    def tiles(self):
        records = self.newest_records()
        record = records.get('CES5') or records.get('CES4')
        if record is None:
            return []
        return [
            ('CES percentile', '—' if record.ci_score_p is None else f'{record.ci_score_p:g}'),
            ('SB535 DAC', 'Yes' if record.dac_sb535 else 'No'),
        ]
```

Row tuples have `1 + 2 * len(versions)` entries; with two versions that is 5, matching the test. Update `get_context` to add `'indicators': self.indicators()`.

Rewrite `camp/templates/admin/regions/panels/tract.html`:

```django
{% load humanize %}
{% if indicators.versions %}
<div class="panel-stats">
<table>
    <caption>Headline</caption>
    <thead><tr><th></th>{% for version in indicators.versions %}<th>{{ version }}</th>{% endfor %}</tr></thead>
    {% for row in indicators.headline %}
    <tr><th>{{ row.0 }}</th>{% for value in row|slice:"1:" %}<td>{{ value|default_if_none:"—" }}</td>{% endfor %}</tr>
    {% endfor %}
</table>
{% include "admin/regions/panels/_monitor_counts.html" %}
</div>
{% for group in indicators.groups %}
<table class="wide">
    <caption>{{ group.label }}</caption>
    <thead><tr><th>Indicator</th>{% for version in indicators.versions %}<th>{{ version }} value</th><th>{{ version }} percentile</th>{% endfor %}</tr></thead>
    <tbody>
        <tr class="is-score"><th>{{ group.score.0 }}</th>{% for value in group.score|slice:"1:" %}<td><strong>{{ value|default_if_none:"—" }}</strong></td>{% endfor %}</tr>
        {% for row in group.rows %}
        <tr><th>{{ row.0 }}</th>{% for value in row|slice:"1:" %}<td>{{ value|default_if_none:"—"|floatformat:"-2" }}</td>{% endfor %}</tr>
        {% endfor %}
    </tbody>
</table>
{% endfor %}
{% else %}
<div class="panel-stats">{% include "admin/regions/panels/_monitor_counts.html" %}</div>
<p>No CalEnviroScreen records for this tract. Run the CES imports first.</p>
{% endif %}
{% for record in records %}
<details class="region-panel-details"><summary>{{ record.label }}: all {{ record.fields|length }} fields</summary>
<table>
    {% for label, value in record.fields %}
    <tr><th>{{ label }}</th><td>{{ value|default_if_none:"—" }}</td></tr>
    {% endfor %}
</table>
</details>
{% endfor %}
{% include "admin/regions/panels/_monitor_list.html" %}
```

`floatformat:"-2"` on a string like "Yes" leaves it unchanged (it returns the input when it cannot parse), so the shared cell template is safe.

- [ ] **Step 4: Overlap panel**

In `camp/apps/reports/panels.py` add:

```python
@register
class OverlapPanel(ScopedPanel):
    """Cities and CDPs whose centroid falls inside a district or zip code, with their coverage."""

    types = (Region.Type.SCHOOL_DISTRICT, Region.Type.ZIPCODE, Region.Type.CONGRESSIONAL_DISTRICT,
             Region.Type.STATE_ASSEMBLY, Region.Type.STATE_SENATE)
    title = 'Communities inside'
    template_name = 'admin/regions/panels/overlap.html'
    order = 30

    def get_context(self):
        inside = set(CoverageCommunity.place_queryset()
            .annotate(c=Centroid('boundary__geometry'))
            .filter(c__within=self.geometry)
            .values_list('pk', flat=True))
        rows = [row for row in CoverageCommunity.build_rows(self.scope) if row['pk'] in inside]
        rows.sort(key=lambda row: (-row['population'], row['name']))
        return {'communities': rows, 'scope': self.scope, 'scope_links': self.scope_links()}

    def tiles(self):
        return [('Communities inside', str(len(self.context['communities'])))]
```

This needs `build_rows` rows to carry `'pk': place['pk']`; add that key in `CoverageCommunity.build_rows` in `camp/apps/reports/views.py` (harmless for the report template).

`camp/templates/admin/regions/panels/overlap.html`:

```django
{% load humanize %}
{% include "admin/regions/panels/_scope_links.html" %}
<table class="wide">
    <caption>{{ communities|length }} cities and census-designated places</caption>
    <thead><tr><th>Place</th><th>Type</th><th>County</th><th>Population</th><th>Monitors</th><th>Per 10k</th><th>Nearest monitor</th></tr></thead>
    <tbody>
        {% for row in communities %}
        <tr>
            <th><a href="{{ row.detail_url }}">{{ row.name }}</a></th>
            <td>{{ row.type }}</td>
            <td>{{ row.county }}</td>
            <td>{{ row.population|intcomma }}</td>
            <td>{{ row.monitors|intcomma }}</td>
            <td>{{ row.per_10k|default_if_none:"—" }}</td>
            <td>{% if row.nearest_km is not None %}{{ row.nearest_km }} km{% else %}—{% endif %}</td>
        </tr>
        {% empty %}
        <tr><td colspan="7">No city or CDP centroid falls inside this boundary.</td></tr>
        {% endfor %}
    </tbody>
</table>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/regions/tests.py camp/apps/reports/tests.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add camp/apps/regions/panels.py camp/templates/admin/regions/panels/tract.html camp/templates/admin/regions/panels/overlap.html camp/apps/regions/tests.py camp/apps/reports/panels.py camp/apps/reports/views.py camp/apps/reports/tests.py
git commit -m "feat(regions): CES indicator grid for tracts and overlapping communities for districts"
```

---

### Task 6: Verification

- [ ] **Step 1:** `RUN_TESTS camp/apps/regions camp/apps/reports camp/apps/summaries camp/apps/forecasts camp/utils/tests -q` → PASS.
- [ ] **Step 2:** `RUN_TESTS camp -q` → PASS (re-run a failing file alone once if the shared DB is busy).
- [ ] **Step 3:** Smoke each region type against the dev database with Django's test client in a `manage.py shell` (see the reports plan's Task 7 approach): Fresno County, Fresno city, a tract, a school district, a zip code. Report status, elapsed time, and which panel titles rendered, in the task report. Do not commit anything for this step.

## Self-review

- **Spec coverage:** plumbing (Task 1), chart helper (Task 2), trend panel with ranges/pollutants/comparison/tiles (Task 3), forecast (Task 4), tract grid and overlap panel with tiles (Task 5), tiles on coverage panels (Task 1), collapsed fields and tile row (Task 1), verification (Task 6). Out of scope items untouched.
- **Placeholders:** none.
- **Type consistency:** `Panel.context` / `tiles()` / `param_links` from Task 1 are used by Tasks 3–5; `line_chart` signature matches its call in Task 3; `build_rows` gains `pk` in Task 5 and its other keys are unchanged; test helper names (`daily_region_summary`) are defined where used.
