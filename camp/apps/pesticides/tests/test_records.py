from datetime import date

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from camp.apps.pesticides.models import Chemical, Commodity, PesticideUse, Product
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


class RecordsBrowserTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:records')

    def pks(self, response):
        return [u.pk for u in response.context['object_list']]

    def test_defaults_to_latest_year_newest_first(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/records.html')
        assert self.pks(response) == [6, 5, 4, 3, 2, 1]
        assert response.context['totals'] == {'applications': 6, 'lbs': 740.0, 'acres': 74.0}
        assert response.context['form']['start'].value() == date(2023, 1, 1)

    def test_year_param_sets_range(self):
        response = self.client.get(self.url, {'year': 2022})
        assert self.pks(response) == [9, 8, 7]

    def test_explicit_dates_win(self):
        # pk=4 (2023-06-01) falls inside this range too, so it belongs in the
        # result alongside 3 (05-01) and 5 (07-01); the brief's expected [5, 3]
        # dropped it, which the fixture doesn't support.
        response = self.client.get(self.url, {'start': '2023-05-01', 'end': '2023-07-31'})
        assert self.pks(response) == [5, 4, 3]

    def test_invalid_date_keeps_the_year_guard_and_shows_the_error(self):
        response = self.client.get(self.url, {'start': 'garbage'})
        assert response.status_code == 200
        assert self.pks(response) == [6, 5, 4, 3, 2, 1]
        assert 'is-danger' in response.content.decode()
        assert response.context['form'].errors['start']

    def test_county_and_method(self):
        assert self.pks(self.client.get(self.url, {'county': 'kern'})) == [5, 3]
        assert self.pks(self.client.get(self.url, {'method': 'A'})) == [5, 3]
        assert self.pks(self.client.get(self.url, {'county': 'fresno', 'method': 'A'})) == []

    def test_entity_filters(self):
        chem = Chemical.objects.get(pk=1)
        assert self.pks(self.client.get(self.url, {'chemical': chem.sqid})) == [3, 2, 1]
        assert self.pks(self.client.get(self.url, {'product': Product.objects.get(pk=2).sqid})) == [5, 4]
        assert self.pks(self.client.get(self.url, {'commodity': Commodity.objects.get(pk=2).sqid})) == [6, 2]
        assert self.pks(self.client.get(self.url, {'chemical': 'nope'})) == []
        assert [f['label'] for f in self.client.get(self.url, {'chemical': chem.sqid}).context['active_filters']] == ['GLYPHOSATE']

    def test_section_and_region_params_only_accept_their_own_region_types(self):
        county = Region.objects.get(pk=9001)
        section = Region.objects.get(pk=9101)
        assert self.pks(self.client.get(self.url, {'section': county.sqid})) == []
        assert self.pks(self.client.get(self.url, {'region': section.sqid})) == []

    def test_section_filter_centers_map(self):
        section = Region.objects.get(pk=9102)
        response = self.client.get(self.url, {'section': section.sqid})
        assert self.pks(response) == [5, 3]
        cfg = response.context['map_config']
        assert cfg['zoom'] == 13 and cfg['center'] == '35.3600,-119.0400'

    def test_region_filter_uses_spatial_join(self):
        city = Region.objects.create(name='Fresno', slug='fresno-city', type='city', external_id='c1', boundary=None)
        from camp.apps.regions.models import Boundary
        b = Boundary.objects.create(region=city, version='t', geometry='SRID=4326;MULTIPOLYGON (((-119.85 36.65, -119.75 36.65, -119.75 36.75, -119.85 36.75, -119.85 36.65)))')
        city.boundary = b
        city.save()
        response = self.client.get(self.url, {'region': city.sqid})
        assert self.pks(response) == [6, 4, 2, 1]

    def test_radius_filter(self):
        response = self.client.get(self.url, {'lat': 35.36, 'lng': -119.04, 'radius': 1})
        assert self.pks(response) == [5, 3]
        assert response.context['map_config']['radius'] == 1

    def test_sort_and_pagination_keep_filters(self):
        response = self.client.get(self.url, {'sort': '-lbs', 'county': 'fresno'})
        assert self.pks(response) == [6, 1, 2, 4]
        html = response.content.decode()
        assert 'county=fresno' in html

    def test_totals_cached(self):
        self.client.get(self.url)
        PesticideUse.objects.filter(pk=6).delete()
        assert self.client.get(self.url).context['totals']['applications'] == 6

    def test_rows_link_to_section_and_entities(self):
        html = self.client.get(self.url).content.decode()
        assert reverse('pesticides:section-detail', kwargs={'sqid': Region.objects.get(pk=9101).sqid}) in html
        assert Chemical.objects.get(pk=3).get_absolute_url() in html

    def test_nav_has_records(self):
        html = self.client.get(reverse('pesticides:chemical-list')).content.decode()
        assert reverse('pesticides:records') in html

    def test_page_is_hydrated_without_a_query_per_row(self):
        # Two-step hydration (unjoined page of pks, then one select_related
        # in_bulk() for that page) means the query count shouldn't grow with
        # the number of rows on the page -- a per-row N+1 would blow well
        # past this bound.
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.url, {'county': 'fresno'})
        assert len(ctx.captured_queries) <= 25
        objects = response.context['object_list']
        assert len(objects) == 4

    def test_out_of_range_coordinates_ignored(self):
        response = self.client.get(self.url, {'lat': 200, 'lng': -119.79, 'radius': 1})
        assert response.status_code == 200
        assert self.pks(response) == [6, 5, 4, 3, 2, 1]
        assert response.context['map_config']['radius'] == ''
        assert [f['label'] for f in response.context['active_filters']] == []
