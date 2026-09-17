from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides import places
from camp.apps.pesticides.models import PesticideNotice
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


class AreaTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_point_area_finds_sections_in_radius(self):
        area = places.point_area(36.71, -119.79, 1, label='near Fresno')
        assert area.kind == 'point' and area.section_pks == [9101]
        assert area.map_kwargs() == {'center': '36.7100,-119.7900', 'zoom': 12, 'radius': 1, 'county': None}

    def test_region_area_county_uses_fk_and_caches_sections(self):
        fresno = Region.objects.get(pk=9001)
        area = places.region_area(fresno)
        assert area.section_pks == [9101]
        assert list(area.rollup_rows().values_list('county', flat=True).distinct()) == [9001]
        assert cache.get('pesticides:area-sections:9001') == [9101]
        assert area.map_kwargs()['zoom'] == 9 and area.map_kwargs()['county'] == 'fresno'

    def test_place_context_totals_and_peak(self):
        ctx = places.place_context(places.region_area(Region.objects.get(pk=9001)), 2023)
        assert ctx['totals'] == {'lbs': 670.0, 'applications': 4, 'sections_used': 1, 'sections_total': 1, 'chemicals': 3}
        assert ctx['peak_month'] == 'August'
        assert [r.obj.name for r in ctx['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert ctx['records_url'].startswith(reverse('pesticides:records') + '?')
        assert 'county=fresno' in ctx['records_url'] and 'year=2023' in ctx['records_url']

    def test_place_context_active_notices(self):
        PesticideNotice.objects.filter(pk=2).update(point=Point(-119.79, 36.71, srid=4326), mtrs_id=9101)
        ctx = places.place_context(places.point_area(36.71, -119.79, 1), 2023)
        assert [n.pk for n in ctx['upcoming']] == [2] and ctx['upcoming_count'] == 1
        assert 'lat=36.71' in ctx['notices_url'] and 'radius=1' in ctx['notices_url']


class NearMeTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:near-me')

    def test_renders(self):
        response = self.client.get(self.url, {'lat': 36.71, 'lng': -119.79, 'radius': 3, 'label': 'near Selma, Fresno County'})
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/place.html')
        html = response.content.decode()
        assert 'near Selma, Fresno County' in html and 'Within 3 miles' in html
        assert 'only in this page' in html and 'spraydays.cdpr.ca.gov' in html
        assert response.context['map_config']['radius'] == 3
        assert [o['miles'] for o in response.context['radius_options']] == [1, 5]

    def test_label_is_escaped_and_truncated(self):
        html = self.client.get(self.url, {'lat': 36.71, 'lng': -119.79, 'label': '<b>x</b>' + 'y' * 200}).content.decode()
        assert '<b>x</b>' not in html and '&lt;b&gt;x&lt;/b&gt;' in html
        assert 'y' * 121 not in html

    def test_bad_or_missing_coordinates_redirect_home(self):
        for params in ({}, {'lat': 'nan', 'lng': -119.79}, {'lat': 95, 'lng': -119.79}, {'lat': 36.71, 'lng': -119.79, 'radius': 7}):
            response = self.client.get(self.url, params)
            assert response.status_code == 302, params
            assert response['Location'] == reverse('pesticides:home') + '?find=1'


class RegionPageTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(pk=9001)
        self.url = reverse('pesticides:region', kwargs={'sqid': self.fresno.sqid, 'slug': 'fresno'})

    def test_renders(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.context['totals']['lbs'] == 670.0
        html = response.content.decode()
        assert 'Fresno County' in html and 'Spraying peaks in August here' in html and 'month-bars' in html
        assert 'only in this page' not in html

    def test_slug_redirect_and_404s(self):
        response = self.client.get(reverse('pesticides:region', kwargs={'sqid': self.fresno.sqid, 'slug': 'wrong'}))
        assert response.status_code == 301 and response['Location'] == self.url
        section = Region.objects.get(pk=9101)
        assert self.client.get(reverse('pesticides:region', kwargs={'sqid': section.sqid, 'slug': section.slug})).status_code == 404
        assert self.client.get(reverse('pesticides:region', kwargs={'sqid': 'nope', 'slug': 'x'})).status_code == 404

    def test_by_county_table_links_to_county_pages(self):
        html = self.client.get(reverse('pesticides:home')).content.decode()
        assert self.url in html
