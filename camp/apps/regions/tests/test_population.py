from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from django.contrib.gis.geos import GEOSGeometry
from django.core.management import call_command, CommandError
from django.test import TestCase

from camp.apps.regions import population
from camp.apps.regions.models import Boundary, Region


def response(rows):
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = rows
    return mock


def html_response():
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.side_effect = ValueError('Expecting value: line 1 column 1 (char 0)')
    return mock


def make(region_type, name, external_id, version='2020'):
    region = Region.objects.create(name=name, slug=name.lower(), type=region_type, external_id=external_id)
    boundary = Boundary.objects.create(region=region, version=version, geometry=GEOSGeometry(
        'MULTIPOLYGON(((-120 36, -119 36, -119 37, -120 37, -120 36)))', srid=4326))
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


class PopulationTests(TestCase):
    def test_fetch_builds_geoids_per_geography(self):
        rows = {
            'county': [['B01003_001E', 'state', 'county'], ['1017162', '06', '019']],
            'zipcode': [['B01003_001E', 'zip code tabulation area'], ['52131', '93725']],
            'tract': [['B01003_001E', 'state', 'county', 'tract'], ['4321', '06', '019', '000100']],
        }
        for geography, expected in (('county', {'06019': 1017162}), ('zipcode', {'93725': 52131}),
                                    ('tract', {'06019000100': 4321})):
            with patch('requests.get', return_value=response(rows[geography])) as get:
                assert population.fetch(geography, 2024) == expected
            assert '/2024/acs/acs5' in get.call_args[0][0]

    def test_geography_params_encode_as_a_single_in_value(self):
        # `in` must be a single Census-style "state:06 county:*" string, not a
        # list -- `requests` encodes a list value as repeated `in=` keys,
        # which the Census API rejects/misinterprets. This guards the
        # tract geography, whose `in` combines two hierarchy levels.
        for geography, (_, params, _) in population.GEOGRAPHIES.items():
            query = {'get': population.VARIABLE, **params}
            url = requests.Request('GET', population.URL.format(year=2024), params=query).prepare().url
            parsed = parse_qs(urlparse(url).query)
            if 'in' in params:
                assert url.count('in=') == 1
                assert len(parsed['in']) == 1

        # The tract geography's combined hierarchy, specifically.
        _, tract_params, _ = population.GEOGRAPHIES['tract']
        query = {'get': population.VARIABLE, **tract_params}
        url = requests.Request('GET', population.URL.format(year=2024), params=query).prepare().url
        assert url.count('in=') == 1
        assert 'state%3A06+county%3A%2A' in url

    def test_fetch_passes_key_when_given(self):
        with patch('requests.get', return_value=response([['B01003_001E', 'state', 'county'],
                                                            ['1017162', '06', '019']])) as get:
            population.fetch('county', 2024, key='secret')
        assert get.call_args.kwargs['params']['key'] == 'secret'

    def test_fetch_raises_on_html_response(self):
        with patch('requests.get', return_value=html_response()):
            with pytest.raises(population.CensusAPIError, match='CENSUS_API_KEY'):
                population.fetch('county', 2024)

    def test_apply_writes_metadata_and_counts_misses(self):
        fresno = make(Region.Type.COUNTY, 'Fresno', '06019')
        make(Region.Type.COUNTY, 'Nowhere', '06999')
        updated, missing = population.apply(Region.Type.COUNTY, {'06019': 1017162})
        fresno.refresh_from_db()
        assert fresno.metadata['population'] == 1017162
        assert (updated, missing) == (1, 1)

    def test_retired_tracts_are_skipped(self):
        make(Region.Type.TRACT, 'Old', '06019999999', version='2010')
        updated, missing = population.apply(Region.Type.TRACT, {'06019999999': 10})
        assert (updated, missing) == (0, 0)

    def test_command(self):
        make(Region.Type.COUNTY, 'Fresno', '06019')
        with patch.object(population, 'fetch', return_value={'06019': 5}) as fetch:
            call_command('import_population', '--year', '2023')
        assert fetch.call_count == 3
        assert Region.objects.get(external_id='06019').metadata['population'] == 5

    def test_command_raises_command_error_on_missing_key(self):
        with patch('requests.get', return_value=html_response()):
            with pytest.raises(CommandError, match='CENSUS_API_KEY'):
                call_command('import_population')
