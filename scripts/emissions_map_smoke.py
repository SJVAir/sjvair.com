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
parameters). Then the Dairies tab: its two views (dairies drawn, counties
shaded), a measure change redrawing the legend, a sort (a boosted swap)
keeping Counties and its measure, a table row's name zooming to its dairy
with its popup, a county narrowing the dairies, and the NOx / 2024 fallback
notes. Fails on any console error. Dev-only;
nothing here runs in CI. Needs local data (import_air_districts,
import_ceidars, import_cepam, import_cadd, and the regions with their
boundaries).

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


def dairy_count(driver):
    return driver.execute_script(
        "var m = window.EmissionsDairyMap.instances()[0];"
        "return m ? m.map.querySourceFeatures('dairies').length : 0;"
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
        driver.find_element(By.CSS_SELECTOR, '.buttons.explorer-scope a').click()
        time.sleep(1)
        stayed = wait_areas(driver) and driver.execute_script(
            "var list = window.EmissionsFacilityMap.instances(); return list.length === 1 && list[0].view === 'areas';")
        check(results, 'near-me radius button keeps Areas view', stayed and 'view=areas' in driver.current_url, driver.current_url)

        driver.get(args.base + '/tools/emissions/dairies/')
        check(results, 'dairies tab loads', wait_dairies(driver))
        drawn = settled_count(driver, dairy_count)
        check(results, 'dairies tab draws dairies', drawn > 0, f'{drawn} dairies')
        driver.execute_script("document.querySelector('.dairy-map-view [data-view=counties]').click()")
        shaded = settled_count(driver, shaded_counties)
        check(results, 'counties view shades counties', shaded > 0 and 'view=counties' in driver.current_url, f'{shaded} shaded')
        driver.execute_script("document.querySelector('.dairy-map-measure [data-measure=animal_units]').click()")
        time.sleep(0.5)
        legend = driver.execute_script("return document.querySelector('.dairy-map-legend .legend-title').textContent;")
        check(results, 'a measure change redraws the legend',
              'Animal units' in legend and 'measure=animal_units' in driver.current_url, legend)
        # A boosted swap from the table (a sort) keeps the view and measure.
        driver.find_element(By.CSS_SELECTOR, '.dairy-table thead a.sort-link').click()
        time.sleep(1)
        kept = wait_dairies(driver) and driver.execute_script(
            "var list = window.EmissionsDairyMap.instances();"
            "return list.length === 1 && list[0].view === 'counties' && list[0].measure === 'animal_units';")
        check(results, 'a sort (boosted swap) keeps Counties and its measure',
              kept and 'view=counties' in driver.current_url and 'measure=animal_units' in driver.current_url, driver.current_url)
        driver.execute_script("var a = document.querySelector('.dairy-zoom'); a.scrollIntoView(); a.click();")
        opened = False
        deadline = time.time() + 8
        while time.time() < deadline and not opened:
            opened = driver.execute_script(
                "var p = document.querySelector('.maplibregl-popup .dairy-popup');"
                "return !!p && p.textContent.indexOf('Animal units') !== -1;")
            time.sleep(0.25)
        back = driver.execute_script("return window.EmissionsDairyMap.instances()[0].view === 'dairies';")
        check(results, 'a row name zooms to its dairy, back in Dairies, with its popup', opened and back)

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

        errors = console_errors(driver)
        check(results, 'no console errors', not errors, '; '.join(errors)[:300])
    finally:
        driver.quit()

    failed = [name for name, passed, _ in results if not passed]
    print(f'\n{len(results) - len(failed)}/{len(results)} checks passed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
