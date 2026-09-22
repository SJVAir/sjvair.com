"""
Headless smoke test for the Pesticides Explorer's section map.

Loads explorer pages in headless Chrome, waits for the map to come up, runs
a set of checks against the live map (layers, controls, the grid and its
legend, the lens and its popups, "all sections", an htmx year change that
must keep the same map instance, expand/collapse) and reports a table per
page. Exits 1 on any failed check, a console error, or a map that never
loads. Dev-only; nothing here runs in CI.

Setup (Chrome must be installed: `google-chrome-stable` on the PATH):

    python3 -m venv .venv && .venv/bin/pip install selenium

Usage:

    .venv/bin/python scripts/pesticides_map_smoke.py --base http://localhost:8002 --gl \\
        /tools/pesticides/map/ /tools/pesticides/region/hez8v/fresno/ \\
        "/tools/pesticides/region/hez8v/fresno/?sections=1"

    --gl            append `gl=1` to each page URL (the MapTiler SDK map, while
                    it lives beside the Leaflet one)
    --screenshots   a directory to save a screenshot per page into
    --year YEAR     the year the scope bar is switched to (default 2022)

Every check on a page runs even after one fails, except that a map which
never loads skips the checks that need it. Checks that need a particular
state (the township grid for the township popup, `?sections=1` for "all
sections", a lens for the lens popup) report themselves skipped on pages
without it. The lens check moves the map to zoom 9 (township level), so
the checks after it start there.

Each page gets a fresh browser: the explorer's static files aren't
cache-busted, so a reused profile could serve a stale script.

Later tasks extend this with more checks: add a `check_*` function that takes
the `Page` and returns a (passed, detail) tuple, and list it in CHECKS.
"""
import argparse
import re
import sys
import time
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

MAP_TIMEOUT = 40
SWAP_TIMEOUT = 20
GRID_TIMEOUT = 30
ALL_SECTIONS_TIMEOUT = 120
# The lens must be up this long after the hover (a 50 ms rest plus one
# sections request).
LENS_TIMEOUT = 1.5

# The map instance, whichever module owns it: the SDK module while it lives
# beside the Leaflet one, the renamed module after the flip.
JS_INSTANCE = """
var mod = window.PesticidesSectionMapGL || window.PesticidesSectionMap;
if (!mod || typeof mod.instances !== 'function') return null;
var list = mod.instances();
return list && list.length ? list[0] : null;
"""

JS_MAP_LOADED = """
var inst = (function () { %s })();
return !!(inst && inst.map && inst.loaded && inst.map.loaded());
""" % JS_INSTANCE

# The grid for the current view is on the map (at `arguments[0]`'s level
# when given), no grid load is in flight (the status line is clear), and
# the camera has settled.
JS_GRID_LOADED = """
var inst = (function () { %s })();
if (!inst || !inst.loadedLevel || !inst.sourceData.grid || !inst.sourceData.grid.features.length) return false;
if (arguments[0] && inst.loadedLevel !== arguments[0]) return false;
if (/^Loading (grid|sections)…$/.test(document.querySelector('.section-map-status').textContent)) return false;
return !inst.map.isMoving();
""" % JS_INSTANCE

# Among `features` (an expression on `inst`), the one with data nearest the
# map's centre (farthest, with `farthest`) whose bounds centre lands on bare
# canvas (not under the toolbar or a panel) and actually on the feature (an
# irregular edge township's bounds centre can fall outside it), as an
# offset from the container's centre for a pointer action.
def js_pick(features_expr, farthest=False):
    return """
function bboxOf(f) {
  if (f.bbox) return f.bbox;
  var b = [Infinity, Infinity, -Infinity, -Infinity];
  (function walk(c) {
    if (typeof c[0] === 'number') { b[0] = Math.min(b[0], c[0]); b[1] = Math.min(b[1], c[1]); b[2] = Math.max(b[2], c[0]); b[3] = Math.max(b[3], c[1]); }
    else c.forEach(walk);
  })(f.geometry.coordinates);
  return b;
}
var canvas = inst.map.getCanvas();
var rect = canvas.getBoundingClientRect();
var fills = ['grid-fill', 'lens-fill', 'all-sections-fill'].filter(function (l) { return inst.map.getLayer(l); });
var best = null;
(%s).forEach(function (f) {
  if (!(f.properties.value > 0) || !f.geometry) return;
  var b = bboxOf(f);
  var p = inst.map.project([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]);
  if (p.x < 0 || p.y < 0 || p.x > rect.width || p.y > rect.height) return;
  if (document.elementFromPoint(rect.left + p.x, rect.top + p.y) !== canvas) return;
  if (!inst.map.queryRenderedFeatures(p, { layers: fills }).some(function (r) { return r.id === f.properties.id; })) return;
  var d = Math.hypot(p.x - rect.width / 2, p.y - rect.height / 2);
  if (!best || (%s)) best = { id: f.properties.id, dx: p.x - rect.width / 2, dy: p.y - rect.height / 2, d: d };
});
return best;
""" % (features_expr, 'd > best.d' if farthest else 'd < best.d')

POPUP = '.maplibregl-popup.section-popup-wrap .section-popup'
LEGEND_ROWS = ".section-map-legend li:not(.is-marker)"


def browser():
    opts = Options()
    opts.add_argument('--headless=new')
    opts.add_argument('--window-size=1400,1000')
    # Software WebGL: the SDK map needs a GL context and headless has no GPU.
    opts.add_argument('--enable-unsafe-swiftshader')
    opts.add_argument('--ignore-gpu-blocklist')
    opts.add_argument('--disable-application-cache')
    opts.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    return webdriver.Chrome(options=opts)


class Page:
    """One loaded page: the driver plus helpers the checks share."""

    def __init__(self, driver, url):
        self.driver = driver
        self.url = url
        parsed = urlparse(url)
        self.origin = '%s://%s' % (parsed.scheme, parsed.netloc)
        self.timings = {}
        self.errors = []

    def js(self, script, *args):
        return self.driver.execute_script(script, *args)

    def instance_js(self, expr, *args):
        """Evaluate `expr` with `inst` bound to the live map instance."""
        return self.js('var inst = (function () { %s })(); if (!inst) return null; %s' % (JS_INSTANCE, expr), *args)

    def wait_for(self, script, timeout, *args):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.js(script, *args):
                return True
            time.sleep(0.2)
        return False

    def wait_for_map(self, timeout=MAP_TIMEOUT):
        started = time.time()
        ok = self.wait_for(JS_MAP_LOADED, timeout)
        self.timings['map_loaded_s'] = round(time.time() - started, 2)
        return ok

    def wait_idle(self, timeout=20):
        """Wait for the map to finish rendering (sources loaded, no pending tiles)."""
        return self.wait_for('var inst = (function () { %s })(); return !!(inst && inst.map && inst.map.loaded() && !inst.map.isMoving());' % JS_INSTANCE, timeout)

    def wait_grid(self, level=None, timeout=GRID_TIMEOUT):
        """Wait for the grid (at `level`, if given) to be on the map; seconds taken."""
        started = time.time()
        ok = self.wait_for(JS_GRID_LOADED, timeout, level)
        return ok, round(time.time() - started, 2)

    def console_errors(self):
        noise = ('favicon', 'DevTools')
        entries = []
        for entry in self.driver.get_log('browser'):
            if entry['level'] != 'SEVERE':
                continue
            message = entry['message']
            if any(word in message for word in noise):
                continue
            # A third-party script or font that didn't load (offline, a
            # blocked CDN) isn't the map's doing; a resource on the page's
            # own origin failing is. The message starts with the URL.
            if 'Failed to load resource' in message and not message.startswith(self.origin + '/'):
                continue
            entries.append(message[:300])
        self.errors.extend(entries)
        return entries

    def container(self):
        return self.driver.find_element(By.CSS_SELECTOR, '.section-map')

    def scroll_to_map(self):
        el = self.container()
        self.js("arguments[0].scrollIntoView({block: 'center'})", el)
        time.sleep(0.3)
        return el

    # Pointer actions relative to the map container's centre. The pointer
    # move is animated by default (a sweep across the map, as a reader's);
    # `instant` lands it in one step, so a timing starts at the arrival.
    def hover_map(self, dx=0, dy=0, settle=1.5, instant=False):
        el = self.scroll_to_map()
        ActionChains(self.driver, duration=0 if instant else 250).move_to_element_with_offset(el, dx, dy).perform()
        time.sleep(settle)

    def click_map(self, dx=0, dy=0, settle=1.5, instant=False):
        el = self.scroll_to_map()
        ActionChains(self.driver, duration=0 if instant else 250).move_to_element_with_offset(el, dx, dy).click().perform()
        time.sleep(settle)

    def press_escape(self):
        """Escape, sent to the map canvas (focused, as after a click on it)."""
        self.driver.find_element(By.CSS_SELECTOR, '.section-map canvas.maplibregl-canvas').send_keys(Keys.ESCAPE)

    def wait_lens(self, township_id=None, timeout=LENS_TIMEOUT):
        """Wait for the lens (around `township_id`, if given) to be drawn;
        seconds taken."""
        started = time.time()
        ok = self.wait_for("""
            var inst = (function () { %s })();
            if (!inst || !inst.lensFeatures.length) return false;
            return !arguments[0] || inst.lensId === arguments[0];
        """ % JS_INSTANCE, timeout, township_id)
        return ok, round(time.time() - started, 2)

    def wait_prefetch(self, township_id, timeout=10):
        """Wait for the ring around `township_id` (the 5x5 block) to be cached
        and no prefetch to be in flight."""
        return self.wait_for("""
            var inst = (function () { %s })();
            if (!inst || inst.prefetching) return false;
            return !inst.uncached(inst.neighborhoodOf(arguments[0], 2.5).map(function (h) { return h.properties.id; })).length;
        """ % JS_INSTANCE, timeout, township_id)

    def sections_requests(self):
        return [r for r in self.grid_requests() if r[0] == 'sections']

    def pick(self, features_expr, farthest=False):
        """A clickable feature with data (see js_pick), or None."""
        self.scroll_to_map()
        return self.instance_js(js_pick(features_expr, farthest))

    def hover_stamped(self, dx, dy):
        """An instant pointer move, with the moment the map saw it stamped
        in the page (`window.__hoverAt`, Date.now) so a draw that records
        its own time can be measured against it."""
        el = self.scroll_to_map()
        self.js('window.__hoverAt = null')
        # A capture listener on the canvas container runs before the SDK's
        # own handlers, so the stamp precedes a draw made in the same event.
        # One listener at a time: a previous one that never fired (a move
        # that landed where the pointer already was) is removed first.
        self.instance_js("""
            var container = inst.map.getCanvasContainer();
            if (window.__hoverListener) container.removeEventListener('mousemove', window.__hoverListener, true);
            window.__hoverListener = function () {
                window.__hoverAt = Date.now();
                container.removeEventListener('mousemove', window.__hoverListener, true);
                window.__hoverListener = null;
            };
            container.addEventListener('mousemove', window.__hoverListener, true);
        """)
        ActionChains(self.driver, duration=0).move_to_element_with_offset(el, dx, dy).perform()

    def lens_latency_ms(self):
        """Milliseconds from the stamped hover to the lens draw, or None."""
        return self.instance_js('return window.__hoverAt && inst.lensDrawnAt >= window.__hoverAt ? inst.lensDrawnAt - window.__hoverAt : null')

    def set_control(self, selector, value):
        """Set an Options control (a select or a radio) and fire its change."""
        self.js("""
            var el = document.querySelector(arguments[0]);
            if (el.type === 'radio' || el.type === 'checkbox') { el.checked = arguments[1]; } else { el.value = arguments[1]; }
            el.dispatchEvent(new Event('change', {bubbles: true}));
        """, selector, value)
        time.sleep(0.6)

    def popup_text(self):
        return self.js("var el = document.querySelector(arguments[0]); return el ? el.innerText : null;", POPUP)

    def legend_rows(self):
        return self.js("return document.querySelectorAll(arguments[0]).length", LEGEND_ROWS)

    def grid_requests(self):
        """The grid endpoints' requests so far (Performance API): kind, duration
        in ms, and when the response landed in seconds after navigation; a
        values-only township refetch (geometry=0) is marked."""
        return self.js("""
            return performance.getEntriesByType('resource')
                .filter(function (r) { return /\\/pesticides\\/(sections|townships)\\/\\?/.test(r.name); })
                .map(function (r) { return [(r.name.indexOf('townships') !== -1 ? 'townships' : 'sections') + (r.name.indexOf('geometry=0') !== -1 ? '(values)' : ''), Math.round(r.duration), Math.round(r.responseEnd) / 1000]; });
        """)

    def maptiler_sessions(self):
        return self.js("""
            var ids = {};
            performance.getEntriesByType('resource').forEach(function (r) {
                if (r.name.indexOf('api.maptiler.com') === -1) return;
                var m = /[?&]mtsid=([^&]+)/.exec(r.name);
                if (m) ids[m[1]] = true;
            });
            return Object.keys(ids);
        """)


# --- checks: each takes a Page and returns (passed, detail) ---

def check_map_loaded(page):
    if not page.wait_for_map():
        return False, 'map never reported loaded'
    return True, '%ss' % page.timings['map_loaded_s']


def check_layers(page):
    """Every layer is in the style, under the basemap's labels, in the
    expected paint order (grid under the county lines, county lines under
    the page outline); the county outlines have data; the outline/radius
    layers carry data when the page asks for them."""
    result = page.instance_js("""
        var map = inst.map;
        var layers = map.getStyle().layers.map(function (l) { return l.id; });
        var firstSymbol = -1;
        map.getStyle().layers.some(function (l, i) { if (l.type === 'symbol') { firstSymbol = i; return true; } });
        var mine = ['radius-fill', 'radius-line', 'grid-fill', 'grid-line', 'all-sections-fill', 'all-sections-line',
                    'lens-fill', 'lens-line', 'lens-outline',
                    'selected-line', 'highlight-line', 'counties-line', 'outline-fill', 'outline-line', 'locate-circle'];
        var missing = mine.filter(function (id) { return layers.indexOf(id) === -1; });
        var aboveLabels = mine.filter(function (id) { return firstSymbol !== -1 && layers.indexOf(id) > firstSymbol; });
        var order = mine.filter(function (id) { return layers.indexOf(id) !== -1; }).map(function (id) { return layers.indexOf(id); });
        var inOrder = order.every(function (i, n) { return n === 0 || i > order[n - 1]; });
        var counts = {};
        ['counties', 'outline', 'radius'].forEach(function (id) {
            var d = inst.sourceData[id];
            counts[id] = d ? (d.features ? d.features.length : (d.geometry ? 1 : 0)) : 0;
        });
        return { missing: missing, aboveLabels: aboveLabels, inOrder: inOrder, counts: counts,
                 wantsOutline: !!inst.data.outlineUrl, wantsRadius: !!inst.data.radius };
    """)
    if result is None:
        return False, 'no instance'
    problems = []
    if result['missing']:
        problems.append('missing layers %s' % result['missing'])
    if result['aboveLabels']:
        problems.append('layers above labels %s' % result['aboveLabels'])
    if not result['inOrder']:
        problems.append('layers out of paint order')
    if not result['counts']['counties']:
        problems.append('counties source empty')
    if result['wantsOutline'] and not result['counts']['outline']:
        problems.append('outline source empty')
    if result['wantsRadius'] and not result['counts']['radius']:
        problems.append('radius source empty')
    detail = 'counties=%(counties)s outline=%(outline)s radius=%(radius)s' % result['counts']
    return (not problems), (detail if not problems else '; '.join(problems))


def check_controls(page):
    """Zoom, locate and reset controls (stacked in that order), the toolbar
    and legend panel are shown. The SDK can add its buttons a beat after the
    map reports loaded, so they are waited for rather than queried once."""
    if not page.wait_for("return !!document.querySelector('.maplibregl-ctrl-zoom-in')", 10):
        return False, 'zoom buttons never appeared'
    result = page.js("""
        var wrap = document.querySelector('.section-map-wrap');
        var q = function (sel) { return !!document.querySelector(sel); };
        var top = function (sel) { var el = document.querySelector(sel); return el ? el.getBoundingClientRect().top : NaN; };
        var locate = document.querySelector('.section-map-locate a');
        var reset = document.querySelector('.section-map-reset a');
        return {
            zoom: q('.maplibregl-ctrl-zoom-in') && q('.maplibregl-ctrl-zoom-out'),
            'no compass': !q('.maplibregl-ctrl-compass'),
            locate: !!locate && locate.getAttribute('aria-label') === 'Zoom to my location',
            reset: !!reset && reset.getAttribute('aria-label') === 'Zoom out to the whole map',
            'zoom above locate above reset': top('.maplibregl-ctrl-zoom-in') < top('.section-map-locate') && top('.section-map-locate') < top('.section-map-reset'),
            toolbar: !!wrap && !wrap.querySelector('.section-map-toolbar').hidden,
            legend: !!wrap && !wrap.querySelector('.section-map-legend-panel').hidden,
            expand: !!wrap && !!wrap.querySelector('.section-map-expand[data-bound]'),
        };
    """)
    missing = [key for key, ok in result.items() if not ok]
    return (not missing), ('all present, in order' if not missing else 'missing: %s' % ', '.join(missing))


def check_fit(page):
    """A county page frames its county; a valley page frames the counties;
    an outline page sits inside its outline's bounds; nothing is left at the
    placeholder view unless that's what the page asked for."""
    result = page.instance_js("""
        var b = inst.map.getBounds();
        return { west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth(),
                 zoom: inst.map.getZoom(), fit: inst.data.fit, county: inst.data.county,
                 countyFitted: !!inst.countyFitted, valleyFitted: !!inst.valleyFitted,
                 hasValley: !!inst.valleyBounds };
    """)
    if result is None:
        return False, 'no instance'
    if result['county'] and not result['countyFitted']:
        return False, 'county page did not fit its county'
    if result['fit'] == 'valley' and not result['valleyFitted']:
        return False, 'valley page did not fit the counties'
    return True, 'zoom %.2f, county=%s valley=%s' % (result['zoom'], result['countyFitted'], result['valleyFitted'])


def check_grid(page):
    """The grid for the view is on the map at the level the zoom calls for,
    every feature classed (fill/opacity written), the legend showing one
    row per non-empty class plus "No data", the level note set, and the
    page's own section (data-highlight) outlined when there is one."""
    ok, secs = page.wait_grid()
    if not ok:
        return False, 'grid never loaded'
    requests = page.grid_requests()
    # When the first grid response landed, from navigation.
    page.timings['grid_at_s'] = requests[0][2] if requests else secs
    result = page.instance_js("""
        var features = inst.sourceData.grid.features;
        return {
            level: inst.level, expected: inst.atSectionZoom() ? 'section' : 'township', zoom: inst.map.getZoom(),
            count: features.length,
            unclassed: features.filter(function (f) { return f.properties.fill === undefined || f.properties.opacity === undefined; }).length,
            classes: inst.currentClasses.members.filter(function (m) { return m.length; }).length,
            rows: document.querySelectorAll(arguments[0]).length,
            levelText: document.querySelector('.section-map-level').textContent,
            status: document.querySelector('.section-map-status').textContent,
            highlight: inst.data.highlight || '',
            highlighted: inst.sourceData.highlight && inst.sourceData.highlight.properties ? inst.sourceData.highlight.properties.id : '',
        };
    """, LEGEND_ROWS)
    problems = []
    if result['level'] != result['expected']:
        problems.append('level %s at zoom %.2f (expected %s)' % (result['level'], result['zoom'], result['expected']))
    if result['unclassed']:
        problems.append('%d features unclassed' % result['unclassed'])
    if result['rows'] != result['classes'] + 1:
        problems.append('%d legend rows for %d classes' % (result['rows'], result['classes']))
    if not result['levelText']:
        problems.append('no level note')
    # "All sections" reports its block progress on the same line; that isn't a grid load.
    if result['status'] and not re.match(r'^Loading sections… \d+ of \d+$', result['status']):
        problems.append('status left at %r' % result['status'])
    if result['level'] == 'section' and result['highlight'] and result['highlighted'] != result['highlight']:
        problems.append('highlight %s not outlined' % result['highlight'])
    detail = '%s %d features, %d classes, %d rows; requests %s' % (
        result['level'], result['count'], result['classes'], result['rows'],
        ' '.join('%s=%dms' % (kind, ms) for kind, ms, _ in requests) or 'none')
    return (not problems), (detail if not problems else '; '.join(problems))


def check_legend_options(page):
    """The bins and ramp selects reclass the grid live: bins=4 gives four
    classes (plus "No data"), the ramp changes the swatch colours, both
    land in the URL and leave it when set back to the defaults."""
    problems = []
    swatch_before = page.js("return document.querySelector('.section-map-legend .swatch').style.backgroundColor")
    page.set_control('select[name="bins"]', '4')
    rows = page.legend_rows()
    classes = page.instance_js("return inst.currentClasses.members.filter(function (m) { return m.length; }).length")
    if classes > 4 or rows != classes + 1:
        problems.append('bins=4 gave %d classes, %d rows' % (classes, rows))
    page.set_control('select[name="ramp"]', 'purd')
    swatch_after = page.js("return document.querySelector('.section-map-legend .swatch').style.backgroundColor")
    if swatch_after == swatch_before:
        problems.append('ramp change left the swatches at %s' % swatch_before)
    fill_matches = page.instance_js("""
        var f = inst.sourceData.grid.features.filter(function (f) { return f.properties.value > 0; })[0];
        return !!f && inst.currentClasses.colors.indexOf(f.properties.fill) !== -1;
    """)
    if not fill_matches:
        problems.append('a feature fill is not one of the new class colours')
    url = page.driver.current_url
    if 'bins=4' not in url or 'ramp=purd' not in url:
        problems.append('URL missing bins/ramp: %s' % url)
    page.set_control('select[name="bins"]', '6')
    page.set_control('select[name="ramp"]', 'blues')
    url = page.driver.current_url
    if 'bins=' in url or 'ramp=' in url:
        problems.append('URL kept bins/ramp after reset: %s' % url)
    return (not problems), ('bins=4 -> %d rows; %s -> %s' % (rows, swatch_before, swatch_after) if not problems else '; '.join(problems))


def check_lens(page):
    """At the township zoom (the map is moved to zoom 9), hovering a
    township brings up the lens within LENS_TIMEOUT: its neighbourhood's
    sections in the `lens` source, classed, the hovered township's outline
    in the `lens-outline` source, the hosts' fills stepped aside. Once the
    ring beyond it is prefetched, moving one township over draws from the
    cache: at most one new sections request (the next ring). Under "all
    sections" the lens stays off."""
    if page.instance_js('return inst.showAllSections'):
        if page.instance_js('return inst.level') != 'township':
            return None, 'section level (skipped)'
        target = page.pick('inst.sourceData.grid.features')
        if not target:
            return False, 'no township with data on bare canvas to hover'
        page.hover_map(target['dx'], target['dy'], settle=0.6, instant=True)
        state = page.instance_js("return { lensId: inst.lensId, features: inst.lensFeatures.length, source: (inst.sourceData.lens || {features: []}).features.length };")
        if state['lensId'] or state['features'] or state['source']:
            return False, 'lens drawn under all sections: %s' % state
        return True, 'inactive under all sections (township %s hovered)' % target['id']

    page.instance_js("inst.map.jumpTo({ center: inst.map.getCenter(), zoom: 9 });")
    ok, _ = page.wait_grid('township')
    if not ok:
        return False, 'township grid never loaded at zoom 9'
    target = page.pick('inst.sourceData.grid.features')
    if not target:
        return False, 'no township with data on bare canvas to hover'
    problems = []
    requests_before = len(page.sections_requests())
    # The draw is timed from the hover the map saw (the poll below only
    # sees 0.2 s steps).
    page.hover_stamped(target['dx'], target['dy'])
    drawn, secs = page.wait_lens(target['id'])
    if not drawn:
        state = page.instance_js("""
            return { hovered: !!window.__hoverAt, lensId: inst.lensId, hosts: inst.lensHosts ? inst.lensHosts.length : null,
                     uncached: inst.lensHosts ? inst.uncached(inst.lensHosts.map(function (h) { return h.properties.id; })).length : null,
                     features: inst.lensFeatures.length, fetchPending: !!inst.lensFetchTimer };
        """)
        return False, 'lens not drawn within %ss of hovering %s: %s, requests since %s' % (
            LENS_TIMEOUT, target['id'], state, page.sections_requests()[requests_before:])
    page.timings['lens_ms'] = page.lens_latency_ms()
    result = page.instance_js("""
        var hosts = inst.lensHosts || [];
        var outline = inst.sourceData['lens-outline'];
        return {
            hosts: hosts.length,
            features: inst.lensFeatures.length,
            unclassed: inst.lensFeatures.filter(function (f) { return f.properties.fill === undefined; }).length,
            classes: inst.lensClasses.members.filter(function (m) { return m.length; }).length,
            outline: outline && outline.properties ? outline.properties.id : null,
            hostsDimmed: hosts.filter(function (h) { return inst.map.getFeatureState({ source: 'grid', id: h.properties.id }).lensHost === true; }).length,
            rendered: inst.map.queryRenderedFeatures({ layers: ['lens-fill'] }).length,
        };
    """)
    if result['hosts'] < 4:
        problems.append('only %d hosts in the neighbourhood' % result['hosts'])
    if result['unclassed']:
        problems.append('%d lens sections unclassed' % result['unclassed'])
    if result['outline'] != target['id']:
        problems.append('lens outline holds %s, hovered %s' % (result['outline'], target['id']))
    if result['hostsDimmed'] != result['hosts']:
        problems.append('%d of %d hosts dimmed' % (result['hostsDimmed'], result['hosts']))
    if not page.wait_for("var inst = (function () { %s })(); return !!inst && inst.map.queryRenderedFeatures({ layers: ['lens-fill'] }).length > 0;" % JS_INSTANCE, 5):
        problems.append('no lens features rendered')
    first_requests = page.sections_requests()[requests_before:]
    # The ring prefetch (5x5 minus the 3x3) lands in idle time; wait for it,
    # then the neighbour's own 3x3 is entirely cached.
    if not page.wait_prefetch(target['id']):
        problems.append('ring prefetch never completed')
    neighbour = page.pick("inst.neighborhoodOf(%s).filter(function (f) { return f.properties.id !== %s; })" % (repr(target['id']), repr(target['id'])))
    if not neighbour:
        problems.append('no neighbouring township with data on bare canvas')
        return False, '; '.join(problems)
    requests_before = len(page.sections_requests())
    page.hover_stamped(neighbour['dx'], neighbour['dy'])
    moved, _ = page.wait_lens(neighbour['id'])
    if not moved:
        problems.append('lens did not move to neighbour %s within %ss' % (neighbour['id'], LENS_TIMEOUT))
    page.timings['lens_move_ms'] = page.lens_latency_ms()
    # The prefetch around the new centre may add one request (its ring).
    time.sleep(0.7)
    page.wait_prefetch(neighbour['id'])
    new_requests = page.sections_requests()[requests_before:]
    if len(new_requests) > 1:
        problems.append('%d sections requests to move one township over' % len(new_requests))
    # From a lens section straight onto a township beyond the prefetched
    # 5x5 (uncached) in one move, then resting there: the lens must follow
    # and stay (the lens section's mouseleave, which runs after the grid
    # handler recentres, must not clear the new lens).
    on_section = page.instance_js('return inst.hoverIds.lens != null')
    outside = page.pick("""(function () {
        var ring = {};
        inst.neighborhoodOf(inst.lensId, 2.5).forEach(function (h) { ring[h.properties.id] = true; });
        return inst.gridFeatures.filter(function (f) { return !ring[f.properties.id] && !inst.lensCache[f.properties.id]; });
    })()""", farthest=True)
    if not outside:
        problems.append('no uncached township outside the 5x5 on bare canvas')
    else:
        page.hover_stamped(outside['dx'], outside['dy'])
        followed, _ = page.wait_lens(outside['id'])
        time.sleep(0.5)
        rested = page.instance_js('return { lensId: inst.lensId, features: inst.lensFeatures.length }')
        if not followed or rested['lensId'] != outside['id'] or not rested['features']:
            problems.append('lens did not survive a move from a %s to %s outside the block: followed=%s, after 0.5 s %s' % (
                'lens section' if on_section else 'township gap', outside['id'], followed, rested))
    detail = 'township %s: %d hosts, %d sections (%d classes) drawn %sms after the hover (request %s); -> %s drawn after %sms with %d new request(s); -> %s outside the block from a %s, kept' % (
        target['id'], result['hosts'], result['features'], result['classes'], page.timings['lens_ms'],
        ' '.join('%dms' % ms for _, ms, _ in first_requests) or 'cached',
        neighbour['id'], page.timings['lens_move_ms'], len(new_requests),
        outside['id'] if outside else '?', 'lens section' if on_section else 'township gap')
    return (not problems), (detail if not problems else '; '.join(problems))


def check_lens_popup(page):
    """Clicking a lens section opens the section popup (with the "Zoom in"
    button, since the township popup is unreachable under the lens),
    selects and outlines it, and pins the lens: the pointer moving to
    another township leaves the lens and its popup in place. Escape closes
    the popup, which releases the lens: the next township hovered gets its
    own."""
    if not page.instance_js('return inst.lensFeatures.length'):
        return None, 'no lens up (skipped)'
    lens_id = page.instance_js('return inst.lensId')
    # A section of the lens's own township: the pointer arriving on a
    # neighbour's section would recentre the lens there first (by design).
    target = page.pick("inst.lensFeatures.filter(function (f) { var m = f.properties.mtrs || ''; return m.slice(0, m.lastIndexOf('-')) === inst.lensId; })")
    if not target:
        return False, 'no section of township %s with data on bare canvas to click' % lens_id
    page.click_map(target['dx'], target['dy'], settle=0.3, instant=True)
    filled = page.wait_for("""
        var el = document.querySelector(arguments[0]);
        return !!el && el.innerText.indexOf('Loading') === -1 && !!el.querySelector('.section-popup-chems li, .section-popup-note');
    """, 15, POPUP)
    problems = []
    if not filled:
        problems.append('popup never filled in')
    result = page.instance_js("""
        var el = document.querySelector(arguments[0]);
        return {
            text: el ? el.innerText : '',
            zoomIn: !!(el && el.querySelector('.section-map-zoom[data-id]')),
            openLensId: inst.openLensId, popupKey: inst.popupKey, selected: inst.selectedSectionId,
            outline: inst.sourceData.selected && inst.sourceData.selected.properties ? inst.sourceData.selected.properties.id : null,
            lensId: inst.lensId,
        };
    """, POPUP)
    if 'Square-mile section' not in result['text']:
        problems.append('popup text %r' % result['text'][:120])
    if not result['zoomIn']:
        problems.append('no "Zoom in" button on the lens section popup')
    if result['openLensId'] != target['id'] or result['popupKey'] != 'openLensId':
        problems.append('popup not tracked as the lens popup: %s' % {k: result[k] for k in ('openLensId', 'popupKey')})
    if result['selected'] != target['id'] or result['outline'] != target['id']:
        problems.append('selection state %s for %s' % ({k: result[k] for k in ('selected', 'outline')}, target['id']))
    if result['lensId'] != lens_id:
        problems.append('lens moved from %s to %s on the click' % (lens_id, result['lensId']))
    # Away to the township with data farthest from the centre (the lens's
    # own township excluded) that lands on bare canvas.
    far = page.pick("inst.gridFeatures.filter(function (f) { return f.properties.id !== inst.lensId; })", farthest=True)
    if not far:
        problems.append('no other township on bare canvas to move to')
        return False, '; '.join(problems)
    page.hover_map(far['dx'], far['dy'], settle=0.5, instant=True)
    pinned = page.instance_js("return { lensId: inst.lensId, features: inst.lensFeatures.length, popup: !!inst.popup && !!document.querySelector(arguments[0]) };", POPUP)
    if pinned['lensId'] != lens_id or not pinned['features'] or not pinned['popup']:
        problems.append('lens not pinned while its popup is open: %s' % pinned)
    page.press_escape()
    released = page.wait_for("""
        var inst = (function () { %s })();
        return !!inst && !inst.popup && !inst.openLensId && !inst.selectedSectionId && !document.querySelector(arguments[0]);
    """ % JS_INSTANCE, 3, POPUP)
    if not released:
        problems.append('Escape did not close the popup and release the lens: %s' % page.instance_js("return { popup: !!inst.popup, openLensId: inst.openLensId, selected: inst.selectedSectionId };"))
    # The lens follows the pointer again: a nudge over the far township
    # draws its lens (it may be uncached: a rest and a request).
    requests_before = len(page.sections_requests())
    page.hover_stamped(far['dx'] + 2, far['dy'] + 2)
    # What's under test here is the release, so a slow sections request
    # (the dev server has taken over a second at times) is allowed and the
    # latency is reported; the first hover in check_lens keeps the bound.
    moved, _ = page.wait_lens(far['id'], timeout=6)
    if not moved:
        state = page.instance_js("""
            return { lensId: inst.lensId, features: inst.lensFeatures.length, hosts: inst.lensHosts ? inst.lensHosts.length : null,
                     uncached: inst.lensHosts ? inst.uncached(inst.lensHosts.map(function (h) { return h.properties.id; })).length : null,
                     fetchPending: !!inst.lensFetchTimer, prefetching: inst.prefetching };
        """)
        problems.append('lens did not move to %s after the release: %s, requests since %s' % (far['id'], state, page.sections_requests()[requests_before:]))
    detail = 'section %s: popup pinned lens %s; Escape released it; -> %s drawn after %sms' % (target['id'], lens_id, far['id'], page.lens_latency_ms())
    return (not problems), (detail if not problems else '; '.join(problems))


def check_all_sections(page):
    """On a `?sections=1` page at the township zoom, every visible township's
    sections are drawn (well over a thousand at a county zoom), the township
    fills step aside, the legend takes the all-sections note, a ramp change
    reshades the drawn sections, and switching the mode off puts the
    township grid back and drops `sections` from the URL."""
    if not page.instance_js('return inst.showAllSections'):
        return None, 'not a ?sections=1 page (skipped)'
    if page.instance_js("return inst.level") != 'township':
        return None, 'section level (skipped)'
    done = page.wait_for("""
        var inst = (function () { %s })();
        if (!inst) return false;
        var run = inst.allSectionsRun;
        return !!(run && run.done === run.total && inst.allSectionsFeatures.length && document.querySelector('.section-map-status').textContent === '');
    """ % JS_INSTANCE, ALL_SECTIONS_TIMEOUT)
    if not done:
        return False, 'blocks never finished loading'
    # When the last block landed, from navigation.
    secs = max(landed for kind, _, landed in page.grid_requests() if kind == 'sections')
    page.timings['all_sections_at_s'] = secs
    result = page.instance_js("""
        return {
            blocks: inst.allSectionsRun.total,
            features: inst.allSectionsFeatures.length,
            unclassed: inst.allSectionsFeatures.filter(function (f) { return f.properties.fill === undefined; }).length,
            gridFill: inst.map.getPaintProperty('grid-fill', 'fill-opacity'),
            rendered: inst.map.queryRenderedFeatures({layers: ['all-sections-fill']}).length,
            levelText: document.querySelector('.section-map-level').textContent,
            rows: document.querySelectorAll(arguments[0]).length,
            classes: inst.currentClasses.members.filter(function (m) { return m.length; }).length,
        };
    """, LEGEND_ROWS)
    problems = []
    if result['features'] <= 1000:
        problems.append('only %d sections drawn' % result['features'])
    if result['unclassed']:
        problems.append('%d sections unclassed' % result['unclassed'])
    if result['gridFill'] != 0:
        problems.append('township fill not hidden (%s)' % result['gridFill'])
    if not result['rendered']:
        problems.append('no all-sections features rendered')
    if 'across every township' not in result['levelText']:
        problems.append('level note %r' % result['levelText'])
    if result['rows'] != result['classes'] + 1:
        problems.append('%d legend rows for %d classes' % (result['rows'], result['classes']))
    # A reshade (ramp change) reaches the drawn sections through the source
    # diff, which the SDK's worker applies and re-tiles; wait for it.
    page.set_control('select[name="ramp"]', 'purd')
    started = time.time()
    js_reshaded = """
        var rendered = inst.map.queryRenderedFeatures({layers: ['all-sections-fill']}).filter(function (f) { return f.properties.value > 0; });
        if (!rendered.length) return 'nothing rendered';
        var bad = rendered.filter(function (f) { var own = inst.allSectionsById[f.properties.id]; return !own || own.properties.fill !== f.properties.fill; });
        return bad.length ? bad.length + ' of ' + rendered.length + ' rendered fills stale' : 'ok';
    """
    deadline = time.time() + 15
    reshaded = page.instance_js(js_reshaded)
    while reshaded != 'ok' and time.time() < deadline:
        time.sleep(0.25)
        reshaded = page.instance_js(js_reshaded)
    reshade_s = round(time.time() - started, 2)
    if reshaded != 'ok':
        problems.append('ramp change: %s after %ss' % (reshaded, reshade_s))
    page.set_control('select[name="ramp"]', 'blues')
    # Off again: the township grid returns and the URL forgets the mode.
    page.set_control('input[name="sections"]', False)
    after = page.instance_js("""
        return { features: inst.allSectionsFeatures.length, gridFill: JSON.stringify(inst.map.getPaintProperty('grid-fill', 'fill-opacity')),
                 levelText: document.querySelector('.section-map-level').textContent, url: location.search };
    """)
    if after['features'] or after['gridFill'] == '0' or 'sections=' in after['url'] or 'across every township' in after['levelText']:
        problems.append('mode did not switch off cleanly: %s' % after)
    detail = '%d blocks, %d sections (%d rendered) in %ss; reshade visible after %ss' % (result['blocks'], result['features'], result['rendered'], secs, reshade_s)
    return (not problems), (detail if not problems else '; '.join(problems))


def check_style_swap(page):
    """The tiles select rebuilds the style; the grid and its data come back
    on the new style with the same paint."""
    before = page.instance_js("return inst.sourceData.grid.features.length")
    page.set_control('select[name="tiles"]', 'toner-v2')
    back = page.wait_for("""
        var inst = (function () { %s })();
        return !!(inst && inst.map.isStyleLoaded() && inst.map.getLayer('grid-fill') && inst.map.getLayer('counties-line')
                  && inst.map.querySourceFeatures('grid').length);
    """ % JS_INSTANCE, 20)
    if not back:
        return False, 'grid layers/data did not return after the style swap'
    result = page.instance_js("""
        return { style: inst.map.getStyle().name, url: location.search,
                 fill: JSON.stringify(inst.map.getPaintProperty('grid-fill', 'fill-opacity')),
                 features: inst.sourceData.grid.features.length };
    """)
    problems = []
    if 'tiles=toner-v2' not in result['url']:
        problems.append('URL missing tiles: %s' % result['url'])
    if result['features'] != before:
        problems.append('grid data changed across the swap (%s -> %s)' % (before, result['features']))
    page.set_control('select[name="tiles"]', page.instance_js('return inst.defaultTileStyle'))
    page.wait_for("var inst = (function () { %s })(); return !!(inst && inst.map.isStyleLoaded() && inst.map.getLayer('grid-fill'));" % JS_INSTANCE, 20)
    if 'tiles=' in page.driver.current_url:
        problems.append('URL kept tiles after reset')
    return (not problems), ('style %s, %d features kept' % (result['style'], result['features']) if not problems else '; '.join(problems))


def check_township_popup(page):
    """At the township zoom a click opens the township popup (name, section
    count, the metric headline that follows the metric toggle); its "Zoom in
    to sections" button reaches the section grid at the clicked spot."""
    if page.instance_js("return inst.level") != 'township':
        return None, 'section level (skipped)'
    target = page.pick('inst.sourceData.grid.features')
    if not target:
        return False, 'no township with data on bare canvas to click'
    # The township popup is reachable where the lens hasn't drawn (its
    # sections take the click otherwise): with the cache emptied an
    # uncached township waits out the 50 ms rest and a request, and an
    # instant move-and-click lands before either (a sweep in would let the
    # rest elapse over the township on the way).
    page.instance_js("inst.lensCache = {}; inst.clearLens();")
    page.click_map(target['dx'], target['dy'], settle=1.0, instant=True)
    text = page.popup_text() or ''
    problems = []
    if page.instance_js('return inst.openGridId') != target['id']:
        problems.append('openGridId is %s, clicked %s' % (page.instance_js('return inst.openGridId'), target['id']))
    if 'Township' not in text or 'lbs' not in text or 'Zoom in to sections' not in text:
        problems.append('popup text %r' % text[:120])
    page.set_control('input[name="metric"][value="applications"]', True)
    text_after = page.popup_text() or ''
    if 'application' not in text_after:
        problems.append('popup headline did not follow the metric: %r' % text_after[:120])
    page.set_control('input[name="metric"][value="lbs_chemical"]', True)
    started = time.time()
    page.js("document.querySelector('%s .section-map-zoom').click()" % POPUP)
    ok, secs = page.wait_grid('section', 40)
    if not ok:
        problems.append('section grid did not load after Zoom in')
    else:
        page.timings['zoom_in_s'] = round(time.time() - started, 2)
    if page.js("return !!document.querySelector(arguments[0])", POPUP):
        problems.append('township popup still open after Zoom in')
    zoom = page.instance_js('return [inst.map.getZoom(), inst.sectionZoom(), inst.sourceData.grid.features.length]')
    if zoom and zoom[0] < zoom[1]:
        problems.append('zoom %.2f is below sectionZoom %s' % (zoom[0], zoom[1]))
    detail = 'township %s; Zoom in -> %d sections at zoom %.2f in %ss' % (target['id'], zoom[2], zoom[0], page.timings.get('zoom_in_s', '?'))
    return (not problems), (detail if not problems else '; '.join(problems))


def check_section_popup(page):
    """At the section zoom a click opens the section popup, selects the
    section (outline source), and fills in the top chemicals with links."""
    ok, _ = page.wait_grid('section', 10)
    if not ok:
        return False, 'not at the section grid'
    target = page.pick('inst.sourceData.grid.features')
    if not target:
        return False, 'no section with data on bare canvas to click'
    page.click_map(target['dx'], target['dy'], settle=0.5)
    filled = page.wait_for("""
        var el = document.querySelector(arguments[0]);
        return !!el && el.innerText.indexOf('Loading') === -1 && !!el.querySelector('.section-popup-chems li, .section-popup-note');
    """, 15, POPUP)
    problems = []
    if not filled:
        problems.append('popup never filled in')
    result = page.instance_js("""
        var el = document.querySelector(arguments[0]);
        var chems = el ? Array.from(el.querySelectorAll('.section-popup-chems li')) : [];
        return {
            text: el ? el.innerText : '',
            selected: inst.selectedSectionId, openGridId: inst.openGridId,
            outline: inst.sourceData.selected && inst.sourceData.selected.properties ? inst.sourceData.selected.properties.id : null,
            chems: chems.length,
            linked: chems.filter(function (li) { return li.querySelector('a[href*="/chemicals/"]'); }).length,
            concern: chems.filter(function (li) { return li.querySelector('.is-of-concern'); }).length,
            details: !!(el && el.querySelector('.section-popup-action[href*="/sections/"]')),
        };
    """, POPUP)
    if 'Square-mile section' not in result['text']:
        problems.append('popup text %r' % result['text'][:120])
    if result['selected'] != target['id'] or result['outline'] != target['id'] or result['openGridId'] != target['id']:
        problems.append('selection state %s for %s' % ({k: result[k] for k in ('selected', 'outline', 'openGridId')}, target['id']))
    if not result['chems']:
        problems.append('no top chemicals listed')
    elif result['linked'] != result['chems']:
        problems.append('%d of %d chemicals linked' % (result['linked'], result['chems']))
    if not result['details']:
        problems.append('no "Section details" link')
    detail = 'section %s: %d chemicals (%d of concern), selected + outlined' % (target['id'], result['chems'], result['concern'])
    return (not problems), (detail if not problems else '; '.join(problems))


def check_selection_survives_metric(page):
    """With a section popup open, a metric change reclasses the grid but
    keeps the popup, the selection and its outline; `?metric=` follows."""
    before = page.instance_js("return inst.selectedSectionId")
    if not before:
        return False, 'no section selected'
    page.set_control('input[name="metric"][value="applications"]', True)
    result = page.instance_js("""
        return { selected: inst.selectedSectionId, popup: !!inst.popup && !!document.querySelector(arguments[0]),
                 outline: inst.sourceData.selected && inst.sourceData.selected.properties ? inst.sourceData.selected.properties.id : null,
                 unit: document.querySelector('.section-map-legend .range').textContent, url: location.search };
    """, POPUP)
    problems = []
    if result['selected'] != before or result['outline'] != before:
        problems.append('selection lost: %s' % result)
    if not result['popup']:
        problems.append('popup closed')
    if 'applications' not in result['unit']:
        problems.append('legend unit %r' % result['unit'])
    if 'metric=applications' not in result['url']:
        problems.append('URL missing metric: %s' % result['url'])
    page.set_control('input[name="metric"][value="lbs_chemical"]', True)
    if 'metric=' in page.driver.current_url:
        problems.append('URL kept metric after reset')
    return (not problems), ('selection %s kept, legend in %s' % (before, result['unit'].split(' ', 1)[-1]) if not problems else '; '.join(problems))


def check_year_swap(page, year):
    """Changing the year in the scope bar swaps the page over htmx; the map
    instance must survive it (adopted in place), the container carry the
    new year, and no new MapTiler session start."""
    link = page.js("""
        var links = document.querySelectorAll('.explorer-scope-picker[data-scope="year"] a[href*="year=%s"]');
        return links.length ? links[0].getAttribute('href') : null;
    """ % year)
    if not link:
        return True, 'no year picker on this page (skipped)'
    before = page.instance_js('return inst.el.id')
    page.js("window.__smokeInstance = (function () { %s })();" % JS_INSTANCE)
    sessions_before = set(page.maptiler_sessions())
    page.js('document.querySelector(\'.explorer-scope-picker[data-scope="year"] a[href*="year=%s"]\').click()' % year)
    swapped = page.wait_for("""
        var inst = (function () { %s })();
        return !!(inst && inst.data.year === '%s' && document.body.contains(inst.el));
    """ % (JS_INSTANCE, year), SWAP_TIMEOUT)
    if not swapped:
        return False, 'container never carried year=%s after the swap' % year
    same = page.js('var inst = (function () { %s })(); return inst === window.__smokeInstance;' % JS_INSTANCE)
    if not same:
        return False, 'a new map instance was created on the swap'
    canvases = page.js("return document.querySelectorAll('canvas.maplibregl-canvas').length")
    if canvases != 1:
        return False, '%d map canvases after the swap' % canvases
    page.wait_idle()
    ok, _ = page.wait_grid()
    if not ok:
        return False, 'grid did not reload after the swap'
    sessions_after = set(page.maptiler_sessions())
    new_sessions = sessions_after - sessions_before
    if sessions_before and new_sessions:
        return False, 'new MapTiler session after the swap: %s' % sorted(new_sessions)
    if year not in page.driver.current_url:
        return False, 'URL did not change: %s' % page.driver.current_url
    after = page.instance_js('return inst.el.id')
    return True, 'same instance (container %s -> %s), %d session(s)' % (before, after, len(sessions_after))


def check_expand(page):
    """Expand fills the viewport (html class, wrapper class, a wider canvas);
    collapse puts everything back."""
    page.scroll_to_map()
    width_before = page.instance_js('return inst.map.getCanvas().clientWidth')
    canvas_width_is = 'var inst = (function () { %s })(); return !!inst && inst.map.getCanvas().clientWidth === arguments[0];' % JS_INSTANCE
    canvas_width_not = 'var inst = (function () { %s })(); return !!inst && inst.map.getCanvas().clientWidth !== arguments[0];' % JS_INSTANCE
    page.js("document.querySelector('.section-map-expand').click()")
    page.wait_for(canvas_width_not, 10, width_before)
    expanded = page.js("""
        return {
            html: document.documentElement.classList.contains('section-map-expanded'),
            wrap: document.querySelector('.section-map-wrap').classList.contains('is-expanded'),
            pressed: document.querySelector('.section-map-expand').getAttribute('aria-pressed') === 'true',
            label: document.querySelector('.section-map-expand').getAttribute('aria-label'),
        };
    """)
    width_after = page.instance_js('return inst.map.getCanvas().clientWidth')
    problems = []
    if not (expanded['html'] and expanded['wrap'] and expanded['pressed']):
        problems.append('expanded state not applied: %s' % expanded)
    if expanded['label'] != 'Back to the page':
        problems.append('button label %r' % expanded['label'])
    if not (width_after and width_before and width_after > width_before):
        problems.append('canvas did not widen (%s -> %s)' % (width_before, width_after))
    page.js("document.querySelector('.section-map-expand').click()")
    page.wait_for(canvas_width_is, 10, width_before)
    collapsed = page.js("""
        return !document.documentElement.classList.contains('section-map-expanded')
            && !document.querySelector('.section-map-wrap').classList.contains('is-expanded')
            && document.querySelector('.section-map-expand').getAttribute('aria-pressed') === 'false';
    """)
    width_back = page.instance_js('return inst.map.getCanvas().clientWidth')
    if not collapsed:
        problems.append('expanded state not cleared')
    if width_back != width_before:
        problems.append('canvas width did not return (%s -> %s)' % (width_before, width_back))
    return (not problems), ('%s -> %s -> %s px' % (width_before, width_after, width_back) if not problems else '; '.join(problems))


def check_console(page):
    errors = page.console_errors()
    return (not errors), ('clean' if not errors else '\n      '.join(errors))


CHECKS = [
    ('map loaded', check_map_loaded),
    ('layers', check_layers),
    ('controls', check_controls),
    ('fit', check_fit),
    ('grid', check_grid),
    ('legend options', check_legend_options),
    ('lens', check_lens),
    ('lens popup', check_lens_popup),
    ('all sections', check_all_sections),
    ('style swap', check_style_swap),
    ('township popup', check_township_popup),
    ('section popup', check_section_popup),
    ('selection', check_selection_survives_metric),
    ('year swap', check_year_swap),
    ('expand', check_expand),
    ('console', check_console),
]


def run_page(base, path, gl, year, screenshots):
    url = base.rstrip('/') + path
    if gl:
        url += ('&' if '?' in url else '?') + 'gl=1'
    driver = browser()
    started = time.time()
    rows = []
    try:
        driver.get(url)
        page = Page(driver, url)
        page.timings['page_get_s'] = round(time.time() - started, 2)
        failed = False
        for name, check in CHECKS:
            if failed and name != 'console':
                rows.append((name, None, 'skipped'))
                continue
            try:
                if check is check_year_swap:
                    passed, detail = check(page, year)
                else:
                    passed, detail = check(page)
            except Exception as err:  # a broken page must still report
                passed, detail = False, 'raised %s: %s' % (type(err).__name__, err)
            rows.append((name, passed, detail))
            if not passed and name == 'map loaded':
                failed = True
        if screenshots:
            import os
            os.makedirs(screenshots, exist_ok=True)
            name = path.strip('/').replace('/', '_').replace('?', '_').replace('=', '-') or 'landing'
            page.scroll_to_map()
            driver.save_screenshot(os.path.join(screenshots, name + '.png'))
        return url, rows, page.timings
    finally:
        driver.quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('paths', nargs='+', help='page paths under --base, e.g. /tools/pesticides/map/')
    parser.add_argument('--base', default='http://localhost:8002')
    parser.add_argument('--gl', action='store_true', help='append gl=1 (the MapTiler SDK map)')
    parser.add_argument('--year', default='2022', help='year to switch the scope bar to')
    parser.add_argument('--screenshots', help='directory for a screenshot per page')
    args = parser.parse_args(argv)

    any_failed = False
    for path in args.paths:
        url, rows, timings = run_page(args.base, path, args.gl, args.year, args.screenshots)
        print('\n%s' % url)
        # Keys end in their unit: `_s` or `_ms`.
        print('  ' + ', '.join('%s %s%s' % (key.rsplit('_', 1)[0].replace('_', ' '), value, key.rsplit('_', 1)[1]) for key, value in timings.items()))
        for name, passed, detail in rows:
            status = 'PASS' if passed else ('SKIP' if passed is None else 'FAIL')
            print('  %-4s %-16s %s' % (status, name, detail))
            if passed is False:
                any_failed = True
    print()
    return 1 if any_failed else 0


if __name__ == '__main__':
    sys.exit(main())
