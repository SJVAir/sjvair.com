import io
import re
import time

import pandas as pd
import requests

from django.core.management.base import BaseCommand, CommandError

from camp.apps.ceidars.models import EmissionsRecord, Facility
from camp.apps.regions.models import Region
from camp.utils import geocode


COUNTY_CODES = {
    10: 'Fresno County',
    15: 'Kern County',
    16: 'Kings County',
    20: 'Madera County',
    24: 'Merced County',
    39: 'San Joaquin County',
    50: 'Stanislaus County',
    54: 'Tulare County',
}

BASE_URL = 'https://www.arb.ca.gov/app/emsinv/iframe/facinfo'

CRITERIA_COLS = {
    'TOGT': 'tog', 'ROGT': 'rog', 'COT': 'co',
    'NOXT': 'nox', 'SOXT': 'sox', 'PMT': 'pm25', 'PM10T': 'pm10',
}

TOXICS_COLS = {
    'TS': 'total_score', 'HRA': 'hra',
    'CHINDEX': 'chindex', 'AHINDEX': 'ahindex',
}

# CAS number → EmissionsRecord field name for named toxic air contaminants.
TOXIC_POLLUTANTS = {
    '75070': 'acetaldehyde',
    '71432': 'benzene',
    '106990': 'butadiene',
    '56235': 'carbon_tetrachloride',
    '18540299': 'chromium_hexavalent',
    '106467': 'dichlorobenzene',
    '50000': 'formaldehyde',
    '75092': 'methylene_chloride',
    '91203': 'naphthalene',
    '127184': 'perchloroethylene',
}

# Known corrections for CEIDARS city name variants.
# Keys are uppercase raw values; values are the corrected uppercase form
# used for region lookup. Strip-CA-suffix handling is done separately.
CITY_CORRECTIONS = {
    'AWAHNEE': 'AHWAHNEE',
    'BAKERSIFLED': 'BAKERSFIELD',
    'KETTLEMAN': 'KETTLEMAN CITY',
    'LAKE OF THE WDS': 'LAKE OF THE WOODS',
    'LEGRAND': 'LE GRAND',
    'LEMONCOVE': 'LEMON COVE',
    'MC FARLAND': 'MCFARLAND',
    "O'NEILS": "O'NEALS",
    'ONEALS': "O'NEALS",
    'PINE MTN CLUB': 'PINE MOUNTAIN CLUB',
    'PORTERVILE': 'PORTERVILLE',
    'TRANQUILITY': 'TRANQUILLITY',
}

# Patterns that indicate a value is not a city name (county strings,
# GPS coordinates, descriptive strings, etc.) — these resolve to None.
_NON_CITY_RE = re.compile(
    r'county|sjvapcd|valley$|national|nat park|\bnf\b|cyn\b|site near|'
    r'mi n/o|w/o\s|west of|skyline|tejon ranch|terminus|pampa peak|'
    r'las yeguas|western fresno|& kings|sec\s*\d|\bt\d+s\b',
    re.IGNORECASE,
)

_STRIP_CA_RE = re.compile(r',?\s*CA$', re.IGNORECASE)


def normalize_city(raw, city_lookup):
    """
    Normalize a raw CEIDARS city string and return a matching Region or None.

    city_lookup: dict mapping uppercase city/CDP name → Region object.
    """
    city = _STRIP_CA_RE.sub('', raw.strip()).strip().upper()
    if not city or _NON_CITY_RE.search(city):
        return None
    city = CITY_CORRECTIONS.get(city, city)
    return city_lookup.get(city)


def fetch_csv(url, retries=5):
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            try:
                return pd.read_csv(io.StringIO(response.text), dtype=str).fillna('')
            except pd.errors.EmptyDataError:
                return pd.DataFrame()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep((2 ** attempt) * 0.5)


def decimal_or_none(val):
    val = str(val).strip()
    if not val or val.lower() == 'nan':
        return None
    return val


class Command(BaseCommand):
    help = 'Import CEIDARS emissions data for a given year.'

    def status(self, msg):
        """Write an overwriting status line, clearing any leftover characters."""
        self.stdout.write(f'{msg}\033[K', ending='\r')

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True, help='Inventory year (e.g. 2023)')
        parser.add_argument('--county', type=int, help='Limit to a single CARB county code (debugging)')
        parser.add_argument('--regeocode', action='store_true', help='Re-geocode all facilities, not just new ones')

    def handle(self, *args, **options):
        year = options['year']
        regeocode = options['regeocode']
        county_filter = options.get('county')

        if county_filter and county_filter not in COUNTY_CODES:
            raise CommandError(f'Unknown county code: {county_filter}. Valid codes: {list(COUNTY_CODES)}')

        counties = {county_filter: COUNTY_CODES[county_filter]} if county_filter else COUNTY_CODES

        # Pre-load region lookups once for the entire import.
        county_regions = {
            r.name: r
            for r in Region.objects.filter(type=Region.Type.COUNTY, name__in=COUNTY_CODES.values())
        }
        zipcode_regions = {
            r.name: r
            for r in Region.objects.filter(type=Region.Type.ZIPCODE)
        }
        city_regions = {
            r.name.upper(): r
            for r in Region.objects.filter(type__in=[Region.Type.CITY, Region.Type.CDP])
        }

        total_facilities = total_records = total_geocode_failures = 0
        start_time = time.monotonic()

        for county_code, county_name in counties.items():
            created_count = updated_count = record_count = geocode_failures = 0
            county_start = time.monotonic()
            county_region = county_regions.get(county_name)

            criteria_url = f'{BASE_URL}/faccrit_output.csv?dbyr={year}&ab_=SJV&dis_=SJU&co_={county_code}'
            toxics_url = f'{BASE_URL}/factox_output.csv?dbyr={year}&ab_=SJV&dis_=SJU&co_={county_code}'

            self.status(f'{county_name} ({county_code}): fetching...')
            try:
                criteria = fetch_csv(criteria_url)
                toxics = fetch_csv(toxics_url)
            except requests.RequestException as e:
                self.stderr.write(f'{county_name} ({county_code}): fetch failed — {e}')
                continue

            # Fetch per-pollutant EMS (tons/yr) for each named toxic.
            # Facilities that don't emit a given pollutant won't appear in that response.
            toxic_ems = {}  # {facid: {field_name: value}}
            for cas_id, field_name in TOXIC_POLLUTANTS.items():
                pol_url = f'{BASE_URL}/factox_output.csv?dbyr={year}&ab_=SJV&dis_=SJU&co_={county_code}&showpol={cas_id}'
                try:
                    pol_df = fetch_csv(pol_url)
                    for _, row in pol_df.iterrows():
                        facid = int(row['FACID'])
                        toxic_ems.setdefault(facid, {})[field_name] = decimal_or_none(row.get('EMS', ''))
                except requests.RequestException as e:
                    self.stderr.write(f'{county_name} ({county_code}): {field_name} fetch failed — {e}')

            merged = pd.merge(
                criteria, toxics,
                on=['CO', 'AB', 'FACID', 'DIS', 'FNAME', 'FSTREET', 'FCITY', 'FZIP', 'FSIC'],
                how='outer',
                suffixes=('_crit', '_tox'),
            )

            # Determine which facilities need geocoding
            all_facids = [int(row['FACID']) for _, row in merged.iterrows()]
            existing_facids = set(
                Facility.objects.filter(county_code=county_code, facid__in=all_facids)
                .values_list('facid', flat=True)
            )

            geocode_index = []   # list of (facid, address_dict) in batch order
            for _, row in merged.iterrows():
                facid = int(row['FACID'])
                if facid not in existing_facids or regeocode:
                    geocode_index.append((facid, {
                        'street': row.get('FSTREET', '').strip(),
                        'city': row.get('FCITY', '').strip(),
                        'state': 'CA',
                        'zipcode': row.get('FZIP', '').strip(),
                    }))

            # Batch geocode upfront via Census, falling back to MapTiler for failures.
            positions = {}
            if geocode_index:
                self.status(f'{county_name} ({county_code}): geocoding {len(geocode_index)} facilities...')
                addr_to_facid = {id(addr): facid for facid, addr in geocode_index}
                for addr, point in geocode.resolve_batch([addr for _, addr in geocode_index]):
                    positions[addr_to_facid[id(addr)]] = point

            # Upsert facilities and emissions records
            total_rows = len(merged)
            for i, (_, row) in enumerate(merged.iterrows(), 1):
                self.status(f'{county_name} ({county_code}): {i}/{total_rows} facilities...')
                facid = int(row['FACID'])

                address = {
                    'street': row.get('FSTREET', '').strip(),
                    'city': row.get('FCITY', '').strip(),
                    'zipcode': row.get('FZIP', '').strip(),
                }
                zipcode_region = zipcode_regions.get(address['zipcode'])
                city_region = normalize_city(address['city'], city_regions)

                facility, created = Facility.objects.get_or_create(
                    county_code=county_code,
                    facid=facid,
                    defaults={
                        'name': row.get('FNAME', '').strip(),
                        'address': address,
                        'sic_code': int(row['FSIC']) if row.get('FSIC') else None,
                        'metadata_year': year,
                        'county': county_region,
                        'zipcode': zipcode_region,
                        'city': city_region,
                    },
                )

                if created:
                    created_count += 1
                    facility.point = positions.get(facid)
                    if facility.point is None:
                        geocode_failures += 1
                    facility.save()
                else:
                    updated_count += 1
                    if regeocode:
                        facility.point = positions.get(facid)
                        if facility.point is None:
                            geocode_failures += 1

                    if facility.metadata_year is None or year >= facility.metadata_year:
                        facility.name = row.get('FNAME', '').strip()
                        facility.address = address
                        facility.sic_code = int(row['FSIC']) if row.get('FSIC') else None
                        facility.metadata_year = year
                        facility.county = county_region
                        facility.zipcode = zipcode_region
                        facility.city = city_region

                    facility.save()

                emissions_data = {
                    col: decimal_or_none(row.get(src))
                    for src, col in CRITERIA_COLS.items()
                }
                emissions_data.update({
                    col: decimal_or_none(row.get(src))
                    for src, col in TOXICS_COLS.items()
                })
                emissions_data.update(toxic_ems.get(facid, {}))

                if all(v is None for v in emissions_data.values()):
                    continue

                EmissionsRecord.objects.update_or_create(
                    facility=facility,
                    year=year,
                    defaults=emissions_data,
                )
                record_count += 1

            elapsed = time.monotonic() - county_start
            self.stdout.write(
                f'{county_name} ({county_code}): '
                f'{created_count + updated_count} facilities '
                f'({created_count} new, {updated_count} updated), '
                f'{record_count} emissions records upserted, '
                f'{geocode_failures} geocoding failures '
                f'[{elapsed:.1f}s]'
            )

            total_facilities += created_count + updated_count
            total_records += record_count
            total_geocode_failures += geocode_failures

        total_elapsed = time.monotonic() - start_time
        self.stdout.write(
            f'\nDone. {total_facilities} facilities, '
            f'{total_records} emissions records, '
            f'{total_geocode_failures} geocoding failures '
            f'[{total_elapsed:.1f}s]'
        )
