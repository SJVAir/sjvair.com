"""
Headless smoke test for the Pesticides Explorer's section map.

Loads explorer pages in headless Chrome, waits for the map to come up, runs
a set of checks against the live map (layers, controls, an htmx year change
that must keep the same map instance, expand/collapse) and reports a table
per page. Exits 1 on any failed check, a console error, or a map that never
loads. Dev-only; nothing here runs in CI.

Setup (Chrome must be installed: `google-chrome-stable` on the PATH):

    python3 -m venv .venv && .venv/bin/pip install selenium

Usage:

    .venv/bin/python scripts/pesticides_map_smoke.py --base http://localhost:8002 --gl \\
        /tools/pesticides/ /tools/pesticides/region/hez8v/fresno/

    --gl            append `gl=1` to each page URL (the MapTiler SDK map, while
                    it lives beside the Leaflet one)
    --screenshots   a directory to save a screenshot per page into
    --year YEAR     the year the scope bar is switched to (default 2022)

Every check on a page runs even after one fails, except that a map which
never loads skips the checks that need it.

Each page gets a fresh browser: the explorer's static files aren't
cache-busted, so a reused profile could serve a stale script.

Later tasks extend this with more checks: add a `check_*` function that takes
the `Page` and returns a (passed, detail) tuple, and list it in CHECKS.
"""
import argparse
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By

MAP_TIMEOUT = 40
SWAP_TIMEOUT = 20

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
        self.timings = {}
        self.errors = []

    def js(self, script, *args):
        return self.driver.execute_script(script, *args)

    def instance_js(self, expr):
        """Evaluate `expr` with `inst` bound to the live map instance."""
        return self.js('var inst = (function () { %s })(); if (!inst) return null; %s' % (JS_INSTANCE, expr))

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

    def console_errors(self):
        noise = ('favicon', 'DevTools')
        entries = []
        for entry in self.driver.get_log('browser'):
            if entry['level'] != 'SEVERE':
                continue
            message = entry['message']
            if any(word in message for word in noise):
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

    # Pointer hooks for the checks that later tasks add (lens on hover,
    # popups on click), relative to the map container's centre.
    def hover_map(self, dx=0, dy=0, settle=1.5):
        el = self.scroll_to_map()
        ActionChains(self.driver).move_to_element_with_offset(el, dx, dy).perform()
        time.sleep(settle)

    def click_map(self, dx=0, dy=0, settle=1.5):
        el = self.scroll_to_map()
        ActionChains(self.driver).move_to_element_with_offset(el, dx, dy).click().perform()
        time.sleep(settle)

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
    """The shell's layers are in the style, under the basemap's labels, and
    the county outlines have data; the outline/radius layers carry data when
    the page asks for them."""
    result = page.instance_js("""
        var map = inst.map;
        var layers = map.getStyle().layers.map(function (l) { return l.id; });
        var firstSymbol = -1;
        map.getStyle().layers.some(function (l, i) { if (l.type === 'symbol') { firstSymbol = i; return true; } });
        var mine = ['radius-fill', 'radius-line', 'counties-line', 'outline-fill', 'outline-line', 'locate-circle'];
        var missing = mine.filter(function (id) { return layers.indexOf(id) === -1; });
        var aboveLabels = mine.filter(function (id) { return firstSymbol !== -1 && layers.indexOf(id) > firstSymbol; });
        var counts = {};
        ['counties', 'outline', 'radius'].forEach(function (id) {
            var d = inst.sourceData[id];
            counts[id] = d ? (d.features ? d.features.length : (d.geometry ? 1 : 0)) : 0;
        });
        return { missing: missing, aboveLabels: aboveLabels, counts: counts,
                 wantsOutline: !!inst.data.outlineUrl, wantsRadius: !!inst.data.radius };
    """)
    if result is None:
        return False, 'no instance'
    problems = []
    if result['missing']:
        problems.append('missing layers %s' % result['missing'])
    if result['aboveLabels']:
        problems.append('layers above labels %s' % result['aboveLabels'])
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
            name = path.strip('/').replace('/', '_').replace('?', '_') or 'landing'
            page.scroll_to_map()
            driver.save_screenshot(os.path.join(screenshots, name + '.png'))
        return url, rows, page.timings
    finally:
        driver.quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('paths', nargs='+', help='page paths under --base, e.g. /tools/pesticides/')
    parser.add_argument('--base', default='http://localhost:8002')
    parser.add_argument('--gl', action='store_true', help='append gl=1 (the MapTiler SDK map)')
    parser.add_argument('--year', default='2022', help='year to switch the scope bar to')
    parser.add_argument('--screenshots', help='directory for a screenshot per page')
    args = parser.parse_args(argv)

    any_failed = False
    for path in args.paths:
        url, rows, timings = run_page(args.base, path, args.gl, args.year, args.screenshots)
        print('\n%s' % url)
        print('  page get %ss, map loaded %ss' % (timings.get('page_get_s'), timings.get('map_loaded_s')))
        for name, passed, detail in rows:
            status = 'PASS' if passed else ('SKIP' if passed is None else 'FAIL')
            print('  %-4s %-12s %s' % (status, name, detail))
            if passed is False:
                any_failed = True
    print()
    return 1 if any_failed else 0


if __name__ == '__main__':
    sys.exit(main())
