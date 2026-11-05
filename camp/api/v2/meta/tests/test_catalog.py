import json
import os
from pathlib import Path

from django.test import RequestFactory, TestCase
from django.urls import reverse

from camp.api.v2.meta import catalog
from camp.api.v2.meta.endpoints import DatasetCatalogEndpoint
from camp.apps.calheatscore.scales import get_heat_scale
from camp.apps.calibrations.models import DefaultCalibration
from camp.apps.forecasts.scales import get_aqi_forecast_scale, get_burn_status_scale
from camp.apps.hms.scales import get_fire_scale, get_smoke_scale
from camp.utils.test import get_response_data

datasets_view = DatasetCatalogEndpoint.as_view()

SNAPSHOT = Path(__file__).with_name('catalog_snapshot.json')


class DatasetCatalogTests(TestCase):
    fixtures = ['default-calibrations.yaml']

    def get(self):
        return get_response_data(datasets_view(RequestFactory().get(reverse('api:v2:meta:datasets'))))['data']

    def entry(self, dataset, entry_type):
        ds = next(d for d in self.get()['datasets'] if d['id'] == dataset)
        return next(e for e in ds['entry_types'] if e['id'] == entry_type)

    def test_catalog_unchanged(self):
        # Pins the whole catalog. Regenerate on purpose only:
        # WRITE_CATALOG_SNAPSHOT=1 pytest camp/api/v2/meta/tests/test_catalog.py
        data = json.loads(json.dumps(self.get()))
        if os.environ.get('WRITE_CATALOG_SNAPSHOT') == '1':
            SNAPSHOT.write_text(json.dumps(data, sort_keys=True, indent=1, ensure_ascii=False) + '\n')
        assert data == json.loads(SNAPSHOT.read_text())

    def test_lists_every_domain(self):
        assert [d['id'] for d in self.get()['datasets']] == list(catalog.DATASET_IDS)
        assert len(catalog.DATASET_IDS) == 11

    def test_places_url(self):
        url = reverse('api:v2:monitors:monitor-list')
        urls = {d['id']: d['places_url'] for d in self.get()['datasets']}
        assert urls['weather'] == f'{url}?dataset=weather'
        assert urls['air-quality'] == f'{url}?dataset=air-quality'
        assert all(v == '' for k, v in urls.items() if k not in ('weather', 'air-quality'))

    def test_no_dataset_level_resolutions(self):
        assert all('resolutions' not in d for d in self.get()['datasets'])

    def test_pm25_is_summarized_and_pm10_is_raw_only(self):
        assert self.entry('air-quality', 'pm25')['resolutions'] == ['raw', 'hour', 'day', 'month', 'quarter', 'season', 'year']
        assert self.entry('air-quality', 'pm10')['resolutions'] == ['raw']

    def test_available_follows_default_calibration(self):
        assert self.entry('air-quality', 'pm25')['available'] is True
        assert self.entry('air-quality', 'no2')['available'] is False
        DefaultCalibration.objects.create(monitor_type='airnow', entry_type='no2', calibration='')
        assert self.entry('air-quality', 'no2')['available'] is True

    def test_temperature_kind(self):
        assert self.entry('weather', 'temperature')['kind'] == 'meteorological'

    def test_retired_present_and_null(self):
        for d in self.get()['datasets']:
            assert d['retired'] is None
            assert all(e['retired'] is None for e in d['entry_types'])

    def test_summary_rules(self):
        assert self.get()['summary_rules'] == {'complete_after_period_end': ['month', 'quarter', 'season', 'year']}

    def test_cache_control_header(self):
        response = datasets_view(RequestFactory().get(reverse('api:v2:meta:datasets')))
        assert response['Cache-Control'] == 'public, max-age=300'

    def test_tempo_products_and_kinds(self):
        kinds = {e['id']: e['kind'] for e in next(d for d in self.get()['datasets'] if d['id'] == 'tempo')['entry_types']}
        assert kinds == {'no2': 'pollutant', 'o3tot': 'other', 'hcho': 'pollutant', 'cldo4': 'other'}

    def test_meta_urls_and_weather_excludes_air_quality_types(self):
        by_id = {d['id']: d for d in self.get()['datasets']}
        assert by_id['air-quality']['meta_url'] == '/api/2.0/monitors/meta/'
        assert by_id['hms-smoke']['meta_url'] == '/api/2.0/hms/meta/'
        assert 'pm25' not in catalog.dataset_entry_types('weather')

    def test_dataset_entry_types(self):
        assert catalog.dataset_entry_types('pesticide-use') == ['pounds-applied', 'acres-treated']
        assert catalog.dataset_entry_types('nope') == []

    def test_dataset_entry_types_match_catalog_without_queries(self):
        listed = {d['id']: [e['id'] for e in d['entry_types']] for d in self.get()['datasets']}
        with self.assertNumQueries(0):
            assert {i: catalog.dataset_entry_types(i) for i in catalog.DATASET_IDS} == listed

    def test_burn_status_listed(self):
        assert catalog.dataset_entry_types('forecasts') == ['aqi-forecast', 'burn-status']
        entry = self.entry('forecasts', 'burn-status')
        assert entry['label'] == 'Burn Status'
        assert entry['resolutions'] == ['day']

    def test_every_entry_type_has_display(self):
        for dataset in self.get()['datasets']:
            for entry in dataset['entry_types']:
                assert set(entry['display']) == {'precision', 'chart', 'y_min'}, entry['id']

    def test_display_values(self):
        assert self.entry('air-quality', 'pm25')['display'] == {'precision': 1, 'chart': 'line', 'y_min': 0}
        assert self.entry('air-quality', 'particulates')['display'] == {'precision': 0, 'chart': 'line', 'y_min': 0}
        assert self.entry('weather', 'temperature')['display'] == {'precision': 1, 'chart': 'line', 'y_min': None}
        assert self.entry('calheatscore', 'heat-score')['display'] == {'precision': 0, 'chart': 'bar', 'y_min': 0}
        assert self.entry('hms-fire', 'fire-frp')['display'] == {'precision': 1, 'chart': 'bar', 'y_min': 0}
        assert self.entry('emissions', 'facility-nox')['display'] == {'precision': 1, 'chart': 'bar', 'y_min': 0}
        assert self.entry('emissions', 'methane-emission-rate')['display'] == {'precision': 1, 'chart': 'line', 'y_min': 0}
        assert self.entry('hms-smoke', 'smoke-density')['display'] == {'precision': None, 'chart': None, 'y_min': None}
        assert self.entry('forecasts', 'burn-status')['display'] == {'precision': None, 'chart': None, 'y_min': None}
        assert self.entry('tempo', 'no2')['display'] == {'precision': None, 'chart': 'line', 'y_min': None}

    def test_meta_urls(self):
        by_id = {d['id']: d for d in self.get()['datasets']}
        assert by_id['hms-smoke']['meta_url'] == reverse('api:v2:hms:hms-meta')
        assert by_id['hms-fire']['meta_url'] == reverse('api:v2:hms:hms-meta')
        assert by_id['forecasts']['meta_url'] == reverse('api:v2:forecasts:forecast-meta')
        assert by_id['calheatscore']['meta_url'] == reverse('api:v2:calheatscore:calheatscore-meta')

    def test_domain_scale_labels_match_catalog(self):
        scales = [
            get_heat_scale(), get_smoke_scale(), get_fire_scale(),
            get_aqi_forecast_scale(), get_burn_status_scale(),
        ]
        assert {s.id for s in scales} == {'heat-score', 'smoke-density', 'fire-frp', 'aqi-forecast', 'burn-status'}
        for scale in scales:
            entry = next(
                e for d in self.get()['datasets'] for e in d['entry_types'] if e['id'] == scale.id
            )
            assert scale.label == entry['label'], scale.id

    def test_licenses_only_asserted_for_federal_works(self):
        licenses = {d['id']: d['license'] for d in self.get()['datasets']}
        assert {k for k, v in licenses.items() if v} == {'hms-smoke', 'hms-fire', 'tempo'}

    def test_emissions_entry_types_match_api(self):
        ids = catalog.dataset_entry_types('emissions')
        assert 'facility-nox' in ids and 'methane-emission-rate' in ids
        assert self.entry('emissions', 'facility-nox')['units'] == 'tons/yr'
        assert self.entry('emissions', 'methane-emission-rate')['units'] == 'kg/h'


LAUNCH_ENTRY_TYPES = {
    'air-quality': {'co', 'co2', 'humidity', 'no2', 'o3', 'particulates', 'pm10', 'pm100', 'pm25', 'pressure', 'so2', 'temperature'},
    'weather': {
        'dewpoint', 'eto', 'etr', 'humidity', 'netradiation', 'precipitation', 'soiltemperature',
        'solarradiation', 'temperature', 'vaporpressure', 'winddirection', 'windspeed',
    },
    'hms-smoke': {'smoke-density'},
    'hms-fire': {'fire-frp'},
    'pesticide-use': {'pounds-applied', 'acres-treated'},
    'pesticide-notices': {'spray-notice'},
    'forecasts': {'aqi-forecast', 'burn-status'},
    'calheatscore': {'heat-score'},
    'calenviroscreen': {'ces-score'},
    'emissions': {
        'facility-nox', 'facility-rog', 'facility-pm', 'facility-pm10', 'facility-sox', 'facility-co',
        'facility-tog', 'facility-nh3', 'methane-emission-rate',
    },
    'tempo': {'no2', 'o3tot', 'hcho', 'cldo4'},
}


class LaunchIdsArePermanentTests(TestCase):
    fixtures = ['default-calibrations.yaml']

    def test_launch_ids_still_present(self):
        """
        Ids are permanent: to remove one, mark it retired in the catalog instead of deleting it.
        """
        response = datasets_view(RequestFactory().get(reverse('api:v2:meta:datasets')))
        datasets = {d['id']: d for d in get_response_data(response)['data']['datasets']}
        assert set(datasets) == set(LAUNCH_ENTRY_TYPES)
        for dataset, launch_ids in LAUNCH_ENTRY_TYPES.items():
            current = {e['id'] for e in datasets[dataset]['entry_types']}
            assert launch_ids <= current, f'{dataset} dropped {sorted(launch_ids - current)}'
