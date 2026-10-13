from django.core.cache import cache
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import TestCase, override_settings

from camp.utils import mapconfig


class CoveredBoundsTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        cache.clear()

    def test_bounds_contain_the_counties(self):
        west, south, east, north = (float(v) for v in mapconfig.covered_bounds().split(','))
        # Fresno city is inside the covered counties.
        assert west < -119.787 < east
        assert south < 36.737 < north

    def test_cached(self):
        first = mapconfig.covered_bounds()
        from camp.apps.regions.models import Region
        Region.objects.filter(type=Region.Type.COUNTY).delete()
        assert mapconfig.covered_bounds() == first


class NoCountiesTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_empty_without_counties(self):
        assert mapconfig.covered_bounds() == ''

    def test_empty_is_not_cached(self):
        # An environment that renders a map before the counties are imported
        # would otherwise serve empty bounds for a day after they land.
        assert mapconfig.covered_bounds() == ''
        assert cache.get(mapconfig.BOUNDS_CACHE_KEY) is None
        call_command('loaddata', 'regions.yaml', verbosity=0)
        assert mapconfig.covered_bounds() != ''


@override_settings(MAPTILER_API_KEY='test-key')
class MapConfigTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        cache.clear()

    def test_fills_the_shared_keys(self):
        config = mapconfig.map_config('facility-map', data={'geojson-url': '/x/'}, features={'toolbar': True})
        assert config['container_class'] == 'facility-map'
        assert config['data']['geojson-url'] == '/x/'
        assert config['data']['maptiler-key'] == 'test-key'
        assert config['data']['style'] == 'dataviz'
        assert config['data']['bounds'] == mapconfig.covered_bounds()
        assert config['features'] == {'toolbar': True}
        assert config['data']['features'] == 'toolbar'

    def test_features_name_the_rendered_chrome(self):
        # What the include renders, for the script to read off the container
        # instead of trusting the map module's own spec.
        config = mapconfig.map_config('m', data={'bounds': ''}, features={
            'toolbar': True, 'legend': True, 'status': True, 'expand': True,
        })
        assert config['data']['features'] == 'expand legend status toolbar'

    def test_features_leave_out_what_is_off(self):
        config = mapconfig.map_config('m', data={'bounds': ''}, features={
            'toolbar': True, 'legend': False, 'expand': None,
        })
        assert config['data']['features'] == 'toolbar'
        assert mapconfig.map_config('m', data={'bounds': ''}, features={})['data']['features'] == ''

    def test_caller_overrides_win(self):
        config = mapconfig.map_config('m', data={'style': 'streets', 'bounds': ''}, features={})
        assert config['data']['style'] == 'streets'
        assert config['data']['bounds'] == ''

    def test_caller_bounds_skip_the_lookup(self):
        with self.assertNumQueries(0):
            config = mapconfig.map_config('m', data={'bounds': ''}, features={})
        assert config['data']['bounds'] == ''

    def test_values_are_strings(self):
        config = mapconfig.map_config('m', data={'zoom': 11, 'center': None}, features={})
        assert config['data']['zoom'] == '11'
        assert config['data']['center'] == ''


class IncludeTests(TestCase):
    fixtures = ['regions.yaml']

    def render(self, **kwargs):
        config = mapconfig.map_config('facility-map', data={'geojson-url': '/x/?a=1&b=2'}, **kwargs)
        return render_to_string('maps/includes/map.html', {'map': config})

    def test_container_and_data_attributes(self):
        html = self.render(features={}, container_id='m1')
        assert 'class="facility-map map-canvas"' in html
        assert 'id="m1"' in html
        assert 'data-geojson-url="/x/?a=1&amp;b=2"' in html
        assert 'data-maptiler-key=' in html

    def test_no_chrome_without_features(self):
        html = self.render(features={})
        assert 'map-toolbar' not in html
        assert 'map-legend-panel' not in html
        assert 'map-expand' not in html
        assert 'class="map-status"' not in html
        assert 'data-features=""' in html

    def test_status_pill_is_a_feature(self):
        html = self.render(features={'status': True})
        assert 'class="map-status"' in html
        assert 'data-features="status"' in html

    def test_toolbar_expand_and_legend(self):
        html = self.render(features={'toolbar': True, 'expand': True, 'legend': True})
        assert 'data-features="expand legend toolbar"' in html
        assert 'class="map-toolbar"' in html
        assert 'map-expand' in html
        assert 'map-legend-panel' in html
        assert 'map-options' not in html
        assert 'aria-controls' not in html  # no container id, nothing to point at

    def test_legend_toggle_controls_its_body(self):
        html = self.render(features={'legend': True}, container_id='m1')
        assert 'aria-controls="m1-legend"' in html
        assert 'id="m1-legend"' in html

    def test_options_dropdown_only_with_a_template(self):
        html = self.render(features={'toolbar': True}, options_template='maps/includes/scripts.html')
        assert 'map-options' in html
        assert 'js/maps/core.js' in html  # the named template rendered inside the Options menu

    def test_compact(self):
        assert 'map-wrap is-compact' in self.render(features={}, compact=True)
