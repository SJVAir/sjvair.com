"""
The dataset catalog behind GET /api/2.0/meta/datasets/.

Dataset ids and entry-type ids are a permanent public contract: never reused,
and a rename changes only the label.
"""
from django.urls import reverse

from camp.apps.calibrations.models import DefaultCalibration
from camp.apps.entries.models import meteorological
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.models import Monitor
from camp.apps.summaries.models import BaseSummary
from camp.apps.tempo.models import Granule

SUMMARY_RESOLUTIONS = [r.value for r in BaseSummary.Resolution]
SUMMARIZED = ['raw', *SUMMARY_RESOLUTIONS]
RAW_ONLY = ['raw']

SUMMARY_RULES = {
    'complete_after_period_end': ['month', 'quarter', 'season', 'year'],
}

# Units and kind per TEMPO product; labels come from Granule.Product.
TEMPO_PRODUCTS = {
    Granule.Product.NO2: ('pollutant', 'molecules/cm²'),
    Granule.Product.O3TOT: ('other', 'molecules/cm²'),
    Granule.Product.HCHO: ('pollutant', 'molecules/cm²'),
    Granule.Product.CLDO4: ('other', 'fraction'),
}


def _entry(id, label, kind, units, resolutions, **extra):
    return {
        'id': id,
        'label': str(label),
        'kind': kind,
        'units': units,
        'resolutions': resolutions,
        'retired': None,
        **extra,
    }


def _other(id, label, units, resolutions):
    return _entry(id, label, 'other', units, resolutions)


def _dataset(id, label, description, source, license, geographies, entry_types, meta_url=''):
    return {
        'id': id,
        'label': label,
        'description': description,
        'source': source,
        'license': license,
        'geographies': geographies,
        'meta_url': meta_url,
        'entry_types': entry_types,
        'retired': None,
    }


STATIC_DATASETS = {
    'hms-smoke': lambda: _dataset(
        'hms-smoke', 'Wildfire Smoke',
        'Daily smoke plume outlines and density from satellite imagery.',
        'NOAA Hazard Mapping System', 'Public domain', ['polygon'],
        [_other('smoke-density', 'Smoke Density', '', ['day'])],
    ),
    'hms-fire': lambda: _dataset(
        'hms-fire', 'Fire Detections',
        'Satellite-detected active fire points with fire radiative power.',
        'NOAA Hazard Mapping System', 'Public domain', ['point'],
        [_other('fire-frp', 'Fire Radiative Power', 'MW', ['raw'])],
    ),
    'pesticide-use': lambda: _dataset(
        'pesticide-use', 'Pesticide Use',
        'Reported agricultural pesticide applications, summed by region.',
        'California DPR Pesticide Use Reporting (PUR)', 'Public records', ['region'],
        [
            _other('pounds-applied', 'Pounds Applied', 'lbs', ['month', 'year']),
            _other('acres-treated', 'Acres Treated', 'acres', ['month', 'year']),
        ],
    ),
    'pesticide-notices': lambda: _dataset(
        'pesticide-notices', 'Pesticide Spray Notices',
        'Advance notices of planned restricted-use pesticide applications.',
        'SprayDays (California DPR)', 'Public records', ['point'],
        [_other('spray-notice', 'Spray Notices', '', ['day'])],
    ),
    'forecasts': lambda: _dataset(
        'forecasts', 'Air Quality Forecasts',
        'Daily air quality index forecasts for each forecast zone.',
        'San Joaquin Valley Air Pollution Control District', 'Public records', ['zone'],
        [_other('aqi-forecast', 'AQI Forecast', 'AQI', ['day'])],
    ),
    'calheatscore': lambda: _dataset(
        'calheatscore', 'CalHeatScore',
        'Daily heat health risk score by ZIP code.',
        'OEHHA CalHeatScore', 'Public records', ['zip'],
        [_other('heat-score', 'Heat Score', '', ['day'])],
    ),
    'calenviroscreen': lambda: _dataset(
        'calenviroscreen', 'CalEnviroScreen',
        'Cumulative pollution burden and vulnerability percentile by census tract.',
        'OEHHA CalEnviroScreen', 'Public records', ['tract'],
        [_other('ces-score', 'CalEnviroScreen Score', 'percentile', [])],
    ),
    'emissions': lambda: _dataset(
        'emissions', 'Facility Emissions',
        'Annual reported emissions from permitted facilities.',
        'CARB and U.S. EPA', 'Public records', ['point'],
        [_other('facility-emissions', 'Facility Emissions', 'tons/yr', ['year'])],
    ),
    'tempo': lambda: _dataset(
        'tempo', 'NASA TEMPO Satellite',
        'Hourly satellite column measurements over the San Joaquin Valley.',
        'NASA TEMPO', 'Public domain', ['point', 'region'],
        [
            _entry(product.value, product.label, kind, units, ['hour'])
            for product, (kind, units) in TEMPO_PRODUCTS.items()
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


def _monitor_entry_models(weather):
    """
    Entry models for the weather dataset (CIMIS's ENTRY_CONFIG) or the air-quality
    one (every enabled monitor type except CIMIS). CIMIS is not in
    MONITOR_ENABLED_TYPES, so weather reads it directly.
    """
    monitor_models = [CIMIS] if weather else [
        m for m in Monitor.get_enabled_subclasses() if m is not CIMIS
    ]
    models = {}
    for monitor_model in monitor_models:
        for entry_model in monitor_model.ENTRY_CONFIG:
            models[entry_model.entry_type] = entry_model
    return [models[key] for key in sorted(models)]


def _monitor_entry_types(weather):
    available = None if weather else set(DefaultCalibration.objects.available_pollutants())
    entry_types = []
    for entry_model in _monitor_entry_models(weather):
        kind = _kind(entry_model)
        extra = {}
        if available is not None and kind == 'pollutant':
            extra['available'] = entry_model.entry_type in available
        entry_types.append(_entry(
            entry_model.entry_type,
            entry_model.label,
            kind,
            entry_model.units or '',
            SUMMARIZED if entry_model.summarize else RAW_ONLY,
            **extra,
        ))
    return entry_types


def _air_quality():
    return _dataset(
        'air-quality', 'Air Quality',
        'Air quality measurements from SJVAir sensors and partner monitoring networks.',
        'SJVAir sensors, AirNow, AQview, AQLite', 'CC BY 4.0', ['monitor', 'region'],
        _monitor_entry_types(weather=False),
        meta_url=reverse('api:v2:monitors:monitor-meta'),
    )


def _weather():
    return _dataset(
        'weather', 'Weather',
        'Hourly weather observations from agricultural weather stations.',
        'California Irrigation Management Information System (CIMIS)', 'Public records',
        ['monitor'],
        _monitor_entry_types(weather=True),
        meta_url=reverse('api:v2:monitors:monitor-meta'),
    )


def get_catalog():
    builders = {'air-quality': _air_quality, 'weather': _weather, **STATIC_DATASETS}
    return {
        'datasets': [builders[dataset_id]() for dataset_id in DATASET_IDS],
        'summary_rules': SUMMARY_RULES,
    }


def dataset_entry_types(dataset_id):
    """Entry-type ids of one dataset; empty for an unknown dataset id."""
    for dataset in get_catalog()['datasets']:
        if dataset['id'] == dataset_id:
            return [e['id'] for e in dataset['entry_types']]
    return []
