from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides import places, stats
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
        assert 'upcoming_by_county' not in ctx  # single-county area: would just restate the total

    def test_place_context_all_years(self):
        area = places.region_area(Region.objects.get(pk=9001))
        ctx = places.place_context(area, None, all_years=True)
        assert ctx['totals'] == {
            'lbs': 1150.0, 'applications': 6, 'sections_used': 1, 'sections_total': 1, 'chemicals': 3,
        }
        assert ctx['by_month'][7]['lbs'] == 900.0
        assert 'year=all' in ctx['records_url']
        assert ctx['map_config']['year'] == 'all'
        assert ctx['map_config']['year_label'] == '2022\u20132023'
        # Built once and cached; a later import is what clears it.
        assert cache.get(stats.all_years_key('place', 'region:9001')) is not None

    def test_place_context_active_notices(self):
        PesticideNotice.objects.filter(pk=2).update(point=Point(-119.79, 36.71, srid=4326), mtrs_id=9101)
        ctx = places.place_context(places.point_area(36.71, -119.79, 1), 2023)
        assert [n.pk for n in ctx['upcoming']] == [2] and ctx['upcoming_count'] == 1
        assert 'lat=36.71' in ctx['notices_url'] and 'radius=1' in ctx['notices_url']


class RegionOutlineTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_non_county_regions_get_an_outline_url(self):
        from camp.apps.regions.models import Boundary
        city = Region.objects.create(name='Selma', slug='selma', type=Region.Type.CITY, external_id='c-selma')
        boundary = Boundary.objects.create(region=city, version='t', geometry='SRID=4326;MULTIPOLYGON (((-119.85 36.65, -119.75 36.65, -119.75 36.75, -119.85 36.75, -119.85 36.65)))')
        city.boundary = boundary
        city.save()
        assert places.region_area(city).map_kwargs()['outline_url'] == f'/api/2.0/regions/{city.sqid}/'
        assert 'outline_url' not in places.region_area(Region.objects.get(pk=9001)).map_kwargs()
        html = self.client.get(reverse('pesticides:region', kwargs={'sqid': city.sqid, 'slug': 'selma'})).content.decode()
        assert f'data-outline-url="/api/2.0/regions/{city.sqid}/"' in html


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
        assert [o['miles'] for o in response.context['radius_options']] == [1, 3, 5]
        assert [o['miles'] for o in response.context['radius_options'] if o['current']] == [3]

    def test_radius_switcher_links_to_the_other_radii(self):
        html = self.client.get(self.url, {'lat': 36.71, 'lng': -119.79, 'radius': 3}).content.decode()
        assert 'radius-switcher' in html
        for miles in (1, 5):
            assert f'radius={miles}' in html

    def test_label_is_escaped_and_truncated(self):
        html = self.client.get(self.url, {'lat': 36.71, 'lng': -119.79, 'label': '<b>x</b>' + 'y' * 200}).content.decode()
        assert '<b>x</b>' not in html and '&lt;b&gt;x&lt;/b&gt;' in html
        assert 'y' * 121 not in html

    def test_bad_or_missing_coordinates_redirect_home(self):
        for params in ({}, {'lat': 'nan', 'lng': -119.79}, {'lat': 95, 'lng': -119.79}, {'lat': 36.71, 'lng': -119.79, 'radius': 7}):
            response = self.client.get(self.url, params)
            assert response.status_code == 302, params
            assert response['Location'] == reverse('pesticides:home') + '?find=1'


class RegionsWithinTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        from camp.apps.regions.models import Boundary
        self.fresno = Region.objects.get(pk=9001)
        square = 'SRID=4326;MULTIPOLYGON (((-119.85 36.65, -119.75 36.65, -119.75 36.75, -119.85 36.75, -119.85 36.65)))'
        outside = 'SRID=4326;MULTIPOLYGON (((-118.5 35.2, -118.4 35.2, -118.4 35.3, -118.5 35.3, -118.5 35.2)))'
        for name, slug, kind, geom in (
            ('Selma', 'selma', Region.Type.CITY, square),
            ('Selma', 'selma-place', Region.Type.PLACE, square),
            ('Selma Unified', 'selma-unified', Region.Type.SCHOOL_DISTRICT, square),
            ('93662', '93662', Region.Type.ZIPCODE, square),
            ('Tehachapi', 'tehachapi', Region.Type.CITY, outside),
        ):
            region = Region.objects.create(name=name, slug=slug, type=kind, external_id=f'x-{slug}')
            region.boundary = Boundary.objects.create(region=region, version='t', geometry=geom)
            region.save()

    def test_county_lists_places_districts_and_zips_inside_it(self):
        within = places.regions_within(self.fresno)
        assert [p['name'] for p in within['places']] == ['Selma']
        assert '/selma/' in within['places'][0]['url']
        assert [d['name'] for d in within['school_districts']] == ['Selma Unified']
        assert [z['name'] for z in within['zipcodes']] == ['93662']

    def test_county_page_renders_the_lists(self):
        html = self.client.get(reverse('pesticides:region', kwargs={'sqid': self.fresno.sqid, 'slug': 'fresno'})).content.decode()
        assert 'In Fresno County' in html and 'Selma Unified' in html and '93662' in html
        assert 'Tehachapi' not in html

    def test_school_district_pages_render(self):
        district = Region.objects.get(slug='selma-unified')
        response = self.client.get(reverse('pesticides:region', kwargs={'sqid': district.sqid, 'slug': 'selma-unified'}))
        assert response.status_code == 200


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
        # The canonical redirect keeps the query string, so ?year= survives it.
        response = self.client.get(
            reverse('pesticides:region', kwargs={'sqid': self.fresno.sqid, 'slug': 'wrong'}), {'year': 2022},
        )
        assert response['Location'] == self.url + '?year=2022'
        section = Region.objects.get(pk=9101)
        assert self.client.get(reverse('pesticides:region', kwargs={'sqid': section.sqid, 'slug': section.slug})).status_code == 404
        assert self.client.get(reverse('pesticides:region', kwargs={'sqid': 'nope', 'slug': 'x'})).status_code == 404

    def test_by_county_table_links_to_county_pages(self):
        html = self.client.get(reverse('pesticides:home')).content.decode()
        assert self.url in html
