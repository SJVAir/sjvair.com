"""
Headless smoke test for the map figures (assets/js/admin/map-figure.js).

Loads explorer pages in headless Chrome and checks the county choropleth
that `camp.utils.mapfigure.MapFigure` renders into a `.map-figure`
container: that it becomes a live map, that all eight counties are drawn
and hit-testable, that a linked county shows a pointer cursor and a hover
label and follows its url on click, that a figure starting inside a
`display: none` subtree builds when it is revealed, and that an htmx
navigation away and back leaves exactly one live map (no leaked WebGL
contexts). Exits 1 on any failed check or console error; same-origin
console warnings are reported but don't fail the run. Dev-only; nothing
here runs in CI.

The admin's figures use the same container, payload and script, so what
holds here holds for them; the admin side is covered by Python tests
(camp/utils/tests/test_admin_maps.py), which need a login this script has
no credentials for. The hidden-container check stands in for the one admin
shape that isn't otherwise exercised: the Region admin's collapsed
BoundaryInline fieldsets.

Setup (Chrome must be installed: `google-chrome-stable` on the PATH):

    python3 -m venv .venv && .venv/bin/pip install selenium

Usage:

    .venv/bin/python scripts/map_figure_smoke.py --base http://localhost:8002 \\
        /tools/pesticides/ /tools/pesticides/chemicals/gs65e/sulfur/

    --screenshots   a directory to save a screenshot per page into

On an entity page the choropleth is only the section map's `<noscript>`
fallback, which a scripting browser never draws: there the payload in the
fallback is checked and the live checks report themselves skipped. Every
check on a page runs even after one fails, except that a map that never
loads skips the checks that need it. The link check navigates away, so it
runs last, after the screenshot.

Each page gets a fresh browser: the explorer's static files aren't
cache-busted, so a reused profile could serve a stale script.
"""
import argparse
import os
import sys
import time
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

MAP_TIMEOUT = 40
SWAP_TIMEOUT = 20
COUNTY_COUNT = 8

# The live map figure (the module keeps one per container; these pages have
# exactly one).
JS_INSTANCE = """
var mod = window.SJVAirMapFigures;
if (!mod || typeof mod.instances !== 'function') return null;
var list = mod.instances();
return list && list.length ? list[0] : null;
"""

JS_MAP_LOADED = """
var inst = (function () { %s })();
return !!(inst && inst.map && inst.map.loaded() && inst.map.getLayer('areas-fill'));
""" % JS_INSTANCE

# The area nearest the container's centre that is drawn on bare canvas (not
# under the attribution or the logo) and carries a url, as an offset from
# the container's centre for a pointer action.
JS_PICK_AREA = """
var canvas = inst.map.getCanvas();
var rect = canvas.getBoundingClientRect();
var best = null;
inst.areas.features.forEach(function (feature) {
  var id = feature.properties.id;
  var anchor = inst.anchors[id];
  if (!anchor || !feature.properties.url) return;
  var p = inst.map.project(anchor);
  if (p.x < 2 || p.y < 2 || p.x > rect.width - 2 || p.y > rect.height - 2) return;
  if (document.elementFromPoint(rect.left + p.x, rect.top + p.y) !== canvas) return;
  var hit = inst.map.queryRenderedFeatures([p.x, p.y], { layers: ['areas-fill'] });
  if (!hit.some(function (f) { return f.id === id; })) return;
  var d = Math.hypot(p.x - rect.width / 2, p.y - rect.height / 2);
  if (!best || d < best.d) best = {
    id: id, label: feature.properties.label, url: feature.properties.url,
    dx: Math.round(p.x - rect.width / 2), dy: Math.round(p.y - rect.height / 2), d: d,
  };
});
return best;
"""

# The module's view of the page: the containers it claims (the inert copies
# an htmx history restore materialises inside <noscript> are not its), the
# maps it holds, the WebGL canvases those maps own, and the containers still
# waiting to be scrolled into view.
JS_COUNTS_FN = """
function () {
  var claimed = [].filter.call(document.querySelectorAll('.map-figure'), function (el) { return !el.closest('noscript'); });
  return {
    containers: claimed.length,
    maps: (window.SJVAirMapFigures.instances() || []).length,
    canvases: document.querySelectorAll('.map-figure canvas.maplibregl-canvas').length,
    pending: (window.SJVAirMapFigures.pending() || []).length,
  };
}
"""
JS_COUNTS = 'return (%s)();' % JS_COUNTS_FN


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
        self.warnings = []
        self.prepare()

    def prepare(self):
        # The Django Debug Toolbar (dev only) opens over the page and would
        # take the hit test at a county's centre. Hidden, not removed: its
        # own script expects the element.
        self.js("var djdt = document.getElementById('djDebug'); if (djdt) djdt.style.display = 'none';")

    def js(self, script, *args):
        return self.driver.execute_script(script, *args)

    def instance_js(self, expr, *args):
        """Evaluate `expr` with `inst` bound to the live map figure."""
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
        if self.has_container():
            self.scroll_to_map()
        ok = self.wait_for(JS_MAP_LOADED, timeout)
        self.timings['map_loaded_s'] = round(time.time() - started, 2)
        return ok

    def drain_console(self):
        """New console entries, split into errors (SEVERE) and warnings
        (WARNING). Third-party scripts on the page (the translate widget)
        are not the map's doing; anything served from this origin is. Only
        errors fail the run, but the warnings are kept so the console check
        can name them instead of passing over them in silence."""
        noise = ('favicon', 'DevTools')
        errors, warnings = [], []
        for entry in self.driver.get_log('browser'):
            message = entry['message']
            if any(word in message for word in noise):
                continue
            if entry['level'] not in ('SEVERE', 'WARNING'):
                continue
            # The message starts with the URL that logged it.
            if message.startswith('http') and not message.startswith(self.origin + '/'):
                continue
            (errors if entry['level'] == 'SEVERE' else warnings).append(message[:300])
        self.errors.extend(errors)
        self.warnings.extend(warnings)
        return errors

    def container(self):
        """The figure's container -- the one the module claims, not an
        inert <noscript> copy of it."""
        el = self.js("return [].filter.call(document.querySelectorAll('.map-figure'),"
                     " function (e) { return !e.closest('noscript'); })[0] || null;")
        if el is None:
            raise NoSuchElementException('no map figure container on this page')
        return el

    def has_container(self):
        return bool(self.js(JS_COUNTS)['containers'])

    def noscript_counties(self):
        """The number of features in the choropleth the section map keeps in
        its `<noscript>`. Scripting is on, so the fallback is inert text in
        the DOM, not markup: it is read out of the element's text."""
        return self.js("""
            var nodes = document.querySelectorAll('noscript');
            for (var i = 0; i < nodes.length; i++) {
              var text = nodes[i].textContent || '';
              if (text.indexOf('class="map-figure"') === -1) continue;
              var start = text.indexOf('{"type": "FeatureCollection"');
              if (start === -1) return -1;
              var end = text.indexOf('<\\/script>', start);
              try {
                return JSON.parse(text.slice(start, end === -1 ? undefined : end)).features.length;
              } catch (err) { return -1; }
            }
            return 0;
        """)

    def scroll_to_map(self):
        el = self.container()
        self.js("arguments[0].scrollIntoView({block: 'center'})", el)
        time.sleep(0.3)
        return el

    def hover_map(self, dx=0, dy=0, settle=0.8):
        el = self.scroll_to_map()
        ActionChains(self.driver, duration=100).move_to_element_with_offset(el, dx, dy).perform()
        time.sleep(settle)

    def click_map(self, dx=0, dy=0, settle=1.5):
        el = self.scroll_to_map()
        ActionChains(self.driver, duration=100).move_to_element_with_offset(el, dx, dy).click().perform()
        time.sleep(settle)

    def pick_area(self):
        self.scroll_to_map()
        return self.instance_js(JS_PICK_AREA)

    def sample_areas(self):
        """Each area's colour where it is drawn: the page is screenshotted,
        the PNG decoded back inside the page (the map's GL canvas keeps no
        drawing buffer to read from), and the pixel at each area's anchor
        read off it."""
        self.scroll_to_map()
        time.sleep(0.6)
        shot = 'data:image/png;base64,' + self.driver.get_screenshot_as_base64()
        return self.driver.execute_async_script("""
            var done = arguments[arguments.length - 1];
            var inst = (function () { %s })();
            var img = new Image();
            img.onload = function () {
              var canvas = document.createElement('canvas');
              canvas.width = img.width; canvas.height = img.height;
              var ctx = canvas.getContext('2d');
              ctx.drawImage(img, 0, 0);
              // The shot is of the viewport, possibly at a different scale.
              var scale = img.width / window.innerWidth;
              var rect = inst.map.getCanvas().getBoundingClientRect();
              var out = [];
              inst.areas.features.forEach(function (feature) {
                var anchor = inst.anchors[feature.properties.id];
                if (!anchor) return;
                var p = inst.map.project(anchor);
                if (p.x < 0 || p.y < 0 || p.x > rect.width || p.y > rect.height) return;
                var d = ctx.getImageData(Math.round((rect.left + p.x) * scale),
                                         Math.round((rect.top + p.y) * scale), 1, 1).data;
                out.push({ color: [d[0], d[1], d[2]], fillColor: feature.properties.fillColor });
              });
              done(out);
            };
            img.onerror = function () { done([]); };
            img.src = arguments[0];
        """ % JS_INSTANCE, shot)

    def screenshot(self, suffix=''):
        """Save a screenshot as <name><suffix>.png into the screenshots
        directory, when one was given."""
        if not self.screenshots:
            return
        os.makedirs(self.screenshots, exist_ok=True)
        # A page with no figure is still worth a picture: its section map,
        # whose <noscript> holds the choropleth, is what to look at there.
        self.js("""
            var el = [].filter.call(document.querySelectorAll('.map-figure'),
                                    function (e) { return !e.closest('noscript'); })[0]
                     || document.querySelector('.section-map');
            if (el) el.scrollIntoView({ block: 'center' });
        """)
        time.sleep(0.3)
        self.driver.save_screenshot(os.path.join(self.screenshots, self.name + suffix + '.png'))


def check_map_loaded(page):
    """The container becomes a live map with the areas layer on it. On a
    page whose only choropleth is the section map's `<noscript>` fallback
    (the entity pages), there is no container to draw into and the live
    checks are skipped; the fallback's own payload is checked instead."""
    if not page.has_container():
        counties = page.noscript_counties()
        ok = counties == COUNTY_COUNT
        return ok, 'noscript fallback only: %s counties in its payload (want %s)' % (counties, COUNTY_COUNT)
    if not page.wait_for_map():
        return False, 'no live map after %ss' % MAP_TIMEOUT
    count = page.js('return (window.SJVAirMapFigures.instances() || []).length')
    canvases = page.js("return document.querySelectorAll('.map-figure canvas.maplibregl-canvas').length")
    ok = count == 1 and canvases == 1
    return ok, 'instances %s, canvases %s, loaded in %ss' % (count, canvases, page.timings['map_loaded_s'])


def check_counties(page):
    """All eight counties are in the payload and drawn (hit-testable)."""
    if not page.has_container():
        return None, 'no live figure on this page'
    payload = page.instance_js('return inst.areas.features.length')
    drawn = page.instance_js("""
        var ids = {};
        inst.map.queryRenderedFeatures({ layers: ['areas-fill'] }).forEach(function (f) { ids[f.id] = 1; });
        return Object.keys(ids).length;
    """)
    labelled = page.instance_js("""
        return inst.areas.features.filter(function (f) { return /County/.test(f.properties.label || ''); }).length;
    """)
    ok = payload == COUNTY_COUNT and drawn == COUNTY_COUNT and labelled == COUNTY_COUNT
    return ok, 'payload %s, drawn %s, labelled %s (want %s)' % (payload, drawn, labelled, COUNTY_COUNT)


def check_paint(page):
    """The fill layer paints from the feature's own `fillColor`, so every
    county keeps its own choropleth shade. Checked against the drawn
    pixels, not just the expression: were the `get` not to resolve, every
    county would fall back to the same default fill."""
    if not page.has_container():
        return None, 'no live figure on this page'
    fill = page.instance_js("return JSON.stringify(inst.map.getPaintProperty('areas-fill', 'fill-color'))")
    shades = page.instance_js("""
        var seen = {};
        inst.areas.features.forEach(function (f) { seen[f.properties.fillColor] = 1; });
        return Object.keys(seen).length;
    """)
    drawn = page.sample_areas()
    distinct = len(set(tuple(c['color']) for c in drawn))
    # The extremes of the ramp, as drawn: light and dark must be far apart.
    lums = [luminance(c['color']) for c in drawn]
    spread = max(lums) - min(lums) if lums else 0
    ok = (fill == '["get","fillColor"]' and shades > 1
          and distinct >= shades - 1 and spread > 40)
    return ok, 'fill-color %s, %s shades in the payload, %s drawn, light-to-dark spread %s' % (
        fill, shades, distinct, round(spread))


def luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def check_cursor(page):
    """A county carrying a url shows a pointer cursor under the cursor."""
    if not page.has_container():
        return None, 'no live figure on this page'
    area = page.pick_area()
    if not area:
        return False, 'no county found on bare canvas'
    page.hover_map(area['dx'], area['dy'])
    cursor = page.instance_js('return inst.map.getCanvas().style.cursor')
    return cursor == 'pointer', '%s -> cursor %r' % (area['label'], cursor)


def check_hover_outline(page):
    """The county under the cursor takes the hover outline, and gives it up
    when the cursor leaves. Read off the feature state the paint expression
    keys on, so it proves the mechanism and not just a repaint."""
    if not page.has_container():
        return None, 'no live figure on this page'
    area = page.pick_area()
    if not area:
        return False, 'no county found on bare canvas'
    page.hover_map(area['dx'], area['dy'])
    on = page.instance_js("""
        var id = inst.areaHoverId;
        if (id == null) return null;
        var state = inst.map.getFeatureState({ source: 'areas', id: id });
        return { id: String(id), hover: state && state.hover === true };
    """)
    # Offsets are measured from the element's centre, so the corner is the
    # way off every county without leaving the map.
    size = page.scroll_to_map().size
    page.hover_map(-(size['width'] // 2) + 4, -(size['height'] // 2) + 4)
    off = page.instance_js('return inst.areaHoverId')
    if not on or not on['hover']:
        return False, '%s did not take the outline (state %r)' % (area['label'], on)
    if off is not None:
        return False, 'outline stayed on %r after the cursor left' % off
    return True, '%s outlined on hover, released on leave' % area['label']


def check_label(page):
    """The county's hover label opens while the cursor is over it, and
    closes when it leaves."""
    if not page.has_container():
        return None, 'no live figure on this page'
    area = page.pick_area()
    if not area:
        return False, 'no county found on bare canvas'
    page.hover_map(area['dx'], area['dy'])
    text = page.js("""
        var el = document.querySelector('.map-figure-label .maplibregl-popup-content');
        return el ? el.textContent.trim() : null;
    """)
    # Off the map entirely, so mouseleave fires on the fill layer.
    ActionChains(page.driver, duration=100).move_to_element_with_offset(
        page.driver.find_element(By.TAG_NAME, 'body'), 5, 5).perform()
    time.sleep(0.6)
    gone = page.js("return document.querySelectorAll('.map-figure-label').length === 0")
    ok = bool(text) and text == area['label'] and gone
    return ok, 'label %r (want %r), closed %s' % (text, area['label'], gone)


def check_htmx_round_trip(page):
    """An htmx navigation away and back leaves one live map per container
    and no more: the map whose container the swap took away is released,
    the one the new content brings is built. Run three times over, because
    a history restore re-runs the page's scripts and a second copy of the
    module would only show up on the round trip after it."""
    counts = page.js(JS_COUNTS)
    counts.pop('pending')
    if counts['maps'] != counts['containers'] or counts['canvases'] != counts['containers']:
        return False, 'before: %s' % counts
    away_path = '/chemicals/'
    here = urlparse(page.driver.current_url).path
    for _ in range(3):
        tab = page.driver.find_element(By.CSS_SELECTOR, '#explorer-tabs a[href*="%s"]' % away_path)
        page.js("arguments[0].scrollIntoView({block: 'center'})", tab)
        tab.click()
        if not page.wait_for("return window.location.pathname === %r && !document.querySelector('.htmx-request')"
                             % tab.get_attribute('pathname'), SWAP_TIMEOUT):
            return False, 'the swap to %s never landed' % away_path
        time.sleep(1.0)
        # The swap took this page's containers out of the document, so
        # their maps must have been released with them.
        gone = page.js(JS_COUNTS)
        gone.pop('containers')
        page.driver.back()
        if not page.wait_for("return window.location.pathname === %r && !document.querySelector('.htmx-request')" % here,
                             SWAP_TIMEOUT):
            return False, 'the way back to %s never landed' % here
        if not page.wait_for('return (%s)().containers === arguments[0];' % JS_COUNTS_FN,
                             SWAP_TIMEOUT, counts['containers']):
            return False, 'the restored page brought back %s containers, not %s' % (
                page.js(JS_COUNTS)['containers'], counts['containers'])
        if counts['containers'] and not page.wait_for_map():
            return False, 'no live map after coming back'
        time.sleep(1.0)
        back = page.js(JS_COUNTS)
        if gone != {'maps': 0, 'canvases': 0, 'pending': 0}:
            return False, 'away left %s' % gone
        if back != dict(counts, pending=0):
            return False, 'back left %s (want %s)' % (back, dict(counts, pending=0))
    return True, '3x away (0 maps, 0 canvases) -> back (%s map, %s canvas) per container' % (
        counts['maps'], counts['canvases'])


# A copy of the page's figure, container and payload alike, dropped into a
# `display: none` wrapper at the end of the document: the shape the Region
# admin renders its boundary figures in, inside a collapsed fieldset.
JS_ADD_HIDDEN = """
var source = [].filter.call(document.querySelectorAll('.map-figure'),
                            function (e) { return !e.closest('noscript'); })[0];
if (!source) return false;
var data = document.getElementById(source.dataset.geojson);
if (!data) return false;
var payload = document.createElement('script');
payload.type = 'application/json';
payload.id = 'smoke-hidden-geojson';
payload.textContent = data.textContent;
var el = document.createElement('div');
el.id = 'smoke-hidden-map';
el.className = 'map-figure';
el.style.width = '400px';
el.style.height = '300px';
el.dataset.geojson = 'smoke-hidden-geojson';
el.dataset.style = source.dataset.style || 'dataviz';
el.dataset.maptilerKey = source.dataset.maptilerKey || '';
el.dataset.padding = source.dataset.padding || '20';
el.dataset.zoom = source.dataset.zoom || '14';
var wrap = document.createElement('div');
wrap.id = 'smoke-hidden-wrap';
wrap.style.display = 'none';
wrap.appendChild(payload);
wrap.appendChild(el);
document.body.appendChild(wrap);
window.SJVAirMapFigures.init(document);
return true;
"""

# The figure built for that container, once there is one.
JS_HIDDEN_INSTANCE = """
return (window.SJVAirMapFigures.instances() || []).filter(function (f) {
  return f.el && f.el.id === 'smoke-hidden-map';
})[0] || null;
"""

JS_HIDDEN_DRAWN = """
var inst = (function () { %s })();
if (!inst || !inst.map || !inst.map.loaded() || !inst.map.getLayer('areas-fill')) return 0;
return inst.map.queryRenderedFeatures({ layers: ['areas-fill'] }).length;
""" % JS_HIDDEN_INSTANCE


def check_hidden_container(page):
    """A figure inside a `display: none` subtree waits, then builds when it
    is revealed. This is the Region admin's shape -- its BoundaryInline is a
    collapsed fieldset, so those containers start hidden and only come into
    view when someone expands the section -- and the admin needs a login
    this script has no credentials for, so it is reproduced here on a public
    page: a copy of this page's container and payload in a hidden wrapper,
    handed to the module, then revealed."""
    if not page.has_container():
        return None, 'no live figure to copy on this page'
    before = page.js(JS_COUNTS)
    if not page.js(JS_ADD_HIDDEN):
        return False, 'could not copy the page figure into a hidden wrapper'
    try:
        # IntersectionObserver delivers asynchronously, so give it a beat
        # before concluding nothing was built.
        time.sleep(1.5)
        hidden = page.js(JS_COUNTS)
        if hidden['maps'] != before['maps'] or hidden['pending'] != before['pending'] + 1:
            return False, 'while hidden: %s (want %s maps, %s pending)' % (
                hidden, before['maps'], before['pending'] + 1)

        page.js("""
            var wrap = document.getElementById('smoke-hidden-wrap');
            wrap.style.display = '';
            document.getElementById('smoke-hidden-map').scrollIntoView({ block: 'center' });
        """)
        drawn = 0
        deadline = time.time() + MAP_TIMEOUT
        while time.time() < deadline:
            drawn = page.js(JS_HIDDEN_DRAWN)
            if drawn:
                break
            time.sleep(0.2)
        if not drawn:
            return False, 'revealed but nothing drawn after %ss' % MAP_TIMEOUT
        shown = page.js(JS_COUNTS)
        ok = shown['maps'] == before['maps'] + 1 and shown['pending'] == before['pending']
        return ok, 'hidden: %s maps; revealed: %s maps, %s areas drawn' % (
            hidden['maps'], shown['maps'], drawn)
    finally:
        # The page's own checks count maps and canvases, so the copy goes
        # away again: detached, it is the module's sweep that releases it.
        page.js("""
            var wrap = document.getElementById('smoke-hidden-wrap');
            if (wrap) wrap.remove();
            window.SJVAirMapFigures.init(document);
        """)
        time.sleep(0.5)


def check_link(page):
    """A click on a county follows its url. Navigates away, so it runs last."""
    if not page.has_container():
        return None, 'no live figure on this page'
    area = page.pick_area()
    if not area:
        return False, 'no county found on bare canvas'
    page.click_map(area['dx'], area['dy'])
    landed = page.wait_for('return window.location.pathname', SWAP_TIMEOUT)
    path = page.js('return window.location.pathname + window.location.search')
    want = urlparse(area['url']).path
    ok = bool(landed) and path.startswith(want)
    return ok, 'click %s -> %s (want %s)' % (area['label'], path, want)


def check_console(page):
    """Same-origin console output over the whole run. Errors fail the
    check; warnings only get reported, so a new one is visible here rather
    than silently tolerated."""
    page.drain_console()
    detail = []
    if page.errors:
        detail.append('%s error(s):' % len(page.errors))
        detail.extend(page.errors)
    if page.warnings:
        detail.append('%s warning(s) (not failing):' % len(page.warnings))
        detail.extend(page.warnings)
    if not detail:
        detail = ['no errors, no warnings']
    return (not page.errors), '\n      '.join(detail)


CHECKS = [
    ('map loaded', check_map_loaded),
    ('counties', check_counties),
    ('paint', check_paint),
    ('cursor', check_cursor),
    ('hover outline', check_hover_outline),
    ('label', check_label),
    ('htmx round trip', check_htmx_round_trip),
    ('hidden container', check_hidden_container),
    ('link', check_link),
    ('console', check_console),
]


def run_page(base, path, screenshots):
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
        for label, check in CHECKS:
            if failed and label != 'console':
                rows.append((label, None, 'skipped'))
                continue
            try:
                # The screenshot, before the link check navigates away.
                if check is check_link:
                    page.screenshot()
                passed, detail = check(page)
            except Exception as err:  # a broken page must still report
                passed, detail = False, 'raised %s: %s' % (type(err).__name__, err)
            try:
                page.drain_console()
            except Exception:
                pass
            rows.append((label, passed, detail))
            if not passed and label == 'map loaded':
                failed = True
        return url, rows, page.timings
    finally:
        driver.quit()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('paths', nargs='+', help='page paths under --base, e.g. /tools/pesticides/')
    parser.add_argument('--base', default='http://localhost:8002')
    parser.add_argument('--screenshots', help='directory for a screenshot per page')
    args = parser.parse_args(argv)

    any_failed = False
    for path in args.paths:
        url, rows, timings = run_page(args.base, path, args.screenshots)
        print('\n%s' % url)
        # Keys end in their unit: `_s` or `_ms`.
        print('  ' + ', '.join('%s %s%s' % (key.rsplit('_', 1)[0].replace('_', ' '), value, key.rsplit('_', 1)[1]) for key, value in timings.items()))
        for label, passed, detail in rows:
            status = 'PASS' if passed else ('SKIP' if passed is None else 'FAIL')
            print('  %-4s %-16s %s' % (status, label, detail))
            if passed is False:
                any_failed = True
    print()
    return 1 if any_failed else 0


if __name__ == '__main__':
    sys.exit(main())
