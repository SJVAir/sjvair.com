from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase

from camp.apps.pesticides import stats
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Location, Region


class LandingDerivedStatsTests(RollupTestMixin, TestCase):
    """The landing stat row: figures worked out from the year's totals, not counts."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_rates_and_shares(self):
        data = stats.landing_stats(2023)
        assert data['lbs_per_acre'] == data['total_lbs'] / data['acres']
        assert data['lbs_per_application'] == data['total_lbs'] / data['applications']
        assert 0 <= data['flagged_share'] <= 1
        top = data['top_county']
        assert top['county_name'] == data['by_county'][0]['county_name']
        assert top['share'] == data['by_county'][0]['lbs'] / sum(row['lbs'] for row in data['by_county'])

    def test_no_share_that_would_read_100_percent(self):
        # Inside one county its own share is the whole; under a narrowing the flagged share is.
        fresno = Region.objects.get(pk=9001)
        assert stats.landing_stats(2023, county=fresno)['top_county'] is None
        assert stats.landing_stats(2023, concern=stats.NARROW_CONCERN)['flagged_share'] is None

    def test_schools_near_use(self):
        section = Region.objects.get(pk=9101)
        near = section.boundary.geometry.point_on_surface
        Location.objects.create(type=Location.Type.PUBLIC_SCHOOL, name='Near', external_id='x-near', source='cde-public', point=near)
        Location.objects.create(type=Location.Type.CHILD_CARE, name='Far', external_id='x-far', source='cdss-ccl',
            point=Point(near.x + 1, near.y + 1, srid=4326))
        data = stats.landing_stats(2023)
        assert data['schools_near_use'] == 1 and data['schools_total'] == 2
