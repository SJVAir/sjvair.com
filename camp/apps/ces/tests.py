from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.cache import cache
from django.test import TestCase

from camp.apps.ces import stats
from camp.apps.ces.models import CES4, CES5, DACCategory
from camp.apps.regions.models import Boundary, Region


class CES4ModelTests(TestCase):
    fixtures = ['calenviroscreen']

    def get_tract(self, geoid, year):
        return CES4.objects.get(
            boundary__region__external_id=geoid,
            boundary__version=year,
        )

    def test_tract_property(self):
        record = self.get_tract('06019000101', '2020')
        assert record.tract == '06019000101'

    def test_census_year_property(self):
        record = self.get_tract('06019000101', '2020')
        assert record.census_year == '2020'

    def test_region_property(self):
        record = self.get_tract('06019000101', '2020')
        assert record.region.name == 'Census Tract 1.01'

    def test_str(self):
        record = self.get_tract('06019000101', '2020')
        assert 'CES4' in str(record)
        assert '06019000101' in str(record)
        assert '2020' in str(record)

    def test_dac_category_choices(self):
        record = self.get_tract('06019000101', '2020')
        assert record.dac_sb535 is True
        assert record.dac_category == DACCategory.TOP_CES_SCORE

    def test_non_dac_record(self):
        record = self.get_tract('06019000102', '2020')
        assert record.dac_sb535 is False
        assert record.dac_category is None

    def test_queryset_for_version(self):
        qs = CES4.objects.for_version('2020')
        assert qs.count() == 2
        assert all(r.census_year == '2020' for r in qs)

    def test_queryset_for_tract(self):
        qs = CES4.objects.for_tract('06019000101')
        assert qs.count() == 2  # one per vintage
        assert all(r.tract == '06019000101' for r in qs)

    def test_both_vintages_exist(self):
        for geoid in ('06019000101', '06019000102'):
            for year in ('2010', '2020'):
                assert CES4.objects.filter(
                    boundary__region__external_id=geoid,
                    boundary__version=year,
                ).exists()

    def test_sqid_is_a_nonempty_string(self):
        record = self.get_tract('06019000101', '2020')
        assert isinstance(record.sqid, str)
        assert record.sqid


class CES5ModelTests(TestCase):
    fixtures = ['calenviroscreen']

    def get_tract(self, geoid):
        return CES5.objects.get(boundary__region__external_id=geoid)

    def test_tract_property(self):
        record = self.get_tract('06019000101')
        assert record.tract == '06019000101'

    def test_census_year_property(self):
        record = self.get_tract('06019000101')
        assert record.census_year == '2020'

    def test_region_property(self):
        record = self.get_tract('06019000101')
        assert record.region.name == 'Census Tract 1.01'

    def test_region_name_field(self):
        record = self.get_tract('06019000101')
        assert record.region_name == 'San Joaquin Valley'

    def test_str(self):
        record = self.get_tract('06019000101')
        assert 'CES5' in str(record)
        assert '06019000101' in str(record)
        assert '2020' in str(record)

    def test_dac_category_choices(self):
        record = self.get_tract('06019000101')
        assert record.dac_sb535 is True
        assert record.dac_category == DACCategory.TOP_CES_SCORE

    def test_non_dac_record(self):
        record = self.get_tract('06019000102')
        assert record.dac_sb535 is False
        assert record.dac_category is None

    def test_only_one_vintage_exists(self):
        assert CES5.objects.for_tract('06019000101').count() == 1

    def test_new_indicators_present(self):
        record = self.get_tract('06019000101')
        assert record.pol_small_ats_p == 68.0
        assert record.char_diabetes_p == 77.0

    def test_demographic_percentages(self):
        record = self.get_tract('06019000101')
        assert record.pop_hispanic_pct == 60.2
        assert record.pop_asian_pct == 5.8
        assert record.pop_pacisl_pct == 0.4

    def test_sqid_is_a_nonempty_string(self):
        record = self.get_tract('06019000101')
        assert isinstance(record.sqid, str)
        assert record.sqid


def bbox(west, south, east, north):
    return MultiPolygon(Polygon.from_bbox((west, south, east, north)), srid=4326)


def make_tract(geoid, west, east, **ces5_fields):
    """A 2020 tract between longitudes west..east, latitude 36.7..36.8 (like the fixture tracts), with a CES5 row."""
    region = Region.objects.create(name=f'Census Tract {geoid[-4:]}', slug=f'tract-{geoid}', type=Region.Type.TRACT, external_id=geoid)
    boundary = Boundary.objects.create(region=region, version='2020', geometry=bbox(west, 36.7, east, 36.8))
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    CES5.objects.create(boundary=boundary, **ces5_fields)
    return region


class TractSummaryTests(TestCase):
    """Fixture tracts: 1.01 is -119.8..-119.7 (89.2, DAC, pop 4650); 1.02 is -119.7..-119.6 (51.0, not DAC, pop 3350)."""
    fixtures = ['regions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        cache.clear()

    def test_current_model_prefers_ces5_then_ces4(self):
        assert stats.current_model() == (CES5, '2020')
        CES5.objects.all().delete()
        assert stats.current_model() == (CES4, '2020')
        CES4.objects.all().delete()
        assert stats.current_model() == (None, None)
        assert stats.tract_summary(bbox(-119.8, 36.7, -119.6, 36.8)) is None

    def test_a_small_place_falls_to_its_containing_tract(self):
        # Inside tract 1.01 but clear of its centroid (-119.75, 36.75), and 4% of its area.
        summary = stats.tract_summary(bbox(-119.79, 36.71, -119.77, 36.73))
        assert summary['count'] == 0 and summary['tracts'] == [] and summary['scored'] == 0
        assert summary['containing']['region'].external_id == '06019000101'
        assert summary['containing']['ci_score_p'] == 89.2 and summary['containing']['dac'] is True
        assert summary['dac_share'] is None and summary['min_p'] is None

    def test_overlap_rule(self):
        # 5% of tract 1.01 (its centroid is outside): only 1.02 counts.
        summary = stats.tract_summary(bbox(-119.705, 36.7, -119.6, 36.8))
        assert [row['region'].external_id for row in summary['tracts']] == ['06019000102']
        # 40% of tract 1.01: both count, highest first.
        summary = stats.tract_summary(bbox(-119.74, 36.7, -119.6, 36.8))
        assert [row['region'].external_id for row in summary['tracts']] == ['06019000101', '06019000102']
        assert summary['highest']['region'].external_id == '06019000101' and summary['lowest']['region'].external_id == '06019000102'

    def test_an_import_orphans_cached_summaries(self):
        area = bbox(-119.79, 36.71, -119.77, 36.73)
        assert stats.tract_summary(area)['containing']['ci_score_p'] == 89.2
        CES5.objects.filter(boundary__region__external_id='06019000101').update(ci_score_p=12.5)
        assert stats.tract_summary(area)['containing']['ci_score_p'] == 89.2
        stats.clear_caches()
        assert stats.tract_summary(area)['containing']['ci_score_p'] == 12.5

    def test_a_shared_border_is_not_membership(self):
        # Exactly tract 1.01: 1.02 touches it along one edge (intersects, overlap 0).
        summary = stats.tract_summary(bbox(-119.8, 36.7, -119.7, 36.8))
        assert summary['count'] == 1 and summary['population'] == 4650

    def test_no_score_tracts_count_but_are_not_scored(self):
        make_tract('06019000103', -119.6, -119.5, population=1000, ci_score_p=-999, dac_sb535=True)
        summary = stats.tract_summary(bbox(-119.8, 36.7, -119.5, 36.8))
        assert summary['model'] == 'CES5' and summary['version'] == '2020' and summary['label'] == 'CalEnviroScreen 5.0'
        assert summary['count'] == 3 and summary['scored'] == 2
        assert summary['dac_tracts'] == 2 and summary['dac_population'] == 5650 and summary['population'] == 9000
        assert abs(summary['dac_share'] - 5650 / 9000) < 1e-9
        assert summary['min_p'] == 51.0 and summary['max_p'] == 89.2 and abs(summary['mean_p'] - 70.1) < 1e-9
        assert summary['top25_tracts'] == 1
        assert summary['tracts'][-1]['ci_score_p'] is None  # the unscored tract sorts last
        assert [row['region'].external_id for row in summary['top']] == ['06019000101', '06019000102']

    def test_cached_per_geometry(self):
        geometry = bbox(-119.8, 36.7, -119.6, 36.8)
        assert stats.tract_summary(geometry)['count'] == 2
        CES5.objects.filter(boundary__region__external_id='06019000102').delete()
        assert stats.tract_summary(geometry)['count'] == 2
        cache.clear()
        assert stats.tract_summary(geometry)['count'] == 1

    def test_ces4_when_asked(self):
        summary = stats.tract_summary(bbox(-119.8, 36.7, -119.6, 36.8), model=CES4)
        assert summary['model'] == 'CES4' and summary['max_p'] == 87.9


class TractRecordTests(TestCase):
    fixtures = ['regions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        cache.clear()

    def test_the_tracts_own_row(self):
        tract = Region.objects.get(external_id='06019000101', type=Region.Type.TRACT)
        record = stats.tract_record(tract)
        assert record['ci_score_p'] == 89.2 and record['pollution_p'] == 83.0
        assert record['dac'] is True and record['dac_category'] == 'Top 25% CES overall score'
        assert record['label'] == 'CalEnviroScreen 5.0' and record['region'] == tract

    def test_not_a_tract_or_no_data(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        assert stats.tract_record(fresno) is None
        assert stats.tract_record(None) is None
        tract = Region.objects.get(external_id='06019000101', type=Region.Type.TRACT)
        CES5.objects.all().delete()
        CES4.objects.all().delete()
        assert stats.tract_record(tract) is None


def make_place(name, kind, west, south, east, north):
    region = Region.objects.create(name=name, slug=name.lower(), type=kind, external_id=f'{kind}-{name}')
    region.boundary = Boundary.objects.create(region=region, version='t', geometry=bbox(west, south, east, north))
    region.save(update_fields=['boundary'])
    return region


class TractLabelTests(TestCase):
    """A tract names itself by number and by the place it sits in."""
    fixtures = ['regions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        cache.clear()
        self.tract = Region.objects.get(external_id='06019000101')

    def test_tract_number_is_the_census_number(self):
        assert stats.tract_number(Region(external_id='06019002001')) == '20.01'
        assert stats.tract_number(Region(external_id='06019000400')) == '4'
        assert stats.tract_number(Region(external_id='06019000101')) == '1.01'
        assert stats.tract_number(Region(external_id='nope')) is None

    def test_the_city_wins_over_the_cdp_that_also_contains_it(self):
        # The fixture's Fresno city contains the tract.
        make_place('Calwa', Region.Type.CDP, -119.9, 36.6, -119.6, 36.9)
        assert stats.tract_place(self.tract.boundary.geometry) == 'Fresno'
        Region.objects.filter(type=Region.Type.CITY).delete()
        assert stats.tract_place(self.tract.boundary.geometry) == 'Calwa'

    def test_the_nearest_place_when_none_contains_it(self):
        Region.objects.filter(type=Region.Type.CITY).delete()
        assert stats.tract_place(self.tract.boundary.geometry) is None
        make_place('Easton', Region.Type.CDP, -119.69, 36.7, -119.65, 36.8)
        # The tract's interior point is about 0.02 degrees west of Easton.
        assert stats.tract_place(self.tract.boundary.geometry) == 'near Easton'

    def test_the_summary_labels_the_tracts_it_names(self):
        summary = stats.tract_summary(bbox(-119.8, 36.7, -119.6, 36.8))
        assert [row['place'] for row in summary['top']] == ['Fresno', 'near Fresno']
        assert summary['highest']['number'] == '1.01'

    def test_places_can_be_skipped(self):
        summary = stats.tract_summary(bbox(-119.8, 36.7, -119.6, 36.8), places=False)
        assert all('place' not in row for row in summary['top'])
        assert summary['highest']['number'] == '1.01'
