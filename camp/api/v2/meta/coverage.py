"""
First and last dates of data behind GET /api/2.0/meta/coverage/.

Computed on request (the endpoint caches it), never by a background task or
a stored table, so every query here has to be cheap on production-sized
tables: per-monitor lookups go through the entry tables' (monitor, timestamp,
...) unique index, and nothing takes a table-wide MIN/MAX of an entry table
(those have only a BRIN index on timestamp). Dates are Pacific calendar dates.
"""
from datetime import date, datetime
from typing import Optional, TypedDict

from django.conf import settings
from django.db.models import Max, Min, OuterRef, Subquery
from django.utils import timezone

from camp.apps.calheatscore.models import CalHeatScore
from camp.apps.calibrations.models import DefaultCalibration
from camp.apps.emissions.models import EmissionsRecord, MethanePlume
from camp.apps.entries.fields import EntryTypeField
from camp.apps.forecasts.models import Forecast
from camp.apps.hms.models import Fire, Smoke
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.models import LatestEntry
from camp.apps.pesticides.models import PesticideNotice, PesticideUse
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.tempo.models import Granule

HOURLY = BaseSummary.Resolution.HOURLY


class Span(TypedDict):
    first: Optional[date]
    last: Optional[date]


class CoverageError(ValueError):
    """A request coverage can't answer; the message is the client-facing 400."""


def pacific_date(value):
    """A timestamp's Pacific calendar date; a date passes through."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return timezone.localtime(value, settings.DEFAULT_TIMEZONE).date()
    return value


def make_span(first, last) -> Span:
    return {'first': pacific_date(first), 'last': pacific_date(last)}


def min_max(queryset, field) -> Span:
    """MIN and MAX of one field in a single query."""
    result = queryset.aggregate(first=Min(field), last=Max(field))
    return make_span(result['first'], result['last'])


def combine(*spans) -> Span:
    """The span covering all of `spans`, ignoring empty ones."""
    firsts = [s['first'] for s in spans if s['first'] is not None]
    lasts = [s['last'] for s in spans if s['last'] is not None]
    return {'first': min(firsts, default=None), 'last': max(lasts, default=None)}


def entry_model(entry_type):
    return EntryTypeField.get_model_map()[entry_type]


def require_summarized(entry_type, message):
    if not entry_model(entry_type).summarize:
        raise CoverageError(message)


# ---------- Monitors and regions ----------

def published_processor(monitor, model):
    """
    The processor the map and dashboard show for this monitor's entry type,
    or None when the (monitor type, entry type) pair isn't published. A blank
    DefaultCalibration means the default stage's first processor, as in
    calibrations.utils.get_default_calibration (inlined to keep it one query).
    """
    calibration = (
        DefaultCalibration.objects
        .filter(monitor_type=monitor.monitor_type, entry_type=model.entry_type)
        .values_list('calibration', flat=True)
        .first()
    )
    if calibration is None or calibration:
        return calibration
    stage = monitor.get_default_stage(model)
    processors = monitor.ENTRY_CONFIG.get(model, {}).get('processors', {}).get(stage) or []
    return processors[0].name if processors else ''


def monitor_span(monitor, entry_type: str) -> Span:
    """
    A published pair counts only the published processor's entries; any other
    pair counts every stage. `first` is MIN(timestamp) over the monitor's
    entries (the unique index), `last` the matching LatestEntry, falling back
    to MAX over the same entries if there is none. Three queries with data.
    """
    model = entry_model(entry_type)
    processor = published_processor(monitor, model)
    entries = model.objects.filter(monitor_id=monitor.pk)
    latest = LatestEntry.objects.filter(monitor_id=monitor.pk, entry_type=entry_type)
    if processor is not None:
        entries = entries.filter(processor=processor)
        latest = latest.filter(processor=processor)

    first = entries.aggregate(value=Min('timestamp'))['value']
    if first is None:
        return make_span(None, None)
    last = latest.aggregate(value=Max('timestamp'))['value']
    if last is None:
        last = entries.aggregate(value=Max('timestamp'))['value']
    return make_span(first, last)


def region_span(region, entry_type: str) -> Span:
    """Hourly RegionSummary rows, via the (region, entry_type, resolution, timestamp) index."""
    require_summarized(entry_type, f'{entry_type} has no region-level coverage; ask for a monitor.')
    return min_max(
        RegionSummary.objects.filter(region_id=region.pk, entry_type=entry_type, resolution=HOURLY),
        'timestamp',
    )


# ---------- Datasets ----------

def air_quality_span(entry_type):
    """
    Hourly MonitorSummary rows (the (resolution, timestamp) index) rather than
    the entry tables, so `first` is the first summarized hour.
    """
    if entry_type is None:
        entry_types = DefaultCalibration.objects.available_pollutants()
    else:
        require_summarized(entry_type, f'{entry_type} has no dataset-level coverage; ask for a monitor.')
        entry_types = [entry_type]
    return min_max(
        MonitorSummary.objects.filter(resolution=HOURLY, entry_type__in=entry_types),
        'timestamp',
    )


def weather_span(entry_type):
    """
    `first`: per CIMIS station, its earliest entry through the unique index
    (a correlated subquery, so one query for every station and entry type);
    `last`: the newest CIMIS LatestEntry.
    """
    models = [entry_model(entry_type)] if entry_type else list(CIMIS.ENTRY_CONFIG)
    firsts = CIMIS.objects.aggregate(**{
        model.entry_type: Min(Subquery(
            model.objects.filter(monitor_id=OuterRef('pk')).order_by('timestamp').values('timestamp')[:1]
        ))
        for model in models
    })
    last = LatestEntry.objects.filter(
        monitor_id__in=CIMIS.objects.values('pk'),
        entry_type__in=[model.entry_type for model in models],
    ).aggregate(value=Max('timestamp'))['value']
    first = min((v for v in firsts.values() if v is not None), default=None)
    return make_span(first, last)


def years_span(queryset) -> Span:
    """An annual table's years as whole calendar years."""
    result = queryset.aggregate(first=Min('year'), last=Max('year'))
    if result['first'] is None:
        return make_span(None, None)
    return make_span(date(result['first'], 1, 1), date(result['last'], 12, 31))


def emissions_span(entry_type):
    """Facility inventories by year (the (year, facility) index); methane plumes by observation."""
    spans = []
    if entry_type is None or entry_type.startswith('facility-'):
        spans.append(years_span(EmissionsRecord.objects.all()))
    if entry_type is None or entry_type == 'methane-emission-rate':
        spans.append(min_max(MethanePlume.objects.all(), 'observed_at'))
    return combine(*spans)


def tempo_span(entry_type):
    """Granules, via the (product, timestamp) index when a product is given."""
    granules = Granule.objects.all()
    if entry_type is not None:
        granules = granules.filter(product=entry_type)
    return min_max(granules, 'timestamp')


DATASET_SPANS = {
    'air-quality': air_quality_span,
    'weather': weather_span,
    # Small table (tens of rows a day), no date index needed.
    'hms-smoke': lambda entry_type: min_max(Smoke.objects.all(), 'date'),
    'hms-fire': lambda entry_type: min_max(Fire.objects.all(), 'date'),
    'pesticide-use': lambda entry_type: min_max(PesticideUse.objects.all(), 'application_date'),
    'pesticide-notices': lambda entry_type: min_max(PesticideNotice.objects.all(), 'scheduled_application'),
    # Small table (one row per zone per day).
    'forecasts': lambda entry_type: min_max(Forecast.objects.all(), 'forecast_date'),
    'calheatscore': lambda entry_type: min_max(CalHeatScore.objects.all(), 'date'),
    # A static release: no date range.
    'calenviroscreen': lambda entry_type: make_span(None, None),
    'emissions': emissions_span,
    'tempo': tempo_span,
}


def dataset_span(dataset_id: str, entry_type: Optional[str] = None) -> Span:
    return DATASET_SPANS[dataset_id](entry_type)
