import pytest

from django.contrib.gis.geos import Point, Polygon
from django.test import TestCase, override_settings

from shapely.geometry import Point as ShapelyPoint

from camp.utils import leaflet


class GeoJSONTests(TestCase):
    def test_marker_becomes_point_feature_with_style(self):
        lmap = leaflet.LeafletMap()
        lmap.add(leaflet.Marker(
            geometry=Point(-119.787, 36.737, srid=4326),
            fill_color='dodgerblue',
            shape='star',
            size=20,
        ))

        feature = lmap.to_geojson()['features'][0]
        assert feature['geometry']['type'] == 'Point'
        assert feature['geometry']['coordinates'] == [-119.787, 36.737]
        assert feature['properties']['kind'] == 'marker'
        assert feature['properties']['shape'] == 'star'
        assert feature['properties']['size'] == 20
        assert feature['properties']['style']['fillColor'] == 'dodgerblue'

    def test_area_becomes_polygon_feature_with_style(self):
        lmap = leaflet.LeafletMap()
        lmap.add(leaflet.Area(
            geometry=Polygon(((0, 0), (0, 1), (1, 1), (0, 0)), srid=4326),
            fill_color='white',
            border_color='dimgrey',
            fill_opacity=0.5,
            border_width=2,
        ))

        feature = lmap.to_geojson()['features'][0]
        assert feature['geometry']['type'] == 'Polygon'
        assert feature['properties']['kind'] == 'area'
        assert feature['properties']['style'] == {
            'fillColor': 'white',
            'fillOpacity': 0.5,
            'color': 'dimgrey',
            'weight': 2,
        }

    def test_labels_are_permanent_by_default_and_hover_on_request(self):
        lmap = leaflet.LeafletMap()
        lmap.add(
            leaflet.Area(geometry=Polygon(((0, 0), (0, 1), (1, 1), (0, 0)), srid=4326), label='a'),
            leaflet.Area(geometry=Polygon(((0, 0), (0, 1), (1, 1), (0, 0)), srid=4326), label='b', label_on_hover=True),
            leaflet.Marker(geometry=Point(0, 0, srid=4326), label='c', label_on_hover=True),
        )
        flags = [f['properties']['labelOnHover'] for f in lmap.to_geojson()['features']]
        assert flags == [False, True, True]

    def test_shapely_geometry_is_accepted(self):
        lmap = leaflet.LeafletMap()
        lmap.add(leaflet.Marker(geometry=ShapelyPoint(-119.0, 36.0)))
        feature = lmap.to_geojson()['features'][0]
        assert feature['geometry']['coordinates'] == [-119.0, 36.0]

    def test_geometry_is_transformed_to_wgs84(self):
        point = Point(-119.787, 36.737, srid=4326)
        point.transform(3857)
        lmap = leaflet.LeafletMap()
        lmap.add(leaflet.Marker(geometry=point))
        lon, lat = lmap.to_geojson()['features'][0]['geometry']['coordinates']
        assert round(lon, 3) == -119.787
        assert round(lat, 3) == 36.737

    def test_elements_keep_insertion_order(self):
        lmap = leaflet.LeafletMap()
        lmap.add(
            leaflet.Area(geometry=Polygon(((0, 0), (0, 1), (1, 1), (0, 0)), srid=4326)),
            leaflet.Marker(geometry=Point(0.5, 0.5, srid=4326)),
        )
        kinds = [f['properties']['kind'] for f in lmap.to_geojson()['features']]
        assert kinds == ['area', 'marker']


@override_settings(MAPTILER_API_KEY='test-key')
class RenderTests(TestCase):
    def test_render_raises_with_no_elements(self):
        with pytest.raises(ValueError):
            leaflet.LeafletMap().render()

    def test_render_outputs_container_and_geojson(self):
        lmap = leaflet.LeafletMap(width=300, height=200, zoom=12)
        lmap.add(leaflet.Marker(geometry=Point(-119.787, 36.737, srid=4326)))
        html = lmap.render()

        assert 'class="admin-leaflet-map"' in html
        assert 'width: 300px' in html
        assert 'height: 200px' in html
        assert 'data-zoom="12"' in html
        assert 'api.maptiler.com' in html
        assert 'key=test-key' in html
        assert 'type="application/json"' in html
        assert '"coordinates": [-119.787, 36.737]' in html

    def test_render_escapes_geojson(self):
        lmap = leaflet.LeafletMap()
        lmap.add(leaflet.Marker(
            geometry=Point(0, 0, srid=4326),
            label='</script><b>x</b>',
        ))
        html = lmap.render()
        assert '</script><b>' not in html
        assert '\\u003C/script\\u003E' in html
