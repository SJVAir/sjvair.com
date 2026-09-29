"""
CalGEM's WellSTAR wells, from the state's ArcGIS REST layer (CC-BY, no key):
every Active, Idle or New well in the covered counties, 5,000 a page. The
data.ca.gov package (wellstar-oil-and-gas-wells) documents it; its hub CSV
lags the service by months, so the service is the source.

Wells join nothing in CEIDARS (no shared key; don't try). They join regions
by point and schools by distance (wells.py).
"""
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone

import requests
from django.conf import settings
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone as django_timezone

from camp.apps.emissions.models import SourceImport, Well
from camp.apps.regions.models import Region

URL = 'https://gis.conservation.ca.gov/server/rest/services/WellSTAR/Wells/MapServer/0/query'
SOURCE = 'wellstar'
STATUSES = tuple(Well.Status.values)
OUT_FIELDS = (
    'API', 'LeaseName', 'WellNumber', 'WellDesignation', 'WellStatus', 'WellType', 'WellTypeLabel', 'OperatorCode',
    'OperatorName', 'FieldName', 'CountyName', 'Latitude', 'Longitude', 'SpudDate', 'inHPZ', 'isDirectionallyDrilled', 'GISSource',
)
PAGE_SIZE = 5000
RETRIES = 4
# The Well fields apply() compares and updates on a re-run.
FIELDS = (
    'lease_name', 'well_number', 'designation', 'status', 'well_type', 'well_type_label', 'operator_code',
    'operator_name', 'field_name', 'county', 'point', 'spud_date', 'in_hpz', 'directional',
)
TRUE_WORDS = {'y', 'yes', 'true', 't', '1'}
DATE_FORMATS = ('%m/%d/%Y', '%Y-%m-%d', '%m/%d/%Y %H:%M:%S', '%Y-%m-%dT%H:%M:%S')


class WellSTARError(RuntimeError):
    """The service answered with an error object instead of features."""


def where(counties=None):
    names = ', '.join(f"'{name}'" for name in (counties or settings.SJVAIR_COUNTIES))
    statuses = ', '.join(f"'{status}'" for status in STATUSES)
    return f'CountyName IN ({names}) AND WellStatus IN ({statuses})'


def params(offset, counties=None):
    return {
        'where': where(counties), 'outFields': ','.join(OUT_FIELDS), 'returnGeometry': 'false',
        # A stable order is what makes offset paging complete and duplicate-free.
        'orderByFields': 'API', 'resultOffset': offset, 'resultRecordCount': PAGE_SIZE, 'f': 'json',
    }


def fetch_page(offset, counties=None):
    """One page of the layer (a dict with `features` and `exceededTransferLimit`). The one network call here; tests patch it."""
    for attempt in range(RETRIES):
        try:
            response = requests.get(URL, params=params(offset, counties), timeout=120)
            response.raise_for_status()
            data = response.json()
            if 'error' in data:
                raise WellSTARError(str(data['error']))
            return data
        except (requests.RequestException, ValueError) as exc:
            if attempt == RETRIES - 1:
                raise
            time.sleep(2 ** attempt)


def pages(counties=None):
    """Yields each page's feature list until the service says it has no more."""
    offset = 0
    while True:
        data = fetch_page(offset, counties)
        features = data.get('features') or []
        yield features
        if not data.get('exceededTransferLimit') or len(features) < 1:
            return
        offset += len(features)


def parse_date(value):
    """A date from ArcGIS epoch milliseconds, or a 'MM/DD/YYYY' / ISO string; None for blank or nonsense."""
    if value in (None, '', 0):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None


def parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in TRUE_WORDS


def _text(attrs, name, limit):
    return str(attrs.get(name) or '').strip()[:limit]


def parse_feature(feature):
    """
    A Well's field values from one REST feature, or None when it has no API
    number or no usable coordinates. `county_name` is CalGEM's ("Kern");
    apply() resolves it.
    """
    attrs = feature.get('attributes', feature)
    api = _text(attrs, 'API', 14)
    try:
        lat, lng = float(attrs.get('Latitude')), float(attrs.get('Longitude'))
    except (TypeError, ValueError):
        return None
    if not api or not (math.isfinite(lat) and math.isfinite(lng)) or not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        return None
    status = _text(attrs, 'WellStatus', 8)
    if status not in STATUSES:
        return None
    hpz = _text(attrs, 'inHPZ', 24)
    return {
        'api': api,
        'lease_name': _text(attrs, 'LeaseName', 128),
        'well_number': _text(attrs, 'WellNumber', 32),
        'designation': _text(attrs, 'WellDesignation', 64),
        'status': status,
        'well_type': _text(attrs, 'WellType', 8),
        'well_type_label': _text(attrs, 'WellTypeLabel', 64),
        'operator_code': _text(attrs, 'OperatorCode', 16),
        'operator_name': _text(attrs, 'OperatorName', 128),
        'field_name': _text(attrs, 'FieldName', 128),
        'county_name': _text(attrs, 'CountyName', 64),
        'point': Point(lng, lat, srid=4326),
        'spud_date': parse_date(attrs.get('SpudDate')),
        'in_hpz': hpz if hpz in Well.HPZ.values else '',
        'directional': parse_bool(attrs.get('isDirectionallyDrilled')),
    }


@dataclass
class Report:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    skipped: int = 0

    def lines(self):
        return [
            f'WellSTAR: {self.fetched:,} features; {self.created:,} wells created, {self.updated:,} updated, '
            f'{self.unchanged:,} unchanged, {self.deleted:,} removed (no longer active, idle or new), {self.skipped:,} skipped.',
        ]


def _counties():
    """{'Kern': Region, 'Kern County': Region, ...} for the covered counties."""
    result = {}
    for region in Region.objects.counties():
        result[region.name] = region
        result[region.short_name] = region
    return result


def _same(well, values):
    for field in FIELDS:
        current = getattr(well, field)
        new = values[field]
        if field == 'point':
            if abs(current.x - new.x) > 1e-7 or abs(current.y - new.y) > 1e-7:
                return False
        elif field == 'county':
            if well.county_id != new.pk:
                return False
        elif current != new:
            return False
    return True


def apply(features):
    """
    Upsert every parsed feature on `api`, delete the wells not in `features`
    (plugged or cancelled since, or gone from the service), stamp
    SourceImport('wellstar') and bump the wells cache generation, in one
    transaction. `features` is the whole Valley (every page): a partial list
    would delete the rest.
    """
    from camp.apps.emissions import wells

    report = Report(fetched=len(features))
    counties = _counties()
    with transaction.atomic():
        existing = {well.api: well for well in Well.objects.all()}
        seen, new, changed = set(), [], []
        for feature in features:
            values = parse_feature(feature)
            if values is None:
                report.skipped += 1
                continue
            county = counties.get(values.pop('county_name'))
            if county is None or values['api'] in seen:
                report.skipped += 1
                continue
            values['county'] = county
            seen.add(values['api'])
            well = existing.get(values['api'])
            if well is None:
                new.append(Well(**values))
            elif _same(well, values):
                report.unchanged += 1
            else:
                for field, value in values.items():
                    setattr(well, field, value)
                well.imported_at = django_timezone.now()
                changed.append(well)
        Well.objects.bulk_create(new, batch_size=1000)
        Well.objects.bulk_update(changed, list(FIELDS) + ['imported_at'], batch_size=1000)
        report.created, report.updated = len(new), len(changed)
        report.deleted, _ = Well.objects.exclude(api__in=seen).delete()
        SourceImport.objects.create(
            source=SOURCE, data_through=date.today(),
            notes={'wells': len(seen), 'created': report.created, 'updated': report.updated, 'deleted': report.deleted},
        )
    wells.clear_caches()
    return report
