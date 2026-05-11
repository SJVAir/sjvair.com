import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from django.contrib.gis.geos import Point
from django.utils.timezone import make_aware

from camp.apps.regions.models import Region

BASE_URL = 'https://spraydays.cdpr.ca.gov'
DELAY = 0.5
PT = ZoneInfo('America/Los_Angeles')

SJV_COUNTIES = {
    '10': {'name': 'Fresno',      'region_name': 'Fresno County',      'extent': (-120.91874387116177, 35.906918921644284, -118.36059845591876, 37.58584217244814)},
    '15': {'name': 'Kern',        'region_name': 'Kern County',        'extent': (-120.19416465753791, 34.790613897603095, -117.61620722389377, 35.79820707546911)},
    '16': {'name': 'Kings',       'region_name': 'Kings County',       'extent': (-120.3150806921342,  35.78868292674303,  -119.47436659496141, 36.488967029419356)},
    '20': {'name': 'Madera',      'region_name': 'Madera County',      'extent': (-120.54554884301392, 36.763052005975005, -119.02237565751238, 37.777991170180144)},
    '24': {'name': 'Merced',      'region_name': 'Merced County',      'extent': (-121.24865995448454, 36.74038596070541,  -120.05206778225329, 37.633369079327096)},
    '39': {'name': 'San Joaquin', 'region_name': 'San Joaquin County', 'extent': (-121.58509112060935, 37.48178798747774,  -120.91701998347031, 38.30025709137086)},
    '50': {'name': 'Stanislaus',  'region_name': 'Stanislaus County',  'extent': (-121.48678803889365, 37.13477897457777,  -120.38734188505447, 38.077426078999295)},
    '54': {'name': 'Tulare',      'region_name': 'Tulare County',      'extent': (-119.57320663026515, 35.78916605794458,  -117.98077330401863, 36.74482113093293)},
}

# Matches MTRS external_id like "MDM-T13S-R14E-08"
_MTRS_RE = re.compile(r'^[A-Z]+-T(\d+)([NS])-R(\d+)([EW])-(\d+)$')


def comtr_from_mtrs(external_id, county_code):
    """Convert an MTRS external_id + two-digit county code string to a COMTR code."""
    m = _MTRS_RE.match(external_id)
    if not m:
        return None
    t_num, t_dir, r_num, r_dir, section = m.groups()
    return f'{county_code}{int(t_num):02d}{t_dir}{int(r_num):02d}{r_dir}{int(section):02d}'


class SprayDaysClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': f'{BASE_URL}/Map/GetMap',
        })

    def authenticate(self):
        self.session.get(f'{BASE_URL}/Map/GetMap', timeout=30)

    def _get(self, path, params=None):
        resp = self.session.get(f'{BASE_URL}{path}', params=params, timeout=30)
        resp.raise_for_status()
        time.sleep(DELAY)
        return resp.json()

    def get_active_counties(self):
        all_counties = self._get('/Map/GetCountyData') or []
        return [
            c for c in all_counties
            if str(c['CountyId']) in SJV_COUNTIES and c['ApplicationCount'] > 0
        ]

    def get_noi_locations(self, extent):
        west, south, east, north = extent
        return self._get('/Map/GetNoiInBounds', {
            'topLeftLat': south,
            'topLeftLong': west,
            'bottomRightLat': north,
            'bottomRightLong': east,
        }) or []

    def get_applications(self, comtr):
        return self._get('/NoticeOfIntent/GetApplicationsInComtrs', {'comtrs': comtr}) or []


def _parse_products(raw_products):
    return [
        {
            'name': p.get('ProductName', ''),
            'epa_reg_no': p.get('EPARegNo', ''),
            'chemicals': [
                {'name': c.get('ChemicalName', ''), 'code': c.get('ChemicalCode', '')}
                for c in (p.get('Chemicals') or [])
            ],
        }
        for p in (raw_products or [])
    ]


def _chem_pks_from_products(products, chemical_map):
    pks = set()
    for p in products:
        for c in p['chemicals']:
            try:
                code = int(c['code'])
                if code in chemical_map:
                    pks.add(chemical_map[code])
            except (ValueError, TypeError):
                pass
    return pks


def _upsert_application(app_data, comtr, mtrs, county_region, lat, lon, chemical_map):
    from camp.apps.pesticides.models import SprayApplication

    scheduled_str = app_data.get('ScheduledApplicationFormatted', '')
    try:
        scheduled_dt = make_aware(
            datetime.strptime(scheduled_str, '%m/%d/%Y %I:%M:%S %p'), PT
        )
    except (ValueError, TypeError):
        return None, False

    products = _parse_products(app_data.get('Products'))
    chem_pks = _chem_pks_from_products(products, chemical_map)

    obj, created = SprayApplication.objects.update_or_create(
        application_id=app_data['Id'],
        defaults={
            'comtr': comtr,
            'mtrs': mtrs,
            'county': county_region,
            'point': Point(lon, lat, srid=4326),
            'scheduled_application': scheduled_dt,
            'treated_amount': app_data.get('TreatedAmount'),
            'treated_units': (app_data.get('TreatedUnits') or '').strip(),
            'application_method': (app_data.get('ApplicationMethod') or '').strip(),
            'products': products,
        },
    )
    obj.chemicals.set(chem_pks)
    return obj, created


def fetch_applications(county_filter=None, stdout=None):
    from camp.apps.pesticides.models import Chemical

    def log(msg, **kwargs):
        if stdout:
            stdout.write(msg, **kwargs)

    client = SprayDaysClient()
    log('Authenticating...')
    client.authenticate()

    chemical_map = {c.chem_code: c.pk for c in Chemical.objects.only('id', 'chem_code')}
    county_regions = {
        code: Region.objects.filter(type=Region.Type.COUNTY, name=info['region_name']).first()
        for code, info in SJV_COUNTIES.items()
    }

    active_counties = client.get_active_counties()
    if county_filter:
        active_counties = [c for c in active_counties if str(c['CountyId']) == county_filter]

    seen_locs = {}   # (lat, lon) → (comtr, mtrs_region)
    processed = set()
    created = updated = skipped = 0

    for county_data in active_counties:
        county_code = str(county_data['CountyId'])
        county_info = SJV_COUNTIES[county_code]
        county_region = county_regions.get(county_code)

        log(f'{county_info["name"]}: fetching NOI locations...')
        noi_points = client.get_noi_locations(county_info['extent'])
        log(f'{county_info["name"]}: {len(noi_points)} NOI pins')

        for noi in noi_points:
            lat, lon = noi['Latitude'], noi['Longitude']
            loc_key = (lat, lon)

            if loc_key not in seen_locs:
                point = Point(lon, lat, srid=4326)
                mtrs = Region.objects.filter(
                    type=Region.Type.MTRS,
                    boundary__geometry__covers=point,
                ).first()
                if mtrs and mtrs.external_id:
                    comtr = comtr_from_mtrs(mtrs.external_id, county_code)
                    seen_locs[loc_key] = (comtr, mtrs)
                else:
                    seen_locs[loc_key] = (None, None)

            comtr, mtrs = seen_locs[loc_key]
            if not comtr or comtr in processed:
                continue
            processed.add(comtr)

            raw_apps = client.get_applications(comtr)
            for app_data in raw_apps:
                obj, was_created = _upsert_application(
                    app_data, comtr, mtrs, county_region, lat, lon, chemical_map
                )
                if obj is None:
                    skipped += 1
                elif was_created:
                    created += 1
                else:
                    updated += 1

    log(
        f'Done: {created} created, {updated} updated, {skipped} skipped '
        f'(bad date / parse error)'
    )
    return created, updated
