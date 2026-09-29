from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import ghg, ghg_crosswalk
from camp.apps.emissions.models import Facility, GHGReport
from camp.apps.regions.models import Region


# TEST PLANT: Fresno (10, 'SJU', 1), point (-119.787, 36.737), ZIP 93728 (a fixture ZIP Region).
# TEST GAS STATION: Kern (15, 'SJU', 2), ZIP 93301 (no fixture ZIP Region).
# TEST CEMENT: Eastern Kern (15, 'KER', 2), point (-118.17, 35.05).
NEAR_PLANT = Point(-119.790, 36.739, srid=4326)      # ~350 m from TEST PLANT
FAR_FROM_PLANT = Point(-119.72, 36.737, srid=4326)   # ~6 km east


class GHGTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.station = Facility.objects.get(name='TEST GAS STATION')
        self.cement = Facility.objects.get(name='TEST CEMENT')
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        # Phase 2: only trusted points take part in the distance match.
        Facility.objects.update(point_source=Facility.PointSource.CENSUS)


def report(program='mrr', external_id='1', year=2024, **kwargs):
    values = dict(name='X', co2e=10000.0)
    values.update(kwargs)
    return GHGReport.objects.create(program=program, external_id=external_id, year=year, **values)


class NameKeyTests(TestCase):
    def test_key_drops_corporate_noise(self):
        assert ghg.name_key('Ardagh Glass Inc.') == 'ARDAGH GLASS'
        assert ghg.name_key('PG&E McDonald Island Underground Storage Station') == 'PG AND E MCDONALD ISLAND UNDERGROUND STORAGE STATION'
        assert ghg.name_key('The Test Plant, LLC (Fresno)') == 'TEST PLANT FRESNO'
        assert ghg.name_key('') == ''

    def test_similarity(self):
        assert ghg.similarity('Test Plant Inc', 'TEST PLANT') == 1.0
        assert ghg.similarity('Mt. Poso Cogeneration Company', 'Sycamore Cogeneration Co') < ghg.AUTO_RATIO


class ResolveTests(GHGTestCase):
    def test_frs_id_wins(self):
        facility, method = ghg.resolve('ghgrp', '1', name='UNRELATED NAME', frs_air_id='CASJV00006019C0001', point=FAR_FROM_PLANT)
        assert facility == self.plant and method == 'frs'

    def test_frs_id_for_an_unknown_facility_falls_through(self):
        facility, method = ghg.resolve('ghgrp', '1', name='Nothing Like It', frs_air_id='CASJV00006019C9999', point=FAR_FROM_PLANT)
        assert facility is None and method == ''
        # Eastern Kern ids don't parse; they fall through too.
        facility, method = ghg.resolve('ghgrp', '1', name='Test Cement', frs_air_id='CAKCA000000000002', point=Point(-118.17, 35.05, srid=4326))
        assert facility == self.cement and method == 'auto'

    def test_crosswalk_beats_auto_and_can_pin_none(self):
        with patch.dict(ghg_crosswalk.MRR, {'7': (15, 'KER', 2), '8': None}, clear=True):
            assert ghg.resolve('mrr', '7', name='Test Plant', zipcode='93728') == (self.cement, 'crosswalk')
            assert ghg.resolve('mrr', '8', name='Test Plant', zipcode='93728') == (None, 'crosswalk')
        with patch.dict(ghg_crosswalk.MRR, {'7': (15, 'KER', 999)}, clear=True):
            # A stale key (no such facility) is ignored, not fatal.
            assert ghg.resolve('mrr', '7', name='Test Plant', zipcode='93728') == (self.plant, 'auto')

    def test_auto_match_by_zip(self):
        assert ghg.resolve('mrr', '1', name='Test Plant Inc.', zipcode='93728') == (self.plant, 'auto')
        assert ghg.resolve('mrr', '1', name='Test Plant Inc.', zipcode='93728-1234') == (self.plant, 'auto')
        # Same ZIP, different name.
        assert ghg.resolve('mrr', '1', name='Fresno Cogeneration Partners', zipcode='93728') == (None, '')
        # Right name, other ZIP.
        assert ghg.resolve('mrr', '1', name='Test Plant', zipcode='93301') == (None, '')

    def test_auto_match_by_distance(self):
        assert ghg.resolve('ghgrp', '1', name='Test Plant', point=NEAR_PLANT) == (self.plant, 'auto')
        assert ghg.resolve('ghgrp', '1', name='Test Plant', point=FAR_FROM_PLANT) == (None, '')
        Facility.objects.filter(pk=self.plant.pk).update(point_source=Facility.PointSource.MAPTILER)
        assert ghg.resolve('ghgrp', '1', name='Test Plant', point=NEAR_PLANT) == (None, '')

    def test_auto_match_needs_a_clear_winner(self):
        # Multi-site companies reuse a name across CEIDARS facilities: two
        # equal candidates (1.0 and 1.0) is no match at all.
        twin = Facility.objects.create(
            county_code=10, air_district=self.plant.air_district, facid=77, name='TEST PLANT', sic_code=3221,
            address={'zipcode': '93728'}, point=Point(-119.788, 36.738, srid=4326), point_source=Facility.PointSource.CENSUS,
            county=self.fresno, zipcode=self.plant.zipcode,
        )
        assert ghg.resolve('mrr', '1', name='Test Plant', zipcode='93728') == (None, '')
        # 'TEST PLANT NORTH' scores 0.8 against 'Test Plant' (at the ratio floor)
        # and the original scores 1.0: a clear winner either way round.
        Facility.objects.filter(pk=twin.pk).update(name='TEST PLANT NORTH')
        twin.refresh_from_db()
        assert ghg.resolve('mrr', '1', name='Test Plant', zipcode='93728') == (self.plant, 'auto')
        assert ghg.resolve('mrr', '1', name='Test Plant North', zipcode='93728') == (twin, 'auto')
