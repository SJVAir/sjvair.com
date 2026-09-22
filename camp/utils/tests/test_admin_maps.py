from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from camp.apps.accounts.models import User
from camp.apps.ceidars.models import Facility
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region


class AdminMapTestMixin:
    def setUp(self):
        user = User.objects.create_superuser(
            email='admin@example.com',
            password='password',
            phone='+15595551234',
            full_name='Admin',
        )
        self.client.force_login(user)

    def assert_map_figure_page(self, url):
        with patch('camp.utils.maps.StaticMap.render') as static_render:
            response = self.client.get(url)

        assert response.status_code == 200
        content = response.content.decode()
        assert 'class="map-figure"' in content
        # The mixin's media: the MapTiler SDK, then the figure module.
        assert 'maptiler-sdk/maptiler-sdk.js' in content
        assert 'maptiler-sdk/maptiler-sdk.css' in content
        assert 'js/admin/map-figure.js' in content
        assert 'js/admin/map-figure.css' in content
        assert content.index('maptiler-sdk/maptiler-sdk.js') < content.index('js/admin/map-figure.js')
        assert 'leaflet' not in content.lower()
        assert not static_render.called
        return content


class MonitorAdminMapTests(AdminMapTestMixin, TestCase):
    fixtures = ['purple-air.yaml']

    def test_change_view_renders_map_figure(self):
        monitor = PurpleAir.objects.get(sensor_id=8892)
        url = reverse('admin:purpleair_purpleair_change', args=[monitor.pk])
        self.assert_map_figure_page(url)


class RegionAdminMapTests(AdminMapTestMixin, TestCase):
    fixtures = ['regions.yaml', 'purple-air.yaml']

    def test_change_view_renders_map_figures(self):
        region = Region.objects.get(name='Fresno County')
        url = reverse('admin:regions_region_change', args=[region.pk])
        content = self.assert_map_figure_page(url)
        # Overview map, monitor map, and the boundary inline map
        assert content.count('class="map-figure"') == 3


class FacilityAdminMapTests(AdminMapTestMixin, TestCase):
    fixtures = ['regions.yaml', 'ceidars.yaml']

    def test_change_view_renders_map_figure(self):
        facility = Facility.objects.get(pk=1)
        url = reverse('admin:ceidars_facility_change', args=[facility.pk])
        self.assert_map_figure_page(url)
