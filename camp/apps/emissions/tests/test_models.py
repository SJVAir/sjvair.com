from unittest.mock import patch

import pytest

from django.contrib.gis.geos import Point
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from camp.apps.emissions.models import EmissionsRecord, Facility
from camp.apps.regions.models import Region


class FacilityTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_same_facid_in_two_districts_is_two_facilities(self):
        assert Facility.objects.filter(county_code=15, facid=2).count() == 2

    def test_county_district_facid_is_unique(self):
        sju = Region.objects.get(pk=9001)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Facility.objects.create(county_code=10, air_district=sju, facid=1, name='DUPLICATE')

    def test_district_is_protected(self):
        from django.db.models import ProtectedError
        with pytest.raises(ProtectedError):
            Region.objects.get(pk=9002).delete()

    def test_minor_sources(self):
        assert list(Facility.objects.minor_sources().values_list('name', flat=True)) == ['TEST GAS STATION']
        assert set(Facility.objects.major_sources().values_list('name', flat=True)) == {'TEST PLANT', 'TEST CEMENT'}
        assert Facility.objects.get(pk=2).is_minor_source

    def test_geocode_sets_point_without_saving(self):
        facility = Facility.objects.get(pk=2)
        point = Point(-119.0, 35.4, srid=4326)
        with patch('camp.utils.geocode.census', return_value=point):
            assert facility.geocode() is True
        assert facility.point == point
        facility.refresh_from_db()
        assert facility.point != point


class EmissionsRecordTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_total_pm_field(self):
        record = EmissionsRecord.objects.get(pk=3)
        assert float(record.pm) == 1.0
        assert not hasattr(record, 'pm25')

    def test_one_record_per_facility_year(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                EmissionsRecord.objects.create(facility_id=1, year=2024)


class CeidarsTablesDroppedTests(TestCase):
    def test_ceidars_tables_are_gone(self):
        tables = connection.introspection.table_names()
        assert 'ceidars_facility' not in tables
        assert 'ceidars_emissionsrecord' not in tables
        assert 'emissions_facility' in tables
