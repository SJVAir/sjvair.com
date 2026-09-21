from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides import places, stats
from camp.apps.pesticides.models import PesticideNotice, PesticideUseRollup
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Boundary, Location, Region
from camp.apps.regions.tests.test_locations import make_district


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
        assert within['counties'] == []
        assert [p['name'] for p in within['places']] == ['Selma']
        assert '/selma/' in within['places'][0]['url']
        assert [d['name'] for d in within['school_districts']] == ['Selma Unified']
        assert [z['name'] for z in within['zipcodes']] == ['93662']

    def test_other_regions_list_what_overlaps_them_and_their_county(self):
        selma = Region.objects.get(slug='selma')
        within = places.regions_within(selma)
        assert [c['name'] for c in within['counties']] == ['Fresno County']
        # Itself and its same-name place twin are left out; Tehachapi is elsewhere.
        assert within['places'] == []
        assert [d['name'] for d in within['school_districts']] == ['Selma Unified']
        assert [z['name'] for z in within['zipcodes']] == ['93662']
        assert within['any'] is True

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

    def test_trend_chart(self):
        response = self.client.get(self.url)
        assert [(r['year'], r['lbs']) for r in response.context['by_year']] == [(2023, 670.0), (2022, 480.0)]
        html = response.content.decode()
        assert 'class="trend-chart"' in html
        assert 'Up 40% since 2022' in html

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


class SchoolDistrictPageTests(RollupTestMixin, TestCase):
    """
    The "Schools & child care in this district" panel, the demographics
    strip, and the map's school markers. The fixture's section 9101 sits in
    Fresno with 2023 use; a school inside it picks that up, a school out of
    any section reports nothing.
    """

    fixtures = ['pesticides-explorer']

    # Sections a mile and three miles east of the fixture's section 9101
    # (centroid -119.79, 36.71): one in the ring around it, one outside.
    NEIGHBOR = 'SRID=4326;MULTIPOLYGON (((-119.78 36.70, -119.76 36.70, -119.76 36.72, -119.78 36.72, -119.78 36.70)))'
    FAR = 'SRID=4326;MULTIPOLYGON (((-119.745 36.70, -119.725 36.70, -119.725 36.72, -119.745 36.72, -119.745 36.70)))'

    # As CDE publishes it with the district boundaries.
    DISTRICT_METADATA = {
        'enrollment': {'total': 44091, 'charter': 837, 'non_charter': 43254},
        'demographics': {
            'hispanic_latino': {'count': 18716, 'pct': 42.4},
            'white': {'count': 12572, 'pct': 28.5},
        },
        'subgroups': {
            'english_learners': {'count': 1874, 'pct': 4.3},
            'socioeconomically_disadvantaged': {'count': 23756, 'pct': 53.9},
            'migrant': {'count': 40, 'pct': 0.1},
        },
    }

    def setUp(self):
        cache.clear()
        self.neighbor = self.make_section('MDM-T14S-R20E-02', self.NEIGHBOR, lbs=25, applications=2)
        self.far = self.make_section('MDM-T14S-R20E-03', self.FAR, lbs=999, applications=9)
        self.district = make_district(
            'Selma Unified', 'selma-unified', '10621170000000', **self.DISTRICT_METADATA)
        self.district.boundary.version = '2025-2026'
        self.district.boundary.save()
        self.inside = Location.objects.create(
            type=Location.Type.PUBLIC_SCHOOL,
            name='Selma High',
            external_id='inside',
            source='cde-public',
            metadata={'district_code': '1062117'},
            point=Point(-119.79, 36.71, srid=4326),
            school_district=self.district,
        )
        self.away = Location.objects.create(
            type=Location.Type.CHILD_CARE,
            name='AWAY CHILD CARE',
            external_id='away',
            source='cdss-ccl',
            point=Point(-121.5, 38.5, srid=4326),
            school_district=self.district,
        )
        self.url = reverse('pesticides:region', kwargs={'sqid': self.district.sqid, 'slug': 'selma-unified'})

    def make_section(self, name, geometry, lbs, applications):
        """An MTRS section with one 2023 rollup row, for the ring around 9101."""
        section = Region.objects.create(
            name=name, slug=name.lower(), type=Region.Type.MTRS, external_id=name,
        )
        section.boundary = Boundary.objects.create(region=section, version='t', geometry=geometry)
        section.save()
        PesticideUseRollup.objects.create(
            year=2023, month=8, county_id=9001, mtrs=section,
            lbs_chemical=lbs, applications=applications,
        )
        return section

    def make_location(self, name, **kwargs):
        kwargs.setdefault('type', Location.Type.CHILD_CARE)
        kwargs.setdefault('source', 'cdss-ccl')
        kwargs.setdefault('point', Point(-121.5, 38.5, srid=4326))
        return Location.objects.create(
            name=name, external_id=name, school_district=self.district, **kwargs)

    def test_block_sections_is_the_section_and_its_ring(self):
        home, pks = stats.block_sections(self.inside.point)
        assert home.pk == 9101
        # The section a mile east is in the ring; the one three miles east isn't.
        assert pks == sorted([9101, self.neighbor.pk])

    def test_block_totals_sum_the_sections_around_a_point(self):
        rows = PesticideUseRollup.objects.all()
        totals = stats.block_totals(rows, self.inside.point, 2023)
        # 670 lbs / 4 applications in section 9101, 25 / 2 in the section a
        # mile east; the section three miles east is left out.
        assert totals['lbs'] == 695.0 and totals['applications'] == 6
        assert totals['section'].pk == 9101

    def test_block_totals_outside_any_section(self):
        totals = stats.block_totals(PesticideUseRollup.objects.all(), self.away.point, 2023)
        assert totals == {'lbs': 0, 'applications': 0, 'section': None}

    def test_schools_nearby_groups_by_administering_district(self):
        # A charter the county office runs, and a private school: both sit in
        # the district's boundary but aren't run by it.
        charter = self.make_location(
            'Selma Charter', type=Location.Type.PUBLIC_SCHOOL, source='cde-public',
            metadata={'district_code': '1062166'},
        )
        private = self.make_location(
            'Selma Christian', type=Location.Type.PRIVATE_SCHOOL, source='cde-private')
        groups = places.schools_nearby(self.district, 2023)
        assert [row['location'].pk for row in groups['run_by']] == [self.inside.pk]
        assert sorted(row['location'].pk for row in groups['others']) == sorted(
            [self.away.pk, charter.pk, private.pk])

    def test_schools_nearby_ranks_by_pounds(self):
        heavier = self.make_location(
            'Selma Elementary', type=Location.Type.PUBLIC_SCHOOL, source='cde-public',
            metadata={'district_code': '1062117'}, point=Point(-119.79, 36.71, srid=4326),
        )
        groups = places.schools_nearby(self.district, 2023)
        # Same pounds: the name breaks the tie.
        assert [row['location'].pk for row in groups['run_by']] == [heavier.pk, self.inside.pk]
        assert groups['run_by'][0]['lbs'] == 695.0 and groups['run_by'][0]['applications'] == 6
        assert groups['run_by'][0]['section_mtrs'] == 'MDM-T14S-R20E-01'
        assert groups['others'] == [{
            'location': self.away, 'lbs': 0, 'applications': 0,
            'section_sqid': None, 'section_mtrs': None,
        }]

    def test_page_renders_the_panel(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        html = response.content.decode()
        assert 'Schools &amp; child care in this district' in html
        assert 'Run by Selma Unified' in html
        assert 'Other schools and child care in the area' in html
        assert 'Selma High' in html and 'Away Child Care' in html
        assert 'Public school' in html and 'Child care' in html
        assert reverse('pesticides:section-detail', kwargs={'sqid': Region.objects.get(pk=9101).sqid}) in html
        assert [row['lbs'] for row in response.context['schools_nearby']['run_by']] == [695.0]

    def test_panel_titlecases_only_the_child_care_names(self):
        self.inside.name = 'Selma High'
        self.inside.city_name = 'Selma'
        self.inside.save()
        self.away.city_name = 'SELMA'
        self.away.save()
        cache.clear()
        html = self.client.get(self.url).content.decode()
        # CDSS shouts its names; CDE's are already properly cased.
        assert '<td>Away Child Care</td>' in html
        assert 'AWAY CHILD CARE' not in html
        assert '<td>Selma High</td>' in html
        assert html.count('<td>Selma</td>') == 2

    def test_panel_leaves_a_shouted_cde_name_alone(self):
        self.inside.name = 'SELMA HIGH'
        self.inside.save()
        cache.clear()
        html = self.client.get(self.url).content.decode()
        assert '<td>SELMA HIGH</td>' in html

    def test_panel_section_links_carry_the_scope(self):
        section_url = reverse('pesticides:section-detail', kwargs={'sqid': Region.objects.get(pk=9101).sqid})
        html = self.client.get(self.url, {'year': '2022', 'concern': '1'}).content.decode()
        assert f'{section_url}?year=2022&amp;concern=1' in html

    def test_panel_caps_each_group_separately(self):
        for index in range(20):
            self.make_location(f'EXTRA CARE {index:02d}')
        for index in range(20):
            self.make_location(
                f'Extra School {index:02d}', type=Location.Type.PUBLIC_SCHOOL,
                source='cde-public', metadata={'district_code': '1062117'},
            )
        cache.clear()
        html = self.client.get(self.url).content.decode()
        # 21 run by the district, 21 others: each group caps at 15.
        assert html.count('Show all 21') == 2
        assert html.count('schools-table') == 4
        assert html.count('Extra Care') == 20
        assert html.count('Extra School') == 20
        open_rows = html.split('<details class="schools-more">')
        assert open_rows[0].count('Extra School') == 14  # plus Selma High makes 15

    def test_empty_group_says_so(self):
        self.inside.delete()
        cache.clear()
        html = self.client.get(self.url).content.decode()
        assert 'No schools are run by this district in the data.' in html
        assert 'Away Child Care' in html

    def test_empty_other_group_says_so(self):
        self.away.delete()
        cache.clear()
        html = self.client.get(self.url).content.decode()
        assert 'Nothing else in the area.' in html
        assert 'Selma High' in html

    def test_page_opens_with_the_school_markers_on(self):
        response = self.client.get(self.url)
        assert response.context['map_config']['show_locations'] == '1'
        html = response.content.decode()
        assert 'data-show-locations="1"' in html
        assert 'name="locations" checked' in html

    def test_empty_district_says_so(self):
        Location.objects.all().delete()
        cache.clear()
        html = self.client.get(self.url).content.decode()
        assert 'No schools or child care on record here.' in html
        assert 'Run by Selma Unified' not in html

    def test_schools_nearby_follows_the_concern_scope(self):
        # Section 9101's concern pounds only (170); the neighbouring
        # section's rollup row carries no chemical at all.
        assert [row['lbs'] for row in places.schools_nearby(self.district, 2023, concern=True)['run_by']] == [170.0]
        assert [row['lbs'] for row in places.schools_nearby(self.district, 2023)['run_by']] == [695.0]

    def test_demographics_strip(self):
        data = places.district_demographics(self.district)
        assert data['enrollment'] == 44091
        assert data['year'] == '2025-2026'
        assert [(m['label'], m['pct']) for m in data['metrics']] == [
            ('Hispanic or Latino', 42.4),
            ('English learners', 4.3),
            ('Socioeconomically disadvantaged', 53.9),
            ('Migrant', 0.1),
        ]

    def test_demographics_strip_renders(self):
        html = self.client.get(self.url).content.decode()
        assert 'Who goes to school here' in html
        assert '2025-2026' in html
        assert '44,091' in html
        assert 'Socioeconomically disadvantaged' in html and '53.9%' in html
        assert 'Migrant' in html and '0.1%' in html

    def test_demographics_strip_hides_without_metadata(self):
        self.district.metadata = {}
        self.district.save()
        cache.clear()
        assert places.district_demographics(self.district) is None
        html = self.client.get(self.url).content.decode()
        assert 'Who goes to school here' not in html

    def test_demographics_strip_skips_missing_metrics(self):
        self.district.metadata = {'enrollment': {'total': 100}}
        self.district.save()
        data = places.district_demographics(self.district)
        assert data['enrollment'] == 100 and data['metrics'] == []

    def test_other_place_pages_have_no_panel(self):
        html = self.client.get(reverse('pesticides:region', kwargs={'sqid': Region.objects.get(pk=9001).sqid, 'slug': 'fresno'})).content.decode()
        assert 'child care in this district' not in html
        assert 'Who goes to school here' not in html
        assert 'data-show-locations="0"' in html


class PlaceConcernScopeTests(RollupTestMixin, TestCase):
    """Place pages follow the chemicals-of-concern scope like everything else."""

    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(pk=9001)

    def test_place_context_totals_narrow(self):
        area = places.region_area(self.fresno)
        ctx = places.place_context(area, 2023, concern=True)
        assert ctx['totals']['lbs'] == 170.0
        assert ctx['totals']['chemicals'] == 2
        assert [r.obj.name for r in ctx['top_chemicals']] == ['GLYPHOSATE', 'CHLORPYRIFOS']
        assert [(r['year'], r['lbs']) for r in ctx['by_year']] == [(2023, 170.0), (2022, 80.0)]
        assert ctx['map_config']['concern'] == '1'
        assert 'concern=1' in ctx['records_url']

    def test_place_context_all_years_caches_separately(self):
        area = places.region_area(self.fresno)
        assert places.place_context(area, None, all_years=True, concern=True)['totals']['lbs'] == 250.0
        assert places.place_context(area, None, all_years=True)['totals']['lbs'] == 1150.0

    def test_notices_are_counted_once_per_county_under_the_scope(self):
        # concern_notices() joins the chemicals M2M, so a notice listing two
        # concern chemicals matches twice -- the county table must still say 1.
        square = 'SRID=4326;MULTIPOLYGON (((-119.85 36.65, -119.75 36.65, -119.75 36.75, -119.85 36.75, -119.85 36.65)))'
        city = Region.objects.create(name='Selma', slug='selma', type=Region.Type.CITY, external_id='x-selma')
        city.boundary = Boundary.objects.create(region=city, version='t', geometry=square)
        city.save()
        notice = PesticideNotice.objects.get(pk=2)   # upcoming, Fresno County
        notice.mtrs_id = 9101
        notice.save()
        notice.chemicals.set([1, 2])                 # GLYPHOSATE and CHLORPYRIFOS

        ctx = places.place_context(places.region_area(city), 2023, concern=True)
        assert ctx['upcoming_by_county'] == [{'county_name': 'Fresno County', 'count': 1}]
        assert ctx['upcoming_count'] == 1
        assert [n.pk for n in ctx['upcoming']] == [notice.pk]

    def test_region_page_follows_the_scope(self):
        url = reverse('pesticides:region', kwargs={'sqid': self.fresno.sqid, 'slug': 'fresno'})
        response = self.client.get(url, {'concern': '1'})
        assert response.context['totals']['lbs'] == 170.0
        assert response.context['concern'] is True
