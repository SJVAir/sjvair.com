from django.test import RequestFactory, TestCase
from django.urls import reverse

from camp.api.v2.meta import catalog
from camp.api.v2.meta.endpoints import DatasetCatalogEndpoint
from camp.apps.calibrations.models import DefaultCalibration
from camp.utils.test import get_response_data

datasets_view = DatasetCatalogEndpoint.as_view()


class DatasetCatalogTests(TestCase):
    fixtures = ['default-calibrations.yaml']

    def get(self):
        return get_response_data(datasets_view(RequestFactory().get(reverse('api:v2:meta:datasets'))))['data']

    def entry(self, dataset, entry_type):
        ds = next(d for d in self.get()['datasets'] if d['id'] == dataset)
        return next(e for e in ds['entry_types'] if e['id'] == entry_type)

    def test_lists_every_domain(self):
        assert [d['id'] for d in self.get()['datasets']] == list(catalog.DATASET_IDS)
        assert len(catalog.DATASET_IDS) == 11

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
        assert by_id['hms-smoke']['meta_url'] == ''
        assert 'pm25' not in catalog.dataset_entry_types('weather')

    def test_dataset_entry_types(self):
        assert catalog.dataset_entry_types('pesticide-use') == ['pounds-applied', 'acres-treated']
        assert catalog.dataset_entry_types('nope') == []

    def test_dataset_entry_types_match_catalog_without_queries(self):
        listed = {d['id']: [e['id'] for e in d['entry_types']] for d in self.get()['datasets']}
        with self.assertNumQueries(0):
            assert {i: catalog.dataset_entry_types(i) for i in catalog.DATASET_IDS} == listed

    def test_licenses_only_asserted_for_federal_works(self):
        licenses = {d['id']: d['license'] for d in self.get()['datasets']}
        assert {k for k, v in licenses.items() if v} == {'hms-smoke', 'hms-fire', 'tempo'}

    def test_emissions_entry_types_match_api(self):
        ids = catalog.dataset_entry_types('emissions')
        assert 'facility-nox' in ids and 'methane-emission-rate' in ids
        assert self.entry('emissions', 'facility-nox')['units'] == 'tons/yr'
        assert self.entry('emissions', 'methane-emission-rate')['units'] == 'kg/h'
