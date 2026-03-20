import io
import math

import pandas as pd
import requests

from django.core.management.base import BaseCommand

from camp.utils import geocode


BASE_URL = 'https://www.arb.ca.gov/app/emsinv/iframe/facinfo'


def fetch_csv(url):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return pd.read_csv(io.StringIO(response.text), dtype=str).fillna('')


def haversine_km(p1, p2):
    """Approximate distance in km between two Points (lon, lat, srid=4326)."""
    R = 6371
    lat1, lon1 = math.radians(p1.y), math.radians(p1.x)
    lat2, lon2 = math.radians(p2.y), math.radians(p2.x)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def fmt_point(point):
    if point is None:
        return '--'
    return f'{point.y:.6f}, {point.x:.6f}'


def fmt_dist(p1, p2):
    if p1 is None or p2 is None:
        return '--'
    km = haversine_km(p1, p2)
    if km < 1:
        return f'{km * 1000:.0f} m'
    return f'{km:.2f} km'


class Command(BaseCommand):
    help = 'Compare Census, MapTiler, and batch geocoders on a random sample of CEIDARS facilities.'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=2023)
        parser.add_argument('--county', type=int, default=10)
        parser.add_argument('--count', type=int, default=20, help='Number of facilities to sample')
        parser.add_argument('--seed', type=int, default=None, help='Random seed for reproducibility')

    def handle(self, *args, **options):
        year = options['year']
        county = options['county']
        count = options['count']
        seed = options['seed']

        criteria_url = f'{BASE_URL}/faccrit_output.csv?dbyr={year}&ab_=SJV&dis_=SJU&co_={county}'
        toxics_url = f'{BASE_URL}/factox_output.csv?dbyr={year}&ab_=SJV&dis_=SJU&co_={county}'

        self.stdout.write(f'Fetching county {county}, year {year}...')
        criteria = fetch_csv(criteria_url)
        toxics = fetch_csv(toxics_url)

        merged = pd.merge(
            criteria, toxics,
            on=['CO', 'AB', 'FACID', 'DIS', 'FNAME', 'FSTREET', 'FCITY', 'FZIP', 'FSIC'],
            how='outer',
            suffixes=('_crit', '_tox'),
        )

        sample = merged.sample(n=min(count, len(merged)), random_state=seed)
        self.stdout.write(f'Sampled {len(sample)} of {len(merged)} facilities.\n')

        # Build structured address dicts for batch
        rows = []
        for _, row in sample.iterrows():
            rows.append({
                'name': row.get('FNAME', '').strip(),
                'street': row.get('FSTREET', '').strip(),
                'city': row.get('FCITY', '').strip(),
                'state': 'CA',
                'zipcode': row.get('FZIP', '').strip(),
            })

        # Batch geocode all at once
        self.stdout.write(f'Running batch (Census)...')
        batch_results = geocode.census_batch(rows)

        # Individual geocodes
        census_results = []
        maptiler_loose = []   # strict=False: address or poi
        maptiler_strict = []  # strict=True: address only
        for i, addr in enumerate(rows, 1):
            self.stdout.write(f'  census {i}/{len(rows)}...   ', ending='\r')
            address = f'{addr["street"]}, {addr["city"]}, CA {addr["zipcode"]}'
            census_results.append(geocode.census(address))

        self.stdout.write('')
        for i, addr in enumerate(rows, 1):
            self.stdout.write(f'  maptiler {i}/{len(rows)}...', ending='\r')
            address = f'{addr["street"]}, {addr["city"]}, CA {addr["zipcode"]}'
            maptiler_loose.append(geocode.maptiler(address, strict=False))
            maptiler_strict.append(geocode.maptiler(address, strict=True))

        self.stdout.write('\n')

        # Output comparison
        col_addr = 42
        col_result = 22
        header = (
            f'{"Address":<{col_addr}} '
            f'{"Census":<{col_result}} '
            f'{"MT loose":<{col_result}} '
            f'{"MT strict":<{col_result}} '
            f'{"Batch":<{col_result}} '
            f'{"C↔ML":>8}  {"C↔MS":>8}  {"C↔B":>8}'
        )
        self.stdout.write(header)
        self.stdout.write('-' * len(header))

        census_hits = loose_hits = strict_hits = batch_hits = 0

        for addr, c, ml, ms, b in zip(rows, census_results, maptiler_loose, maptiler_strict, batch_results):
            address_str = f'{addr["street"]}, {addr["city"]} {addr["zipcode"]}'[:col_addr]

            if c:
                census_hits += 1
            if ml:
                loose_hits += 1
            if ms:
                strict_hits += 1
            if b:
                batch_hits += 1

            self.stdout.write(
                f'{address_str:<{col_addr}} '
                f'{fmt_point(c):<{col_result}} '
                f'{fmt_point(ml):<{col_result}} '
                f'{fmt_point(ms):<{col_result}} '
                f'{fmt_point(b):<{col_result}} '
                f'{fmt_dist(c, ml):>8}  {fmt_dist(c, ms):>8}  {fmt_dist(c, b):>8}'
            )

        self.stdout.write('')
        self.stdout.write(
            f'Matched: Census {census_hits}/{len(rows)}, '
            f'MT loose {loose_hits}/{len(rows)}, '
            f'MT strict {strict_hits}/{len(rows)}, '
            f'Batch {batch_hits}/{len(rows)}'
        )
