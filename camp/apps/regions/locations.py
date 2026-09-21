"""
Import adapters for `regions.Location`: schools and child care facilities.

Each source knows where to download its file, how to parse it into plain
dicts, and which `Location.Type` its rows become. `import_source()` does the
rest: geocoding the rows that arrive without coordinates, resolving the
county and school district, upserting by (source, external_id), and removing
the rows that have disappeared from the source.
"""

import codecs
import csv
import hashlib
import io
import tempfile
import time

from contextlib import contextmanager
from datetime import datetime

import requests

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from camp.apps.regions.models import Location, Region
from camp.utils.geocode import clean_address, resolve


# The eight San Joaquin Valley counties, lowercased and without " County".
SJV_COUNTIES = frozenset([
    'fresno', 'kern', 'kings', 'madera',
    'merced', 'san joaquin', 'stanislaus', 'tulare',
])

# Private schools this small are almost always a family homeschooling under
# the affidavit, not a school with a campus. A blank enrollment doesn't clear
# the bar either: the spec's filter is enrollment >= 6.
MIN_PRIVATE_ENROLLMENT = 6

# CDSS facility types that are child care centers, as FAC_TYPE_DESC spells
# them (the column is truncated at 20 characters, hence "SINGLE CHILD CARE CE"
# for a single child care center). Family child care homes are private
# residences and aren't in this dataset at all.
CHILD_CARE_TYPES = (
    'DAY CARE CENTER',
    'INFANT CENTER',
    'SCHOOL-AGE',
    'SINGLE CHILD CARE',
)
CHILD_CARE_PROGRAM = 'CHILD CARE'

GEOCODE_CACHE_TTL = 60 * 60 * 24 * 30  # 30 days
# An address the geocoder couldn't place is cached too, so a re-import doesn't
# pay for the same failed lookup again -- but for a day rather than a month,
# since the miss may be the geocoder's rather than the address's.
GEOCODE_MISS_TTL = 60 * 60 * 24
GEOCODE_MISS = 'miss'

# CDE's Virtual codes for a school that exists only online: 'V' (exclusively
# virtual, a facility used by staff) and 'F' (exclusively virtual, no
# facility). Neither has a campus children stand on.
EXCLUSIVELY_VIRTUAL = ('V', 'F')

# The grade code for adult education. This file has no "Adult" School Type
# or School Level -- the types run Elementary…State Special and the levels
# Elementary, Middle, High, Elem-High Combo, Ungraded -- so the adult sites
# are the ones whose grade span starts at AD (8 statewide, 2 in the valley:
# "Madera Unified Adult Transition Program" and "Rising Sun"). A school that
# merely runs up to AD, like a K-AD special education campus, still teaches
# children and stays.
ADULT_GRADE = 'AD'

# School Level values that belong to the elementary district, for a school
# that isn't inside a unified district.
ELEMENTARY_LEVELS = ('elementary', 'middle')

PUBLIC_GRADE_COLUMNS = (
    ('tk', 'grade tk'),
    ('kg', 'grade kg'),
    *((str(grade), f'grade {grade}') for grade in range(1, 13)),
)

PRIVATE_GRADE_COLUMNS = (
    ('kg', 'user_enrollk'),
    *((str(grade), f'user_enroll{grade}') for grade in range(1, 13)),
)

# metadata key -> the public file's column, whose percentage lives in the
# same column name with ' (%)' appended.
PUBLIC_DEMOGRAPHICS = (
    ('african_american', 'african american'),
    ('american_indian', 'american indian'),
    ('asian', 'asian'),
    ('filipino', 'filipino'),
    ('hispanic_latino', 'hispanic'),
    ('pacific_islander', 'pacific islander'),
    ('white', 'white'),
    ('multiracial', 'two or more races'),
    ('not_reported', 'not reported'),
)

PUBLIC_SUBGROUPS = (
    ('english_learners', 'english learner'),
    ('foster_youth', 'foster'),
    ('homeless', 'homeless'),
    ('migrant', 'migrant'),
    ('socioeconomically_disadvantaged', 'socioeconomically disadvantaged'),
    ('students_with_disabilities', 'students with disabilities'),
    ('free_reduced_meals', 'free/reduced meal eligible'),
)

GRADE_WORDS = {
    'pre-kindergarten': 'PK',
    'prekindergarten': 'PK',
    'pk': 'PK',
    'transitional kindergarten': 'TK',
    'tk': 'TK',
    'kindergarten': 'K',
    'kg': 'K',
    'first grade': '1',
    'second grade': '2',
    'third grade': '3',
    'fourth grade': '4',
    'fifth grade': '5',
    'sixth grade': '6',
    'seventh grade': '7',
    'eighth grade': '8',
    'ninth grade': '9',
    'tenth grade': '10',
    'eleventh grade': '11',
    'twelfth grade': '12',
    'adult': 'AD',
}

# A source that answers a download with a web page is a bot wall, not data.
HTML_PREFIXES = (b'<html', b'<!doctype')

# What the public schools' district cross-check found, tallied per import:
# the file's district replaced a different spatial one, filled in where the
# point fell outside every district we have, or named a district we don't
# have a Region for at all (the location keeps the spatial answer).
DISTRICT_CORRECTED = 'district_corrected'
DISTRICT_FILLED_IN = 'district_filled_in'
DISTRICT_UNKNOWN = 'district_unknown'
DISTRICT_TALLIES = (
    (DISTRICT_CORRECTED, 'corrected'),
    (DISTRICT_FILLED_IN, 'filled in'),
    (DISTRICT_UNKNOWN, 'unknown district'),
)

# data.ca.gov's CDE datasets are ArcGIS Hub exports, generated on demand: a
# request that arrives while one is being rebuilt is answered 202 with a
# short "still processing" body rather than the file. That isn't an error
# and isn't HTML either, so without this it reads as a successful import of
# zero schools. Wait it out instead.
DOWNLOAD_PENDING_STATUSES = (202,)
DOWNLOAD_ATTEMPTS = 5
DOWNLOAD_RETRY_WAIT = 10  # seconds, doubling per attempt


class DownloadError(Exception):
    """A source file couldn't be fetched."""


# -- Geocoding --

def geocode_cached(address):
    """
    A single-line address → (lat, lng) or None, cached for 30 days. A failed
    lookup is cached as well, for a day (see GEOCODE_MISS_TTL).
    """
    cleaned = clean_address(address)
    if not cleaned:
        return None

    digest = hashlib.sha1(cleaned.encode('utf-8', 'replace')).hexdigest()
    key = f'regions:geocode:{digest}'

    cached = cache.get(key)
    if cached == GEOCODE_MISS:
        return None
    if cached is not None:
        return tuple(cached)

    point = resolve(cleaned)
    if point is None:
        cache.set(key, GEOCODE_MISS, GEOCODE_MISS_TTL)
        return None

    result = (point.y, point.x)
    cache.set(key, result, GEOCODE_CACHE_TTL)
    return result


# -- Row helpers --

def _text(file, encoding):
    """
    Decode a source file. The data.ca.gov exports are UTF-8, most of them
    with a BOM, but each source says which encoding it expects and a source
    that turns out not to be UTF-8 falls back to latin-1 rather than
    failing the import.
    """
    data = file.read()

    if data.startswith(codecs.BOM_UTF8):
        return data.decode('utf-8-sig')

    if encoding != 'latin-1':
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass

    return data.decode('latin-1')


def _rows(file, delimiter=',', encoding='utf-8'):
    """Yield dicts keyed by the lowercased header, from a binary file object."""
    reader = csv.reader(io.StringIO(_text(file, encoding), newline=''), delimiter=delimiter)

    header = next(reader, None)
    if header is None:
        return

    keys = [_key(name) for name in header]
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        yield dict(zip(keys, [cell.strip() for cell in row]))


def _key(name):
    return str(name or '').strip().lstrip('﻿').strip().lower()


def _get(row, *names, default=''):
    for name in names:
        value = row.get(name)
        if value:
            return value
    return default


def _float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _int(value):
    try:
        return int(float(str(value).strip().replace(',', '')))
    except (TypeError, ValueError):
        return None


def _clean(value):
    """A stripped source string, or None when the cell is blank."""
    text = str(value or '').strip()
    return text or None


def _yes_no(value):
    """'Yes'/'No' as a bool; None for anything else, blanks included."""
    text = str(value or '').strip().lower()
    if text in ('yes', 'y', 'true'):
        return True
    if text in ('no', 'n', 'false'):
        return False
    return None


def _date(value):
    """The CDE files' 'M/D/YYYY 12:00:00 AM' as an ISO date string."""
    text = str(value or '').strip().split(' ')[0]
    if not text:
        return None
    try:
        return datetime.strptime(text, '%m/%d/%Y').date().isoformat()
    except ValueError:
        return text


def _grade(value):
    """
    One grade, in a spelling that reads the same whichever file it came
    from: the public directory's zero-padded codes ('09', 'KG') and the
    private affidavit's words ('Ninth Grade', 'Kindergarten') both become
    '9' and 'K'. Anything unrecognized is kept as it was written.
    """
    text = str(value or '').strip()
    if not text:
        return None
    word = GRADE_WORDS.get(text.lower())
    if word:
        return word
    if text.isdigit():
        return str(int(text))
    return text.upper()


def _count_and_pct(row, column):
    return {
        'count': _int(_get(row, column)),
        'pct': _float(_get(row, f'{column} (%)')),
    }


def _in_the_valley(county):
    name = str(county or '').strip().lower()
    if name.endswith(' county'):
        name = name[:-len(' county')]
    return name in SJV_COUNTIES


def _address_string(row):
    """
    The single line to geocode a row by: the address the source gave us,
    unless the source already worked out a better one (`geocode_address`).
    Empty when there's nothing to place the row by -- a state and a ZIP on
    their own aren't an address.
    """
    if row.get('geocode_address'):
        return row['geocode_address'].strip()

    parts = [row.get('address') or '', row.get('city') or '']
    if not any(part.strip() for part in parts):
        return ''

    zipcode = (row.get('zip') or '').strip()
    parts.append(f'CA {zipcode}'.strip())
    return ', '.join(part for part in parts if part.strip())


# -- Parsers --

def parse_cde_public(file):
    """
    CDE public schools, the point file published on data.ca.gov as
    `california-public-schools-2025-26` (UTF-8 with a BOM, one row per
    school, with Latitude/Longitude).

    The two vocabularies the filters lean on, as the 2025-26 file spells
    them:

    * `Status`: 'Active' (9,944 rows) or 'Closed' (2). Only Active is kept.
    * `Virtual`: 'N' not virtual (8,566), 'C' primarily virtual but with
      classroom instruction (1,157), 'V' exclusively virtual, facility used
      (168), 'F' exclusively virtual, no facility (55). N and C have a
      campus children stand on, so they stay; V and F are dropped. CDE also
      documents 'P' (primarily classroom, some virtual), which doesn't
      appear in this year's file -- it's kept if it turns up.

    Adult education sites are dropped as well; see ADULT_GRADE.

    Names arrive properly cased and are stored as they come.
    """
    for row in _rows(file, encoding='utf-8'):
        name = _get(row, 'school name')
        if not name:
            continue
        if _get(row, 'status').lower() != 'active':
            continue
        if _get(row, 'virtual').upper() in EXCLUSIVELY_VIRTUAL:
            continue
        if _grade(_get(row, 'grade low')) == ADULT_GRADE:
            continue  # Adult education: no children on the campus.
        if not _in_the_valley(_get(row, 'county name')):
            continue

        cds_code = _get(row, 'cds code')
        yield {
            'external_id': cds_code,
            # The district whose boundary the school stands in, which is not
            # always the district that runs it (see _geographic_district).
            'district_cds': _geographic_district(row),
            'name': name,
            'address': _get(row, 'street'),
            'city': _get(row, 'city'),
            'zip': _get(row, 'zip'),
            'lat': _float(_get(row, 'latitude')),
            'lng': _float(_get(row, 'longitude')),
            'metadata': {
                'cds_code': cds_code,
                'district_code': _clean(_get(row, 'district code')),
                'district_name': _clean(_get(row, 'district name')),
                'geographic': {
                    'county': _geographic(row, 'county'),
                    'elementary': _geographic(row, 'elementary district'),
                    'high': _geographic(row, 'high district'),
                    'unified': _geographic(row, 'unified district'),
                },
                'school_type': _clean(_get(row, 'school type')),
                'school_level': _clean(_get(row, 'school level')),
                'grade_low': _grade(_get(row, 'grade low')),
                'grade_high': _grade(_get(row, 'grade high')),
                'charter': _get(row, 'charter').upper() == 'Y',
                'charter_number': _clean(_get(row, 'charter num')),
                'charter_funding': _clean(_get(row, 'charter funding type')),
                'virtual': _clean(_get(row, 'virtual')),
                'magnet': _clean(_get(row, 'magnet')),
                'title_i': _clean(_get(row, 'title i')),
                'dass': _clean(_get(row, 'dass')),
                'assistance_status': _clean(_get(row, 'assistance status essa')),
                'locale': _clean(_get(row, 'locale')),
                'website': _clean(_get(row, 'school website')),
                'open_date': _date(_get(row, 'open date')),
                'enrollment': {
                    'total': _int(_get(row, 'enroll total')),
                    'by_grade': {key: _int(_get(row, column))
                        for key, column in PUBLIC_GRADE_COLUMNS},
                },
                'demographics': {key: _count_and_pct(row, column)
                    for key, column in PUBLIC_DEMOGRAPHICS},
                'subgroups': {key: _count_and_pct(row, column)
                    for key, column in PUBLIC_SUBGROUPS},
                'staff': {
                    'total': _int(_get(row, 'staff total')),
                    'teacher': _int(_get(row, 'staff teacher')),
                    'admin': _int(_get(row, 'staff admin')),
                    'pupil_services': _int(_get(row, 'staff pupil services')),
                    'other': _int(_get(row, 'staff other')),
                },
            },
        }


def _geographic(row, kind):
    return {
        'code': _clean(_get(row, f'geographic {kind} code')),
        'name': _clean(_get(row, f'geographic {kind} name')),
    }


def _geographic_district(row):
    """
    The 7-digit CDS code of the district whose boundary the school stands
    in. A unified district covers every grade, so it wins outright; where
    there is none the file names an elementary and a high district for the
    same address, and the school belongs to whichever teaches its grades.
    """
    unified = _get(row, 'geographic unified district code')
    if unified:
        return unified

    elementary = _get(row, 'geographic elementary district code')
    high = _get(row, 'geographic high district code')
    if not (elementary and high):
        return elementary or high or None

    level = _get(row, 'school level').lower()
    if level in ELEMENTARY_LEVELS:
        return elementary
    return high


def parse_cde_private(file):
    """
    CDE private school affidavit, the point file published on data.ca.gov
    as `california-private-schools-2024-25`. The affidavit's own columns are
    prefixed `USER_`; `X`/`Y`, `Status`, `Score` and `Match_addr` are the
    result of CDE geocoding the address.

    `Status` is the Esri geocoder's: 'M' matched (2,818 rows), 'T' tied --
    several candidates scored the same (15), 'U' unmatched (3). Only an M
    row's X/Y is the school; the rest carry a fallback point (a street or a
    city centroid), so they are geocoded here instead, from `Match_addr`
    where there is one.
    """
    for row in _rows(file, encoding='utf-8'):
        name = _get(row, 'user_name')
        if not name:
            continue
        if not _in_the_valley(_get(row, 'user_county')):
            continue

        enrollment = _int(_get(row, 'user_totalenroll'))
        if enrollment is None or enrollment < MIN_PRIVATE_ENROLLMENT:
            continue

        # X/Y are Web Mercator, and only a matched row's is the school.
        matched = _get(row, 'status').upper().startswith('M')
        lat, lng = _webmercator(row) if matched else (None, None)

        cds_code = _get(row, 'user_cds')
        yield {
            'external_id': cds_code,
            'district_cds': None,
            'name': name,
            'address': _get(row, 'user_street'),
            'city': _get(row, 'user_city'),
            'zip': _get(row, 'user_zip'),
            'lat': lat,
            'lng': lng,
            # What to geocode when there's nothing to place it by: the
            # address the geocoder itself settled on, where it got that far.
            'geocode_address': _get(row, 'match_addr') if not matched else None,
            'metadata': {
                'cds_code': cds_code,
                'district_name': _clean(_get(row, 'user_district')),
                'classification': _clean(_get(row, 'user_classification')),
                'school_type': _clean(_get(row, 'user_type')),
                'accommodations': _clean(_get(row, 'user_accommodations')),
                'grade_low': _grade(_get(row, 'user_lowgrade')),
                'grade_high': _grade(_get(row, 'user_highgrade')),
                'enrollment': {
                    'total': enrollment,
                    'by_grade': {key: _int(_get(row, column))
                        for key, column in PRIVATE_GRADE_COLUMNS},
                },
                'staff': {
                    'full_time_teachers': _int(_get(row, 'user_fulltimeteach')),
                    'part_time_teachers': _int(_get(row, 'user_parttimeteach')),
                    'administrators': _int(_get(row, 'user_administrators')),
                    'other': _int(_get(row, 'user_otherstaff')),
                },
                'tax_exempt': _yes_no(_get(row, 'user_taxexempt')),
            },
        }


def _webmercator(row):
    """(lat, lng) from the file's EPSG:3857 X/Y, or (None, None)."""
    x, y = _float(_get(row, 'x')), _float(_get(row, 'y'))
    if x is None or y is None:
        return None, None
    point = Point(x, y, srid=3857)
    point.transform(4326)
    return point.y, point.x


def parse_cdss_ccl(file):
    """
    CDSS Community Care Licensing facilities, as published on data.ca.gov.
    The file is every licensed facility in the state -- child care, adult and
    senior care, residential -- so the child care centers are picked out by
    PROGRAM_TYPE and FAC_TYPE_DESC. STATUS is a numeric code on the licensed
    layer, so it's recorded rather than filtered on.
    """
    # One site is often licensed as two or three facilities -- a day care
    # center, an infant center and a school-age center at the same name and
    # address, each with its own facility number. Readers see one place, so
    # those merge into one row keyed by the lowest facility number, carrying
    # every number and type and the summed capacity.
    sites = {}
    for row in _rows(file, encoding='utf-8'):
        program = _get(row, 'program_type', 'program').upper()
        if program and program != CHILD_CARE_PROGRAM:
            continue

        facility_type = _get(row, 'fac_type_desc', 'facility type', 'facilitytype', 'type').upper()
        if not facility_type.startswith(CHILD_CARE_TYPES):
            continue

        if not _in_the_valley(_get(row, 'county', 'county name')):
            continue

        name = _get(row, 'name', 'facility name', 'facilityname')
        if not name:
            continue

        facility_number = _get(row, 'fac_nbr', 'facility number', 'facilitynumber', 'facility id')
        address = _get(row, 'res_street_addr', 'facility address', 'address')
        zip_code = _get(row, 'res_zip_code', 'facility zip', 'zip')
        capacity = _int(_get(row, 'capacity', 'facility capacity'))
        key = (name.upper(), address.upper(), zip_code)
        site = sites.get(key)
        if site is None:
            site = sites[key] = {
                'external_id': facility_number,
                'name': name,
                'address': address,
                'city': _get(row, 'res_city', 'facility city', 'city'),
                'zip': zip_code,
                'lat': _float(_get(row, 'fac_latitude', 'latitude', 'facility latitude', 'y')),
                'lng': _float(_get(row, 'fac_longitude', 'longitude', 'facility longitude', 'x')),
                'metadata': {
                    'county': _get(row, 'county', 'county name'),
                    'facility_type': facility_type,
                    'facility_types': [],
                    'facility_numbers': [],
                    'capacity': 0,
                    'status': _get(row, 'status', 'facility status'),
                    'client_served': _get(row, 'client_served'),
                },
            }
        meta = site['metadata']
        meta['facility_types'].append(facility_type)
        meta['facility_numbers'].append(facility_number)
        meta['capacity'] += capacity or 0
        # The lowest facility number keys the merged row, so it is stable
        # across imports; the day care center is the site's primary type.
        if facility_number < site['external_id']:
            site['external_id'] = facility_number
        if facility_type.startswith('DAY CARE CENTER'):
            meta['facility_type'] = facility_type
    for site in sites.values():
        site['metadata']['facility_types'].sort()
        site['metadata']['facility_numbers'].sort()
        if not site['metadata']['capacity']:
            site['metadata']['capacity'] = None
        yield site


# -- Sources --

SOURCES = {
    'cde-public': {
        'label': 'CDE public schools (2025-26)',
        'type': Location.Type.PUBLIC_SCHOOL,
        # cde.ca.gov itself answers server-side downloads with a JS bot wall
        # (the same one that blocks the OEHHA Prop 65 list). CDE publishes
        # the same schools as a point file on data.ca.gov, which doesn't.
        'ckan_dataset': 'california-public-schools-2025-26',
        'page_url': 'https://data.ca.gov/dataset/california-public-schools-2025-26',
        'parse': parse_cde_public,
    },
    'cde-private': {
        'label': 'CDE private schools (2024-25)',
        'type': Location.Type.PRIVATE_SCHOOL,
        'ckan_dataset': 'california-private-schools-2024-25',
        'page_url': 'https://data.ca.gov/dataset/california-private-schools-2024-25',
        'parse': parse_cde_private,
    },
    'cdss-ccl': {
        'label': 'CDSS community care licensing facilities',
        'type': Location.Type.CHILD_CARE,
        'ckan_dataset': 'community-care-licensing-facilities1',
        'page_url': 'https://data.ca.gov/dataset/community-care-licensing-facilities1',
        'parse': parse_cdss_ccl,
    },
}

CKAN_PACKAGE_URL = 'https://data.ca.gov/api/3/action/package_show'


def _source_url(config):
    """
    The CSV's URL, looked up in the source's CKAN package. The package lists
    its resources by format, and a package that no longer offers a CSV is a
    changed dataset rather than a transient failure -- say so instead of
    importing nothing.
    """
    try:
        response = requests.get(CKAN_PACKAGE_URL,
            params={'id': config['ckan_dataset']}, timeout=60)
        response.raise_for_status()
        resources = response.json().get('result', {}).get('resources', [])
    except (requests.RequestException, ValueError) as exc:
        raise DownloadError(f'Could not look up {config["label"]}: {exc}')

    for resource in resources:
        if (resource.get('format') or '').upper() == 'CSV' and resource.get('url'):
            return resource['url']

    raise DownloadError(
        f'No download URL for {config["label"]}: get the file from'
        f' {config.get("page_url") or "the source site"} and pass it with --path.'
    )


def _reject_html(config, url, content_type, chunk):
    """
    A 200 that hands back a web page is a bot wall, not the file. Say so
    loudly rather than parsing zero rows and calling it a successful import.
    """
    looks_like_html = (
        'text/html' in content_type
        or bytes(chunk or b'').lstrip()[:9].lower().startswith(HTML_PREFIXES)
    )
    if not looks_like_html:
        return

    raise DownloadError(
        f'{config["label"]} returned a web page instead of a file: the site'
        f' blocks server-side downloads ({url}). Download it in a browser from'
        f' {config.get("page_url") or "the source site"} and pass it with --path.'
    )


@contextmanager
def _open_source(config, path):
    if path:
        with open(path, 'rb') as handle:
            yield handle
        return

    with tempfile.TemporaryFile() as handle:
        url = _source_url(config)
        try:
            response = _fetch(config, url)
            content_type = (response.headers.get('Content-Type') or '').lower()
            for index, chunk in enumerate(response.iter_content(chunk_size=1024 * 64)):
                if index == 0:
                    _reject_html(config, url, content_type, chunk)
                handle.write(chunk)
        except requests.RequestException as exc:
            raise DownloadError(f'Could not download {config["label"]}: {exc}')
        if not handle.tell():
            raise DownloadError(
                f'{config["label"]} downloaded as an empty file ({url}).')
        handle.seek(0)
        yield handle


def _fetch(config, url):
    """GET the file, waiting out an export the source is still building."""
    wait = DOWNLOAD_RETRY_WAIT
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        response = requests.get(url, timeout=300, stream=True)
        response.raise_for_status()
        if response.status_code not in DOWNLOAD_PENDING_STATUSES:
            return response
        response.close()
        if attempt < DOWNLOAD_ATTEMPTS:
            time.sleep(wait)
            wait *= 2

    raise DownloadError(
        f'{config["label"]} is still being generated by the source after'
        f' {DOWNLOAD_ATTEMPTS} attempts ({url}); try again in a few minutes.')


# -- Import --

def import_source(source, path=None, geocode=True):
    """
    Import one source into `Location`, returning a dict of counts:
    imported, updated, removed, geocoded, skipped.
    """
    try:
        config = SOURCES[source]
    except KeyError:
        raise ValueError(f'Unknown location source: {source}')

    counts = {'imported': 0, 'updated': 0, 'removed': 0, 'geocoded': 0,
        'skipped': 0, **{key: 0 for key, _ in DISTRICT_TALLIES}}

    with _open_source(config, path) as handle:
        rows = [row for row in config['parse'](handle) if row.get('external_id')]

    if not rows:
        # An empty parse means a failed download or a changed format, never
        # that every school in the valley closed. Don't remove anything.
        return counts

    existing = {location.external_id: location
        for location in Location.objects.filter(source=source)}

    # Resolve coordinates first, outside any transaction: geocoding is
    # network work and must not hold a database transaction open.
    seen = set()
    resolved = []
    for row in rows:
        # Every row in the file is "seen", even one we can't place, so the
        # removal step below never deletes a school that's still listed.
        seen.add(row['external_id'])

        point = _point(row.get('lat'), row.get('lng'))
        if point is None:
            current = existing.get(row['external_id'])
            if current is not None:
                # Already imported: keep the coordinates we have.
                resolved.append((row, current.point))
                continue
            address = _address_string(row)
            if not geocode or not address:
                counts['skipped'] += 1
                continue
            result = geocode_cached(address)
            if result is None:
                counts['skipped'] += 1
                continue
            counts['geocoded'] += 1
            point = _point(*result)

        resolved.append((row, point))

    with transaction.atomic():
        for row, point in resolved:
            location = existing.get(row['external_id'])
            created = location is None
            if created:
                location = Location(source=source, external_id=row['external_id'])

            location.type = config['type']
            location.name = row['name'][:200]
            location.address = (row.get('address') or '')[:200]
            location.city_name = (row.get('city') or '')[:100]
            location.zip = (row.get('zip') or '')[:10]
            location.point = point
            location.metadata = row.get('metadata') or {}
            location.imported_at = timezone.now()
            # Always re-resolve rather than leaving it to save(): the
            # boundaries move between imports even where the location hasn't.
            location.resolve_regions()
            outcome = _cross_check_district(location, row.get('district_cds'))
            if outcome is not None:
                counts[outcome] += 1
            location.save()

            counts['imported' if created else 'updated'] += 1

        stale = Location.objects.filter(source=source).exclude(external_id__in=seen)
        counts['removed'] = stale.count()
        stale.delete()

    return counts


def _cross_check_district(location, district_cds):
    """
    Cross-check the district resolved from the point against the one the
    source says the address sits in, and prefer the source's when they
    differ: elementary and high district boundaries overlap, and the CDS
    code is CDE's own answer for the address.

    Returns None when the two agree (or the source names no district), and
    otherwise which of the three ways they parted: DISTRICT_CORRECTED,
    DISTRICT_FILLED_IN or DISTRICT_UNKNOWN. They mean different things --
    a correction is the overlap being settled, a fill-in is a point that
    landed outside every boundary we have, and an unknown district is a
    district missing from the Region table -- so they're counted apart.
    """
    if not district_cds:
        return None

    prefix = str(district_cds)[:7]
    current = location.school_district
    if current is not None and (current.external_id or '')[:7] == prefix:
        return None

    district = Region.objects.filter(
        type=Region.Type.SCHOOL_DISTRICT,
        external_id__startswith=prefix,
    ).first()
    if district is None:
        return DISTRICT_UNKNOWN

    location.school_district = district
    return DISTRICT_CORRECTED if current is not None else DISTRICT_FILLED_IN


def _point(lat, lng):
    if lat is None or lng is None:
        return None
    return Point(float(lng), float(lat), srid=4326)
