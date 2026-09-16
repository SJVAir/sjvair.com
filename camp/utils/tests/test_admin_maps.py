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

    def assert_leaflet_page(self, url):
        with patch('camp.utils.maps.StaticMap.render') as static_render:
            response = self.client.get(url)

        assert response.status_code == 200
        content = response.content.decode()
        assert 'class="admin-leaflet-map"' in content
        assert 'js/admin/leaflet/leaflet.js' in content
        assert 'js/admin/leaflet-maps.js' in content
        assert 'js/admin/leaflet/leaflet.css' in content
        assert not static_render.called
        return content


class MonitorAdminMapTests(AdminMapTestMixin, TestCase):
    fixtures = ['purple-air.yaml']

    def test_change_view_renders_leaflet_map(self):
        monitor = PurpleAir.objects.get(sensor_id=8892)
        url = reverse('admin:purpleair_purpleair_change', args=[monitor.pk])
        self.assert_leaflet_page(url)


class RegionAdminMapTests(AdminMapTestMixin, TestCase):
    fixtures = ['regions.yaml', 'purple-air.yaml']

    def test_change_view_renders_leaflet_maps(self):
        region = Region.objects.get(name='Fresno County')
        url = reverse('admin:regions_region_change', args=[region.pk])
        content = self.assert_leaflet_page(url)
        # Overview map, monitor map, and the boundary inline map
        assert content.count('class="admin-leaflet-map"') == 3


class FacilityAdminMapTests(AdminMapTestMixin, TestCase):
    fixtures = ['regions.yaml', 'ceidars.yaml']

    def test_change_view_renders_leaflet_map(self):
        facility = Facility.objects.get(pk=1)
        url = reverse('admin:ceidars_facility_change', args=[facility.pk])
        self.assert_leaflet_page(url)
