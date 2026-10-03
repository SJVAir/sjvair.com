from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from django.contrib.gis.geos import Point
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from camp.apps.emissions.models import (
    AirComplianceFacility, ComplianceEvent, EmissionsRecord, Facility, SourceImport, ToxicPollutant,
)
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

    def test_point_source_choices_and_trust(self):
        plant = Facility.objects.get(name='TEST PLANT')
        assert plant.point_source == Facility.PointSource.CENSUS
        assert plant.has_trusted_point
        cement = Facility.objects.get(name='TEST CEMENT')
        assert cement.point_source == Facility.PointSource.CARB and cement.has_trusted_point
        station = Facility.objects.get(name='TEST GAS STATION')
        assert station.point_source == Facility.PointSource.MAPTILER and not station.has_trusted_point
        station.point_source = Facility.PointSource.LEGACY
        assert not station.has_trusted_point
        station.point = None
        station.point_source = Facility.PointSource.CENSUS
        assert not station.has_trusted_point  # no point, whatever the source says
        assert Facility._meta.get_field('point_source').default == ''

    def test_geocode_records_the_geocoder(self):
        facility = Facility.objects.get(pk=2)
        point = Point(-119.0, 35.4, srid=4326)
        with patch('camp.utils.geocode.census', return_value=point):
            assert facility.geocode() is True
        assert facility.point_source == Facility.PointSource.CENSUS
        with patch('camp.utils.geocode.census', return_value=None):
            with patch('camp.utils.geocode.maptiler', return_value=point):
                assert facility.geocode() is True
        assert facility.point_source == Facility.PointSource.MAPTILER


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


class AirComplianceFacilityTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_hpv_status_and_dfr_url(self):
        row = AirComplianceFacility.objects.create(pgm_sys_id='CASJV00006019C0001', registry_id='110000000001', name='X')
        assert row.hpv_status == 'none'
        row.current_hpv = 'Unaddressed-Local'
        assert row.hpv_status == 'unaddressed'
        row.current_hpv = 'Addressed-EPA'
        assert row.hpv_status == 'addressed'
        assert row.dfr_url == 'https://echo.epa.gov/detailed-facility-report?fid=110000000001'
        assert row.sqid

    def test_events_are_unique_per_kind_and_id(self):
        row = AirComplianceFacility.objects.create(pgm_sys_id='CASJV00006019C0001', name='X')
        ComplianceEvent.objects.create(icis_facility=row, kind='nov', date=date(2024, 1, 1), agency='L', external_id='1')
        ComplianceEvent.objects.create(icis_facility=row, kind='formal', date=date(2024, 1, 1), agency='L', external_id='1')
        with pytest.raises(IntegrityError):
            ComplianceEvent.objects.create(icis_facility=row, kind='nov', date=date(2024, 2, 2), agency='L', external_id='1')


class MethaneSourceTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def make(self, **overrides):
        from django.contrib.gis.geos import Point
        from camp.apps.emissions.models import MethaneSource
        from camp.apps.regions.models import Region
        values = dict(
            source_name='CH4-test-1', gas='CH4', point=Point(-119.786, 36.736, srid=4326),
            ipcc_sector='4B', persistence=0.6,
            emission_kg_h=120.0, uncertainty_kg_h=40.0, observations=12, detections=5,
            county=Region.objects.get(type=Region.Type.COUNTY, slug='fresno'),
        )
        values.update(overrides)
        return MethaneSource.objects.create(**values)

    def test_a_plume_takes_its_sources_sector(self):
        from datetime import datetime, timezone
        from django.contrib.gis.geos import Point, Polygon
        from camp.apps.emissions.models import MethanePlume
        bounds = Polygon.from_bbox((-119.79, 36.73, -119.78, 36.74))
        bounds.srid = 4326
        values = dict(observed_at=datetime(2024, 6, 1, tzinfo=timezone.utc), point=Point(-119.786, 36.736, srid=4326), bounds=bounds)
        assert MethanePlume(plume_id='p1', source=self.make(), **values).sector_label == 'Dairies & livestock'
        assert MethanePlume(plume_id='p2', **values).sector_label == ''

    def test_sector_groups_and_labels(self):
        from camp.apps.emissions.models import MethaneSource
        assert MethaneSource.sector_for('4B') == ('livestock', 'Dairies & livestock')
        assert MethaneSource.sector_for('1B2') == ('oil-gas', 'Oil & gas')
        assert MethaneSource.sector_for('6A') == ('waste', 'Waste, water & recycling')
        assert MethaneSource.sector_for('6B') == ('waste', 'Waste, water & recycling')
        assert MethaneSource.sector_for('NA') == ('other', 'Other')
        assert MethaneSource.sector_for('1B1') == ('other', 'Coal mining')
        assert MethaneSource.sector_for('9Z') == ('other', '9Z')
        assert MethaneSource.sector_for('') == ('other', 'Unknown sector')
        source = self.make()
        assert source.group == 'livestock' and source.sector_label == 'Dairies & livestock'
        assert self.make(source_name='x', ipcc_sector='1B2').group == 'oil-gas'

    def test_viewer_url_rate_text_and_licence(self):
        from camp.apps.emissions.models import MethaneSource
        source = self.make()
        assert source.viewer_url == 'https://data.carbonmapper.org/#36.73600,-119.78600'
        assert source.rate_text == '120 ± 40 kg/h'
        assert self.make(source_name='y', uncertainty_kg_h=None).rate_text == '120 kg/h'
        assert self.make(source_name='z', emission_kg_h=None).rate_text == 'rate not estimated'
        assert MethaneSource.ATTRIBUTION == 'Data by Carbon Mapper®'
        assert MethaneSource.LICENSE == 'Carbon Mapper non-commercial terms, https://carbonmapper.org/terms'
        assert MethaneSource.LICENSE_URL == 'https://carbonmapper.org/terms'
        assert source.sqid and str(source) == 'CH4-test-1 (Dairies & livestock)'

    def test_methane_generation(self):
        from django.core.cache import cache
        from camp.apps.emissions import methane
        from camp.apps.emissions.models import SourceImport
        cache.clear()
        first = methane.generation()
        assert methane.key('a', 1).endswith(f':{first}:a:1')
        methane.clear_caches()
        assert methane.generation() == first + 1
        assert methane.stamp() is None and not methane.enabled()
        SourceImport.objects.create(source='carbon-mapper')
        assert methane.stamp() is not None and methane.enabled()


class DigesterGrantTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def make(self, **overrides):
        from camp.apps.emissions.models import DigesterGrant
        values = dict(
            project_name='Big Dairy Digester', dairy_name='Big Dairy', city='Riverdale',
            county='Fresno', developer='Dev Co', grant_amount=Decimal('1500000'),
            end_use='Pipeline injection', est_reduction_tco2e=12000.0,
        )
        values.update(overrides)
        return DigesterGrant.objects.create(**values)

    def test_fields_and_str(self):
        grant = self.make()
        assert grant.sqid
        assert grant.dairy is None
        assert grant.match_method == ''
        assert grant.grant_amount == Decimal('1500000')
        assert str(grant) == 'Big Dairy Digester (Big Dairy)'

    def test_dairy_link_and_set_null_on_delete(self):
        from camp.apps.emissions.tests.test_dairies import make_dairies
        big, small, closed = make_dairies()
        grant = self.make(dairy=big, match_method='auto')
        assert grant in big.grants.all()
        big.delete()
        grant.refresh_from_db()
        assert grant.dairy is None
        assert grant.match_method == 'auto'

    def test_ordering_is_newest_award_then_dairy_name(self):
        from camp.apps.emissions.models import DigesterGrant
        older = self.make(project_name='Older', dairy_name='Older Dairy', awarded=date(2020, 1, 1))
        newer = self.make(project_name='Newer', dairy_name='Newer Dairy', awarded=date(2023, 1, 1))
        # Dated grants sort newest-first; undated grants (awarded=None) are
        # grouped separately (Postgres puts NULL first on a DESC order) and
        # sorted by dairy_name among themselves.
        assert list(DigesterGrant.objects.all())[-2:] == [newer, older]

    def test_match_method_choices(self):
        from camp.apps.emissions.models import DigesterGrant
        assert self.make(match_method='auto').match_method == DigesterGrant.Match.AUTO
        assert self.make(match_method='manual').match_method == DigesterGrant.Match.MANUAL
