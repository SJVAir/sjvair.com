from unittest import mock

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import TestCase

from camp.apps.regions import schools
from camp.apps.regions.models import Location, Region
from camp.apps.regions.tests.test_locations import make_district

# The fixture's districts all share Selma's square (-119.8 36.7 -> -119.7 36.8
# or thereabouts); a point inside it, buffered, is the "circle" case.
INSIDE = Point(-119.79, 36.71, srid=4326)
EMISSIONS = lambda self: f'/emissions/{self.slug}/'


class SchoolsTestCase(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        # Region has no get_emissions_url on this branch; stand one in so the
        # url_method plumbing is exercised with a second, different method.
        patch = mock.patch.object(Region, 'get_emissions_url', EMISSIONS, create=True)
        patch.start()
        self.addCleanup(patch.stop)


class DistrictUrlsTests(SchoolsTestCase):
    def setUp(self):
        super().setUp()
        self.selma = make_district('Selma Unified', 'selma-unified', '10621170000000')

    def test_keyed_by_cde_code_and_by_name(self):
        districts = schools.district_urls(url_method='get_pesticides_url')
        assert districts['1062117'] == districts['name:Selma Unified']
        assert districts['1062117']['sqid'] == self.selma.sqid
        assert districts['1062117']['name'] == 'Selma Unified'

    def test_url_comes_from_the_named_method(self):
        pesticides = schools.district_urls(url_method='get_pesticides_url')['1062117']['url']
        emissions = schools.district_urls(url_method='get_emissions_url')['1062117']['url']
        assert pesticides == self.selma.get_pesticides_url()
        assert emissions == '/emissions/selma-unified/'


class AreaDistrictsTests(SchoolsTestCase):
    def setUp(self):
        super().setUp()
        self.districts = [
            make_district(f'{name} Unified', f'{name.lower()}-unified', f'1062{index:03d}0000000',
                enrollment={'total': 600 - index * 100})
            for index, name in enumerate(('Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Foxtrot'))
        ]
        self.fresno = Region.objects.get(pk=9001)

    def call(self, geometry, key='t', url_method='get_pesticides_url'):
        return schools.area_districts(geometry, cache_key=key, url_method=url_method)

    def test_region_geometry_lists_overlapping_districts_in_name_order(self):
        rows = self.call(self.fresno.boundary.geometry)
        assert [d['name'] for d in rows] == [f'{n} Unified' for n in ('Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Foxtrot')]
        assert rows[0]['url'] == self.districts[0].get_pesticides_url()
        assert rows[0]['sqid'] == self.districts[0].sqid
        assert rows[0]['enrollment'] == 600

    def test_all_but_the_five_largest_are_collapsed(self):
        rows = self.call(self.fresno.boundary.geometry)
        assert [d['name'] for d in rows if d['is_collapsed']] == ['Foxtrot Unified']

    def test_a_circle_works_too(self):
        circle = INSIDE.buffer(0.001)
        rows = self.call(circle)
        # The circle is a sliver of each district: under the overlap floor.
        assert rows == []
        wide = INSIDE.buffer(0.05)
        assert len(self.call(wide, key='wide')) == 6

    def test_url_method_and_cache_key(self):
        geometry = self.fresno.boundary.geometry
        rows = self.call(geometry, key='emissions', url_method='get_emissions_url')
        assert rows[0]['url'] == '/emissions/alpha-unified/'
        # The caller's key is the cache identity: same key, same (cached) answer.
        assert self.call(geometry, key='emissions') == rows
        assert cache.get('emissions') == rows


class DistrictFieldsTests(SchoolsTestCase):
    def setUp(self):
        super().setUp()
        self.selma = make_district('Selma Unified', 'selma-unified', '10621170000000')
        self.other = make_district('Other Unified', 'other-unified', '10621180000000')
        self.lookup = schools.district_urls(url_method='get_pesticides_url')

    def location(self, containing=None, **metadata):
        return Location(type=Location.Type.PUBLIC_SCHOOL, name='X', point=INSIDE,
            metadata=metadata, school_district=containing)

    def fields(self, location):
        return schools.district_fields(location, self.lookup, url_method='get_pesticides_url')

    def test_by_code(self):
        fields = self.fields(self.location(self.other, district_code='1062117', district_name='Whatever'))
        assert fields == {'run_by_url': self.selma.get_pesticides_url(),
            'district_sqid': self.selma.sqid, 'district_name': 'Selma Unified'}

    def test_by_containing_district_when_the_names_agree(self):
        lookup = {}
        fields = schools.district_fields(self.location(self.selma, district_name='Selma Unified'),
            lookup, url_method='get_emissions_url')
        assert fields['run_by_url'] == '/emissions/selma-unified/'
        assert fields['district_sqid'] == self.selma.sqid

    def test_by_name(self):
        fields = self.fields(self.location(self.selma, district_name='Other Unified'))
        assert fields['run_by_url'] == self.other.get_pesticides_url()
        assert fields['district_name'] == 'Other Unified'

    def test_falls_back_to_the_containing_district(self):
        fields = self.fields(self.location(self.selma))
        assert fields == {'run_by_url': None, 'district_sqid': self.selma.sqid, 'district_name': 'Selma Unified'}

    def test_no_district_at_all(self):
        fields = self.fields(self.location())
        assert fields == {'run_by_url': None, 'district_sqid': None, 'district_name': ''}


class DisplayNameTests(TestCase):
    def test_only_cdss_child_care_is_title_cased(self):
        shouted = Location(source='cdss-ccl')
        kept = Location(source='cde-public')
        assert schools.display_name(shouted, 'SELMA HIGH') == 'Selma High'
        assert schools.display_name(kept, 'SELMA HIGH') == 'SELMA HIGH'

    def test_title_case_name(self):
        assert schools.title_case_name("CHILDREN'S CENTER #2") == "Children's Center #2"
        assert schools.title_case_name('McKinley Elementary') == 'McKinley Elementary'
        assert schools.title_case_name(None) == ''


class TemplateTests(TestCase):
    def test_name_cell_with_a_linked_run_by(self):
        html = render_to_string('regions/includes/school-name-cell.html', {
            'row': {'display_name': 'Selma High', 'type_label': 'Public school',
                'run_by_name': 'Selma Unified', 'run_by_url': '/d/'},
            'scope_qs': '?year=2023',
        })
        assert html == ('Selma High<span class="school-kind">Public school · '
            '<a href="/d/?year=2023">Selma Unified</a></span>')

    def test_name_cell_with_an_unlinked_or_missing_run_by(self):
        row = {'display_name': 'Kids', 'type_label': 'Child care', 'run_by_name': 'Some COE', 'run_by_url': None}
        html = render_to_string('regions/includes/school-name-cell.html', {'row': row})
        assert '<span class="school-kind">Child care · Some COE</span>' in html
        row['run_by_name'] = ''
        html = render_to_string('regions/includes/school-name-cell.html', {'row': row})
        assert '<span class="school-kind">Child care</span>' in html

    def test_districts_box(self):
        context = {
            'school_districts': [
                {'name': 'Alpha Unified', 'url': '/a/', 'is_collapsed': False},
                {'name': 'Zulu Unified', 'url': '/z/', 'is_collapsed': True},
            ],
            'districts_hidden': 1,
            'scope_qs': '?year=2023',
        }
        html = render_to_string('regions/includes/school-districts-box.html', context)
        assert 'School districts here' in html
        assert '<li><a href="/a/?year=2023">Alpha Unified</a></li>' in html
        assert '<li class="is-collapsed"><a href="/z/?year=2023">Zulu Unified</a></li>' in html
        assert 'Show all 2' in html

    def test_districts_box_renders_nothing_without_districts(self):
        html = render_to_string('regions/includes/school-districts-box.html', {'school_districts': []})
        assert 'school-districts-box' not in html
