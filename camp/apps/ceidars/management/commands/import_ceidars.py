import io

import pandas as pd
import requests

from django.core.management.base import BaseCommand, CommandError

from camp.apps.ceidars.models import EmissionsRecord, Facility
from camp.utils import geocode


COUNTY_CODES = {
    10: 'Fresno',
    15: 'Kern',
    16: 'Kings',
    20: 'Madera',
    24: 'Merced',
    39: 'San Joaquin',
    50: 'Stanislaus',
    54: 'Tulare',
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


def fetch_csv(url):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return pd.read_csv(io.StringIO(response.text), dtype=str).fillna('')


def decimal_or_none(val):
    val = str(val).strip()
    if not val or val.lower() == 'nan':
        return None
    return val


class Command(BaseCommand):
    help = 'Import CEIDARS emissions data for a given year.'

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

        total_facilities = total_records = total_geocode_failures = 0

        for county_code, county_name in counties.items():
            created_count = updated_count = record_count = geocode_failures = 0

            criteria_url = f'{BASE_URL}/faccrit_output.csv?dbyr={year}&ab_=SJV&dis_=SJU&co_={county_code}'
            toxics_url = f'{BASE_URL}/factox_output.csv?dbyr={year}&ab_=SJV&dis_=SJU&co_={county_code}'

            self.stdout.write(f'{county_name} ({county_code}): fetching...', ending='\r')
            try:
                criteria = fetch_csv(criteria_url)
                toxics = fetch_csv(toxics_url)
            except requests.RequestException as e:
                self.stderr.write(f'{county_name} ({county_code}): fetch failed — {e}')
                continue

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

            # Batch geocode upfront via Census, then fall back to MapTiler for failures
            positions = {}
            if geocode_index:
                self.stdout.write(
                    f'{county_name} ({county_code}): geocoding {len(geocode_index)} via Census...',
                    ending='\r',
                )
                results = geocode.batch([addr for _, addr in geocode_index])
                positions = {facid: point for (facid, _), point in zip(geocode_index, results)}

                census_failures = [(facid, addr) for (facid, addr), point in zip(geocode_index, results) if point is None]
                if census_failures:
                    self.stdout.write(
                        f'{county_name} ({county_code}): {len(census_failures)} Census failures, retrying via MapTiler...',
                        ending='\r',
                    )
                    for i, (facid, addr) in enumerate(census_failures, 1):
                        self.stdout.write(
                            f'{county_name} ({county_code}): MapTiler fallback {i}/{len(census_failures)}...',
                            ending='\r',
                        )
                        address = f'{addr["street"]}, {addr["city"]}, CA {addr["zipcode"]}'
                        positions[facid] = geocode.maptiler(address)

            # Upsert facilities and emissions records
            total_rows = len(merged)
            for i, (_, row) in enumerate(merged.iterrows(), 1):
                self.stdout.write(
                    f'{county_name} ({county_code}): {i}/{total_rows} facilities...',
                    ending='\r',
                )
                facid = int(row['FACID'])

                facility, created = Facility.objects.get_or_create(
                    county_code=county_code,
                    facid=facid,
                    defaults={
                        'name': row.get('FNAME', '').strip(),
                        'street': row.get('FSTREET', '').strip(),
                        'city': row.get('FCITY', '').strip(),
                        'zipcode': row.get('FZIP', '').strip(),
                        'sic_code': int(row['FSIC']) if row.get('FSIC') else None,
                        'metadata_year': year,
                    },
                )

                if created:
                    created_count += 1
                    facility.position = positions.get(facid)
                    if facility.position is None:
                        geocode_failures += 1
                    facility.save()
                else:
                    updated_count += 1
                    if regeocode:
                        facility.position = positions.get(facid)
                        if facility.position is None:
                            geocode_failures += 1

                    if facility.metadata_year is None or year >= facility.metadata_year:
                        facility.name = row.get('FNAME', '').strip()
                        facility.street = row.get('FSTREET', '').strip()
                        facility.city = row.get('FCITY', '').strip()
                        facility.zipcode = row.get('FZIP', '').strip()
                        facility.sic_code = int(row['FSIC']) if row.get('FSIC') else None
                        facility.metadata_year = year

                    facility.save()

                emissions_data = {
                    col: decimal_or_none(row.get(src))
                    for src, col in CRITERIA_COLS.items()
                }
                emissions_data.update({
                    col: decimal_or_none(row.get(src))
                    for src, col in TOXICS_COLS.items()
                })

                EmissionsRecord.objects.update_or_create(
                    facility=facility,
                    year=year,
                    defaults=emissions_data,
                )
                record_count += 1

            self.stdout.write(
                f'{county_name} ({county_code}): '
                f'{created_count + updated_count} facilities '
                f'({created_count} new, {updated_count} updated), '
                f'{record_count} emissions records upserted, '
                f'{geocode_failures} geocoding failures'
            )

            total_facilities += created_count + updated_count
            total_records += record_count
            total_geocode_failures += geocode_failures

        self.stdout.write(
            f'\nDone. {total_facilities} facilities, '
            f'{total_records} emissions records, '
            f'{total_geocode_failures} geocoding failures.'
        )
