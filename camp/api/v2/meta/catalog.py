"""
The dataset catalog behind GET /api/2.0/meta/datasets/.

Dataset ids and entry-type ids are a permanent public contract: never reused,
and a rename changes only the label.
"""
from django.conf import settings
from django.urls import reverse

from camp.apps.calheatscore.scales import get_heat_scale
from camp.apps.calibrations.models import DefaultCalibration
from camp.apps.emissions import pollutants
from camp.apps.entries.models import meteorological
from camp.apps.forecasts.scales import get_aqi_forecast_scale, get_burn_status_scale
from camp.apps.hms.scales import get_fire_scale, get_smoke_scale
from camp.apps.monitors.models import Monitor
from camp.apps.summaries.models import BaseSummary
from camp.apps.summaries.selection import is_summarized
from camp.apps.tempo.models import Granule
from camp.apps.tempo.products import TEMPO_UNITS

SUMMARY_RESOLUTIONS = [r.value for r in BaseSummary.Resolution]
SUMMARIZED = ['raw', *SUMMARY_RESOLUTIONS]
RAW_ONLY = ['raw']

SUMMARY_RULES = {
    'complete_after_period_end': ['month', 'quarter', 'season', 'year'],
}

# Kind per TEMPO product; labels come from Granule.Product, units from TEMPO_UNITS.
TEMPO_KINDS = {
    Granule.Product.NO2: 'pollutant',
    Granule.Product.O3TOT: 'other',
    Granule.Product.HCHO: 'pollutant',
    Granule.Product.CLDO4: 'other',
}


# Display hints for ids that don't follow their kind's default: precision is
# decimal places, chart is 'line' | 'bar' | None, y_min 0 starts the axis at
# zero and None leaves it auto.
DISPLAY_OVERRIDES = {
    'particulates': (0, 'line', 0),
    'heat-score': (0, 'bar', 0),
    'aqi-forecast': (0, 'bar', 0),
    'pounds-applied': (0, 'bar', 0),
    'acres-treated': (0, 'bar', 0),
    'applications': (0, 'bar', 0),
    'spray-notice': (0, 'bar', 0),
    'fire-frp': (1, 'bar', 0),
    'ces-score': (1, 'bar', 0),
    'methane-emission-rate': (1, 'line', 0),
    # Weather totals in inches: bars from zero, to the hundredth.
    'precipitation': (2, 'bar', 0),
    'eto': (2, 'bar', 0),
    'etr': (2, 'bar', 0),
    'smoke-density': (None, None, None),
    'burn-status': (None, None, None),
}


# How an entry's values roll up over time: 'sum' (totals add up), 'mean'
# (they average), or None (they never roll up: scores, categories, forecasts,
# single detections). Monitor entry types are 'mean' unless listed here;
# every static entry type states its own.
MONITOR_AGGREGATE_OVERRIDES = {
    'precipitation': 'sum',
    'eto': 'sum',
    'etr': 'sum',
    # A plain average of compass degrees is wrong (350 and 10 give 180).
    'winddirection': None,
}


# TEMPO ids (no2, ...) share names with monitor entry types, so they carry their own.
TEMPO_DISPLAY = {'precision': None, 'chart': 'line', 'y_min': None}


def display_for(entry_id, kind):
    if entry_id in DISPLAY_OVERRIDES or entry_id.startswith('facility-'):
        precision, chart, y_min = DISPLAY_OVERRIDES.get(entry_id, (1, 'bar', 0))
    elif kind == 'meteorological':
        precision, chart, y_min = 1, 'line', None
    else:
        precision, chart, y_min = 1, 'line', 0
    return {'precision': precision, 'chart': chart, 'y_min': y_min}


def _entry(id, label, kind, units, resolutions, aggregate, display=None, **extra):
    return {
        'id': id,
        'label': str(label),
        'kind': kind,
        'units': units,
        'resolutions': resolutions,
        'aggregate': aggregate,
        'display': display or display_for(id, kind),
        'retired': None,
        **extra,
    }


def _other(id, label, units, resolutions, aggregate):
    return _entry(id, label, 'other', units, resolutions, aggregate)


def _from_scale(scale, resolutions, aggregate):
    """An entry type whose label and units come from its domain scale."""
    return _other(scale.id, scale.label, scale.units, resolutions, aggregate)


def _dataset(id, label, description, source, license, geographies, entry_types, meta_url=None, places_url=''):
    return {
        'id': id,
        'label': label,
        'description': description,
        'source': source,
        'license': license,
        'geographies': geographies,
        'meta_url': meta_url() if callable(meta_url) else (meta_url or ''),
        'places_url': places_url,
        'entry_types': entry_types,
        'retired': None,
    }


# Criteria pollutants and ammonia from camp.apps.emissions.pollutants (tons/yr).
# Individual toxics (lbs/yr, rows in the database) are not listed.
FACILITY_POLLUTANTS = pollutants.CRITERIA + pollutants.PRECURSORS

STATIC_DATASETS = {
    'hms-smoke': lambda: _dataset(
        'hms-smoke', 'Wildfire Smoke',
        'Daily smoke plume outlines and density from satellite imagery.',
        'NOAA Hazard Mapping System', 'Public domain', ['polygon'],
        [_from_scale(get_smoke_scale(), ['day'], None)],
        meta_url=lambda: reverse('api:v2:hms:hms-meta'),
    ),
    'hms-fire': lambda: _dataset(
        'hms-fire', 'Fire Detections',
        'Satellite-detected active fire points with fire radiative power.',
        'NOAA Hazard Mapping System', 'Public domain', ['point'],
        [_from_scale(get_fire_scale(), ['raw'], None)],
        meta_url=lambda: reverse('api:v2:hms:hms-meta'),
    ),
    'pesticide-use': lambda: _dataset(
        'pesticide-use', 'Pesticide Use',
        'Reported agricultural pesticide applications, summed by region.',
        'California DPR Pesticide Use Reporting (PUR)', '', ['region'],
        [
            _other('pounds-applied', 'Pounds Applied', 'lbs', ['month', 'year'], 'sum'),
            _other('acres-treated', 'Acres Treated', 'acres', ['month', 'year'], 'sum'),
            _other('applications', 'Applications', 'applications', ['month', 'year'], 'sum'),
        ],
        meta_url=lambda: reverse('api:v2:pesticides:pesticides-meta'),
    ),
    'pesticide-notices': lambda: _dataset(
        'pesticide-notices', 'Pesticide Spray Notices',
        'Advance notices of planned restricted-use pesticide applications.',
        'SprayDays (California DPR)', '', ['point'],
        [_other('spray-notice', 'Spray Notices', '', ['day'], 'sum')],
        meta_url=lambda: reverse('api:v2:pesticides:pesticides-meta'),
    ),
    'forecasts': lambda: _dataset(
        'forecasts', 'Air Quality Forecasts',
        'Daily air quality index forecasts for each forecast zone.',
        'San Joaquin Valley Air Pollution Control District', '', ['zone'],
        [
            _from_scale(get_aqi_forecast_scale(), ['day'], None),
            _from_scale(get_burn_status_scale(), ['day'], None),
        ],
        meta_url=lambda: reverse('api:v2:forecasts:forecast-meta'),
    ),
    'calheatscore': lambda: _dataset(
        'calheatscore', 'CalHeatScore',
        'Daily heat health risk score by ZIP code.',
        'OEHHA CalHeatScore', '', ['zip'],
        [_from_scale(get_heat_scale(), ['day'], None)],
        meta_url=lambda: reverse('api:v2:calheatscore:calheatscore-meta'),
    ),
    'calenviroscreen': lambda: _dataset(
        'calenviroscreen', 'CalEnviroScreen',
        'Cumulative pollution burden and vulnerability percentile by census tract.',
        'OEHHA CalEnviroScreen', '', ['tract'],
        [_other('ces-score', 'CalEnviroScreen Score', 'percentile', [], None)],
    ),
    'emissions': lambda: _dataset(
        'emissions', 'Emissions',
        'Annual facility emissions of criteria pollutants and ammonia, and satellite-detected methane source rates.',
        'CARB CEIDARS facility inventory, Carbon Mapper', '', ['point', 'region'],
        [
            *(_other(f'facility-{p.key}', f'{p.label} (facilities)', p.unit_label, ['year'], None)
              for p in FACILITY_POLLUTANTS),
            _other('methane-emission-rate', 'Methane Emission Rate', 'kg/h', ['raw'], None),
        ],
    ),
    'tempo': lambda: _dataset(
        'tempo', 'NASA TEMPO Satellite',
        'Hourly satellite column measurements over the San Joaquin Valley.',
        'NASA TEMPO', 'Public domain', ['point', 'region'],
        [
            _entry(product.value, product.label, kind, TEMPO_UNITS[product], ['hour'], 'mean', display=TEMPO_DISPLAY)
            for product, kind in TEMPO_KINDS.items()
        ],
    ),
}

DATASET_IDS = (
    'air-quality', 'weather', 'hms-smoke', 'hms-fire', 'pesticide-use',
    'pesticide-notices', 'forecasts', 'calheatscore', 'calenviroscreen',
    'emissions', 'tempo',
)


def _kind(entry_model):
    if entry_model.__module__ == meteorological.__name__:
        return 'meteorological'
    if entry_model.entry_type == 'particulates':
        return 'other'
    return 'pollutant'


def _monitor_dataset(weather):
    """
    (entry models sorted by entry_type, {entry_type: producing monitor models})
    for the weather dataset (the monitor types opted in to it by
    settings.MONITOR_OPT_IN_TYPES) or the air-quality one (every enabled monitor
    type not opted in to another dataset).
    """
    opt_in = settings.MONITOR_OPT_IN_TYPES
    monitor_models = Monitor.get_opt_in_subclasses('weather') if weather else [
        m for m in Monitor.get_enabled_subclasses() if m.monitor_type not in opt_in
    ]
    models = {}
    producers = {}
    for monitor_model in monitor_models:
        for entry_model in monitor_model.ENTRY_CONFIG:
            models[entry_model.entry_type] = entry_model
            producers.setdefault(entry_model.entry_type, []).append(monitor_model)
    return [models[key] for key in sorted(models)], producers


def _monitor_entry_models(weather):
    return _monitor_dataset(weather)[0]


def _monitor_entry_types(weather):
    available = None if weather else set(DefaultCalibration.objects.available_pollutants())
    entry_types = []
    entry_models, producers = _monitor_dataset(weather)
    for entry_model in entry_models:
        kind = _kind(entry_model)
        extra = {}
        if available is not None and kind == 'pollutant':
            extra['available'] = entry_model.entry_type in available
        entry_types.append(_entry(
            entry_model.entry_type,
            entry_model.label,
            kind,
            entry_model.units or '',
            SUMMARIZED if any(is_summarized(m, entry_model) for m in producers[entry_model.entry_type]) else RAW_ONLY,
            MONITOR_AGGREGATE_OVERRIDES.get(entry_model.entry_type, 'mean'),
            **extra,
        ))
    return entry_types


def _monitor_list_url(dataset):
    return f"{reverse('api:v2:monitors:monitor-list')}?dataset={dataset}"


def _air_quality():
    return _dataset(
        'air-quality', 'Air Quality',
        'Air quality measurements from SJVAir sensors and partner monitoring networks.',
        'SJVAir sensors, AirNow, AQview, AQLite', '', ['monitor', 'region'],
        _monitor_entry_types(weather=False),
        meta_url=reverse('api:v2:monitors:monitor-meta'),
        places_url=_monitor_list_url('air-quality'),
    )


def _weather():
    return _dataset(
        'weather', 'Weather',
        'Hourly weather observations from agricultural weather stations.',
        'California Irrigation Management Information System (CIMIS)', '',
        ['monitor'],
        _monitor_entry_types(weather=True),
        meta_url=reverse('api:v2:monitors:monitor-meta'),
        places_url=_monitor_list_url('weather'),
    )


def get_catalog():
    builders = {'air-quality': _air_quality, 'weather': _weather, **STATIC_DATASETS}
    return {
        'datasets': [builders[dataset_id]() for dataset_id in DATASET_IDS],
        'summary_rules': SUMMARY_RULES,
    }


def dataset_entry_types(dataset_id):
    """
    Entry-type ids of one dataset; empty for an unknown dataset id.
    Built without the catalog's DefaultCalibration query (that only sets
    `available`, never which ids are listed), so it is cheap per request.
    """
    if dataset_id in ('air-quality', 'weather'):
        return [m.entry_type for m in _monitor_entry_models(weather=dataset_id == 'weather')]
    if dataset_id in STATIC_DATASETS:
        return [e['id'] for e in STATIC_DATASETS[dataset_id]()['entry_types']]
    return []
