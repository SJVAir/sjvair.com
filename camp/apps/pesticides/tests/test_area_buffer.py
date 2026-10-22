from datetime import datetime, timezone

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase

from camp.apps.pesticides import places, rollup
from camp.apps.pesticides.models import Chemical, PesticideNotice, PesticideUse
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Boundary, Location, Region

# East of Selma's edge (-119.75) by 0.02-0.04 degrees: about 1.1 to 2.2 miles.
OUTSIDE = 'SRID=4326;MULTIPOLYGON (((-119.73 36.70, -119.71 36.70, -119.71 36.72, -119.73 36.72, -119.73 36.70)))'


class RegionBufferWidensEverythingTests(RollupTestMixin, TestCase):
    """With ?buffer= a region's tabs cover the widened region, so their numbers match the map."""
    fixtures = ['pesticides-explorer']

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.fresno = Region.objects.get(pk=9001)
        cls.city = Region.objects.create(name='Selma', slug='selma', type=Region.Type.CITY, external_id='c-selma')
        cls.city.boundary = Boundary.objects.create(
            region=cls.city, version='t',
            geometry='SRID=4326;MULTIPOLYGON (((-119.85 36.65, -119.75 36.65, -119.75 36.75, -119.85 36.75, -119.85 36.65)))',
        )
        cls.city.save()
        cls.outside = Region.objects.create(
            name='MDM-T14S-R20E-02', slug='mdm-t14s-r20e-02', type=Region.Type.MTRS, external_id='MDM-T14S-R20E-02')
        cls.outside.boundary = Boundary.objects.create(region=cls.outside, version='t', geometry=OUTSIDE)
        cls.outside.save()
        PesticideUse.objects.create(
            year=2023, use_no=50, county=cls.fresno, mtrs=cls.outside, chemical=Chemical.objects.get(pk=1),
            lbs_chemical=25, lbs_product=25, application_date='2023-03-05', aerial_ground='G')
        cls.notice = PesticideNotice.objects.create(
            application_id=50, comtrs='10M13S14E10', mtrs=cls.outside, county=cls.fresno,
            scheduled_application=datetime(2099, 3, 1, 8, tzinfo=timezone.utc), application_method='Ground')
        cls.school = Location.objects.create(
            type=Location.Type.PUBLIC_SCHOOL, name='Just Outside High', external_id='x-out', source='cde-public',
            point=Point(-119.72, 36.71, srid=4326))
        rollup.rebuild_all()

    def get(self, tab, **params):
        return self.client.get(self.city.get_pesticides_tab_url(tab), {'year': 2023, **params})

    def test_overview_counts_what_the_buffer_reaches(self):
        assert self.get('overview').context['totals']['lbs'] == 670.0
        assert self.get('overview', buffer=1).context['totals']['lbs'] == 670.0
        context = self.get('overview', buffer=3).context
        assert context['totals']['lbs'] == 695.0
        assert context['totals']['applications'] == 5
        assert context['totals']['sections_total'] == 2
        assert context['upcoming_count'] == 1
        assert self.get('overview').context['upcoming_count'] == 0

    def test_a_widened_area_is_bigger_and_keeps_out_of_the_exact_caches(self):
        exact = places.region_area(self.city)
        wide = places.region_area(self.city, 3)
        assert wide.square_miles > exact.square_miles
        assert wide.cache_key() != exact.cache_key()
        assert wide.area_params() == {'region': self.city.sqid, 'buffer': 3}
        assert exact.area_params() == {'region': self.city.sqid}

    def test_a_widened_county_is_not_the_county(self):
        assert places.region_area(self.fresno).county == self.fresno
        wide = places.region_area(self.fresno, 3)
        assert wide.county is None
        assert wide.total_rows() is None
        assert wide.section_pks == [9101, self.outside.pk]

    def test_overview_links_carry_the_buffer(self):
        context = self.get('overview', buffer=3).context
        assert 'buffer=3' in context['records_url'] and 'buffer=3' in context['notices_url']
        assert 'buffer' not in self.get('overview').context['records_url']

    def test_records_tab_lists_the_records_in_the_widened_region(self):
        assert self.get('records').context['totals']['applications'] == 4
        response = self.get('records', buffer=3)
        assert response.context['totals']['applications'] == 5
        assert response.context['totals']['lbs'] == 695.0
        assert [chip['label'] for chip in response.context['active_filters']] == []

    def test_notices_tab_lists_the_notices_in_the_widened_region(self):
        assert self.get('notices').context['count'] == 0
        response = self.get('notices', buffer=3)
        assert response.context['count'] == 1
        assert response.context['active_filters'] == []
        assert response.context['buffer_note']['miles'] == 3
        assert 'buffer' not in response.context['buffer_note']['url']

    def test_schools_tab_lists_the_sites_in_the_widened_region(self):
        assert self.get('schools').status_code == 200
        assert self.get('schools').context['school_count'] == 0
        response = self.get('schools', buffer=3)
        assert response.context['school_count'] == 1
        assert response.context['map_config']['locations_area'] == f'region={self.city.sqid}&buffer=3'

    def test_the_schools_csv_follows_the_buffer(self):
        assert b'Just Outside High' not in self.get('schools', format='csv').content
        assert b'Just Outside High' in self.get('schools', buffer=3, format='csv').content

    def test_no_note_without_a_buffer(self):
        assert self.get('records').context['buffer_note'] is None

    def test_filter_forms_and_tab_links_keep_the_buffer(self):
        for tab in ('records', 'notices', 'schools'):
            response = self.get(tab, buffer=3)
            assert '<input type="hidden" name="buffer" value="3">' in response.content.decode(), tab
            assert all('buffer=3' in t['url'] for t in response.context['tabs']), tab
