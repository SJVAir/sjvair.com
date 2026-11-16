from unittest import mock

import pytest
from django.test import SimpleTestCase

from camp.utils import arcgis

URL = 'https://example.com/arcgis/rest/services/Layer/FeatureServer/0'


def feature(name, x, y):
    return {
        'type': 'Feature',
        'geometry': {'type': 'Point', 'coordinates': [x, y], 'crs': None},
        'properties': {'name': name, 'maptime': 1793012400000},
    }


def page(features, more=False):
    response = mock.Mock()
    response.json.return_value = {
        'type': 'FeatureCollection',
        'features': features,
        'properties': {'exceededTransferLimit': True} if more else {},
    }
    return response


class GetTests(SimpleTestCase):
    def get(self, *responses, **kwargs):
        session = mock.Mock()
        session.get.side_effect = list(responses)
        return arcgis.get(URL, session=session, **kwargs), session

    def test_returns_features_as_a_geodataframe(self):
        gdf, session = self.get(page([feature('Fresno', -119.86, 36.72)]))

        assert len(gdf) == 1
        assert gdf.crs == 'EPSG:4326'
        row = gdf.to_dict('records')[0]
        assert row['name'] == 'Fresno'
        assert row['maptime'] == 1793012400000
        assert (row['geometry'].x, row['geometry'].y) == (-119.86, 36.72)

        args, kwargs = session.get.call_args
        assert args == (f'{URL}/query',)
        assert kwargs['params']['f'] == 'geojson'
        assert kwargs['params']['outSR'] == '4326'
        assert kwargs['timeout'] == arcgis.TIMEOUT

    def test_pages_until_the_transfer_limit_is_not_exceeded(self):
        gdf, session = self.get(
            page([feature('a', 0, 0), feature('b', 1, 1)], more=True),
            page([feature('c', 2, 2)]),
        )

        assert list(gdf['name']) == ['a', 'b', 'c']
        offsets = [call.kwargs['params']['resultOffset'] for call in session.get.call_args_list]
        assert offsets == [0, 2]

    def test_passes_where_and_fields(self):
        _, session = self.get(page([]), where="countyname in ('Fresno')", fields=['name', 'aobs'])

        params = session.get.call_args.kwargs['params']
        assert params['where'] == "countyname in ('Fresno')"
        assert params['outFields'] == 'name,aobs'

    def test_no_features_is_an_empty_geodataframe(self):
        gdf, _ = self.get(page([]))

        assert len(gdf) == 0
        assert gdf.to_dict('records') == []

    def test_an_error_in_a_200_response_raises(self):
        response = mock.Mock()
        response.json.return_value = {'error': {'code': 400, 'message': 'Invalid query'}}

        with pytest.raises(arcgis.ArcGISError, match='Invalid query'):
            self.get(response)
