"""
Headless smoke test for the Pesticides Explorer's section map.

Loads explorer pages in headless Chrome, waits for the map to come up, runs
a set of checks against the live map (layers, controls, the grid and its
legend, the notice and school markers and their popups, the lens and its
popups, "all sections", a popup panned clear of the legend, an htmx year
change that must keep the same map instance and start one grid request,
expand/collapse, the phone layout) and reports a table per page. Exits 1 on
any failed check, a console error, or a map that never loads. Dev-only;
nothing here runs in CI.

Setup (Chrome must be installed: `google-chrome-stable` on the PATH):

    python3 -m venv .venv && .venv/bin/pip install selenium

Usage:

    .venv/bin/python scripts/pesticides_map_smoke.py --base http://localhost:8002 \\
        /tools/pesticides/map/ /tools/pesticides/region/hez8v/fresno/ \\
        "/tools/pesticides/region/hez8v/fresno/?sections=1"

    --screenshots   a directory to save a screenshot per page into (a desktop
                    one at the end of the desktop checks, and a `-phone` one
                    from the phone layout check)
    --year YEAR     the year the scope bar is switched to (default 2022)

Every check on a page runs even after one fails, except that a map which
never loads skips the checks that need it. Checks that need a particular
state (the township grid for the township popup, `?sections=1` for "all
sections", a lens for the lens popup, active notices or schools in view for
their popups) report themselves skipped on pages without it. The markers checks
leave the toggles as they found them. The lens check moves the map to zoom 9 (township level), so
the checks after it start there. The phone layout check reloads the page in a
phone-sized window and leaves it there, so it runs last.

Each page gets a fresh browser: the explorer's static files aren't
cache-busted, so a reused profile could serve a stale script.

Later tasks extend this with more checks: add a `check_*` function that takes
the `Page` and returns a (passed, detail) tuple, and list it in CHECKS.
"""
import argparse
import os
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
# The window the phone layout check reloads the page in.
PHONE_SIZE = (390, 844)
GRID_TIMEOUT = 30
ALL_SECTIONS_TIMEOUT = 120
# The lens must be up this long after the hover (a 50 ms rest plus one
# sections request).
LENS_TIMEOUT = 1.5

# The map instance (the module keeps one live map per page).
JS_INSTANCE = """
var mod = window.PesticidesSectionMap;
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
if (/^Loading (grid|sections)…$/.test(document.querySelector('.map-status').textContent)) return false;
return !inst.map.isMoving();
""" % JS_INSTANCE

# Among `features` (an expression on `inst`), the one with data nearest the
# map's centre (farthest, with `farthest`; nearest the canvas point `ref_expr`
# returns, as [x, y], when given) whose bounds centre lands on bare canvas
# (not under the toolbar or a panel) and actually on the feature (an
# irregular edge township's bounds centre can fall outside it), as an
# offset from the container's centre for a pointer action.
def js_pick(features_expr, farthest=False, ref_expr=None):
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
// A marker (or its wider hit disc) over the cell would take the click.
var markers = ['notices-circle', 'notices-hit', 'locations-circle', 'locations-hit'].filter(function (l) { return inst.map.getLayer(l); });
// Distances are measured from `ref` (the container's centre unless given).
var ref = (function () { %s })() || [rect.width / 2, rect.height / 2];
var best = null;
(%s).forEach(function (f) {
  if (!(f.properties.value > 0) || !f.geometry) return;
  var b = bboxOf(f);
  var p = inst.map.project([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]);
  if (p.x < 0 || p.y < 0 || p.x > rect.width || p.y > rect.height) return;
  if (document.elementFromPoint(rect.left + p.x, rect.top + p.y) !== canvas) return;
  if (!inst.map.queryRenderedFeatures(p, { layers: fills }).some(function (r) { return r.id === f.properties.id; })) return;
  if (inst.map.queryRenderedFeatures(p, { layers: markers }).length) return;
  var d = Math.hypot(p.x - ref[0], p.y - ref[1]);
  if (!best || (%s)) best = { id: f.properties.id, dx: p.x - rect.width / 2, dy: p.y - rect.height / 2, d: d };
});
return best;
""" % (ref_expr or 'return null;', features_expr, 'd > best.d' if farthest else 'd < best.d')

# Among the `source`'s point features, the one nearest the map's centre
# that is rendered on `layer` at a spot on bare canvas, as an offset from
# the container's centre.
def js_pick_point(source, layer):
    return """
var canvas = inst.map.getCanvas();
var rect = canvas.getBoundingClientRect();
var best = null;
((inst.sourceData[%r] || {}).features || []).forEach(function (f) {
  if (!f.geometry) return;
  var p = inst.map.project(f.geometry.coordinates);
  if (p.x < 0 || p.y < 0 || p.x > rect.width || p.y > rect.height) return;
  if (document.elementFromPoint(rect.left + p.x, rect.top + p.y) !== canvas) return;
  // The topmost marker at the spot is the one a click reaches.
  var under = inst.map.queryRenderedFeatures(p, { layers: [%r] });
  if (!under.length || under[0].id !== f.properties.id) return;
  var d = Math.hypot(p.x - rect.width / 2, p.y - rect.height / 2);
  if (!best || d < best.d) best = { id: f.properties.id, dx: p.x - rect.width / 2, dy: p.y - rect.height / 2, d: d };
});
return best;
""" % (source, layer)


POPUP = '.maplibregl-popup.section-popup-wrap .section-popup'
LOCATIONS_ZOOM_NOTE = 'Zoom in to see schools and child care.'
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

    def __init__(self, driver, url, screenshots=None, name=None):
        self.driver = driver
        self.url = url
        parsed = urlparse(url)
        self.origin = '%s://%s' % (parsed.scheme, parsed.netloc)
        self.screenshots = screenshots
        self.name = name
        self.timings = {}
        self.errors = []
        self.prepare()

    def prepare(self):
        """After a load: the Performance API buffer and the dev-only chrome."""
        # The checks count requests through the Performance API; the
        # default buffer (250 entries) fills with basemap tiles and glyphs
        # within seconds, after which new entries are dropped.
        self.js('performance.setResourceTimingBufferSize(20000)')
        # The Django Debug Toolbar (dev only) opens over a phone-sized
        # window; it isn't the page under test. Hidden, not removed: its own
        # script expects the element.
        self.js("var djdt = document.getElementById('djDebug'); if (djdt) djdt.style.display = 'none';")

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

    def wait_still(self, quiet=0.7, timeout=10):
        """Wait until the camera has been still for `quiet` seconds (a pan
        can follow another after a beat)."""
        deadline = time.time() + timeout
        still_since = None
        while time.time() < deadline:
            moving = self.instance_js('return inst.map.isMoving()')
            if moving:
                still_since = None
            elif still_since is None:
                still_since = time.time()
            elif time.time() - still_since >= quiet:
                return True
            time.sleep(0.1)
        return False

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

    def pick(self, features_expr, farthest=False, ref_expr=None):
        """A clickable feature with data (see js_pick), or None."""
        self.scroll_to_map()
        return self.instance_js(js_pick(features_expr, farthest, ref_expr))

    def rects(self):
        """The container, toolbar, legend panel and popup rects (viewport
        pixels; a missing element is None)."""
        return self.js("""
            var r = function (sel) { var el = document.querySelector(sel); if (!el || el.hidden) return null;
                var b = el.getBoundingClientRect(); return b.width && b.height ? { left: b.left, top: b.top, right: b.right, bottom: b.bottom } : null; };
            return { map: r('.section-map'), toolbar: r('.map-toolbar'), legend: r('.map-legend-panel'),
                     popup: r('.maplibregl-popup.section-popup-wrap') };
        """)

    def screenshot(self, suffix=''):
        """Save a screenshot as <name><suffix>.png into the screenshots
        directory, when one was given."""
        if not self.screenshots:
            return
        os.makedirs(self.screenshots, exist_ok=True)
        self.scroll_to_map()
        self.driver.save_screenshot(os.path.join(self.screenshots, self.name + suffix + '.png'))

    def pick_point(self, source, layer):
        """A clickable marker (see js_pick_point), or None."""
        self.scroll_to_map()
        return self.instance_js(js_pick_point(source, layer))

    def marker_legend(self):
        """The legend's marker rows' labels, in order."""
        return self.js("return Array.from(document.querySelectorAll('.section-map-legend li.is-marker .range')).map(function (el) { return el.textContent; })")

    def marker_requests(self, kind):
        """How many requests the notices or locations endpoint has had."""
        pattern = {'notices': r'/pesticides/notices/active/', 'locations': r'/pesticides/locations/'}[kind]
        return self.js("var needle = arguments[0]; return performance.getEntriesByType('resource').filter(function (r) { return r.name.indexOf(needle) !== -1; }).length", pattern)

    def source_count(self, source):
        return self.instance_js("var d = inst.sourceData[arguments[0]]; return d && d.features ? d.features.length : 0;", source)

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
    """Every layer is in the style, above every basemap layer, in the
    expected paint order (each layer's fill under its own stroke, the grid
    under the sections drawn over it, those under the outlines, and the
    markers last); the county outlines have data; the outline/radius
    layers carry data when the page asks for them."""
    result = page.instance_js("""
        var map = inst.map;
        var all = map.getStyle().layers;
        var layers = all.map(function (l) { return l.id; });
        var mineSet = {};
        var mine = ['radius-fill', 'radius-line', 'grid-fill', 'grid-line',
                    'all-sections-fill', 'all-sections-line', 'lens-fill', 'lens-line', 'lens-outline', 'outline-mask',
                    'selected-line', 'highlight-casing', 'highlight-line', 'counties-line',
                    'outline-fill', 'outline-casing', 'outline-line',
                    'locations-hit', 'locations-circle', 'notices-hit', 'notices-circle', 'locate-circle'];
        var missing = mine.filter(function (id) { return layers.indexOf(id) === -1; });
        mine.forEach(function (id) { mineSet[id] = true; });
        var lastBase = -1;
        layers.forEach(function (id, i) { if (!mineSet[id]) lastBase = i; });
        var underBasemap = mine.filter(function (id) {
            var i = layers.indexOf(id);
            return i !== -1 && i < lastBase;
        });
        var ordered = function (ids) {
            var order = ids.filter(function (id) { return layers.indexOf(id) !== -1; }).map(function (id) { return layers.indexOf(id); });
            return order.every(function (i, n) { return n === 0 || i > order[n - 1]; });
        };
        var counts = {};
        ['counties', 'outline', 'radius'].forEach(function (id) {
            var d = inst.sourceData[id];
            counts[id] = d ? (d.features ? d.features.length : (d.geometry ? 1 : 0)) : 0;
        });
        return { missing: missing, underBasemap: underBasemap, inOrder: ordered(mine), counts: counts, wantsOutline: !!inst.data.outlineUrl, wantsRadius: !!inst.data.radius };
    """)
    if result is None:
        return False, 'no instance'
    problems = []
    if result['missing']:
        problems.append('missing layers %s' % result['missing'])
    if result['underBasemap']:
        problems.append('layers under the basemap %s' % result['underBasemap'])
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
        var wrap = document.querySelector('.map-wrap');
        var q = function (sel) { return !!document.querySelector(sel); };
        var top = function (sel) { var el = document.querySelector(sel); return el ? el.getBoundingClientRect().top : NaN; };
        var locate = document.querySelector('.map-locate a');
        var reset = document.querySelector('.map-reset a');
        return {
            zoom: q('.maplibregl-ctrl-zoom-in') && q('.maplibregl-ctrl-zoom-out'),
            'no compass': !q('.maplibregl-ctrl-compass'),
            locate: !!locate && locate.getAttribute('aria-label') === 'Zoom to my location',
            reset: !!reset && reset.getAttribute('aria-label') === 'Zoom out to the whole map',
            'zoom above locate above reset': top('.maplibregl-ctrl-zoom-in') < top('.map-locate') && top('.map-locate') < top('.map-reset'),
            toolbar: !!wrap && !wrap.querySelector('.map-toolbar').hidden,
            legend: !!wrap && !wrap.querySelector('.map-legend-panel').hidden,
            expand: !!wrap && !!wrap.querySelector('.map-expand[data-bound]'),
        };
    """)
    missing = [key for key, ok in result.items() if not ok]
    return (not missing), ('all present, in order' if not missing else 'missing: %s' % ', '.join(missing))


def check_wheel_zoom(page):
    """The wheel zooms only when the cursor was deliberately moved onto the
    map. Four states, in order: cold (never hovered); a page scroll that
    slides the map under a still cursor (must NOT arm it -- that would trap
    the scroll); a real cursor move over the canvas (arms it); a move onto
    the toolbar, which is chrome outside the canvas but inside .map-wrap
    (must stay armed -- reaching for Options used to disarm it)."""
    armed = "return !!(document.querySelector('.section-map').sjvairMap || {}).map.scrollZoom.isEnabled()"

    # Where the cursor actually is, in viewport coordinates: ActionChains
    # offsets are measured from an element's centre, so they can't be read
    # off the request. The page reports the real position instead.
    page.js("""
        window.__cursor = null;
        document.addEventListener('mousemove', function (e) {
            window.__cursor = {x: e.clientX, y: e.clientY};
        }, true);
    """)

    # Cold: park the cursor on the page heading, well above the map.
    page.js("window.scrollTo(0, 0)")
    time.sleep(0.4)
    heading = page.driver.find_element(By.CSS_SELECTOR, 'h1')
    ActionChains(page.driver, duration=250).move_to_element(heading).perform()
    time.sleep(0.4)
    cursor = page.js("return window.__cursor")
    if not cursor:
        return False, 'the cursor never reported a position'
    states = {'cold': page.js(armed)}

    # Now scroll the map up to that stationary cursor. The browser sends
    # mouseenter and no mousemove, so nothing should arm.
    page.js("""
        var el = arguments[0], y = arguments[1];
        window.scrollTo(0, window.scrollY + el.getBoundingClientRect().top - y + 40);
    """, page.container(), cursor['y'])
    time.sleep(0.6)
    under = page.js("""
        var el = document.elementFromPoint(arguments[0], arguments[1]);
        return !!el && !!el.closest('.map-wrap');
    """, cursor['x'], cursor['y'])
    moved = page.js("return window.__cursor") != cursor
    if not under:
        return False, 'the map never reached the cursor (nothing to test)'
    if moved:
        return False, 'the cursor moved during the scroll (nothing to test)'
    states['after a scroll under a still cursor'] = page.js(armed)

    # A deliberate move onto the canvas.
    page.hover_map(0, 0, settle=0.5)
    states['after a real move onto the map'] = page.js(armed)

    # ...and on to the toolbar, still inside .map-wrap.
    toolbar = page.driver.find_element(By.CSS_SELECTOR, '.map-wrap .map-toolbar')
    ActionChains(page.driver, duration=250).move_to_element(toolbar).perform()
    time.sleep(0.4)
    states['on the toolbar'] = page.js(armed)

    want = {
        'cold': False,
        'after a scroll under a still cursor': False,
        'after a real move onto the map': True,
        'on the toolbar': True,
    }
    wrong = ['%s: %r (wanted %r)' % (k, states[k], want[k]) for k in want if states[k] is not want[k]]
    if wrong:
        return False, '; '.join(wrong)
    return True, 'armed only by a deliberate move; survives the toolbar'


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


def check_home(page):
    """Home returns to what the page is about: its own region when it has an
    outline, otherwise its county or the valley. Zoom away first, so a pass
    means the button moved the map rather than that it never left."""
    before = page.instance_js("""
        if (!inst.outlineBounds) return null;
        inst.map.jumpTo({ center: [-121.5, 38.5], zoom: 6 });
        return { west: inst.outlineBounds[0][0], south: inst.outlineBounds[0][1],
                 east: inst.outlineBounds[1][0], north: inst.outlineBounds[1][1] };
    """)
    if before is None:
        return None, 'no region outline on this page'
    page.driver.find_element(By.CSS_SELECTOR, '.map-reset').click()
    time.sleep(2.5)
    after = page.instance_js("""
        var b = inst.map.getBounds();
        return { west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth(),
                 zoom: inst.map.getZoom() };
    """)
    # the view must contain the region and not be the whole valley
    holds = (after['west'] <= before['west'] + 0.01 and after['east'] >= before['east'] - 0.01
             and after['south'] <= before['south'] + 0.01 and after['north'] >= before['north'] - 0.01)
    span = after['east'] - after['west']
    region_span = before['east'] - before['west']
    if not holds:
        return False, 'home left the region out of view (zoom %.2f)' % after['zoom']
    if span > region_span * 4:
        return False, 'home zoomed out well past the region (%.2f deg vs the region %.2f)' % (span, region_span)
    return True, 'home framed the region again at zoom %.2f' % after['zoom']


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
            status: document.querySelector('.map-status').textContent,
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


def url_param(page, name):
    """The value of `?name=` in the current URL, or None."""
    match = re.search(r'[?&]%s=([^&]*)' % name, page.driver.current_url)
    return match.group(1) if match else None


def check_notices(page):
    """The notice markers: on (the page default or `?notices=`) they load
    from the notices endpoint into the `notices` source and render, the
    legend lists them, and a click opens the notice popup (the section
    popup idiom: the subline, the products and chemicals lists, the
    SprayDays pill). The Options toggle clears the markers and the legend
    row and writes `?notices=` against the page default; back on reloads
    them. Ends with the toggle as it found it."""
    state = page.instance_js("return { on: inst.showNotices, dflt: inst.data.showNotices !== '0', url: !!inst.data.noticesUrl };")
    if not state['url']:
        return None, 'no notices endpoint (skipped)'
    problems = []
    requests_before = page.marker_requests('notices')
    if not state['on']:
        page.set_control('input[name="notices"]', True)
    loaded = page.wait_for('var inst = (function () { %s })(); return !!(inst && inst.loadedNoticeBounds);' % JS_INSTANCE, 20)
    if not loaded:
        return False, 'notices never loaded (%d request(s))' % page.marker_requests('notices')
    count = page.source_count('notices')
    in_view = page.instance_js("""
        var b = inst.map.getBounds();
        return inst.sourceData.notices.features.filter(function (f) { return b.contains(f.geometry.coordinates); }).length;
    """)
    rows = page.marker_legend()
    if 'Notice of intent' not in rows:
        problems.append('legend rows %s lack the notices row' % rows)
    if not state['dflt'] and url_param(page, 'notices') != '1':
        problems.append('URL lacks notices=1 with the layer on against the default: %s' % page.driver.current_url)
    popup_detail = 'no active notices in view'
    if in_view:
        rendered = page.wait_for("var inst = (function () { %s })(); return !!inst && inst.map.queryRenderedFeatures({ layers: ['notices-circle'] }).length > 0;" % JS_INSTANCE, 10)
        if not rendered:
            problems.append('%d notices in view, none rendered' % in_view)
        target = page.pick_point('notices', 'notices-circle')
        if not target:
            problems.append('no notice on bare canvas to click')
        else:
            page.click_map(target['dx'], target['dy'], settle=0.8, instant=True)
            result = page.instance_js("""
                var el = document.querySelector(arguments[0]);
                return { text: el ? el.innerText : '', notice: !!(el && el.classList.contains('notice-popup')),
                         key: inst.popupKey, id: inst.openNoticeId,
                         spraydays: !!(el && el.querySelector('a[href^="https://spraydays.cdpr.ca.gov/"][target="_blank"]')),
                         full: !!(el && el.querySelector('.section-popup-action[href*="/notices/"]')),
                         lists: el ? el.querySelectorAll('.section-popup-chems, .section-popup-note').length : 0 };
            """, POPUP)
            if not result['notice'] or 'Notice of intent' not in result['text'] or 'Active' not in result['text']:
                problems.append('notice popup text %r' % result['text'][:120])
            if result['key'] != 'openNoticeId' or result['id'] != target['id']:
                problems.append('popup state %s/%s for notice %s' % (result['key'], result['id'], target['id']))
            if not result['spraydays'] or not result['full']:
                problems.append('popup pills: spraydays=%s full=%s' % (result['spraydays'], result['full']))
            if result['lists'] < 2:
                problems.append('popup lists products and chemicals: %d block(s)' % result['lists'])
            popup_detail = 'popup for notice %s (%s)' % (target['id'], result['text'].split('\n')[0][:40])
    # Off: markers, legend row and popup go; the URL says so against the default.
    page.set_control('input[name="notices"]', False)
    after = page.instance_js("return { count: (inst.sourceData.notices || {features: []}).features.length, popup: !!inst.popup && inst.popupKey === 'openNoticeId', bounds: inst.loadedNoticeBounds };")
    if after['count'] or after['bounds'] or after['popup']:
        problems.append('toggle off left %d markers, bounds %s, popup %s' % (after['count'], after['bounds'] is not None, after['popup']))
    if 'Notice of intent' in page.marker_legend():
        problems.append('legend kept the notices row after toggle off')
    expected_off = '0' if state['dflt'] else None
    if url_param(page, 'notices') != expected_off:
        problems.append('URL after toggle off: %s (wanted notices=%s)' % (page.driver.current_url, expected_off))
    # On again reloads them.
    page.set_control('input[name="notices"]', True)
    reloaded = page.wait_for('var inst = (function () { %s })(); return !!(inst && inst.loadedNoticeBounds);' % JS_INSTANCE, 20)
    if not reloaded or (in_view and not page.source_count('notices')):
        problems.append('toggle on again: loaded=%s, %d markers (had %d)' % (reloaded, page.source_count('notices'), count))
    expected_on = None if state['dflt'] else '1'
    if url_param(page, 'notices') != expected_on:
        problems.append('URL after toggle on: %s (wanted notices=%s)' % (page.driver.current_url, expected_on))
    if not state['on']:
        page.set_control('input[name="notices"]', False)
    requests = page.marker_requests('notices') - requests_before
    detail = '%d notices fetched, %d in view (%d request(s)); %s; toggle off/on cleared and reloaded, URL and legend followed' % (count, in_view, requests, popup_detail)
    return (not problems), (detail if not problems else '; '.join(problems))


def check_locations(page):
    """The school and child care markers: on (the page default or
    `?locations=`) and at the layer's zoom they load into the `locations`
    source and render, the legend lists both kinds, and a click opens the
    location popup, which fills in the block figure ("within about a
    mile") and carries the "District page" pill. Zoomed out past
    LOCATIONS_MIN_ZOOM the layer stays empty and the legend note and the
    status line say why. The Options toggle clears the markers and the
    legend rows and writes `?locations=` against the page default; back on
    reloads them. Ends with the toggle as it found it. Skips itself (after
    the load and toggle steps) where the layer's zoom has no school in
    view to click."""
    state = page.instance_js("return { on: inst.showLocations, dflt: inst.data.showLocations === '1', url: !!inst.data.locationsUrl, zoom: inst.map.getZoom() };")
    if not state['url']:
        return None, 'no locations endpoint (skipped)'
    problems = []
    requests_before = page.marker_requests('locations')
    if not state['on']:
        page.set_control('input[name="locations"]', True)
    time.sleep(0.5)
    rows = page.marker_legend()
    if 'School' not in rows or 'Child care' not in rows:
        problems.append('legend rows %s lack the school/child care rows' % rows)
    if not state['dflt'] and url_param(page, 'locations') != '1':
        problems.append('URL lacks locations=1 with the layer on against the default: %s' % page.driver.current_url)
    too_far = state['zoom'] < 9
    count = 0
    popup_detail = ''
    skipped = None
    if too_far:
        note = page.js("return { note: document.querySelector('.section-map-locations-note').textContent, status: document.querySelector('.map-status').textContent };")
        if note['note'] != LOCATIONS_ZOOM_NOTE or note['status'] != LOCATIONS_ZOOM_NOTE:
            problems.append('zoom %.2f: note %r, status %r' % (state['zoom'], note['note'], note['status']))
        if page.marker_requests('locations') != requests_before or page.source_count('locations'):
            problems.append('zoom %.2f: the layer loaded anyway' % state['zoom'])
        popup_detail = 'zoom %.2f is under 9: note shown, nothing fetched' % state['zoom']
    else:
        loaded = page.wait_for('var inst = (function () { %s })(); return !!(inst && inst.loadedLocationBounds);' % JS_INSTANCE, 20)
        if not loaded:
            return False, 'locations never loaded (%d request(s))' % page.marker_requests('locations')
        count = page.source_count('locations')
        if page.js("return document.querySelector('.section-map-locations-note').textContent"):
            problems.append('zoom note shown at zoom %.2f' % state['zoom'])
        if not count:
            skipped = 'no locations in view at zoom %.2f' % state['zoom']
        else:
            rendered = page.wait_for("var inst = (function () { %s })(); return !!inst && inst.map.queryRenderedFeatures({ layers: ['locations-circle'] }).length > 0;" % JS_INSTANCE, 10)
            if not rendered:
                problems.append('%d locations in the source, none rendered' % count)
            target = page.pick_point('locations', 'locations-circle')
            if not target:
                problems.append('no location on bare canvas to click')
            else:
                page.click_map(target['dx'], target['dy'], settle=0.3, instant=True)
                opened = page.instance_js("var el = document.querySelector(arguments[0]); return { text: el ? el.innerText : '', key: inst.popupKey, id: inst.openLocationId };", POPUP)
                if opened['key'] != 'openLocationId' or opened['id'] != target['id']:
                    problems.append('popup state %s/%s for location %s' % (opened['key'], opened['id'], target['id']))
                if 'Loading nearby use' not in opened['text'] and 'within about a mile' not in opened['text']:
                    problems.append('location popup opened with %r' % opened['text'][:120])
                filled = page.wait_for("var el = document.querySelector(arguments[0]); return !!el && el.innerText.indexOf('Loading nearby use') === -1;", 15, POPUP)
                result = page.instance_js("""
                    var el = document.querySelector(arguments[0]);
                    var pills = el ? Array.from(el.querySelectorAll('.section-popup-action')).map(function (a) { return a.textContent.trim(); }) : [];
                    return { text: el ? el.innerText : '', location: !!(el && el.classList.contains('location-popup')), pills: pills,
                             district: !!(el && el.querySelector('.section-popup-action[href*="/region/"]')) };
                """, POPUP)
                if not filled or 'within about a mile' not in result['text']:
                    problems.append('block figure never filled in: %r' % result['text'][:120])
                if not result['location']:
                    problems.append('popup is not a location popup')
                if not result['district'] or 'District page' not in result['pills']:
                    problems.append('no "District page" pill: %s' % result['pills'])
                popup_detail = 'popup for %s: %s; pills %s' % (target['id'], result['text'].split('\n')[0][:40], result['pills'])
    # Off: markers, legend rows, note and popup go; the URL says so.
    page.set_control('input[name="locations"]', False)
    after = page.instance_js("""
        return { count: (inst.sourceData.locations || {features: []}).features.length, popup: !!inst.popup && inst.popupKey === 'openLocationId',
                 bounds: inst.loadedLocationBounds, note: document.querySelector('.section-map-locations-note').textContent,
                 status: document.querySelector('.map-status').textContent };
    """)
    if after['count'] or after['bounds'] or after['popup'] or after['note'] or after['status'] == LOCATIONS_ZOOM_NOTE:
        problems.append('toggle off left %s' % after)
    rows = page.marker_legend()
    if 'School' in rows or 'Child care' in rows:
        problems.append('legend kept the location rows after toggle off: %s' % rows)
    expected_off = '0' if state['dflt'] else None
    if url_param(page, 'locations') != expected_off:
        problems.append('URL after toggle off: %s (wanted locations=%s)' % (page.driver.current_url, expected_off))
    # On again reloads them (or shows the note again).
    page.set_control('input[name="locations"]', True)
    if too_far:
        if page.js("return document.querySelector('.section-map-locations-note').textContent") != LOCATIONS_ZOOM_NOTE:
            problems.append('toggle on again: note missing')
    else:
        reloaded = page.wait_for('var inst = (function () { %s })(); return !!(inst && inst.loadedLocationBounds);' % JS_INSTANCE, 20)
        if not reloaded or (count and not page.source_count('locations')):
            problems.append('toggle on again: loaded=%s, %d markers (had %d)' % (reloaded, page.source_count('locations'), count))
    expected_on = None if state['dflt'] else '1'
    if url_param(page, 'locations') != expected_on:
        problems.append('URL after toggle on: %s (wanted locations=%s)' % (page.driver.current_url, expected_on))
    if not state['on']:
        page.set_control('input[name="locations"]', False)
    requests = page.marker_requests('locations') - requests_before
    if problems:
        return False, '; '.join(problems)
    if skipped:
        return None, '%s (%d request(s)); toggle off/on, URL and legend followed; no popup to check (skipped)' % (skipped, requests)
    return True, '%d locations (%d request(s)); %s; toggle off/on, URL and legend followed' % (count, requests, popup_detail)


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
    own_section = "inst.lensFeatures.filter(function (f) { var m = f.properties.mtrs || ''; return m.slice(0, m.lastIndexOf('-')) === inst.lensId; })"
    target = page.pick(own_section)
    if not target:
        # The lens check leaves the lens on the farthest township it could
        # reach, at the viewport's edge, where its sections with data may all
        # sit under a panel, a marker or past the edge; bring the lens to a
        # township with data near the centre and try there.
        near = page.pick("inst.gridFeatures.filter(function (f) { return f.properties.id !== inst.lensId; })")
        if near:
            page.hover_map(near['dx'], near['dy'], settle=0.3, instant=True)
            if page.wait_lens(near['id'], timeout=10)[0]:
                page.wait_prefetch(near['id'])
                lens_id = near['id']
                target = page.pick(own_section)
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
        return !!(run && run.done === run.total && inst.allSectionsFeatures.length && document.querySelector('.map-status').textContent === '');
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


def check_popup_clear(page):
    """A section popup opened beside the legend panel (where its box would
    lie over the panel) is panned clear: after the map settles the popup
    sits inside the map, under the toolbar band, and off the legend."""
    ok, _ = page.wait_grid('section', 10)
    if not ok:
        return False, 'not at the section grid'
    rects = page.rects()
    if not rects['legend']:
        return None, 'no legend panel (skipped)'
    # The cell with data nearest the legend's top-right corner, a little
    # inside the canvas from it, so the popup (centred on the cell) would
    # overlap the panel.
    target = page.pick('inst.sourceData.grid.features', ref_expr="""
        var lr = document.querySelector('.map-legend-panel').getBoundingClientRect();
        return [lr.right - rect.left + 40, lr.top - rect.top + 40];
    """)
    if not target:
        return False, 'no section with data on bare canvas near the legend'
    centre_before = page.instance_js('return inst.map.getCenter().toArray()')
    page.click_map(target['dx'], target['dy'], settle=0.3, instant=True)
    filled = page.wait_for("""
        var el = document.querySelector(arguments[0]);
        return !!el && el.innerText.indexOf('Loading') === -1;
    """, 15, POPUP)
    page.wait_still()
    rects = page.rects()
    problems = []
    if not filled or not rects['popup']:
        problems.append('popup never opened/filled for %s' % target['id'])
        return False, '; '.join(problems)
    popup, box, legend, toolbar = rects['popup'], rects['map'], rects['legend'], rects['toolbar']
    band = toolbar['bottom'] if toolbar else box['top'] + 56
    overlap = lambda a, b: a['left'] < b['right'] and a['right'] > b['left'] and a['top'] < b['bottom'] and a['bottom'] > b['top']
    if popup['left'] < box['left'] or popup['right'] > box['right'] or popup['top'] < box['top'] or popup['bottom'] > box['bottom']:
        problems.append('popup runs off the map: %s vs %s' % (popup, box))
    if popup['top'] < band:
        problems.append('popup under the toolbar band (top %.0f < %.0f)' % (popup['top'], band))
    if overlap(popup, legend):
        problems.append('popup over the legend panel: %s vs %s' % (popup, legend))
    centre_after = page.instance_js('return inst.map.getCenter().toArray()')
    moved = centre_after != centre_before
    detail = 'section %s beside the legend: popup %s (%s)' % (
        target['id'], 'clear', 'map panned' if moved else 'no pan needed')
    return (not problems), (detail if not problems else '; '.join(problems))


# Wraps fetch so the grid endpoints' responses land `delay` ms late (a slow
# server), logging every request to the grid and marker endpoints, aborted
# ones included; the Performance API wouldn't show those.
JS_SLOW_FETCH = """
if (window.__realFetch) return;
window.__realFetch = window.fetch;
window.__fetchLog = [];
var delay = %d;
window.fetch = function (url, opts) {
  var name = String(url);
  var kind = /\\/pesticides\\/sections\\/\\?/.test(name) ? 'sections' : /\\/pesticides\\/townships\\/\\?/.test(name) ? 'townships'
    : /\\/pesticides\\/notices\\/active\\//.test(name) ? 'notices' : /\\/pesticides\\/locations\\//.test(name) ? 'locations' : null;
  var p = window.__realFetch(url, opts);
  if (!kind) return p;
  window.__fetchLog.push(kind);
  if (kind === 'sections' || kind === 'townships') {
    return p.then(function (r) { return new Promise(function (resolve) { setTimeout(function () { resolve(r); }, delay); }); });
  }
  return p;
};
"""
JS_RESTORE_FETCH = "if (window.__realFetch) { window.fetch = window.__realFetch; window.__realFetch = null; }"


def check_year_swap(page, year):
    """Changing the year in the scope bar swaps the page over htmx; the map
    instance must survive it (adopted in place), the container carry the
    new year, and no new MapTiler session start. With the grid response
    held back past the loaders' debounce (the swap's resize fires a moveend
    even at an unchanged size), the swap starts one grid request, not two,
    and one per marker layer that's on."""
    link = page.js("""
        var links = document.querySelectorAll('.explorer-scope-picker[data-scope="year"] a[href*="year=%s"]');
        return links.length ? links[0].getAttribute('href') : null;
    """ % year)
    if not link:
        return None, 'no year picker on this page (skipped)'
    before = page.instance_js('return inst.el.id')
    page.js("window.__smokeInstance = (function () { %s })();" % JS_INSTANCE)
    sessions_before = set(page.maptiler_sessions())
    page.js(JS_SLOW_FETCH % 700)
    try:
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
        # Past the debounce and the held-back response, so a duplicate would
        # have been started by now.
        time.sleep(1.5)
        log = page.js('return window.__fetchLog')
    finally:
        page.js(JS_RESTORE_FETCH)
    counts = {kind: log.count(kind) for kind in ('sections', 'townships', 'notices', 'locations')}
    problems = []
    if counts['sections'] + counts['townships'] != 1:
        problems.append('%d grid request(s) on the swap: %s' % (counts['sections'] + counts['townships'], log))
    if counts['notices'] > 1 or counts['locations'] > 1:
        problems.append('marker requests on the swap: %s' % log)
    sessions_after = set(page.maptiler_sessions())
    new_sessions = sessions_after - sessions_before
    if sessions_before and new_sessions:
        problems.append('new MapTiler session after the swap: %s' % sorted(new_sessions))
    if year not in page.driver.current_url:
        problems.append('URL did not change: %s' % page.driver.current_url)
    after = page.instance_js('return inst.el.id')
    detail = 'same instance (container %s -> %s), %d session(s); requests %s with the grid response held 700 ms' % (
        before, after, len(sessions_after), log)
    return (not problems), (detail if not problems else '; '.join(problems))


def check_wheel_zoom_across_swap(page):
    """An htmx swap leaves the live map in a new page's wrapper, so the wheel
    region has to move with it (Shell.adopt -> bindWheelZoom). Runs after the
    year swap: the region must be the wrapper now in the document, and a move
    onto the map must still arm the wheel."""
    state = page.js("""
        var shell = document.querySelector('.section-map').sjvairMap;
        return {
            bound: !!shell.wheelRegion,
            'is the live wrapper': shell.wheelRegion === shell.el.closest('.map-wrap'),
            'in the document': !!shell.wheelRegion && document.body.contains(shell.wheelRegion),
        };
    """)
    stale = [key for key, ok in state.items() if not ok]
    if stale:
        return False, 'after the swap: %s' % ', '.join(stale)
    page.js("window.scrollTo(0, 0)")
    time.sleep(0.3)
    page.hover_map(0, 0, settle=0.5)
    if not page.js("return document.querySelector('.section-map').sjvairMap.map.scrollZoom.isEnabled()"):
        return False, 'the wheel no longer arms on the swapped-in wrapper'
    return True, 'region followed the swap and still arms'


def check_expand(page):
    """Expand fills the viewport (html class, wrapper class, a wider canvas);
    collapse puts everything back."""
    page.scroll_to_map()
    width_before = page.instance_js('return inst.map.getCanvas().clientWidth')
    canvas_width_is = 'var inst = (function () { %s })(); return !!inst && inst.map.getCanvas().clientWidth === arguments[0];' % JS_INSTANCE
    canvas_width_not = 'var inst = (function () { %s })(); return !!inst && inst.map.getCanvas().clientWidth !== arguments[0];' % JS_INSTANCE
    page.js("document.querySelector('.map-expand').click()")
    page.wait_for(canvas_width_not, 10, width_before)
    expanded = page.js("""
        return {
            html: document.documentElement.classList.contains('map-expanded'),
            wrap: document.querySelector('.map-wrap').classList.contains('is-expanded'),
            pressed: document.querySelector('.map-expand').getAttribute('aria-pressed') === 'true',
            label: document.querySelector('.map-expand').getAttribute('aria-label'),
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
    page.js("document.querySelector('.map-expand').click()")
    page.wait_for(canvas_width_is, 10, width_before)
    collapsed = page.js("""
        return !document.documentElement.classList.contains('map-expanded')
            && !document.querySelector('.map-wrap').classList.contains('is-expanded')
            && document.querySelector('.map-expand').getAttribute('aria-pressed') === 'false';
    """)
    width_back = page.instance_js('return inst.map.getCanvas().clientWidth')
    if not collapsed:
        problems.append('expanded state not cleared')
    if width_back != width_before:
        problems.append('canvas width did not return (%s -> %s)' % (width_before, width_back))
    return (not problems), ('%s -> %s -> %s px' % (width_before, width_after, width_back) if not problems else '; '.join(problems))


def check_phone_layout(page):
    """Reloaded in a phone-sized window (no stored panel state): the legend
    panel starts folded, the filter buttons are icon-only, the attribution
    is folded to its button, the status pill is centred, and a cell's popup
    has a touch-sized close button and fits the phone's map (inside it,
    under the toolbar band, off the folded legend). Saves the `-phone`
    screenshot. Leaves the page in the phone window."""
    page.console_errors()   # the log so far, before the reload
    page.driver.set_window_size(*PHONE_SIZE)
    page.js('try { localStorage.clear(); } catch (err) {}')
    page.driver.get(page.url)
    page.prepare()
    if not page.wait_for_map():
        return False, 'map never loaded in the phone window'
    ok, _ = page.wait_grid()
    if not ok:
        return False, 'grid never loaded in the phone window'
    # The markers too, so the cell picked below is judged against them.
    if page.instance_js('return inst.showNotices && !!inst.data.noticesUrl'):
        page.wait_for('var inst = (function () { %s })(); return !!(inst && inst.loadedNoticeBounds);' % JS_INSTANCE, 20)
    page.wait_idle()
    time.sleep(0.5)
    result = page.js("""
        var wrap = document.querySelector('.map-wrap');
        var legend = wrap.querySelector('.map-legend-panel');
        var labels = Array.from(wrap.querySelectorAll('.map-toolbar-filters .map-toolbar-label'));
        var attrib = wrap.querySelector('.maplibregl-ctrl-attrib');
        var status = wrap.querySelector('.map-status');
        var mapRect = wrap.querySelector('.section-map').getBoundingClientRect();
        status.textContent = 'probe';
        var sr = status.getBoundingClientRect();
        status.textContent = '';
        return {
            width: window.innerWidth,
            collapsed: legend.classList.contains('is-collapsed') && legend.querySelector('.map-panel-toggle').getAttribute('aria-expanded') === 'false',
            filters: labels.length,
            iconOnly: labels.every(function (el) { return getComputedStyle(el).display === 'none'; }),
            compact: !!attrib && attrib.classList.contains('maplibregl-compact'),
            folded: !!attrib && !attrib.classList.contains('maplibregl-compact-show'),
            statusCentred: Math.abs((sr.left + sr.right) / 2 - (mapRect.left + mapRect.right) / 2) < 2,
            toggleHeight: legend.querySelector('.map-panel-toggle').getBoundingClientRect().height,
        };
    """)
    problems = []
    if result['width'] > 768:
        problems.append('window is %dpx wide' % result['width'])
    if not result['collapsed']:
        problems.append('legend panel not folded by default')
    if result['filters'] and not result['iconOnly']:
        problems.append('filter buttons still show their labels')
    if not result['compact'] or not result['folded']:
        problems.append('attribution compact=%s folded=%s' % (result['compact'], result['folded']))
    if not result['statusCentred']:
        problems.append('status pill not centred')
    if result['toggleHeight'] < 36:
        problems.append('legend toggle %.0fpx tall' % result['toggleHeight'])
    # A popup's close button is a touch target.
    target = page.pick('inst.sourceData.grid.features')
    close = None
    clear = 'no cell to click'
    if target:
        page.click_map(target['dx'], target['dy'], settle=0.3, instant=True)
        close = page.js("var b = document.querySelector('.maplibregl-popup-close-button'); return b ? b.getBoundingClientRect().width * b.getBoundingClientRect().height : null;")
        if close is None or close < 32 * 32 - 1:
            problems.append('popup close button %s px^2' % close)
        # And, once the map settles, the popup fits the phone's map: inside
        # it, under the toolbar band, off the (folded) legend.
        page.wait_for("var el = document.querySelector(arguments[0]); return !!el && el.innerText.indexOf('Loading') === -1;", 15, POPUP)
        page.wait_still()
        rects = page.rects()
        popup, box, legend, toolbar = rects['popup'], rects['map'], rects['legend'], rects['toolbar']
        if not popup:
            problems.append('popup gone')
        else:
            band = toolbar['bottom'] if toolbar else box['top'] + 56
            if popup['left'] < box['left'] or popup['right'] > box['right'] or popup['top'] < box['top'] or popup['bottom'] > box['bottom']:
                problems.append('popup runs off the map: %s vs %s' % (popup, box))
            if popup['top'] < band:
                problems.append('popup under the toolbar band (top %.0f < %.0f)' % (popup['top'], band))
            if legend and popup['left'] < legend['right'] and popup['right'] > legend['left'] and popup['top'] < legend['bottom'] and popup['bottom'] > legend['top']:
                problems.append('popup over the legend panel: %s vs %s' % (popup, legend))
            clear = 'popup %.0fpx wide, clear' % (popup['right'] - popup['left'])
    page.screenshot('-phone')
    detail = '%dpx: legend folded, %d filter label(s) hidden, attribution folded, status centred, close button %s px^2, %s' % (
        result['width'], result['filters'], 'n/a' if close is None else '%.0f' % close, clear)
    return (not problems), (detail if not problems else '; '.join(problems))


def chrome_prefix(page):
    """The chrome class prefix in use on this page: `map-` on this branch's
    shared core, `section-map-` on the pesticides-only reference (before the
    map-core rename). Lets a check run unchanged against either."""
    if not hasattr(page, '_chrome_prefix'):
        page._chrome_prefix = 'map-' if page.js("return !!document.querySelector('.map-wrap');") else 'section-map-'
    return page._chrome_prefix


def check_fold_persistence(page):
    """Folding the legend panel collapses it, and a reload remembers the
    fold through localStorage (`pesticides:section-map:panel:legend`), so a
    reader's folded legend stays folded. Restores the panel to how it found
    it, so later checks aren't affected."""
    p = chrome_prefix(page)
    toggle = '.%slegend-panel .%spanel-toggle' % (p, p)
    expanded_before = page.js("var t = document.querySelector('%s'); return !!t && t.getAttribute('aria-expanded') === 'true';" % toggle)
    if expanded_before:
        page.js("document.querySelector('%s').click();" % toggle)
        time.sleep(0.3)
    key = page.js("return localStorage.getItem('pesticides:section-map:panel:legend');")
    page.driver.get(page.url)
    page.prepare()
    problems = []
    if not page.wait_for_map():
        problems.append('map never reloaded')
    collapsed = page.js("""
        var p = document.querySelector('.%slegend-panel');
        return !!p && p.classList.contains('is-collapsed')
            && p.querySelector('.%spanel-toggle').getAttribute('aria-expanded') === 'false';
    """ % (p, p))
    if key != 'collapsed':
        problems.append("localStorage key was %r, not 'collapsed'" % key)
    if not collapsed:
        problems.append('legend panel not still collapsed after the reload')
    # Restore the fold state the check found, for later checks.
    if expanded_before:
        page.js("document.querySelector('%s').click();" % toggle)
        time.sleep(0.3)
    detail = "key=%r, collapsed after reload=%s" % (key, collapsed)
    return (not problems), (detail if not problems else '; '.join(problems))


def check_expand_across_swap(page, year):
    """Expand, then a swap that adopts (a year change in the scope bar): the
    wrap is still `is-expanded` and `html.<prefix>expanded` is set across
    the adopt. Escape then un-expands it."""
    p = chrome_prefix(page)
    link = page.js("""
        var links = document.querySelectorAll('.explorer-scope-picker[data-scope="year"] a[href*="year=%s"]');
        return links.length ? links[0].getAttribute('href') : null;
    """ % year)
    if not link:
        return None, 'no year picker on this page (skipped)'
    state_js = """
        return {html: document.documentElement.classList.contains('%sexpanded'),
                wrap: !!document.querySelector('.%swrap') && document.querySelector('.%swrap').classList.contains('is-expanded')};
    """ % (p, p, p)
    page.js("document.querySelector('.%sexpand').click();" % p)
    page.wait_for("return document.documentElement.classList.contains('%sexpanded');" % p, 10)
    before = page.js(state_js)
    page.js('document.querySelector(\'.explorer-scope-picker[data-scope="year"] a[href*="year=%s"]\').click();' % year)
    swapped = page.wait_for("""
        var inst = (function () { %s })();
        return !!(inst && inst.data.year === '%s' && document.body.contains(inst.el));
    """ % (JS_INSTANCE, year), SWAP_TIMEOUT)
    problems = []
    if not swapped:
        problems.append('container never carried year=%s after the swap' % year)
    after = page.js(state_js)
    if not (before['html'] and before['wrap']):
        problems.append('expand did not apply before the swap: %s' % before)
    if not (after['html'] and after['wrap']):
        problems.append('expanded state lost across the adopt: %s' % after)
    page.driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
    page.wait_for("return !document.documentElement.classList.contains('%sexpanded');" % p, 10)
    unexpanded = page.js("""
        return !document.documentElement.classList.contains('%sexpanded')
            && !!document.querySelector('.%swrap') && !document.querySelector('.%swrap').classList.contains('is-expanded');
    """ % (p, p, p))
    if not unexpanded:
        problems.append('Escape did not un-expand after the adopt')
    detail = 'expanded before=%s, after swap=%s, after Escape unexpanded=%s' % (before, after, unexpanded)
    return (not problems), (detail if not problems else '; '.join(problems))


def check_swap_away(page):
    """An htmx navigation from the map page to a page with no map (the
    Chemicals list, via a boosted tab click) releases the shell: no live
    instances, and `<html>` carries no `<prefix>expanded` class. Expanded
    first, the stronger version of the check."""
    p = chrome_prefix(page)
    has_tab = page.js('return !!document.querySelector(\'#explorer-tabs a[title="Chemicals"]\');')
    if not has_tab:
        return None, 'no Chemicals tab on this page (skipped)'
    page.js("document.querySelector('.%sexpand').click();" % p)
    page.wait_for("return document.documentElement.classList.contains('%sexpanded');" % p, 10)
    page.js('document.querySelector(\'#explorer-tabs a[title="Chemicals"]\').click();')
    swapped = page.wait_for("return location.pathname.indexOf('/chemicals/') !== -1;", SWAP_TIMEOUT)
    problems = []
    if not swapped:
        problems.append('never navigated to the chemicals list')
    time.sleep(0.5)  # let the registry's htmx:load handler finish releasing the shell
    state = page.js("""
        var mod = window.PesticidesSectionMap;
        return {
            instances: (mod && typeof mod.instances === 'function') ? mod.instances().length : null,
            htmlExpanded: document.documentElement.classList.contains('%sexpanded'),
        };
    """ % p)
    if state['instances'] != 0:
        problems.append('%s live instance(s) after the swap-away' % state['instances'])
    if state['htmlExpanded']:
        problems.append('html still carries %sexpanded after the swap-away' % p)
    detail = 'instances=%s, html expanded=%s' % (state['instances'], state['htmlExpanded'])
    return (not problems), (detail if not problems else '; '.join(problems))


def check_back_button(page):
    """`history.back()` after the swap-away check restores exactly one live
    map instance, loaded. Skipped when there's no prior swap-away
    navigation to reverse (the Chemicals tab wasn't on this page)."""
    original_path = urlparse(page.url).path
    if page.js('return location.pathname;') == original_path:
        return None, 'no prior swap-away to reverse (skipped)'
    page.js('window.history.back();')
    back = page.wait_for("return location.pathname === arguments[0];", SWAP_TIMEOUT, original_path)
    problems = []
    if not back:
        problems.append('back button did not return to %s' % original_path)
    if not page.wait_for_map():
        problems.append('map never reloaded after the back button')
    count = page.js("var mod = window.PesticidesSectionMap; return mod ? mod.instances().length : null;")
    if count != 1:
        problems.append('%s live instance(s) after the back button' % count)
    loaded = page.instance_js('return inst.loaded;')
    if not loaded:
        problems.append('instance not loaded after the back button')
    detail = 'path=%s, instances=%s, loaded=%s' % (original_path, count, loaded)
    return (not problems), (detail if not problems else '; '.join(problems))


def check_console(page):
    """Console errors over the whole run (the phone layout check's reload
    included)."""
    page.console_errors()
    errors = page.errors
    return (not errors), ('clean' if not errors else '\n      '.join(errors))


CHECKS = [
    ('map loaded', check_map_loaded),
    ('layers', check_layers),
    ('controls', check_controls),
    ('wheel zoom', check_wheel_zoom),
    ('fit', check_fit),
    ('home', check_home),
    ('grid', check_grid),
    ('legend options', check_legend_options),
    ('notices', check_notices),
    ('locations', check_locations),
    ('lens', check_lens),
    ('lens popup', check_lens_popup),
    ('all sections', check_all_sections),
    ('style swap', check_style_swap),
    ('township popup', check_township_popup),
    ('section popup', check_section_popup),
    ('selection', check_selection_survives_metric),
    ('popup clear', check_popup_clear),
    ('year swap', check_year_swap),
    ('wheel zoom across swap', check_wheel_zoom_across_swap),
    ('expand', check_expand),
    ('fold persistence', check_fold_persistence),
    ('expand across swap', check_expand_across_swap),
    ('swap away', check_swap_away),
    ('back button', check_back_button),
    ('phone layout', check_phone_layout),
    ('console', check_console),
]


def run_page(base, path, year, screenshots):
    url = base.rstrip('/') + path
    driver = browser()
    started = time.time()
    rows = []
    try:
        driver.get(url)
        name = path.strip('/').replace('/', '_').replace('?', '_').replace('=', '-') or 'landing'
        page = Page(driver, url, screenshots, name)
        page.timings['page_get_s'] = round(time.time() - started, 2)
        failed = False
        for name, check in CHECKS:
            if failed and name != 'console':
                rows.append((name, None, 'skipped'))
                continue
            # The desktop screenshot, before the page is reloaded phone-sized.
            if check is check_phone_layout:
                page.screenshot()
            try:
                if check in (check_year_swap, check_expand_across_swap):
                    passed, detail = check(page, year)
                else:
                    passed, detail = check(page)
            except Exception as err:  # a broken page must still report
                passed, detail = False, 'raised %s: %s' % (type(err).__name__, err)
            rows.append((name, passed, detail))
            if not passed and name == 'map loaded':
                failed = True
        return url, rows, page.timings
    finally:
        driver.quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('paths', nargs='+', help='page paths under --base, e.g. /tools/pesticides/map/')
    parser.add_argument('--base', default='http://localhost:8002')
    parser.add_argument('--year', default='2022', help='year to switch the scope bar to')
    parser.add_argument('--screenshots', help='directory for a screenshot per page')
    args = parser.parse_args(argv)

    any_failed = False
    for path in args.paths:
        url, rows, timings = run_page(args.base, path, args.year, args.screenshots)
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
