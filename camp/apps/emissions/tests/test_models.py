from unittest.mock import patch

import pytest

from django.contrib.gis.geos import Point
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from camp.apps.emissions.models import EmissionsRecord, Facility, SourceImport, ToxicPollutant
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

    def test_geocode_falls_back_to_maptiler(self):
        facility = Facility.objects.get(pk=2)
        point = Point(-119.0, 35.4, srid=4326)
        with patch('camp.utils.geocode.census', return_value=None):
            with patch('camp.utils.geocode.maptiler', return_value=point):
                assert facility.geocode() is True
        assert facility.point == point

    def test_geocode_no_results(self):
        facility = Facility.objects.create(
            county_code=99, air_district_id=9001, facid=999, name='NO POINT',
        )
        with patch('camp.utils.geocode.census', return_value=None):
            with patch('camp.utils.geocode.maptiler', return_value=None):
                assert facility.geocode() is False
        assert facility.point is None

    def test_geocode_does_not_save(self):
        facility = Facility.objects.create(
            county_code=99, air_district_id=9001, facid=998, name='NO POINT 2',
        )
        point = Point(-119.0, 35.4, srid=4326)
        with patch('camp.utils.geocode.census', return_value=point):
            facility.geocode()
        facility.refresh_from_db()
        assert facility.point is None


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


class ToxicPollutantTests(TestCase):
    def test_cas_from_carb_id(self):
        assert ToxicPollutant.cas_from_carb_id('71432') == '71-43-2'
        assert ToxicPollutant.cas_from_carb_id('18540299') == '18540-29-9'
        assert ToxicPollutant.cas_from_carb_id('9901') == ''

    def test_weights_follow_carbs_formulas(self):
        benzene = ToxicPollutant(carb_id='71432', name='Benzene', slug='benzene', iur=2.9e-5, chronic_rel=3.0, acute_rel=27.0)
        benzene.set_weights()
        assert abs(benzene.cancer_weight - 2.9e-5 * 7700) < 1e-12
        assert abs(benzene.chronic_weight - 0.01712 / 3) < 1e-12
        assert abs(benzene.acute_weight - 0.1712 / 27) < 1e-12
        chromate = ToxicPollutant(carb_id='7789062', name='Strontium chromate', slug='x', iur=0.15, mwaf=0.2554)
        chromate.set_weights()
        assert abs(chromate.cancer_weight - 0.15 * 0.2554 * 7700) < 1e-9

    def test_unweighted_and_precursor_get_no_weights(self):
        pahs = ToxicPollutant(carb_id='1150', name='PAHs', slug='pahs', iur=1.1e-3, chronic_rel=1.0, weighted=False)
        pahs.set_weights()
        assert pahs.cancer_weight == 0 and pahs.chronic_weight > 0
        ammonia = ToxicPollutant(carb_id='7664417', name='Ammonia', slug='ammonia', kind='precursor', chronic_rel=200.0, acute_rel=3200.0)
        ammonia.set_weights()
        assert (ammonia.cancer_weight, ammonia.chronic_weight, ammonia.acute_weight) == (0, 0, 0)

    def test_create_for_sets_kind_cas_and_a_unique_slug(self):
        ammonia = ToxicPollutant.create_for('7664417', 'Ammonia')
        assert ammonia.kind == ToxicPollutant.Kind.PRECURSOR and ammonia.cas_number == '7664-41-7'
        first = ToxicPollutant.create_for('1001', 'Cancer')
        assert first.slug == 'cancer-1001'
        assert ToxicPollutant.create_for('1002', 'Ammonia').slug == 'ammonia-1002'

    def test_unique_slug_clips_a_long_name_so_the_result_fits(self):
        long_name = 'x' * 128
        carb_id = '123456789012'
        slug = ToxicPollutant.unique_slug(long_name, carb_id)
        assert slug == long_name
        # Force the collision branch: the plain slugify(long_name) is
        # "reserved" from this pollutant's own point of view once it exists.
        ToxicPollutant.objects.create(carb_id='1', cas_number='', name=long_name, slug=long_name, kind='toxic')
        slug = ToxicPollutant.unique_slug(long_name, carb_id)
        assert len(slug) <= 140
        assert slug == f'{long_name[:140 - len(carb_id) - 1]}-{carb_id}'


class SourceImportTests(TestCase):
    def test_latest(self):
        assert SourceImport.latest('contable') is None
        SourceImport.objects.create(source='contable', version='2024-12-17')
        newest = SourceImport.objects.create(source='contable', version='2025-09-25')
        assert SourceImport.latest('contable') == newest
