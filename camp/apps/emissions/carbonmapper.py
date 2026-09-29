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
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db import transaction

from camp.apps.emissions import dairies
from camp.apps.emissions.models import Dairy, DairyHerd, Facility, MethaneSource, SourceImport
from camp.apps.regions.models import Region

URL = 'https://api.carbonmapper.org/api/v1/catalog/sources-csv'
BBOX = (-121.6, 34.8, -118.5, 38.3)
SOURCE = 'carbon-mapper'
MATCH_METERS = 1000
# The index prefilter around a source, in degrees (a little over 1 km of latitude).
COARSE_DEGREES = 0.012
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
