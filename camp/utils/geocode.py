import csv
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests

from django.conf import settings
from django.contrib.gis.geos import Point


# -- Address cleaning --

_unit_re = re.compile(r',?\s*(?:(?:Apt|Unit|Suite)\s*#?\s*\w+|#\s*\w+)$', re.IGNORECASE)


def clean_address(address):
    if not isinstance(address, str):
        return ''
    address = address.replace('\n', ' ').replace('\r', ' ').strip()
    return _unit_re.sub('', address).strip()


def _address_string(addr):
    """Build a single-line address string from a dict with street/city/state/zipcode."""
    parts = [addr.get('street', ''), addr.get('city', '')]
    state = addr.get('state', '')
    zipcode = addr.get('zipcode', '')
    if state or zipcode:
        parts.append(f'{state} {zipcode}'.strip())
    return ', '.join(p for p in parts if p)


# -- Census Geocoding Services --

_CENSUS_URL = 'https://geocoding.geo.census.gov/geocoder/locations'
_CENSUS_BENCHMARK = 'Public_AR_Current'
_BATCH_SIZE = 1000


def census(address, retries=5):
    """Single address string → Point or None via Census Geocoding Services."""
    query = clean_address(address)
    if not query:
        return None

    params = {
        'address': query,
        'benchmark': _CENSUS_BENCHMARK,
        'format': 'json',
    }

    for attempt in range(retries):
        try:
            response = requests.get(f'{_CENSUS_URL}/onelineaddress', params=params, timeout=10)
            response.raise_for_status()
            matches = response.json().get('result', {}).get('addressMatches', [])
            if matches:
                coords = matches[0]['coordinates']
                return Point(coords['x'], coords['y'], srid=4326)
            return None
        except requests.RequestException:
            time.sleep((2 ** attempt) * 0.5)

    return None


def census_batch(addresses, retries=5):
    """
    Batch geocode a list of address dicts via Census Geocoding Services.
    Yields (address, point) pairs in input order. point is None on failure.
    """
    if not addresses:
        return

    results = [None] * len(addresses)

    for chunk_start in range(0, len(addresses), _BATCH_SIZE):
        chunk = addresses[chunk_start:chunk_start + _BATCH_SIZE]

        rows = ['id,street,city,state,zipcode']
        for i, addr in enumerate(chunk):
            street = clean_address(addr.get('street', ''))
            rows.append(f'{i},{street},{addr.get("city", "")},{addr.get("state", "")},{addr.get("zipcode", "")}')
        csv_content = '\n'.join(rows)

        for attempt in range(retries):
            try:
                response = requests.post(
                    f'{_CENSUS_URL}/addressbatch',
                    data={'benchmark': _CENSUS_BENCHMARK},
                    files={'addressFile': ('addresses.csv', csv_content.encode(), 'text/csv')},
                    timeout=120,
                )
                response.raise_for_status()

                for row in csv.reader(io.StringIO(response.text)):
                    if len(row) < 6 or row[2].strip().lower() != 'match':
                        continue
                    try:
                        idx = int(row[0])
                        lon, lat = row[5].split(',', 1)
                        results[chunk_start + idx] = Point(float(lon), float(lat), srid=4326)
                    except (ValueError, IndexError):
                        pass
                break

            except requests.RequestException:
                time.sleep((2 ** attempt) * 0.5)

    yield from zip(addresses, results)


# -- MapTiler Geocoding API --

def maptiler(address, retries=5, strict=False):
    """Single address string → Point or None via MapTiler Geocoding API.

    By default, accepts the first result with place_type 'address' or 'poi',
    skipping city centroids, postal codes, counties, and other low-precision
    fallbacks.

    With strict=True, scans all returned features and only returns a result
    if one has place_type 'address' — useful when poi-level precision isn't
    good enough (e.g. a named park matching instead of a street address).
    """
    query = clean_address(address)
    if not query:
        return None

    url = f'https://api.maptiler.com/geocoding/{quote(query)}.json'
    params = {'key': settings.MAPTILER_API_KEY}

    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            features = response.json().get('features', [])
            for feature in features:
                place_type = set(feature.get('place_type', []))
                if strict:
                    if 'address' in place_type:
                        lon, lat = feature['geometry']['coordinates']
                        return Point(lon, lat, srid=4326)
                else:
                    if place_type & {'address', 'poi'}:
                        lon, lat = feature['geometry']['coordinates']
                        return Point(lon, lat, srid=4326)
            return None
        except requests.RequestException:
            time.sleep((2 ** attempt) * 0.5)

    return None


def maptiler_batch(addresses, workers=5, strict=False):
    """
    Batch geocode a list of address dicts via MapTiler, concurrently.
    Yields (address, point) pairs in completion order. point is None on failure.
    """
    if not addresses:
        return

    def _geocode(addr):
        return addr, maptiler(_address_string(addr), strict=strict)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_geocode, addr): addr for addr in addresses}
        for future in as_completed(futures):
            yield future.result()


# -- Combined geocoder --

def resolve(address, strict=False):
    """Single address string → Point or None. Tries Census first, falls back to MapTiler."""
    return census(address) or maptiler(address, strict=strict)


def resolve_batch(addresses, workers=5, strict=False):
    """
    Geocode a list of address dicts, yielding (address, point) pairs.
    Census batch runs first; failures fall back to MapTiler concurrently.
    Results are yielded as they become available — Census hits up front,
    MapTiler results as each finishes.
    """
    if not addresses:
        return

    fallbacks = []
    for addr, point in census_batch(addresses):
        if point is not None:
            yield addr, point
        else:
            fallbacks.append(addr)

    yield from maptiler_batch(fallbacks, workers=workers, strict=strict)
