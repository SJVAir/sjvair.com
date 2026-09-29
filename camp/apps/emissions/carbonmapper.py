"""
Carbon Mapper's public catalog of methane point sources, for the Valley
bbox: fetch the sources CSV, keep the CH4 sources inside a covered county,
link each to the nearest CADD dairy and the nearest CEIDARS facility with a
trusted point within MATCH_METERS, and write MethaneSource rows. methane.py
is the read side.

The catalog endpoint works unauthenticated; when CARBON_MAPPER_API_KEY is
set, fetch_csv sends it as a bearer token (a higher rate limit, per Carbon
Mapper's docs). Never log or otherwise surface the key's value.

Licence: custom non-commercial terms (MethaneSource.LICENSE). Every import
records them in SourceImport.notes; the pages carry the attribution.
"""
import csv
import io
import math
import re
from dataclasses import dataclass
from datetime import date

import requests
from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point, Polygon
from django.contrib.gis.measure import D
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.dateparse import parse_datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from camp.apps.emissions import dairies
from camp.apps.emissions.models import Dairy, DairyHerd, Facility, MethaneSource, MethanePlume, SourceImport
from camp.apps.regions.models import Region

URL = 'https://api.carbonmapper.org/api/v1/catalog/sources-csv'
BBOX = (-121.6, 34.8, -118.5, 38.3)
SOURCE = 'carbon-mapper'
MATCH_METERS = 1000
# The index prefilter around a source, in degrees (a little over 1 km of latitude).
COARSE_DEGREES = 0.012

# Plumes: the annotated catalog is paginated, not a single CSV.
PLUMES_URL = 'https://api.carbonmapper.org/api/v1/catalog/plumes/annotated'
PLUME_PAGE_SIZE = 500
# A plume's payload carries no source id -- matched to the nearest
# MethaneSource within the same radius sources are matched to a dairy or
# facility (MATCH_METERS; the "1000m" in a source_name's own eps).
PLUME_MATCH_METERS = MATCH_METERS
COLUMNS = (
    'source_name', 'source_latitude', 'source_longitude', 'gas', 'observation_date_count',
    'detection_date_count', 'source_persistence', 'source_emission', 'source_emission_uncertainty', 'ipcc_sector',
)
FIELDS = ('gas', 'point', 'ipcc_sector', 'sector_label', 'persistence', 'emission_kg_h', 'uncertainty_kg_h',
          'observations', 'detections', 'county', 'dairy', 'facility', 'distance_m')

# The ipcc_sector column reads "Livestock (4B)", not the bare code: pull the
# trailing parenthesized code out, falling back to the raw value (the test
# rows, and a value with no parens such as "NA" or "Other").
_SECTOR_CODE = re.compile(r'\(([^()]+)\)\s*$')


class CarbonMapperError(Exception):
    pass


def fetch_csv():
    """The sources CSV for BBOX (requests repeats `bbox` for each value, as the API expects). The one network call; tests patch it."""
    headers = {}
    if settings.CARBON_MAPPER_API_KEY:
        headers['Authorization'] = f'Bearer {settings.CARBON_MAPPER_API_KEY}'
    response = requests.get(URL, params={'bbox': list(BBOX)}, headers=headers, timeout=120)
    response.raise_for_status()
    return response.text


def read_rows(text):
    reader = csv.DictReader(io.StringIO(text))
    missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
    if missing:
        raise CarbonMapperError(f'sources CSV is missing columns: {", ".join(missing)}')
    return list(reader)


def _float(value):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value):
    number = _float(value)
    return int(number) if number is not None else 0


def _sector_code(value):
    value = (value or '').strip()
    match = _SECTOR_CODE.search(value)
    return (match.group(1) if match else value).upper()


def parse_row(row):
    """A MethaneSource's field values (county and links left to apply), or None without a name or usable coordinates."""
    name = (row.get('source_name') or '').strip()[:64]
    lat, lng = _float(row.get('source_latitude')), _float(row.get('source_longitude'))
    if not name or lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        return None
    code = _sector_code(row.get('ipcc_sector'))[:8]
    group, label = MethaneSource.sector_for(code)
    return {
        'source_name': name,
        'gas': (row.get('gas') or '').strip().upper()[:3],
        'point': Point(lng, lat, srid=4326),
        'ipcc_sector': code,
        'sector_label': label[:32],
        'persistence': _float(row.get('source_persistence')),
        'emission_kg_h': _float(row.get('source_emission')),
        'uncertainty_kg_h': _float(row.get('source_emission_uncertainty')),
        'observations': _int(row.get('observation_date_count')),
        'detections': _int(row.get('detection_date_count')),
    }


def county_index():
    """[(Region, prepared geometry)] for the covered counties: ~730 point-in-polygon tests run in GEOS, not SQL."""
    return [(region, region.boundary.geometry.prepared) for region in Region.objects.counties().select_related('boundary') if region.boundary]


def county_for(point, index):
    for region, prepared in index:
        if prepared.contains(point):
            return region
    return None


def nearest(queryset, point):
    """(pk, metres) of the queryset's nearest row within MATCH_METERS of `point`, or (None, None). `point` is the model's PointField name."""
    match = (
        queryset.filter(point__dwithin=(point, COARSE_DEGREES), point__distance_lte=(point, D(m=MATCH_METERS)))
        .annotate(metres=Distance('point', point)).order_by('metres').values_list('pk', 'metres').first()
    )
    if match is None:
        return None, None
    return match[0], match[1].m


def herded_dairies():
    """Dairies CADD has counted cattle at in some year: a site that never had a herd isn't a plume's source."""
    return Dairy.objects.filter(pk__in=DairyHerd.objects.filter(dairies.COUNTED).values('dairy'))


def trusted_facilities():
    """Facilities whose point can be trusted to be the site (Phase 2's rule), never an address geocode or a legacy point."""
    return Facility.objects.filter(point__isnull=False, point_source__in=Facility.TRUSTED_POINT_SOURCES)


@dataclass
class Report:
    fetched: int = 0
    co2: int = 0
    outside: int = 0
    skipped: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    dairy_matches: int = 0
    facility_matches: int = 0

    def lines(self):
        return [
            f'Carbon Mapper: {self.fetched:,} rows; {self.co2:,} CO2 skipped, {self.outside:,} outside the covered counties, '
            f'{self.skipped:,} unparseable or duplicate.',
            f'{self.created:,} sources created, {self.updated:,} updated, {self.deleted:,} removed (no longer in the catalog); '
            f'{self.dairy_matches:,} linked to a dairy and {self.facility_matches:,} to a facility within {MATCH_METERS:,} m.',
        ]


def apply(rows):
    """
    Upsert every CH4 source inside a covered county on `source_name`, delete
    the rest, stamp SourceImport(SOURCE) with the licence, and bump the
    methane and dairies cache generations (the dairy table's methane column
    is cached under the dairies one). `rows` is the whole bbox: a partial
    list would delete the rest.
    """
    from camp.apps.emissions import dairies, methane

    report = Report(fetched=len(rows))
    index = county_index()
    facilities = trusted_facilities()
    dairy_candidates = herded_dairies()
    with transaction.atomic():
        existing = {source.source_name: source for source in MethaneSource.objects.all()}
        seen = set()
        for raw in rows:
            values = parse_row(raw)
            if values is None or values['source_name'] in seen:
                report.skipped += 1
                continue
            if values['gas'] != MethaneSource.Gas.CH4:
                report.co2 += 1
                continue
            county = county_for(values['point'], index)
            if county is None:
                report.outside += 1
                continue
            seen.add(values['source_name'])
            values['county'] = county
            dairy_pk, dairy_m = nearest(dairy_candidates, values['point'])
            facility_pk, facility_m = nearest(facilities, values['point'])
            values['dairy_id'] = dairy_pk
            values['facility_id'] = facility_pk
            distances = [m for m in (dairy_m, facility_m) if m is not None]
            values['distance_m'] = min(distances) if distances else None
            report.dairy_matches += dairy_pk is not None
            report.facility_matches += facility_pk is not None
            source = existing.get(values['source_name'])
            if source is None:
                MethaneSource.objects.create(**values)
                report.created += 1
            else:
                for field, value in values.items():
                    setattr(source, field, value)
                source.save()
                report.updated += 1
        report.deleted, _ = MethaneSource.objects.exclude(source_name__in=seen).delete()
        SourceImport.objects.create(
            source=SOURCE, data_through=date.today(),
            notes={
                'license': MethaneSource.LICENSE, 'license_url': MethaneSource.LICENSE_URL,
                'attribution': MethaneSource.ATTRIBUTION, 'sources': len(seen),
                'created': report.created, 'updated': report.updated, 'deleted': report.deleted,
                'dairy_matches': report.dairy_matches, 'facility_matches': report.facility_matches,
            },
        )
    methane.clear_caches()
    dairies.clear_caches()
    return report


def _bearer_headers():
    headers = {}
    if settings.CARBON_MAPPER_API_KEY:
        headers['Authorization'] = f'Bearer {settings.CARBON_MAPPER_API_KEY}'
    return headers


def fetch_plumes_page(limit, offset):
    """One page of the plumes/annotated catalog for BBOX: published, CH4 plumes only. The one listing network call; tests patch it."""
    params = {
        'bbox': list(BBOX), 'plume_gas': MethaneSource.Gas.CH4,
        'status': 'published', 'limit': limit, 'offset': offset,
    }
    response = requests.get(PLUMES_URL, params=params, headers=_bearer_headers(), timeout=120)
    response.raise_for_status()
    return response.json()


def fetch_all_plumes():
    """Every published CH4 plume for BBOX, paged in order; the API's own bbox_count bounds the loop."""
    items = []
    offset = 0
    while True:
        page = fetch_plumes_page(PLUME_PAGE_SIZE, offset)
        page_items = page.get('items') or []
        items.extend(page_items)
        offset += len(page_items)
        if not page_items or offset >= (page.get('bbox_count') or 0):
            break
    return items


def _image_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))
    session.mount('https://', HTTPAdapter(max_retries=retry))
    return session


def fetch_plume_image(url, session=None):
    """
    The plume PNG's bytes for a (signed, short-lived) `url`, or None on
    failure -- a failed image download is counted and skipped, never fatal.
    Never logs the url: it's a signed S3 link.
    """
    session = session or _image_session()
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException:
        return None
    return response.content


def parse_plume(item):
    """A MethanePlume's field values plus '_image_url' (popped before saving), or None for anything not worth keeping."""
    plume_id = (item.get('plume_id') or '').strip()[:64]
    if not plume_id:
        return None
    if (item.get('gas') or '').strip().upper() != MethaneSource.Gas.CH4:
        return None
    if (item.get('status') or '').strip().lower() != 'published' or item.get('hide_emission'):
        return None
    coords = (item.get('geometry_json') or {}).get('coordinates') or []
    lng = _float(coords[0]) if len(coords) > 0 else None
    lat = _float(coords[1]) if len(coords) > 1 else None
    if lng is None or lat is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    bounds = item.get('plume_bounds') or []
    if len(bounds) != 4:
        return None
    west, south, east, north = (_float(value) for value in bounds)
    if None in (west, south, east, north):
        return None
    observed_at = parse_datetime(item.get('scene_timestamp') or '')
    if observed_at is None:
        return None
    bounds = Polygon.from_bbox((west, south, east, north))
    bounds.srid = 4326
    return {
        'plume_id': plume_id,
        'observed_at': observed_at,
        'platform': (item.get('platform') or '').strip()[:32],
        'instrument': (item.get('instrument') or '').strip()[:16],
        'point': Point(lng, lat, srid=4326),
        'bounds': bounds,
        'emission_kg_h': _float(item.get('emission_auto')),
        'uncertainty_kg_h': _float(item.get('emission_uncertainty_auto')),
        'wind_speed': _float(item.get('wind_speed_avg_auto')),
        'wind_direction': _float(item.get('wind_direction_avg_auto')),
        '_image_url': (item.get('plume_png') or '').strip(),
    }


@dataclass
class PlumeReport:
    fetched: int = 0
    skipped: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    matched: int = 0
    images_fetched: int = 0
    images_failed: int = 0

    def lines(self):
        return [
            f'Carbon Mapper plumes: {self.fetched:,} rows; {self.skipped:,} unparseable, unpublished, hidden, or duplicate.',
            f'{self.created:,} created, {self.updated:,} updated, {self.deleted:,} removed (no longer in the catalog); '
            f'{self.matched:,} linked to a source within {PLUME_MATCH_METERS:,} m.',
            f'{self.images_fetched:,} images fetched, {self.images_failed:,} failed.',
        ]


def _save_plume_image(plume, image_bytes, filename):
    """
    Uploads the image to storage first and returns the stored name, without
    touching the row -- mirrors tempo/sync.py's sync_granule ordering, so a
    failed upload never strands a plume pointing at a name that was never
    written. `plume` need not be saved yet; generate_filename only reads its
    fields (observed_at, for the upload path).
    """
    name = plume.image.field.generate_filename(plume, filename)
    return plume.image.storage.save(name, ContentFile(image_bytes))


def apply_plumes(items):
    """
    Upsert every published, non-hidden CH4 plume in `items` on plume_id,
    link each to the nearest MethaneSource within PLUME_MATCH_METERS (the
    catalog's plume payload carries no source id), delete plumes no longer
    returned (and their image files), and fetch the PNG for any plume that's
    new or still has no image -- never re-downloading one already on file.
    Every image is uploaded before its row is written or updated. `items` is
    the whole bbox: a partial list would delete the rest.
    """
    report = PlumeReport(fetched=len(items))
    sources = MethaneSource.objects.filter(gas=MethaneSource.Gas.CH4)
    session = _image_session()
    existing = {plume.plume_id: plume for plume in MethanePlume.objects.all()}
    seen = set()
    prepared = []
    for raw in items:
        values = parse_plume(raw)
        if values is None or values['plume_id'] in seen:
            report.skipped += 1
            continue
        image_url = values.pop('_image_url')
        seen.add(values['plume_id'])
        source_pk, _ = nearest(sources, values['point'])
        values['source_id'] = source_pk
        report.matched += source_pk is not None

        plume = existing.get(values['plume_id']) or MethanePlume(plume_id=values['plume_id'])
        for field, value in values.items():
            setattr(plume, field, value)

        image_name = None
        if image_url and not plume.image:
            image_bytes = fetch_plume_image(image_url, session=session)
            if image_bytes is None:
                report.images_failed += 1
            else:
                image_name = _save_plume_image(plume, image_bytes, f'{plume.plume_id}.png')
                report.images_fetched += 1
        prepared.append((plume, image_name))

    with transaction.atomic():
        for plume, image_name in prepared:
            if image_name:
                plume.image.name = image_name
            is_new = plume.pk is None
            plume.save()
            report.created += is_new
            report.updated += not is_new
        stale = MethanePlume.objects.exclude(plume_id__in=seen)
        for plume in stale:
            if plume.image:
                plume.image.delete(save=False)
        report.deleted, _ = stale.delete()
    return report
