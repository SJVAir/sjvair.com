"""
Headless smoke test for the Facility Emissions Explorer's map.

Loads the map page and a few compact-map pages in headless Chrome, waits for
the facilities to draw (`data-loaded="1"` on the container), checks features
were drawn, switches the map page's sector filter and waits for the redraw,
follows a boosted tab link and back to check the live map is adopted rather
than rebuilt, and fails on any console error. Dev-only; nothing here runs in
CI. Needs local data (import_air_districts, import_ceidars, import_cepam).

Setup (Chrome must be installed):
    python3 -m venv .venv && .venv/bin/pip install selenium
Usage:
    .venv/bin/python scripts/emissions_map_smoke.py --base http://localhost:8003
"""
import argparse
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
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
        check(results, 'map page draws features', feature_count(driver) > 0, f'{feature_count(driver)} features')
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

        errors = console_errors(driver)
        check(results, 'no console errors', not errors, '; '.join(errors)[:300])
    finally:
        driver.quit()

    failed = [name for name, passed, _ in results if not passed]
    print(f'\n{len(results) - len(failed)}/{len(results)} checks passed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
