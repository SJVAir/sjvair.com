"""
Headless smoke test for the Facility Emissions Explorer's map.

Loads the map page and a few compact-map pages in headless Chrome, waits for
the facilities to draw (`data-loaded="1"` on the container), checks features
were drawn, switches the map page's sector filter and waits for the redraw,
follows a boosted tab link and back to check the live map is adopted rather
than rebuilt, then runs the Areas view (ZIP areas shaded, facilities hidden,
the view in the URL, tracts, a measure change, back to facilities), a county
page (outlined, and a boosted year change keeping one map still in Areas) and
a near-me page (its circle), and checks the scope bar's boosted swaps carry
the map's current state (back to Facilities, a cleared sector, no repeated
parameters). The toxics scope: the cancer-weighted default (legend, a popup
as a percent of the Valley total, Areas limited to Total) and benzene in
pounds. The Oil & gas wells overlay: off until ticked, clusters over Kern, a
cluster zoom, a well's popup with its as-of date, the legend's snapshot note,
and Kern County's page with it on and its wells section. Then the Dairies tab: its two views (dairies drawn, counties
shaded), an Options menu with Tiles only (a size filter surviving the style
swap, tiles= in the URL), a measure change redrawing the legend, a sort (a
boosted swap) keeping Counties and its measure, a table row's name zooming to its dairy
with its popup, a county narrowing the dairies, and the NOx / 2024 fallback
notes, and the Methane sources overlay: off until ticked,
loads the layer and writes ?methane=1, draws the plume images, a legend and
map without a repeated Carbon Mapper credit (it's on the About and data
provider pages), and a plume's popup with its rate, passes and dated
stepper (needs import_carbon_mapper on this DB; skipped otherwise). Last,
a county page in 2023 maps its facilities (sized circles, the
plain legend with a size key -- dairies were removed from this map; the
Dairies tab is the only place they're mapped), and the Dairies tab's own
charts. Then the dairy pages: Tulare County's (outlined, Dairies only, its
three charts, a row zooming to its dairy with its popup, a boosted year
change keeping one outlined map), a community dairy page (outlined, every
drawn dairy in the table's count, a dairy under the wash still opening its
popup), and near-me dairies (the circle, a radius button keeping the page).
Then the tab's `?region=` redirecting to the region's dairy page and its
find box landing on a county dairy page, and Tulare County's emissions page
showing the Dairies section as a summary only, linking to the dairy page,
with its section nav unchanged. Fails on any console error. Dev-only;
nothing here runs in CI. Needs local data (import_air_districts,
import_ceidars, import_cepam, import_cadd, and the regions with their
boundaries); the methane overlay checks additionally need
import_carbon_mapper and are skipped (not failed) without it.

Setup (Chrome must be installed):
    python3 -m venv .venv && .venv/bin/pip install selenium
Usage:
    .venv/bin/python scripts/emissions_map_smoke.py --base http://localhost:8003
"""
import argparse
import sys
import time
from urllib.parse import parse_qs, urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

MAP_TIMEOUT = 40


def browser():
    opts = Options()
    opts.add_argument('--headless=new')
    opts.add_argument('--window-size=1400,1000')
    # Software WebGL: the SDK map needs a GL context and headless has no GPU.
    opts.add_argument('--use-gl=angle')
    opts.add_argument('--use-angle=swiftshader')
    opts.add_argument('--enable-unsafe-swiftshader')
    opts.add_argument('--ignore-gpu-blocklist')
    opts.add_argument('--disable-application-cache')
    opts.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    return webdriver.Chrome(options=opts)


def wait_loaded(driver, timeout=MAP_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if driver.execute_script("var el = document.querySelector('.facility-map'); return !!el && el.dataset.loaded === '1';"):
            return True
        time.sleep(0.25)
    return False


def feature_count(driver):
    return driver.execute_script(
        "var m = window.EmissionsFacilityMap.instances()[0];"
        "return m ? m.map.querySourceFeatures('facilities').length : 0;"
    )


def wait_style_loaded(driver, timeout=MAP_TIMEOUT):
    """After a tiles change (map.setStyle): the SDK is back and addLayers()
    has re-added our sources and layers from cached data."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if driver.execute_script(
                "var m = window.EmissionsFacilityMap.instances()[0];"
                "return !!m && m.map.isStyleLoaded() && !!m.map.getLayer('facilities');"):
            return True
        time.sleep(0.25)
    return False


def wait_dairy_style_loaded(driver, timeout=MAP_TIMEOUT):
    """After a tiles change on the Dairies tab: the SDK is back and addLayers()
    has re-added the dairies/counties sources and layers from cached data."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if driver.execute_script(
                "var m = window.EmissionsDairyMap.instances()[0];"
                "return !!m && m.map.isStyleLoaded() && !!m.map.getLayer('dairies');"):
            return True
        time.sleep(0.25)
    return False


def facility_color(driver):
    """A rendered facility's `_color` (its GeoJSON properties, not paint):
    changes when the Ramp select picks a different colour ramp."""
    return driver.execute_script(
        "var m = window.EmissionsFacilityMap.instances()[0];"
        "var f = m.map.querySourceFeatures('facilities').find(function (x) { return x.properties._empty === 0; });"
        "return f ? f.properties._color : null;"
    )


def legend_swatch_color(driver):
    return driver.execute_script(
        "var el = document.querySelector('.facility-map-legend .legend-swatch');"
        "return el ? el.style.background : null;"
    )


def wait_areas(driver, timeout=MAP_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if driver.execute_script("var el = document.querySelector('.facility-map'); return !!el && el.dataset.areasLoaded === '1';"):
            return True
        time.sleep(0.25)
    return False


def area_count(driver):
    return driver.execute_script(
        "var m = window.EmissionsFacilityMap.instances()[0];"
        "return m ? m.map.querySourceFeatures('areas').filter(function (f) { return f.properties._empty === 0; }).length : 0;"
    )


def wait_dairies(driver, timeout=MAP_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if driver.execute_script("var el = document.querySelector('.dairy-map'); return !!el && el.dataset.loaded === '1';"):
            return True
        time.sleep(0.25)
    return False


def wait_for(driver, script, timeout=MAP_TIMEOUT):
    """Polls `execute_script(script)` until it's truthy."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if driver.execute_script(script):
            return True
        time.sleep(0.25)
    return False


def dairy_count(driver):
    return driver.execute_script(
        "var m = window.EmissionsDairyMap.instances()[0];"
        "return m ? m.map.querySourceFeatures('dairies').length : 0;"
    )


def dairy_count_unique(driver):
    # querySourceFeatures can return the same point more than once when it's
    # drawn from more than one loaded tile (a MapLibre GL caveat, not a
    # drawing bug); dedupe by id for an exact count.
    return driver.execute_script(
        "var m = window.EmissionsDairyMap.instances()[0], seen = {};"
        "if (!m) return 0;"
        "m.map.querySourceFeatures('dairies').forEach(function (f) { seen[f.properties.id] = 1; });"
        "return Object.keys(seen).length;"
    )


def shaded_counties(driver):
    return driver.execute_script(
        "var m = window.EmissionsDairyMap.instances()[0];"
        "return m ? m.map.querySourceFeatures('counties').filter(function (f) { return f.properties._empty === 0; }).length : 0;"
    )


def settled_count(driver, count, timeout=5):
    """`count(driver)` once it's above zero: the SDK redraws a source's tiles
    a frame or so after a setData or a visibility change, and until then it
    reads the old tiles."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = count(driver)
        if value > 0:
            return value
        time.sleep(0.25)
    return count(driver)


def pick_year(driver, nth):
    """Picks the nth year in the scope bar (a boosted swap) and waits for the redraw."""
    driver.find_element(By.CSS_SELECTOR, '.explorer-scope-picker[data-scope=year] .button').click()
    driver.find_element(By.CSS_SELECTOR, f'.explorer-scope-picker[data-scope=year] .dropdown-item:nth-child({nth})').click()
    time.sleep(1)
    wait_loaded(driver)


def query(driver):
    return parse_qs(urlparse(driver.current_url).query)


def no_repeats(driver):
    return all(len(values) == 1 for values in query(driver).values())


# A canvas pixel over a facility circle that the wash outside the page's area
# also covers, clear of the chrome: [x, y] from the canvas centre, or null.
CIRCLE_UNDER_WASH = """
var m = window.EmissionsFacilityMap.instances()[0], map = m.map, c = map.getCanvas(), r = c.getBoundingClientRect();
for (var y = 60; y < r.height - 30; y += 5) for (var x = 20; x < r.width - 20; x += 5) {
  if (!map.queryRenderedFeatures([x, y], {layers: ['facilities']}).length) continue;
  if (!map.queryRenderedFeatures([x, y], {layers: ['outline-mask']}).length) continue;
  if (document.elementFromPoint(r.left + x, r.top + y) !== c) continue;
  return [x - r.width / 2, y - r.height / 2];
}
return null;
"""

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

# A canvas pixel over a shaded county (one with a value, not the empty grey),
# clear of the chrome: [x, y] from the canvas centre, or null.
COUNTY_PIXEL = """
var m = window.EmissionsDairyMap.instances()[0], map = m.map, c = map.getCanvas(), r = c.getBoundingClientRect();
for (var y = 60; y < r.height - 30; y += 5) for (var x = 20; x < r.width - 20; x += 5) {
  var f = map.queryRenderedFeatures([x, y], {layers: ['counties-fill']});
  if (!f.length || f[0].properties._empty !== 0) continue;
  if (document.elementFromPoint(r.left + x, r.top + y) !== c) continue;
  return [x - r.width / 2, y - r.height / 2];
}
return null;
"""

# A canvas pixel over a shaded area (X5), clear of the chrome: [x, y] from
# the canvas centre, or null.
AREA_PIXEL = """
var m = window.EmissionsFacilityMap.instances()[0], map = m.map, c = map.getCanvas(), r = c.getBoundingClientRect();
for (var y = 60; y < r.height - 30; y += 5) for (var x = 20; x < r.width - 20; x += 5) {
  var f = map.queryRenderedFeatures([x, y], {layers: ['areas-fill']});
  if (!f.length || f[0].properties._empty !== 0) continue;
  if (document.elementFromPoint(r.left + x, r.top + y) !== c) continue;
  return [x - r.width / 2, y - r.height / 2];
}
return null;
"""


def console_errors(driver):
    return [entry['message'] for entry in driver.get_log('browser') if entry['level'] == 'SEVERE']


def check(results, name, passed, detail=''):
    results.append((name, passed, detail))
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://localhost:8003')
    args = parser.parse_args()
    results = []

    driver = browser()
    try:
        driver.get(args.base + '/tools/emissions/map/')
        check(results, 'map page loads facilities', wait_loaded(driver))
        drawn = settled_count(driver, feature_count)
        check(results, 'map page draws features', drawn > 0, f'{drawn} features')
        instance = driver.execute_script('return window.EmissionsFacilityMap.instances()[0].map._mapId || 1;')

        # Options menu: Tiles and Ramp (X8). Picking a ramp recolours the
        # facilities layer and the legend, and writes ?ramp=; picking a tile
        # style swaps the basemap and redraws the facilities, and writes
        # ?tiles=; a reload restores both.
        driver.find_element(By.CSS_SELECTOR, '.map-wrap .map-options .dropdown-trigger .button').click()
        time.sleep(0.3)
        ramp_select = driver.find_element(By.CSS_SELECTOR, '.facility-map-options select[name="ramp"]')
        tiles_select = driver.find_element(By.CSS_SELECTOR, '.facility-map-options select[name="tiles"]')
        ramp_values = [o.get_attribute('value') for o in ramp_select.find_elements(By.TAG_NAME, 'option')]
        tile_values = [o.get_attribute('value') for o in tiles_select.find_elements(By.TAG_NAME, 'option')]
        check(results, 'Options menu lists ramp and tile choices', len(ramp_values) > 1 and len(tile_values) > 1,
              f'{len(ramp_values)} ramps, {len(tile_values)} tiles')

        before_color = facility_color(driver)
        before_swatch = legend_swatch_color(driver)
        # 'purd' (magenta) reliably differs from the default 'steelblue' at
        # every class, unlike some sequential candidates that share a stop.
        other_ramp = 'purd' if 'purd' in ramp_values else next(v for v in ramp_values if v != ramp_select.get_attribute('value'))
        Select(ramp_select).select_by_value(other_ramp)
        time.sleep(0.4)
        after_color = facility_color(driver)
        after_swatch = legend_swatch_color(driver)
        check(results, 'choosing a ramp recolours the facilities layer and the legend, and writes ramp=',
              before_color != after_color and before_swatch != after_swatch and f'ramp={other_ramp}' in driver.current_url,
              f'{before_color} -> {after_color}; {driver.current_url}')

        other_tile = next(v for v in tile_values if v != tiles_select.get_attribute('value'))
        Select(tiles_select).select_by_value(other_tile)
        time.sleep(0.3)
        style_loaded = wait_style_loaded(driver)
        redrawn = settled_count(driver, feature_count)
        check(results, 'choosing tiles swaps the style, redraws the facilities, and writes tiles=',
              style_loaded and redrawn > 0 and f'tiles={other_tile}' in driver.current_url,
              f'{redrawn} features; {driver.current_url}')

        reload_url = driver.current_url
        driver.get(reload_url)
        check(results, 'reloading with tiles= and ramp= loads facilities', wait_loaded(driver))
        restored = driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0];"
            "return {ramp: m.rampName, tiles: m.tileStyle};")
        check(results, 'reloading restores the chosen tiles and ramp',
              restored['ramp'] == other_ramp and restored['tiles'] == other_tile, str(restored))

        driver.get(args.base + '/tools/emissions/map/')
        check(results, 'map page loads facilities (Options reset)', wait_loaded(driver))

        driver.find_element(By.CSS_SELECTOR, '.facility-map-sector .dropdown-trigger .button').click()
        driver.find_element(By.CSS_SELECTOR, '.facility-map-sector [data-sector="glass"]').click()
        time.sleep(0.5)
        check(results, 'sector filter redraws', wait_loaded(driver) and 'sector=glass' in driver.current_url, driver.current_url)

        driver.find_element(By.CSS_SELECTOR, '.explorer-scope-picker[data-scope=pollutant] .button').click()
        driver.find_element(By.CSS_SELECTOR, '.explorer-scope-picker[data-scope=pollutant] .dropdown-item:nth-child(2)').click()
        time.sleep(1)
        check(results, 'pollutant change (boosted swap) reloads', wait_loaded(driver))
        same = driver.execute_script('return window.EmissionsFacilityMap.instances().length === 1;')
        check(results, 'one live map after the swap', same, str(instance))

        driver.get(args.base + '/tools/emissions/facilities/')
        link = driver.find_element(By.CSS_SELECTOR, '.facility-table tbody a').get_attribute('href')
        driver.get(link)
        check(results, 'facility page compact map loads', wait_loaded(driver))

        driver.get(args.base + '/tools/emissions/sectors/power-plants/')
        check(results, 'sector page compact map loads', wait_loaded(driver))

        driver.get(args.base + '/tools/emissions/map/')
        wait_loaded(driver)
        controls = driver.execute_script(
            "return ['.map-locate', '.map-reset', '.map-expand', '.map-legend-panel']"
            ".map(function (s) { return !!document.querySelector(s); });"
        )
        check(results, 'locate, home, expand and legend present', all(controls), str(controls))
        driver.execute_script("document.querySelector('.map-expand').click()")
        expanded = driver.execute_script("return document.documentElement.classList.contains('map-expanded');")
        check(results, 'expand fills the viewport', expanded)

        driver.get(args.base + '/tools/emissions/map/')
        wait_loaded(driver)
        driver.execute_script("document.querySelector('.facility-map-view [data-view=areas]').click()")
        shaded = settled_count(driver, area_count) if wait_areas(driver) else 0
        check(results, 'areas view shades ZIP areas', shaded > 0, f'{shaded} shaded')
        check(results, 'areas view hides the facilities', driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0]; return m.map.getLayoutProperty('facilities', 'visibility') === 'none';"))

        # Hovering an area (a real mouse move, not a synthetic event) sets its
        # hover feature-state, and it clears once the cursor leaves the map (X5).
        driver.execute_script("document.querySelector('.facility-map canvas').scrollIntoView({block: 'center'});")
        time.sleep(0.3)
        area_hit = driver.execute_script(AREA_PIXEL)
        if area_hit:
            canvas = driver.find_element(By.CSS_SELECTOR, '.facility-map canvas')
            ActionChains(driver).move_to_element_with_offset(canvas, int(area_hit[0]), int(area_hit[1])).perform()
            time.sleep(0.5)
        hovered = driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0];"
            "return m.map.querySourceFeatures('areas').some(function (f) {"
            "  return !!m.map.getFeatureState({source: 'areas', id: f.id}).hover;"
            "});")
        check(results, 'hovering an area sets hover feature state', bool(area_hit) and hovered)
        ActionChains(driver).move_to_element(driver.find_element(By.CSS_SELECTOR, '.navbar-brand')).perform()
        time.sleep(0.5)
        cleared = driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0];"
            "return m.map.querySourceFeatures('areas').every(function (f) {"
            "  return !m.map.getFeatureState({source: 'areas', id: f.id}).hover;"
            "});")
        check(results, 'moving off the map clears the area hover state', cleared)

        check(results, 'view is in the URL', 'view=areas' in driver.current_url, driver.current_url)
        check(results, 'default level and measure stay out of the URL',
              'level=' not in driver.current_url and 'measure=' not in driver.current_url, driver.current_url)
        driver.execute_script("document.querySelector('.facility-map-level [data-level=tract]').click()")
        shaded = settled_count(driver, area_count) if wait_areas(driver) else 0
        check(results, 'level switches to tracts', shaded > 0 and 'level=tract' in driver.current_url, f'{shaded} shaded')
        driver.execute_script("document.querySelector('.facility-map-measure [data-measure=total]').click()")
        time.sleep(0.5)
        legend = driver.execute_script("return document.querySelector('.facility-map-legend .legend-title').textContent;")
        check(results, 'measure changes the legend', 'per sq mi' not in legend, legend)
        driver.execute_script("document.querySelector('.facility-map-view [data-view=facilities]').click()")
        check(results, 'back to facilities', settled_count(driver, feature_count) > 0 and 'view=' not in driver.current_url)

        # Opened in Areas, so the scope bar's links carry view=areas.
        driver.get(args.base + '/tools/emissions/map/?view=areas')
        wait_loaded(driver)
        wait_areas(driver)
        driver.execute_script("document.querySelector('.facility-map-view [data-view=facilities]').click()")
        pick_year(driver, 2)
        stays = driver.execute_script("return window.EmissionsFacilityMap.instances()[0].view === 'facilities';")
        check(results, 'Areas, back to Facilities, a year change: stays in Facilities',
              stays and 'view=' not in driver.current_url, driver.current_url)

        # Opened on glass, so the scope bar's links carry sector=glass.
        driver.get(args.base + '/tools/emissions/map/?sector=glass')
        wait_loaded(driver)
        driver.execute_script("document.querySelector('.facility-map-sector [data-sector=\"\"]').click()")
        wait_loaded(driver)
        pick_year(driver, 3)
        unfiltered = driver.execute_script(
            "return new URLSearchParams(window.EmissionsFacilityMap.instances()[0].data.query).get('sector') === null;")
        check(results, 'glass, then All sectors, a year change: no sector',
              unfiltered and 'sector=' not in driver.current_url, driver.current_url)

        # Areas, then Facilities, pick a sector, back to Areas: the areas
        # values must be refetched for the new sector rather than reusing
        # the stale all-sector cache (I1).
        driver.get(args.base + '/tools/emissions/map/?view=areas')
        wait_loaded(driver)
        wait_areas(driver)
        driver.execute_script("document.querySelector('.facility-map-view [data-view=facilities]').click()")
        wait_loaded(driver)
        driver.find_element(By.CSS_SELECTOR, '.facility-map-sector .dropdown-trigger .button').click()
        driver.find_element(By.CSS_SELECTOR, '.facility-map-sector [data-sector="glass"]').click()
        time.sleep(0.5)
        driver.execute_script("performance.clearResourceTimings();")
        driver.execute_script("document.querySelector('.facility-map-view [data-view=areas]').click()")
        wait_areas(driver)
        areas_request = driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0];"
            "var entries = performance.getEntriesByType('resource').filter(function (e) { return e.name.indexOf(m.data.areasUrl) !== -1; });"
            "return entries.length ? entries[entries.length - 1].name : '';")
        check(results, 'sector change in Facilities, back to Areas: areas refetch carries sector',
              'sector=glass' in areas_request, areas_request)

        driver.get(args.base + '/tools/emissions/')
        link = driver.find_element(By.CSS_SELECTOR, '.find-area-counties a').get_attribute('href')
        driver.get(link)
        outlined = wait_loaded(driver) and driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0]; return !!m.outlineBounds;")
        check(results, 'county page loads, outlined', outlined, link)
        settled_count(driver, feature_count)
        # The map sits below the header and stats box: bring it on screen
        # before finding a point to click, or the click can land off the
        # viewport (same fix as the county dairy-popup check below).
        driver.execute_script("document.querySelector('.facility-map').scrollIntoView({block: 'center'});")
        time.sleep(0.5)
        hit = driver.execute_script(CIRCLE_UNDER_WASH)
        if hit:
            canvas = driver.find_element(By.CSS_SELECTOR, '.facility-map canvas')
            ActionChains(driver).move_to_element_with_offset(canvas, int(hit[0]), int(hit[1])).click().perform()
            time.sleep(0.8)
        opened = driver.execute_script("return !!document.querySelector('.maplibregl-popup .facility-popup-name a');")
        check(results, 'a facility under the wash still opens its popup', bool(hit) and opened, str(hit))
        driver.execute_script("var p = document.querySelector('.maplibregl-popup-close-button'); if (p) p.click();")
        driver.execute_script("document.querySelector('.facility-map-view [data-view=areas]').click()")
        wait_areas(driver)
        driver.find_element(By.CSS_SELECTOR, '.explorer-scope-picker[data-scope=year] .button').click()
        driver.find_element(By.CSS_SELECTOR, '.explorer-scope-picker[data-scope=year] .dropdown-item:nth-child(2)').click()
        time.sleep(1)
        kept = wait_areas(driver) and driver.execute_script(
            "var list = window.EmissionsFacilityMap.instances(); return list.length === 1 && list[0].view === 'areas';")
        check(results, 'a year change (boosted swap) keeps one map, still in Areas', kept and 'view=areas' in driver.current_url, driver.current_url)
        pick_year(driver, 3)
        wait_areas(driver)
        check(results, 'two year changes in Areas repeat no parameter',
              no_repeats(driver) and query(driver).get('view') == ['areas'], driver.current_url)

        driver.get(args.base + '/tools/emissions/near/?lat=36.7378&lng=-119.7871&radius=3')
        near = wait_loaded(driver) and driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0]; return !!m.outlineBounds;")
        check(results, 'near-me page loads, with its circle', near)

        # The radius buttons must carry the map's live state (M5), same as
        # the scope bar: switch to Areas, then follow a radius button.
        driver.execute_script("document.querySelector('.facility-map-view [data-view=areas]').click()")
        wait_areas(driver)
        driver.find_element(By.CSS_SELECTOR, '.radius-switcher a').click()
        time.sleep(1)
        stayed = wait_areas(driver) and driver.execute_script(
            "var list = window.EmissionsFacilityMap.instances(); return list.length === 1 && list[0].view === 'areas';")
        check(results, 'near-me radius button keeps Areas view', stayed and 'view=areas' in driver.current_url, driver.current_url)

        # Toxics scope: the default is the cancer-weighted share; the legend
        # names it, the popup prints a percent, and the Areas view only
        # offers Total.
        driver.get(args.base + '/tools/emissions/map/?toxics=1')
        check(results, 'toxics map loads (cancer-weighted default)', wait_loaded(driver) and settled_count(driver, feature_count) > 0)
        legend = driver.execute_script("return document.querySelector('.facility-map-legend').textContent;")
        check(results, 'the legend names the share measure and its year',
              'Share of Valley cancer-weighted toxics' in legend and '%' in legend and 'Not a health risk' in legend, legend[:200])
        check(results, 'the URL carries no pollutant (cancer is the default)', 'pollutant=' not in driver.current_url, driver.current_url)
        # Open the largest facility's popup from its feature.
        popup = driver.execute_script("""
            var m = window.EmissionsFacilityMap.instances()[0];
            var fs = m.map.querySourceFeatures('facilities').filter(function (f) { return f.properties.value > 0; });
            fs.sort(function (a, b) { return b.properties.value - a.properties.value; });
            if (!fs.length) return '';
            m.openPopup(fs[0], fs[0].geometry.coordinates);
            var el = document.querySelector('.facility-popup');
            return el ? el.textContent : '';
        """)
        check(results, 'a popup shows the share as a percent of the Valley total', '% of Valley total' in popup and '#1' in popup, popup[:160])
        driver.get(args.base + '/tools/emissions/map/?toxics=1&view=areas&measure=density')
        check(results, 'areas view for a share forces Total and disables density', wait_areas(driver) and 'measure=' not in driver.current_url.replace('measure=total', '')
              and driver.execute_script("return document.querySelectorAll('.facility-map-measure .dropdown-item.is-disabled').length;") == 2, driver.current_url)
        legend = driver.execute_script("return document.querySelector('.facility-map-legend .legend-title').textContent;")
        check(results, 'the areas legend is the share title', 'Share of Valley cancer-weighted toxics' in legend, legend)
        # One toxic in pounds still works, and the old key redirects to it.
        driver.get(args.base + '/tools/emissions/map/?toxics=1&pollutant=benzene')
        check(results, 'benzene in pounds', wait_loaded(driver) and 'lbs/yr' in driver.execute_script("return document.querySelector('.facility-map-legend').textContent;"))

        # The Oil & gas wells overlay: off on the map page until ticked, then
        # clustered over Kern; a cluster click zooms, a well click fetches its
        # record; the state lands in the URL; Kern County's page has it on.
        driver.get(args.base + '/tools/emissions/map/')
        check(results, 'map loads with the wells overlay off', wait_loaded(driver)
              and driver.execute_script("return window.EmissionsFacilityMap.instances()[0].wells;") is False
              and driver.execute_script("return !!document.querySelector('.facility-map-legend [data-wells]');"))
        driver.execute_script("window.EmissionsFacilityMap.instances()[0].setWells(true);")
        deadline = time.time() + MAP_TIMEOUT
        while time.time() < deadline and driver.execute_script(
                "return document.querySelector('.facility-map').dataset.wellsLoaded;") != '1':
            time.sleep(0.25)
        check(results, 'ticking the overlay loads the wells and writes wells=1',
              driver.execute_script("return document.querySelector('.facility-map').dataset.wellsLoaded;") == '1'
              and query(driver).get('wells') == ['1'], driver.current_url)
        driver.execute_script("window.EmissionsFacilityMap.instances()[0].map.jumpTo({center: [-119.1, 35.4], zoom: 9});")
        time.sleep(1.5)
        clusters = driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0];"
            "return m.map.queryRenderedFeatures({layers: ['wells-clusters']}).length;")
        check(results, 'clusters render over Kern at zoom 9', clusters > 0, f'{clusters} clusters')
        zoom_before = driver.execute_script("return window.EmissionsFacilityMap.instances()[0].map.getZoom();")
        driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0];"
            "var f = m.map.queryRenderedFeatures({layers: ['wells-clusters']})[0]; if (f) m.zoomToCluster(f);")
        time.sleep(1.5)
        zoom_after = driver.execute_script("return window.EmissionsFacilityMap.instances()[0].map.getZoom();")
        check(results, 'a cluster click zooms in', zoom_after > zoom_before, f'{zoom_before:.1f} -> {zoom_after:.1f}')
        driver.execute_script("window.EmissionsFacilityMap.instances()[0].map.jumpTo({center: [-119.02, 35.42], zoom: 13.5});")
        time.sleep(1.5)
        popup = driver.execute_script("""
            var m = window.EmissionsFacilityMap.instances()[0];
            var f = m.map.queryRenderedFeatures({layers: ['wells']})[0];
            if (!f) return '';
            m.openWellPopup(f, f.geometry.coordinates);
            return 'opened';
        """)
        deadline = time.time() + 10
        text = ''
        while time.time() < deadline and 'CalGEM record' not in text:
            text = driver.execute_script("var el = document.querySelector('.well-popup'); return el ? el.textContent : '';")
            time.sleep(0.25)
        check(results, 'a well click shows its record, its as-of date and the CalGEM link',
              popup == 'opened' and 'CalGEM record' in text and 'Current status, as of' in text, text[:160])
        legend = driver.execute_script("return document.querySelector('.facility-map-legend').textContent;")
        check(results, "the legend keys the statuses and the HPZ ring, and says it's today's wells",
              'Active' in legend and 'health-protection zone' in legend and "Today's wells, as of" in legend and 'not by year' in legend, legend[-200:])
        driver.execute_script("window.EmissionsFacilityMap.instances()[0].setWells(false);")
        time.sleep(0.3)
        check(results, 'unticking clears wells= and hides the layer', 'wells' not in query(driver)
              and driver.execute_script("return window.EmissionsFacilityMap.instances()[0].map.getLayoutProperty('wells', 'visibility');") == 'none')
        # Kern County's page (its link from the home page): wells off on its
        # Overview (too many to load by default), on its Oil & gas tab with
        # the wells section and its snapshot notice.
        driver.get(args.base + '/tools/emissions/')
        kern_url = driver.execute_script("var a = document.querySelector('a[href*=\"/region/\"][href$=\"/kern/\"]'); return a ? a.href : '';")
        driver.get(kern_url)
        check(results, "Kern County's Overview loads with the wells overlay offered but off",
              wait_loaded(driver) and driver.execute_script("var d = document.querySelector('.facility-map').dataset; return d.wells === '' && !!d.wellsUrl;"), kern_url)
        driver.get(kern_url.split('?')[0] + 'oil-gas/')
        check(results, "Kern County's Oil & gas tab has the overlay on and the wells section",
              wait_loaded(driver) and driver.execute_script("return document.querySelector('.facility-map').dataset.wells;") == '1'
              and driver.execute_script("return !!document.getElementById('wells') && !!document.querySelector('#wells .wells-snapshot');"), driver.current_url)

        driver.get(args.base + '/tools/emissions/dairies/')
        check(results, 'dairies tab loads', wait_dairies(driver))
        drawn = settled_count(driver, dairy_count)
        check(results, 'dairies tab draws dairies', drawn > 0, f'{drawn} dairies')
        legend = driver.execute_script("return document.querySelector('.dairy-map-legend').textContent;")
        check(results, 'its legend has the size key and the three EPA size classes',
              'Mature dairy cows' in legend and 'EPA size class' in legend
              and '700 or more mature dairy cows' in legend and 'Small: Fewer than 200' in legend, legend[:160])

        # X7: the size and digester toolbar filters (a MapLibre layer filter,
        # no refetch). Clicking the checkbox/item directly (as the measure
        # check above clicks its dropdown-item) exercises the bound
        # handler without needing the dropdown visibly open first.
        driver.execute_script("document.querySelector('.dairy-map-sizes [data-size=small]').click()")
        time.sleep(0.4)
        rendered = driver.execute_script(
            "var m = window.EmissionsDairyMap.instances()[0];"
            "return m.map.queryRenderedFeatures({layers: ['dairies']}).map(function (f) { return f.properties.size_class; });")
        check(results, 'unticking Small removes small dairies from the layer, and sizes= lands in the URL',
              bool(rendered) and 'small' not in rendered and query(driver).get('sizes') == ['medium,large'],
              f'{len(rendered)} left, sizes={query(driver).get("sizes")}')
        legend = driver.execute_script("return document.querySelector('.dairy-map-legend').textContent;")
        struck = driver.execute_script(
            "return !!document.querySelector('.dairy-map-legend .legend-bin.is-filtered-out');")
        check(results, 'the unticked size class shows dimmed/struck through in the legend', struck)

        # Options menu on the Dairies tab (X requirement): Tiles only, no Ramp
        # (the dairy colours are the fixed EPA size classes) -- the shared
        # shell.bindTiles logic the facility map uses. Small is still
        # unticked from above; a tile swap must keep that filter.
        driver.find_element(By.CSS_SELECTOR, '.map-wrap .map-options .dropdown-trigger .button').click()
        time.sleep(0.3)
        dairy_tiles_select = driver.find_element(By.CSS_SELECTOR, '.facility-map-options select[name="tiles"]')
        no_ramp = len(driver.find_elements(By.CSS_SELECTOR, '.facility-map-options select[name="ramp"]')) == 0
        dairy_tile_values = [o.get_attribute('value') for o in dairy_tiles_select.find_elements(By.TAG_NAME, 'option')]
        check(results, 'Dairies Options menu offers Tiles only, no Ramp',
              no_ramp and len(dairy_tile_values) > 1, f'{len(dairy_tile_values)} tiles, ramp present={not no_ramp}')

        other_dairy_tile = next(v for v in dairy_tile_values if v != dairy_tiles_select.get_attribute('value'))
        Select(dairy_tiles_select).select_by_value(other_dairy_tile)
        time.sleep(0.3)
        dairy_style_loaded = wait_dairy_style_loaded(driver)
        redrawn = settled_count(driver, dairy_count)
        still_filtered = driver.execute_script(
            "var m = window.EmissionsDairyMap.instances()[0];"
            "return m.map.queryRenderedFeatures({layers: ['dairies']}).every(function (f) { return f.properties.size_class !== 'small'; });")
        check(results, 'choosing tiles on the Dairies tab swaps the style, redraws the dairies with the size filter kept, and writes tiles=',
              dairy_style_loaded and redrawn > 0 and still_filtered and f'tiles={other_dairy_tile}' in driver.current_url,
              f'{redrawn} dairies; filtered={still_filtered}; {driver.current_url}')

        driver.execute_script("document.querySelector('.dairy-map-digester [data-digester=yes]').click()")
        time.sleep(0.4)
        rendered = driver.execute_script(
            "var m = window.EmissionsDairyMap.instances()[0];"
            "return m.map.queryRenderedFeatures({layers: ['dairies']}).map(function (f) { return f.properties.digester; });")
        check(results, "'With a digester' leaves only digester dairies, and digester=yes lands in the URL",
              bool(rendered) and all(rendered) and query(driver).get('digester') == ['yes'], str(rendered))

        # Reloading the URL (sizes=medium,large&digester=yes&tiles=... now in
        # it) restores all three.
        reload_url = driver.current_url
        driver.get(reload_url)
        check(results, 'reloading the URL restores the size and digester filters', wait_dairies(driver))
        settled_count(driver, dairy_count)
        restored = driver.execute_script(
            "var m = window.EmissionsDairyMap.instances()[0];"
            "return {sizes: m.sizes, digester: m.digester, tiles: m.shell.tileStyle};")
        check(results, 'the reloaded map state matches the URL, tiles included',
              restored['digester'] == 'yes' and restored['sizes'] == ['medium', 'large']
              and restored['tiles'] == other_dairy_tile, str(restored))
        rendered = driver.execute_script(
            "var m = window.EmissionsDairyMap.instances()[0];"
            "return m.map.queryRenderedFeatures({layers: ['dairies']}).map(function (f) { return [f.properties.size_class, f.properties.digester]; });")
        check(results, 'the reloaded map only draws medium/large digester dairies',
              bool(rendered) and all(sc != 'small' and dig for sc, dig in rendered), str(rendered[:5]))

        # Phase 9: the methane overlay on the dairy map. Ticking the legend's
        # checkbox loads the layer, writes ?methane=1, and a plume's popup
        # carries the attribution.
        driver.get(args.base + '/tools/emissions/dairies/')
        wait_dairies(driver)
        has_toggle = driver.execute_script("return !!document.querySelector('.dairy-map-legend [data-methane]');")
        check(results, 'dairies tab offers the methane overlay (needs import_carbon_mapper on this DB)', has_toggle)
        if has_toggle:
            driver.execute_script("document.querySelector('.dairy-map-legend [data-methane]').click()")
            loaded = wait_for(driver, "var el = document.querySelector('.dairy-map'); return !!el && el.dataset.methaneLoaded === '1';")
            count = settled_count(driver, lambda d: d.execute_script("var m = window.EmissionsDairyMap.instances()[0]; return m.map.querySourceFeatures('methane').length;"))
            check(results, 'the methane layer loads and ?methane=1 lands in the URL', loaded and count > 0 and 'methane=1' in driver.current_url, f'{count} sources; {driver.current_url}')
            legend = driver.execute_script("return document.querySelector('.dairy-map-legend').textContent;")
            check(results, 'the methane legend explains the plumes, without repeating the credit', 'newest observed plume' in legend and 'Carbon Mapper' not in legend)
            # The sources are drawn as their plume images, painted onto one
            # canvas source: wait for some non-transparent pixels on it.
            painted = wait_for(driver,
                "var m = window.EmissionsDairyMap.instances()[0]; if (!m.map.getLayer('methane-plumes')) return false;"
                "var c = m.methane.canvas, ctx = c.getContext('2d'); if (!c.width) return false;"
                "var d = ctx.getImageData(0, 0, c.width, c.height).data; for (var i = 3; i < d.length; i += 4) { if (d[i]) return true; } return false;")
            check(results, 'the methane sources are drawn as plume images', painted)
            attribution = driver.execute_script("var el = document.querySelector('.maplibregl-ctrl-attrib-inner, .maptiler-ctrl-attrib-inner'); return el ? el.textContent : '';")
            check(results, "the map's attribution control doesn't repeat the Carbon Mapper credit", 'Carbon Mapper' not in attribution, attribution[:120])
            opened = driver.execute_script(
                "var m = window.EmissionsDairyMap.instances()[0]; var f = m.map.querySourceFeatures('methane')[0]; if (!f) return false;"
                "m.methane.openPopup(f, {lng: f.geometry.coordinates[0], lat: f.geometry.coordinates[1]}); return true;")
            popup = driver.execute_script("var p = document.querySelector('.methane-popup'); return p ? p.textContent : '';") if opened else ''
            check(results, 'a methane popup gives the rate and passes, and links the source record', 'Rate' in popup and ' passes' in popup and 'Source record' in popup and 'Carbon Mapper' not in popup, popup[:160])

            # Part 2: the popup's plume image stepper (methane-overlay.js
            # loadPlumes/renderPlumePanel). The plumes fetch is async, so wait
            # for the panel to render past "Loading plumes..."
            panel_ready = wait_for(
                driver,
                "var p = document.querySelector('[data-plume-panel]');"
                "return !!p && p.textContent.indexOf('Loading plumes') === -1;") if opened else False
            if not panel_ready:
                check(results, 'the source popup drapes a plume image (needs plumes imported on this DB)', False, 'plume panel never left the loading state -- skip if import_carbon_mapper plumes are still importing')
            else:
                panel_text = driver.execute_script("return document.querySelector('[data-plume-panel]').textContent;")
                has_plumes = 'No plume images on file' not in panel_text
                if not has_plumes:
                    check(results, 'the source popup drapes a plume image (needs plumes imported on this DB)', False, 'source has no plumes on file yet')
                else:
                    has_image_layer = driver.execute_script("var m = window.EmissionsDairyMap.instances()[0]; return !!(m.map.getLayer('methane-plume-image') && m.map.getSource('methane-plume-image'));")
                    date_text = driver.execute_script("var d = document.querySelector('.methane-plume-date'); return d ? d.textContent : '';")
                    check(results, 'the plume image layer appears with a dated stepper', has_image_layer or 'No image for this pass' in panel_text, f'layer={has_image_layer} date={date_text!r}')
                    next_btn = driver.execute_script("var b = document.querySelector('.methane-plume-prev'); return b && !b.disabled;")
                    if next_btn:
                        driver.execute_script("document.querySelector('.methane-plume-prev').click();")
                        new_date = driver.execute_script("var d = document.querySelector('.methane-plume-date'); return d ? d.textContent : '';")
                        check(results, "stepping the plume popup's controls changes the date", new_date != date_text, f'{date_text!r} -> {new_date!r}')
                    else:
                        check(results, "stepping the plume popup's controls changes the date", True, 'only one plume on file -- stepper correctly disabled')

        driver.execute_script("document.querySelector('.dairy-map-view [data-view=counties]').click()")
        shaded = settled_count(driver, shaded_counties)
        check(results, 'counties view shades counties', shaded > 0 and 'view=counties' in driver.current_url, f'{shaded} shaded')
        legend = driver.execute_script("return document.querySelector('.dairy-map-legend .legend-title').textContent;")
        check(results, 'the Counties view defaults to mature dairy cows',
              'Mature dairy cows' in legend and 'measure=' not in driver.current_url, legend)
        hidden = driver.execute_script(
            "return document.querySelector('.dairy-map-sizes').hidden && document.querySelector('.dairy-map-digester').hidden;")
        check(results, 'the size and digester controls are hidden in the Counties view', hidden)

        # Hovering a county (a real mouse move, not a synthetic event) shows a
        # label with its name and the measure on display, and it disappears
        # once the cursor leaves the map. Scrolled into view first: an
        # offset move scrolls its target into view itself, which would shift
        # the canvas out from under a pixel picked beforehand.
        driver.execute_script("document.querySelector('.dairy-map canvas').scrollIntoView({block: 'center'});")
        time.sleep(0.3)
        county_hit = driver.execute_script(COUNTY_PIXEL)
        if county_hit:
            canvas = driver.find_element(By.CSS_SELECTOR, '.dairy-map canvas')
            ActionChains(driver).move_to_element_with_offset(canvas, int(county_hit[0]), int(county_hit[1])).perform()
            time.sleep(0.5)
        label_text = driver.execute_script(
            "var l = document.querySelector('.map-hover-label .maplibregl-popup-content'); return l ? l.textContent : '';")
        check(results, 'hovering a county shows its name and value',
              bool(county_hit) and 'County' in label_text and any(c.isdigit() for c in label_text), label_text)
        ActionChains(driver).move_to_element(driver.find_element(By.CSS_SELECTOR, '.navbar-brand')).perform()
        time.sleep(0.5)
        gone = driver.execute_script("return document.querySelectorAll('.map-hover-label').length === 0")
        check(results, 'moving off the map clears the county hover label', gone)

        driver.execute_script("document.querySelector('.dairy-map-measure [data-measure=emissions]').click()")
        time.sleep(0.5)
        legend = driver.execute_script("return document.querySelector('.dairy-map-legend').textContent;")
        check(results, 'a measure change redraws the legend, noting CARB\'s flat estimate',
              'Dairy emissions' in legend and 'the same every year since' in legend and 'measure=emissions' in driver.current_url, legend[:200])
        # A boosted swap from the table (a sort) keeps the view and measure.
        driver.find_element(By.CSS_SELECTOR, '.dairy-table thead a.sort-link').click()
        time.sleep(1)
        kept = wait_dairies(driver) and driver.execute_script(
            "var list = window.EmissionsDairyMap.instances();"
            "return list.length === 1 && list[0].view === 'counties' && list[0].measure === 'emissions';")
        check(results, 'a sort (boosted swap) keeps Counties and its measure',
              kept and 'view=counties' in driver.current_url and 'measure=emissions' in driver.current_url, driver.current_url)
        # Let the sort's boosted swap finish first: landing after the click, it
        # would re-read the page's view (Counties) over the zoom's switch.
        wait_for(driver, "return !document.querySelector('.htmx-request') && window.EmissionsDairyMap.instances().length === 1;")
        time.sleep(1)
        driver.execute_script("var a = document.querySelector('.dairy-zoom'); a.scrollIntoView(); a.click();")
        opened = False
        deadline = time.time() + 8
        while time.time() < deadline and not opened:
            opened = driver.execute_script(
                "var p = document.querySelector('.maplibregl-popup .dairy-popup');"
                "return !!p && p.textContent.indexOf('Mature dairy cows') !== -1 && p.textContent.indexOf('EPA size') !== -1;")
            time.sleep(0.25)
        back = driver.execute_script("return window.EmissionsDairyMap.instances()[0].view === 'dairies';")
        popup_text = driver.execute_script("var p = document.querySelector('.maplibregl-popup'); return p ? p.textContent.slice(0, 120) : 'no popup';")
        check(results, 'a row name zooms to its dairy, back in Dairies, with its popup', opened and back, f'back={back} popup={popup_text!r}')

        driver.get(args.base + '/tools/emissions/dairies/?county=tulare')
        wait_dairies(driver)
        settled_count(driver, dairy_count)
        time.sleep(0.5)
        seen = driver.execute_script(
            "var m = window.EmissionsDairyMap.instances()[0], seen = {};"
            "m.map.queryRenderedFeatures({layers: ['dairies']}).forEach(function (f) { seen[f.properties.county] = 1; });"
            "return Object.keys(seen);")
        check(results, 'a county narrows the dairy map', seen == ['tulare'], str(seen))

        driver.get(args.base + '/tools/emissions/dairies/?pollutant=nox&year=2024')
        notes = driver.execute_script(
            "return Array.prototype.map.call(document.querySelectorAll('.dairy-note'), function (n) { return n.textContent; });")
        check(results, 'NOx and 2024 fall back to ROG and 2023, with notes',
              len(notes) == 2 and 'showing ROG' in ' '.join(notes), str(notes))

        driver.get(args.base + '/tools/emissions/')
        county = driver.find_element(By.CSS_SELECTOR, '.find-area-counties a').get_attribute('href').split('?')[0]
        driver.get(county + '?year=2023')
        wait_loaded(driver)
        drawn = settled_count(driver, feature_count)
        check(results, 'a county page maps its facilities (2023)', drawn > 0, f'{drawn} facilities')
        legend = driver.execute_script("return document.querySelector('.facility-map-legend').textContent;")
        check(results, 'its legend is the plain sized-facilities legend (a size key, no dairies ramp)',
              'legend-sizes' in driver.execute_script("return document.querySelector('.facility-map-legend').innerHTML;")
              and 'Dairies' not in legend, legend[:160])

        # The dairy charts: the Dairies tab's herd, CARB estimate and
        # digesters; a county page's Dairies block the same, with the section
        # nav's plain anchors jumping in place (no boosted swap).
        chart_titles = (
            "return Array.prototype.filter.call(document.querySelectorAll('%s .explorer-chart'),"
            " function (f) { return f.querySelector('.uplot'); })"
            ".map(function (f) { return f.querySelector('.chart-title').textContent; });"
        )
        driver.get(args.base + '/tools/emissions/dairies/?pollutant=rog&county=tulare')
        time.sleep(1)
        titles = driver.execute_script(chart_titles % '.dairy-charts')
        check(results, 'the Dairies tab draws its herd, CARB estimate and digester charts',
              len(titles) == 3 and 'Dairy cattle ROG, CARB estimate' in titles, str(titles))
        # Tulare County's dairy page: the dairy map framed on the county
        # (outlined), Dairies only (no view switch), the three charts, a
        # row's name zooming to its dairy, and a year change keeping one map.
        # Found on the Dairies tab's own find box, so it's already the
        # county's dairy page URL (`find_area_places` there uses
        # 'emissions:region-dairies'); the plain region URL is that minus
        # its trailing 'dairies/'.
        tulare = driver.execute_script(
            "var a = Array.prototype.find.call(document.querySelectorAll('.find-area-counties a'),"
            " function (a) { return a.textContent.indexOf('Tulare') !== -1; }); return a ? a.href.split('?')[0] : null;")
        tulare_region = tulare[:-len('dairies/')] if tulare.endswith('dairies/') else tulare
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
        # The first `.within-list a` may be a school district or a
        # no-dairies-this-year CDP, so try a few until one has a map.
        hrefs = driver.execute_script(
            "return Array.prototype.slice.call(document.querySelectorAll('.within-list a'), 0, 8)"
            ".map(function (a) { return a.href.split('?')[0]; });")
        community = None
        for href in hrefs:
            driver.get(href + '?year=2023')
            time.sleep(1)
            if driver.execute_script("return !!document.querySelector('.dairy-map');"):
                community = href
                break
        community = community or hrefs[0]
        driver.get(community + '?year=2023')
        outlined = wait_dairies(driver) and driver.execute_script(
            "var m = window.EmissionsDairyMap.instances()[0]; return !!m.outlineBounds;")
        check(results, 'a community dairy page loads, outlined', outlined, community)
        drawn = settled_count(driver, dairy_count_unique)
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
        driver.find_element(By.CSS_SELECTOR, '.radius-switcher a').click()
        time.sleep(1)
        stayed = wait_dairies(driver) and '/near/dairies/' in driver.current_url and 'radius=1' in driver.current_url
        check(results, 'a radius button keeps the page and redraws', stayed, driver.current_url)

        # The tab's old filters land on the pages; its find box goes to a county dairy page.
        sqid = tulare_region.rstrip('/').split('/')[-2]
        driver.get(args.base + '/tools/emissions/dairies/?region=' + sqid + '&year=2023')
        check(results, 'the tab with ?region= lands on the region dairy page',
              driver.current_url.split('?')[0] == tulare, driver.current_url)
        driver.get(args.base + '/tools/emissions/dairies/')
        driver.find_element(By.CSS_SELECTOR, '.find-area-counties a').click()
        time.sleep(1)
        check(results, "the tab's find box takes you to a county dairy page", '/dairies/' in driver.current_url, driver.current_url)

        # Tulare County's page: a tab row, its Dairies tab the dairy page.
        driver.get(tulare_region + '?year=2023&pollutant=rog')
        time.sleep(1)
        tabs = driver.execute_script(
            "return Array.prototype.map.call(document.querySelectorAll('.area-tabs li'), function (li) {"
            "  return [li.textContent.trim(), li.querySelector('a').getAttribute('href'), li.classList.contains('is-active')]; });")
        labels = [t[0] for t in tabs]
        check(results, "Tulare County's tab row: Overview (current), Facilities, Dairies, Community",
              labels[:3] == ['Overview', 'Facilities', 'Dairies'] and 'Community' in labels and tabs[0][2], str(labels))
        dairies_href = next((t[1] for t in tabs if t[0] == 'Dairies'), '')
        check(results, 'its Dairies tab is the dairy page', dairies_href.split('?')[0] == tulare.replace(args.base, ''), dairies_href)
        # A tab is a page: following one swaps the page (boosted) and lands on its URL.
        driver.find_element(By.CSS_SELECTOR, '.area-tabs a[href*="/facilities/"]').click()
        time.sleep(1.5)
        on_facilities = driver.execute_script(
            "var a = document.querySelector('.area-tabs li.is-active'); return a ? a.textContent.trim() : '';")
        check(results, 'the Facilities tab opens as its own page, marked current',
              '/facilities/' in driver.current_url and on_facilities == 'Facilities' and 'year=2023' in driver.current_url, driver.current_url)

        errors = console_errors(driver)
        check(results, 'no console errors', not errors, '; '.join(errors)[:300])
    finally:
        driver.quit()

    failed = [name for name, passed, _ in results if not passed]
    print(f'\n{len(results) - len(failed)}/{len(results)} checks passed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
