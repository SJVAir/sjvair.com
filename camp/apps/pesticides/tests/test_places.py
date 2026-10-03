from django.contrib.gis.geos import Point
import math

import pytest

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides import places, stats
from camp.apps.pesticides.models import Chemical, PesticideNotice, PesticideUseRollup
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
        totals = ctx['totals']
        assert (totals['lbs'], totals['applications']) == (670.0, 4)
        assert (totals['sections_used'], totals['sections_total'], totals['chemicals']) == (1, 1, 3)
        # One square mile reported use, so that rate is the whole total.
        assert totals['lbs_per_used_sqmi'] == 670.0
        assert totals['lbs_per_sqmi'] == pytest.approx(670.0 / totals['square_miles'])
        assert ctx['peak_month'] == 'August'
        assert [r.obj.name for r in ctx['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert ctx['records_url'].startswith(reverse('pesticides:records') + '?')
        assert 'county=fresno' in ctx['records_url'] and 'year=2023' in ctx['records_url']
        assert 'upcoming_by_county' not in ctx  # single-county area: would just restate the total

    def test_place_context_all_years(self):
        area = places.region_area(Region.objects.get(pk=9001))
        ctx = places.place_context(area, None, all_years=True)
        totals = ctx['totals']
        assert (totals['lbs'], totals['applications']) == (1150.0, 6)
        assert (totals['sections_used'], totals['sections_total'], totals['chemicals']) == (1, 1, 3)
        assert ctx['by_month'][7]['lbs'] == 900.0
        assert 'year=all' in ctx['records_url']
        assert ctx['map_config']['year'] == 'all'
        assert ctx['map_config']['year_label'] == '2022\u20132023'
        # Built once and cached; a later import is what clears it.
        assert cache.get(stats.all_years_key('place-v3', 'region:9001')) is not None

    def test_place_page_cards(self):
        fresno = Region.objects.get(pk=9001)
        url = reverse('pesticides:region', kwargs={'sqid': fresno.sqid, 'slug': 'fresno'})

        response = self.client.get(url, {'year': 2023})

        assert response.context['chemicals_card']['title'] == 'Top chemicals'
        assert 'narrow=concern' not in response.context['chemicals_card']['show_all_url']
        # One card per kind and no more: the chemicals-of-concern card
        # repeated the chemicals card, whose rows carry the same badges.
        assert 'chemicals_of_concern_card' not in response.context
        assert response.content.decode().count('class="card related-card"') == 3

    def test_concern_chemicals_are_badged_in_the_chemicals_card(self):
        # What the dedicated concern card used to say, said in place.
        fresno = Region.objects.get(pk=9001)
        url = reverse('pesticides:region', kwargs={'sqid': fresno.sqid, 'slug': 'fresno'})

        html = self.client.get(url, {'year': 2023}).content.decode()

        assert 'Prop 65' in html

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
            ('Selma', 'selma-ua', Region.Type.URBAN_AREA, square),
            ('Caruthers', 'caruthers', Region.Type.CDP, square),
            ('Selma Unified', 'selma-unified', Region.Type.SCHOOL_DISTRICT, square),
            ('93662', '93662', Region.Type.ZIPCODE, square),
            ('Tehachapi', 'tehachapi', Region.Type.CITY, outside),
        ):
            region = Region.objects.create(name=name, slug=slug, type=kind, external_id=f'x-{slug}')
            region.boundary = Boundary.objects.create(region=region, version='t', geometry=geom)
            region.save()

    def test_county_lists_communities_districts_and_zips_inside_it(self):
        within = places.regions_within(self.fresno)
        assert within['counties'] == []
        # Every community layer, as-is and labelled; same names by layer order.
        assert [(p['name'], p['type_label']) for p in within['communities']] == [
            ('Caruthers', 'Community'), ('Selma', 'City'), ('Selma', 'Urban area'),
        ]
        assert '/selma/' in within['communities'][1]['url']
        assert [d['name'] for d in within['school_districts']] == ['Selma Unified']
        assert [z['name'] for z in within['zipcodes']] == ['93662']

    def test_other_regions_list_what_overlaps_them_and_their_county(self):
        selma = Region.objects.get(slug='selma')
        within = places.regions_within(selma)
        assert [c['name'] for c in within['counties']] == ['Fresno County']
        # Itself is left out, its same-name urban area is not; Tehachapi is elsewhere.
        assert [(p['name'], p['type_label']) for p in within['communities']] == [
            ('Caruthers', 'Community'), ('Selma', 'Urban area'),
        ]
        assert [d['name'] for d in within['school_districts']] == ['Selma Unified']
        assert [z['name'] for z in within['zipcodes']] == ['93662']
        assert within['any'] is True

    def test_county_page_renders_the_lists(self):
        # In and around is on a place's Community tab.
        html = self.client.get(reverse('pesticides:region-community', kwargs={'sqid': self.fresno.sqid, 'slug': 'fresno'})).content.decode()
        assert 'In Fresno County' in html and 'Selma Unified' in html and '93662' in html
        assert 'Tehachapi' not in html

    def test_community_pages_render_labelled(self):
        for slug, label in (('selma-ua', 'Urban area'), ('caruthers', 'Community')):
            region = Region.objects.get(slug=slug)
            response = self.client.get(reverse('pesticides:region', kwargs={'sqid': region.sqid, 'slug': slug}))
            assert response.status_code == 200
            html = response.content.decode()
            assert label in html
            assert 'Census Designated Place' not in html

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
        assert 'Fresno County' in html and 'Spraying peaks in August here' in html
        # Two years are loaded, so seasonality is the grid; the bars would
        # redraw the grid's own top row.
        assert 'month-heatmap' in html and 'month-chart' not in html
        assert 'only in this page' not in html

    def test_trend_chart(self):
        response = self.client.get(self.url)
        assert [(r['year'], r['lbs']) for r in response.context['by_year']] == [(2023, 670.0), (2022, 480.0)]
        html = response.content.decode()
        assert 'class="explorer-chart trend-chart"' in html
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
        # The schools table is the district page's Schools tab.
        self.url = reverse('pesticides:region-schools', kwargs={'sqid': self.district.sqid, 'slug': 'selma-unified'})

    def make_section(self, name, geometry, lbs, applications):
        """An MTRS section with one 2023 rollup row, for the ring around 9101."""
        section = Region.objects.create(
            name=name, slug=name.lower(), type=Region.Type.MTRS, external_id=name,
        )
        section.boundary = Boundary.objects.create(region=section, version='t', geometry=geometry)
        section.save()
        PesticideUseRollup.objects.create(
            year=2023, month=8, county_id=9001, mtrs=section,
            lbs_chemical=lbs, applications=applications, records=applications,
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

    def test_a_school_run_by_the_district_elsewhere_is_still_run_by_it(self):
        # A charter this district runs but that stands in another district's
        # boundary: the FK points elsewhere, the CDS code doesn't.
        elsewhere = make_district('Fowler Unified', 'fowler-unified', '10621990000000',
            geometry=None)
        away_charter = Location.objects.create(
            type=Location.Type.PUBLIC_SCHOOL, name='Selma Charter Annex',
            external_id='annex', source='cde-public',
            metadata={'district_code': '1062117'},
            point=Point(-121.5, 38.5, srid=4326),
            school_district=elsewhere,
        )

        groups = places.schools_nearby(self.district, 2023)

        assert away_charter.pk in [row['location'].pk for row in groups['run_by']]
        assert away_charter.pk not in [row['location'].pk for row in groups['others']]

    def test_a_school_in_the_boundary_run_by_another_district_is_an_other(self):
        charter = self.make_location(
            'County Office Charter', type=Location.Type.PUBLIC_SCHOOL,
            source='cde-public', metadata={'district_code': '1062166'},
        )

        groups = places.schools_nearby(self.district, 2023)

        assert charter.pk in [row['location'].pk for row in groups['others']]
        assert charter.pk not in [row['location'].pk for row in groups['run_by']]

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
        entry = groups['others'][0]
        assert entry['location'] == self.away
        assert (entry['lbs'], entry['applications']) == (0, 0)
        assert entry['section_sqid'] is None and entry['section_mtrs'] is None
        assert entry['display_name'] == 'Away Child Care'
        assert entry['is_run_by'] is False

    def test_page_renders_one_table(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        html = response.content.decode()
        chapter = html.split('class="schools-nearby')[1]
        assert chapter.count('<table') == 1
        assert 'Schools &amp; child care in this district' in html
        assert 'Selma High' in html and 'Away Child Care' in html
        assert 'Public school' in html and 'Child care' in html
        assert reverse('pesticides:section-detail', kwargs={'sqid': Region.objects.get(pk=9101).sqid}) in html
        assert [row['lbs'] for row in response.context['schools']['rows']] == [695.0, 0]

    def test_the_section_column_links_by_its_mtrs(self):
        html = self.client.get(self.url).content.decode()
        assert '>MDM-T14S-R20E-01</a>' in html
        assert 'Section details' not in html

    def test_panel_titlecases_only_the_child_care_names(self):
        self.inside.name = 'Selma High'
        self.inside.city_name = 'Selma'
        self.inside.save()
        self.away.city_name = 'SELMA'
        self.away.save()
        cache.clear()
        html = self.client.get(self.url).content.decode()
        # CDSS shouts its names; CDE's are already properly cased.
        assert '<td>Away Child Care<span' in html
        assert 'AWAY CHILD CARE' not in html
        assert '<td>Selma High<span' in html

    def test_panel_leaves_a_shouted_cde_name_alone(self):
        self.inside.name = 'SELMA HIGH'
        self.inside.save()
        cache.clear()
        html = self.client.get(self.url).content.decode()
        assert '<td>SELMA HIGH<span' in html

    def test_count_line_reads_like_the_other_browsers(self):
        html = self.client.get(self.url).content.decode()
        assert 'summary-sentence' in html[:html.index('schools-table')]
        assert 'schools-count' not in html

    def test_the_city_column_is_dropped_when_every_site_shares_one(self):
        # The postal city is shouted in the CDSS directory and title-cased for
        # display, so the comparison has to be case-insensitive.
        self.inside.city_name = 'Selma'
        self.inside.save()
        self.away.city_name = 'SELMA'
        self.away.save()
        cache.clear()

        groups = places.schools_nearby(self.district, 2023)
        assert groups['show_city'] is False

        html = self.client.get(self.url).content.decode()
        assert '<td>Selma</td>' not in html

    def test_the_city_column_shows_when_the_sites_are_in_more_than_one(self):
        self.inside.city_name = 'Selma'
        self.inside.save()
        self.away.city_name = 'FOWLER'
        self.away.save()
        cache.clear()

        groups = places.schools_nearby(self.district, 2023)
        assert groups['show_city'] is True

        html = self.client.get(self.url).content.decode()
        assert '<td>Selma</td>' in html and '<td>Fowler</td>' in html

    def test_public_schools_name_the_district_that_runs_them(self):
        self.inside.metadata = {'district_code': '1062117', 'district_name': 'Selma Unified'}
        self.inside.save()
        cache.clear()
        html = self.client.get(self.url).content.decode()
        # Under the name, after what it is, linking the district's page.
        district_url = reverse('pesticides:region', kwargs={'sqid': self.district.sqid, 'slug': 'selma-unified'})
        assert f'<span class="school-kind">Public school · <a href="{district_url}">Selma Unified</a></span>' in html
        # Child care has no administering district: just what it is.
        assert '<span class="school-kind">Child care</span>' in html

    def test_panel_section_links_carry_the_scope(self):
        section_url = reverse('pesticides:section-detail', kwargs={'sqid': Region.objects.get(pk=9101).sqid})
        html = self.client.get(self.url, {'year': '2022', 'concern': '1'}).content.decode()
        assert f'{section_url}?year=2022&amp;narrow=concern' in html

    def make_many(self, count):
        for index in range(count):
            self.make_location(f'EXTRA CARE {index:02d}')
        cache.clear()

    def test_rows_past_a_page_go_to_the_next(self):
        self.make_many(50)  # 52 sites with the fixture's two
        response = self.client.get(self.url, {'schools_sort': 'name'})
        assert len(response.context['schools']['rows']) == 50
        assert response.context['is_paginated'] is True
        assert response.context['schools']['matched'] == 52
        html = response.content.decode()
        assert 'is-collapsed' not in html and 'Show the other' not in html
        assert 'page=2' in html and 'schools_sort=name' in html.split('page=2')[0].rsplit('href="', 1)[1]

        second = self.client.get(self.url, {'schools_sort': 'name', 'page': 2})
        assert len(second.context['schools']['rows']) == 2

    def test_filtering_resets_to_page_one(self):
        self.make_many(50)
        html = self.client.get(self.url, {'page': 2}).content.decode()
        form = html[html.index('schools-filters'):html.index('</form>', html.index('schools-filters'))]
        assert 'name="page"' not in form

    def test_bad_page_is_not_a_500(self):
        self.make_many(50)
        for page in ('99', 'nope', '-1'):
            response = self.client.get(self.url, {'page': page})
            assert response.status_code == 200, page
            assert response.context['schools']['rows'], page

    def test_pager_sits_after_the_table(self):
        self.make_many(50)
        html = self.client.get(self.url).content.decode()
        table_end = html.rindex('</table>')
        pager = html.index('class="pagination')
        assert table_end < pager
        assert '</div>' in html[table_end:pager]

    def test_one_page_has_no_pagination(self):
        response = self.client.get(self.url)
        assert response.context['is_paginated'] is False
        assert 'class="pagination' not in response.content.decode()

    def test_sorting_by_name(self):
        rows = self.client.get(self.url, {'schools_sort': 'name'}).context['schools']['rows']
        assert [row['display_name'] for row in rows] == ['Away Child Care', 'Selma High']

        rows = self.client.get(self.url, {'schools_sort': '-name'}).context['schools']['rows']
        assert [row['display_name'] for row in rows] == ['Selma High', 'Away Child Care']

    def test_sorting_by_type(self):
        rows = self.client.get(self.url, {'schools_sort': 'type'}).context['schools']['rows']
        assert [row['type_label'] for row in rows] == ['Child care', 'Public school']

    def test_sorting_by_city(self):
        self.inside.city_name = 'Selma'
        self.inside.save()
        self.away.city_name = 'FOWLER'
        self.away.save()
        cache.clear()
        rows = self.client.get(self.url, {'schools_sort': 'city'}).context['schools']['rows']
        assert [row['display_city'] for row in rows] == ['Fowler', 'Selma']

    def test_sorting_by_lbs_and_applications(self):
        for key, expected in (('lbs', [0, 695.0]), ('-lbs', [695.0, 0])):
            rows = self.client.get(self.url, {'schools_sort': key}).context['schools']['rows']
            assert [row['lbs'] for row in rows] == expected

        rows = self.client.get(self.url, {'schools_sort': 'applications'}).context['schools']['rows']
        assert [row['applications'] for row in rows] == [0, 6]

    def test_an_unknown_sort_falls_back_to_the_default(self):
        panel = self.client.get(self.url, {'schools_sort': 'lol'}).context['schools']
        assert panel['sort'] == '-lbs'
        assert [row['lbs'] for row in panel['rows']] == [695.0, 0]

    def test_the_name_search_filters_the_table(self):
        panel = self.client.get(self.url, {'schools_q': 'away'}).context['schools']
        assert [row['display_name'] for row in panel['rows']] == ['Away Child Care']
        assert panel['total'] == 2 and panel['matched'] == 1

    def test_the_type_filter_narrows_the_table(self):
        panel = self.client.get(self.url, {'schools_type': 'child_care'}).context['schools']
        assert [row['display_name'] for row in panel['rows']] == ['Away Child Care']

        # An unknown type is ignored rather than emptying the table.
        panel = self.client.get(self.url, {'schools_type': 'nope'}).context['schools']
        assert panel['type'] == '' and panel['matched'] == 2

    def test_the_run_by_filter_keeps_only_the_districts_own_schools(self):
        panel = self.client.get(self.url, {'schools_run_by': '1'}).context['schools']
        assert [row['display_name'] for row in panel['rows']] == ['Selma High']
        assert panel['run_by_only'] is True

    def test_filters_that_match_nothing_say_so(self):
        response = self.client.get(self.url, {'schools_q': 'zzz'})
        assert response.context['schools']['rows'] == []
        html = response.content.decode()
        assert 'No schools match.' in html
        assert 'Clear the filters' in html

    def test_the_filter_bar_counts_the_sites(self):
        html = self.client.get(self.url).content.decode()
        assert '2 schools and child care sites' in html
        assert '1 run by Selma Unified' in html

    def test_page_opens_with_the_school_markers_on(self):
        response = self.client.get(self.url)
        assert response.context['map_config']['show_locations'] == '1'
        html = response.content.decode()
        assert 'data-show-locations="1"' in html
        assert 'name="locations" checked' in html

    def test_a_district_with_demographics_but_no_addresses_says_so(self):
        Location.objects.all().delete()
        cache.clear()
        html = self.client.get(self.url).content.decode()
        assert "We don't have school or child care addresses for this district yet." in html
        assert '<table' not in html.split('class="schools-nearby')[1]

    def test_a_district_with_neither_says_so(self):
        Location.objects.all().delete()
        self.district.metadata = {}
        self.district.save()
        cache.clear()
        html = self.client.get(self.url).content.decode()
        assert 'No schools or child care on record here.' in html

    def test_schools_nearby_follows_the_concern_scope(self):
        # Section 9101's concern pounds only (170); the neighbouring
        # section's rollup row carries no chemical at all.
        assert [row['lbs'] for row in places.schools_nearby(self.district, 2023, concern=stats.NARROW_CONCERN)['run_by']] == [170.0]
        assert [row['lbs'] for row in places.schools_nearby(self.district, 2023)['run_by']] == [695.0]

    def test_demographics_strip(self):
        data = places.district_demographics(self.district)
        assert data['enrollment'] == 44091
        assert data['year'] == '2025-2026'
        assert data['year_label'] == 'CDE, 2025–26'
        assert [(m['label'], m['pct']) for m in data['metrics']] == [
            ('Hispanic/Latino', 42.4),
            ('English learners', 4.3),
            ('Low-income students', 53.9),
            ('Migrant students', 0.1),
        ]

    def test_demographics_strip_renders(self):
        html = self.client.get(self.url).content.decode()
        assert 'Who goes to school here' in html
        # A source stamp, not the scope year.
        assert 'CDE, 2025–26' in html
        assert '44,091' in html
        assert 'Low-income students' in html and '53.9%' in html
        assert 'Migrant students' in html and '0.1%' in html
        assert 'California Department of Education' in html
        assert 'https://www.cde.ca.gov/ds/si/ds/pubschls.asp' in html

    def test_a_whole_percent_loses_its_trailing_zero(self):
        self.district.metadata = {
            'enrollment': {'total': 100},
            'subgroups': {'migrant': {'pct': 54.0}},
        }
        self.district.save()
        cache.clear()
        html = self.client.get(self.url).content.decode()
        assert '54%' in html and '54.0%' not in html

    def test_demographics_strip_without_an_enrollment_total(self):
        self.district.metadata = {'subgroups': {'migrant': {'pct': 0.1}}}
        self.district.save()
        cache.clear()

        data = places.district_demographics(self.district)
        assert data['enrollment'] is None
        assert [m['label'] for m in data['metrics']] == ['Migrant students']

        html = self.client.get(self.url).content.decode()
        assert 'Who goes to school here' in html
        assert 'Migrant students' in html
        assert 'Students enrolled' not in html

    def test_demographics_year_is_blank_without_a_boundary(self):
        district = make_district('No Boundary Unified', 'no-boundary-unified',
            '10621990000000', geometry=None, enrollment={'total': 10})

        data = places.district_demographics(district)

        assert data['year'] == '' and data['year_label'] == ''

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

    def test_filters_sit_beside_the_map(self):
        from camp.apps.pesticides.tests.test_area_layout import side
        html = self.client.get(self.url).content.decode()
        assert 'schools-filters' in side(html)
        assert html.index('class="column tab-map"') < html.index('schools-table')


class PlaceConcernScopeTests(RollupTestMixin, TestCase):
    """Place pages follow the chemicals-of-concern scope like everything else."""

    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(pk=9001)

    def test_place_context_totals_narrow(self):
        area = places.region_area(self.fresno)
        ctx = places.place_context(area, 2023, concern=stats.NARROW_CONCERN)
        assert ctx['totals']['lbs'] == 170.0
        assert ctx['totals']['chemicals'] == 2
        assert [r.obj.name for r in ctx['top_chemicals']] == ['GLYPHOSATE', 'CHLORPYRIFOS']
        assert [(r['year'], r['lbs']) for r in ctx['by_year']] == [(2023, 170.0), (2022, 80.0)]
        assert ctx['map_config']['narrow'] == 'concern'
        assert 'narrow=concern' in ctx['records_url']

    def test_place_context_all_years_caches_separately(self):
        area = places.region_area(self.fresno)
        assert places.place_context(area, None, all_years=True, concern=stats.NARROW_CONCERN)['totals']['lbs'] == 250.0
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

        ctx = places.place_context(places.region_area(city), 2023, concern=stats.NARROW_CONCERN)
        assert ctx['upcoming_by_county'] == [{'county_name': 'Fresno County', 'count': 1}]
        assert ctx['upcoming_count'] == 1
        assert [n.pk for n in ctx['upcoming']] == [notice.pk]

    def test_region_page_follows_the_scope(self):
        url = reverse('pesticides:region', kwargs={'sqid': self.fresno.sqid, 'slug': 'fresno'})
        response = self.client.get(url, {'concern': '1'})
        assert response.context['totals']['lbs'] == 170.0
        assert response.context['concern'] == stats.NARROW_CONCERN

    def test_the_concern_card_drops_out_under_the_scope(self):
        # Every card is already of concern, so a dedicated one would just
        # restate the chemicals card -- which says what it now is instead.
        url = reverse('pesticides:region', kwargs={'sqid': self.fresno.sqid, 'slug': 'fresno'})

        response = self.client.get(url, {'concern': '1'})

        assert 'chemicals_of_concern_card' not in response.context
        assert 'top_chemicals_of_concern' not in response.context
        assert response.context['chemicals_card']['title'] == 'Top flagged chemicals'
        assert response.content.decode().count('class="card related-card"') == 3


class AreaSquareMilesTests(TestCase):
    """The denominator behind a place's per-square-mile rate."""

    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_a_region_measures_its_boundary(self):
        area = places.region_area(Region.objects.get(pk=9001))
        assert area.square_miles == Region.objects.get(pk=9001).boundary.area
        assert area.square_miles > 0

    def test_a_radius_measures_its_circle(self):
        area = places.point_area(36.71, -119.79, 5)
        assert area.square_miles == pytest.approx(math.pi * 25)

    def test_a_region_without_a_boundary_has_no_rate(self):
        Region.objects.filter(pk=9001).update(boundary=None)
        area = places.region_area(Region.objects.get(pk=9001))
        assert area.square_miles is None

    def test_the_section_count_is_not_used_as_the_area(self):
        # Sections overlap a boundary rather than tiling it, so counting
        # them would overstate anything smaller than a county.
        area = places.region_area(Region.objects.get(pk=9001))
        assert area.square_miles != len(area.section_pks)


class AreaTabTests(RollupTestMixin, TestCase):
    """A place page is a header and a tab row over Overview, Notices, Records, Schools and Community."""
    fixtures = ['pesticides-explorer']
    POINT = {'lat': 36.71, 'lng': -119.79, 'radius': 3, 'label': 'near Selma'}

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(pk=9001)

    def tab_url(self, tab):
        return self.fresno.get_pesticides_tab_url(tab)

    def tab_keys(self, response):
        return [tab['key'] for tab in response.context['tabs']]

    def test_every_region_tab_renders_under_the_same_header(self):
        for tab in ('overview', 'notices', 'records', 'community'):
            response = self.client.get(self.tab_url(tab))
            assert response.status_code == 200, tab
            html = response.content.decode()
            assert 'area-tabs' in html and '<h1 class="mb-1">Fresno County</h1>' in html, tab
            assert [t['key'] for t in response.context['tabs'] if t['current']] == [tab]

    def test_every_near_me_tab_renders_and_keeps_its_point(self):
        for name in ('near-me', 'near-me-notices', 'near-me-records', 'near-me-schools', 'near-me-community'):
            response = self.client.get(reverse(f'pesticides:{name}'), self.POINT)
            assert response.status_code == 200, name
            html = response.content.decode()
            assert 'near Selma' in html and 'Within 3 miles' in html, name
            for tab in response.context['tabs']:
                assert 'lat=36.71' in tab['url'] and 'label=near+Selma' in tab['url'], (name, tab['key'])

    def test_schools_is_offered_only_where_there_are_sites(self):
        assert 'schools' not in self.tab_keys(self.client.get(self.tab_url('overview')))
        Location.objects.create(
            type=Location.Type.PUBLIC_SCHOOL, name='Inside High', external_id='x-inside', source='cde-public',
            point=self.fresno.boundary.geometry.point_on_surface)
        cache.clear()
        response = self.client.get(self.tab_url('overview'))
        assert 'schools' in self.tab_keys(response)
        schools = self.client.get(self.tab_url('schools'))
        assert schools.status_code == 200
        assert [row['display_name'] for row in schools.context['schools']['rows']] == ['Inside High']
        # Not a district: no run-by filter.
        assert 'schools_run_by' not in schools.content.decode()

    def test_the_records_tab_is_narrowed_to_the_place(self):
        response = self.client.get(self.tab_url('records'))
        assert response.context['totals']['lbs'] == self.client.get(
            reverse('pesticides:records'), {'county': self.fresno.slug}).context['totals']['lbs']
        # The place isn't a filter to clear: it's the tab.
        assert response.context['active_filters'] == []

    def test_the_tabs_carry_the_scope(self):
        response = self.client.get(self.tab_url('notices'), {'year': 2022})
        assert all('year=2022' in tab['url'] for tab in response.context['tabs'])

    def test_a_wrong_slug_redirects_to_the_same_tab(self):
        url = reverse('pesticides:region-community', kwargs={'sqid': self.fresno.sqid, 'slug': 'nope'})
        response = self.client.get(url)
        assert response.status_code == 301 and response['Location'] == self.tab_url('community')

    def test_overview_heads_how_it_was_applied_with_its_year(self):
        html = self.client.get(self.tab_url('overview'), {'year': 2023}).content.decode()
        assert '<h2 class="title is-4">In 2023</h2>' in html
        assert html.index('In 2023') < html.index('How it was applied') < html.index('Over time')
        html = self.client.get(self.tab_url('overview'), {'year': 'all'}).content.decode()
        assert '<h2 class="title is-4">Across 2022–2023</h2>' in html

    def test_overview_points_to_the_notices_tab(self):
        html = self.client.get(self.tab_url('overview')).content.decode()
        assert self.tab_url('notices') in html
        assert 'class="within' not in html  # In and around moved to Community


class SchoolsTabMapTests(RollupTestMixin, TestCase):
    """The Schools tab's map: the place's own sites at any zoom, every section drawn."""
    fixtures = ['pesticides-explorer']

    def test_the_schools_tab_map_loads_the_place_and_draws_sections(self):
        cache.clear()
        fresno = Region.objects.get(pk=9001)
        Location.objects.create(
            type=Location.Type.PUBLIC_SCHOOL, name='Inside High', external_id='x-in', source='cde-public',
            point=fresno.boundary.geometry.point_on_surface)
        config = self.client.get(fresno.get_pesticides_tab_url('schools')).context['map_config']
        assert config['locations_area'] == f'region={fresno.sqid}'
        assert config['show_all_sections'] == '1' and config['show_locations'] == '1'
        # Not on the Overview.
        overview = self.client.get(fresno.get_pesticides_tab_url('overview')).context['map_config']
        assert overview['locations_area'] == '' and overview['show_all_sections'] == '0'

    def test_a_near_me_schools_map_loads_its_circle(self):
        cache.clear()
        config = self.client.get(reverse('pesticides:near-me-schools'), {'lat': 36.71, 'lng': -119.79, 'radius': 3}).context['map_config']
        assert config['locations_area'] == 'lat=36.71000&lng=-119.79000&radius=3'


class SchoolsTabFilterTests(RollupTestMixin, TestCase):
    """The Schools tab's district filter and its "School districts here" box."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(pk=9001)
        # Six overlapping districts, by enrollment: Alpha 600 ... Foxtrot 100.
        self.districts = [
            make_district(f'{name} Unified', f'{name.lower()}-unified', f'1062{index:03d}0000000', enrollment={'total': 600 - index * 100})
            for index, name in enumerate(('Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Foxtrot'))
        ]
        for index, district in enumerate(self.districts[:2]):
            Location.objects.create(
                type=Location.Type.PUBLIC_SCHOOL, name=f'School {index}', external_id=f'x-{index}', source='cde-public',
                point=Point(-119.79, 36.71, srid=4326),
                metadata={'district_code': district.external_id[:7], 'district_name': district.name})
        self.url = self.fresno.get_pesticides_tab_url('schools')

    def test_the_district_filter_narrows_the_table(self):
        response = self.client.get(self.url)
        options = [option['label'] for option in response.context['schools']['district_options']]
        assert options == ['Alpha Unified', 'Bravo Unified']  # only districts the sites are filed under
        narrowed = self.client.get(self.url, {'schools_district': self.districts[1].sqid})
        assert [row['display_name'] for row in narrowed.context['schools']['rows']] == ['School 1']
        assert narrowed.context['schools']['is_filtered']

    def test_an_unknown_district_is_ignored(self):
        response = self.client.get(self.url, {'schools_district': 'nope'})
        assert len(response.context['schools']['rows']) == 2 and not response.context['schools']['is_filtered']

    def test_the_districts_box_shows_the_largest_five_in_name_order(self):
        response = self.client.get(self.url)
        districts = response.context['school_districts']
        assert [d['name'] for d in districts] == [f'{n} Unified' for n in ('Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Foxtrot')]
        assert [d['name'] for d in districts if d['is_collapsed']] == ['Foxtrot Unified']
        html = response.content.decode()
        assert 'School districts here' in html and 'Show all 6' in html

    def test_a_districts_own_page_has_neither(self):
        district = self.districts[0]
        response = self.client.get(district.get_pesticides_tab_url('schools'))
        assert response.context['school_districts'] == []
        assert 'id_schools_district' not in response.content.decode()
