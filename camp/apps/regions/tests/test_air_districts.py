import json
from unittest.mock import MagicMock, patch

import pytest

from django.contrib.gis.geos import Polygon
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.regions import air_districts
from camp.apps.regions.models import Region


def square(x, y, size=0.1):
    """A small lon/lat square as a GeoJSON geometry dict."""
    return json.loads(Polygon.from_bbox((x, y, x + size, y + size)).geojson)


def feature(code, name, geometry):
    return {
        'type': 'Feature',
        'properties': {'Air_District_Code': code, 'Air_District_Name': name},
        'geometry': geometry,
    }


def response(features):
    mock = MagicMock()
    mock.json.return_value = {'type': 'FeatureCollection', 'features': features}
    mock.raise_for_status.return_value = None
    return mock


class GroupByCodeTests(TestCase):
    def test_multi_part_districts_are_unioned(self):
        grouped = air_districts.group_by_code([
            feature('SJU', 'SAN JOAQUIN VALLEY UNIFIED APCD', square(-120, 36)),
            feature('SJU', 'SAN JOAQUIN VALLEY UNIFIED APCD', square(-119, 36)),
            feature('KER', 'EASTERN KERN APCD', square(-118, 35)),
        ])
        assert set(grouped) == {'SJU', 'KER'}
        assert grouped['SJU']['name'] == 'SAN JOAQUIN VALLEY UNIFIED APCD'
        assert grouped['SJU']['geometry'].geom_type == 'MultiPolygon'
        assert len(grouped['SJU']['geometry']) == 2


class DirectoryTests(TestCase):
    def test_datafile_has_every_district_used_here(self):
        directory = air_districts.load_directory()
        assert directory['SJU']['name'] == 'San Joaquin Valley APCD'
        assert directory['KER']['name'] == 'Eastern Kern APCD'
        assert directory['SJU']['complaints_url'].startswith('https://')
        assert len(directory) == 35


class ImportAirDistrictsTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        # Districts drawn to lie inside the fixture's county boundaries, plus
        # one far outside every covered county.
        fresno_point = fresno.boundary.geometry.point_on_surface
        kern_point = kern.boundary.geometry.point_on_surface
        self.features = [
            feature('SJU', 'SAN JOAQUIN VALLEY UNIFIED APCD', square(fresno_point.x, fresno_point.y, 0.01)),
            feature('KER', 'EASTERN KERN APCD', square(kern_point.x, kern_point.y, 0.01)),
            feature('SC', 'SOUTH COAST AQMD', square(-117.5, 33.8)),
        ]

    def run_import(self):
        with patch('camp.apps.regions.air_districts.requests.get', return_value=response(self.features)):
            call_command('import_air_districts')

    def test_imports_only_districts_in_covered_counties(self):
        self.run_import()
        codes = set(Region.objects.filter(type=Region.Type.AIR_DISTRICT).values_list('external_id', flat=True))
        assert codes == {'SJU', 'KER'}

    def test_name_and_metadata_come_from_the_datafile(self):
        self.run_import()
        district = Region.objects.get(type=Region.Type.AIR_DISTRICT, external_id='KER')
        assert district.name == 'Eastern Kern APCD'
        assert district.slug == 'eastern-kern-apcd'
        assert district.metadata['code'] == 'KER'
        assert district.metadata['arcgis_name'] == 'EASTERN KERN APCD'
        assert district.metadata['phone'] == '(661) 862-5250'
        assert district.metadata['carb_url'].startswith('https://ww2.arb.ca.gov/')
        assert district.boundary is not None

    def test_code_missing_from_datafile_falls_back_to_title_cased_arcgis_name(self):
        with patch.object(air_districts, 'load_directory', return_value={}):
            self.run_import()
        district = Region.objects.get(type=Region.Type.AIR_DISTRICT, external_id='SJU')
        assert district.name == 'San Joaquin Valley Unified APCD'
        assert district.metadata['carb_url'] == ''

    def test_rerun_is_idempotent(self):
        self.run_import()
        self.run_import()
        assert Region.objects.filter(type=Region.Type.AIR_DISTRICT).count() == 2

    def test_no_county_regions_is_an_error(self):
        Region.objects.filter(type=Region.Type.COUNTY).delete()
        with pytest.raises(CommandError, match='import_counties'):
            self.run_import()
