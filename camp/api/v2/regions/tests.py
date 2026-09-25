import pytest

from django.contrib.gis.geos import GEOSGeometry
from django.test import TestCase, RequestFactory
from django.urls import reverse

from camp.api.v2.regions.endpoints import RegionDetail, RegionGeoJSON, RegionList, RegionMetaEndpoint
from camp.apps.regions.models import Boundary, Region
from camp.utils.test import get_response_data

region_list = RegionList.as_view()
region_detail = RegionDetail.as_view()
region_meta = RegionMetaEndpoint.as_view()
region_geojson = RegionGeoJSON.as_view()

pytestmark = [
    pytest.mark.django_db(transaction=True),
]


class RegionListTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.factory = RequestFactory()

    def test_list_returns_200(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'))
        response = region_list(request)
        assert response.status_code == 200

    def test_list_fields(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'))
        response = region_list(request)
        data = get_response_data(response)
        assert len(data['data']) > 0
        assert set(data['data'][0].keys()) == {'id', 'name', 'slug', 'type', 'boundary'}

    def test_filter_by_type(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'), {'type': 'county'})
        response = region_list(request)
        data = get_response_data(response)
        assert all(r['type'] == 'county' for r in data['data'])

    def test_filter_by_invalid_type_returns_empty(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'), {'type': 'nonexistent'})
        response = region_list(request)
        data = get_response_data(response)
        assert data['data'] == []

    def test_filter_by_name(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'), {'name': 'fresno'})
        response = region_list(request)
        data = get_response_data(response)
        assert len(data['data']) > 0
        assert all('fresno' in r['name'].lower() for r in data['data'])

    def test_filter_by_slug(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'), {'slug': 'fresno'})
        response = region_list(request)
        data = get_response_data(response)
        assert len(data['data']) > 0
        assert all(r['slug'] == 'fresno' for r in data['data'])


class RegionMetaTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _fetch_region_meta(self):
        url = reverse('api:v2:regions:region-meta')
        request = self.factory.get(url)
        response = region_meta(request)
        return response, get_response_data(response)

    def test_returns_200(self):
        response, content = self._fetch_region_meta()
        assert response.status_code == 200

    def test_includes_every_region_type(self):
        response, content = self._fetch_region_meta()
        assert set(content['data']['types'].keys()) == set(Region.Type.values)

    def test_type_fields(self):
        response, content = self._fetch_region_meta()
        county = content['data']['types']['county']
        assert county == {
            'type': 'county',
            'label': 'County',
            'category': 'administrative',
        }

    def test_category_matches_model_mapping(self):
        response, content = self._fetch_region_meta()
        for region_type, category in Region.TYPE_CATEGORIES.items():
            assert content['data']['types'][region_type]['category'] == category.value


class RegionDetailTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.region = Region.objects.filter(boundary__isnull=False).first()

    def test_detail_returns_200(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.sqid)
        assert response.status_code == 200

    def test_detail_has_geometry(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.sqid)
        data = get_response_data(response)
        assert data['data']['boundary'] is not None
        assert data['data']['boundary']['geometry'] is not None

    def test_detail_has_bbox(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.sqid)
        data = get_response_data(response)
        bbox = data['data']['boundary']['bbox']
        assert bbox == list(self.region.boundary.geometry.extent)

    def test_detail_fields(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.sqid)
        data = get_response_data(response)
        assert set(data['data'].keys()) == {'id', 'name', 'slug', 'type', 'boundary'}



def make_place(name, slug, geom_wkt):
    region = Region.objects.create(name=name, slug=slug, type=Region.Type.PLACE)
    boundary = Boundary.objects.create(
        region=region,
        version='2020',
        geometry=GEOSGeometry(geom_wkt, srid=4326),
    )
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


def make_city(name, slug, geom_wkt):
    region = Region.objects.create(name=name, slug=slug, type=Region.Type.CITY)
    boundary = Boundary.objects.create(
        region=region,
        version='2020',
        geometry=GEOSGeometry(geom_wkt, srid=4326),
    )
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


def make_county(name, geom_wkt):
    region = Region.objects.create(name=name, slug=name.lower().replace(' ', '-'), type=Region.Type.COUNTY)
    boundary = Boundary.objects.create(
        region=region,
        version='2020',
        geometry=GEOSGeometry(geom_wkt, srid=4326),
    )
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


def make_tract(name, geom_wkt):
    region = Region.objects.create(name=name, slug=name.lower().replace(' ', '-'), type=Region.Type.TRACT)
    boundary = Boundary.objects.create(
        region=region,
        version='2020',
        geometry=GEOSGeometry(geom_wkt, srid=4326),
    )
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


FRESNO_PLACE_WKT = 'MULTIPOLYGON(((-119.9 36.7, -119.7 36.7, -119.7 36.9, -119.9 36.9, -119.9 36.7)))'
CLOVIS_CITY_WKT = 'MULTIPOLYGON(((-119.83 36.75, -119.73 36.75, -119.73 36.85, -119.83 36.85, -119.83 36.75)))'
FRESNO_COUNTY_WKT = 'MULTIPOLYGON(((-120.5 36.5, -119.0 36.5, -119.0 37.5, -120.5 37.5, -120.5 36.5)))'
KERN_COUNTY_WKT = 'MULTIPOLYGON(((-119.5 34.5, -118.0 34.5, -118.0 35.5, -119.5 35.5, -119.5 34.5)))'
FRESNO_TRACT_WKT = 'MULTIPOLYGON(((-120.2 36.8, -120.0 36.8, -120.0 37.0, -120.2 37.0, -120.2 36.8)))'
KERN_TRACT_WKT = 'MULTIPOLYGON(((-119.2 34.8, -119.0 34.8, -119.0 35.0, -119.2 35.0, -119.2 34.8)))'
ELSEWHERE_WKT = 'MULTIPOLYGON(((-116.0 33.0, -115.8 33.0, -115.8 33.2, -116.0 33.2, -116.0 33.0)))'


class TestPlaceSearch(TestCase):
    def setUp(self):
        self.fresno = make_place('Fresno', 'fresno', FRESNO_PLACE_WKT)
        self.clovis = make_city('Clovis', 'clovis', CLOVIS_CITY_WKT)
        self.url = reverse('api:v2:regions:place-search')

    def test_returns_list(self):
        response = self.client.get(self.url, {'q': 'Fresno'})
        assert response.status_code == 200
        assert isinstance(response.json()['data'], list)

    def test_matches_by_name(self):
        response = self.client.get(self.url, {'q': 'Fresno'})
        names = [r['name'] for r in response.json()['data']]
        assert 'Fresno' in names

    def test_case_insensitive(self):
        response = self.client.get(self.url, {'q': 'fresno'})
        names = [r['name'] for r in response.json()['data']]
        assert 'Fresno' in names

    def test_type_filter_scopes_results(self):
        response = self.client.get(self.url, {'q': 'Clovis', 'type': 'city'})
        data = response.json()['data']
        assert len(data) == 1
        assert data[0]['name'] == 'Clovis'
        assert data[0]['type'] == 'city'

    def test_type_filter_excludes_other_types(self):
        response = self.client.get(self.url, {'q': 'Fresno', 'type': 'city'})
        names = [r['name'] for r in response.json()['data']]
        assert 'Fresno' not in names

    def test_no_match_returns_empty_list(self):
        response = self.client.get(self.url, {'q': 'nonexistent'})
        assert response.status_code == 200
        assert response.json()['data'] == []

    def test_empty_query_returns_empty_list(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json()['data'] == []


class TestPlaceLookup(TestCase):
    def setUp(self):
        self.fresno = make_place('Fresno', 'fresno', FRESNO_PLACE_WKT)
        self.url = reverse('api:v2:regions:place-lookup')

    def test_exact_match(self):
        response = self.client.get(self.url, {'q': 'Fresno'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Fresno'
        assert response.json()['data']['type'] == Region.Type.PLACE

    def test_case_insensitive(self):
        response = self.client.get(self.url, {'q': 'fresno'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Fresno'

    def test_fuzzy_match(self):
        response = self.client.get(self.url, {'q': 'Fresnoo'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Fresno'

    def test_city_resolves_to_containing_place(self):
        make_city('Clovis', 'clovis', CLOVIS_CITY_WKT)
        response = self.client.get(self.url, {'q': 'Clovis'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Fresno'

    def test_type_returns_direct_match_not_place(self):
        make_city('Clovis', 'clovis', CLOVIS_CITY_WKT)
        response = self.client.get(self.url, {'q': 'Clovis', 'type': 'city'})
        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Clovis'
        assert response.json()['data']['type'] == 'city'

    def test_no_match_returns_null(self):
        response = self.client.get(self.url, {'q': 'nonexistent'})
        assert response.status_code == 200
        assert response.json()['data'] is None

    def test_empty_query_returns_null(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json()['data'] is None

    def test_response_includes_boundary_geometry(self):
        response = self.client.get(self.url, {'q': 'Fresno'})
        assert response.status_code == 200
        boundary = response.json()['data']['boundary']
        assert boundary is not None
        assert boundary['geometry']['type'] == 'MultiPolygon'


class RegionGeoJSONTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.url = reverse('api:v2:regions:region-geojson')

    def get(self, params):
        response = region_geojson(RequestFactory().get(self.url, params))
        return response, get_response_data(response)

    def test_route_is_not_read_as_a_region_id(self):
        assert self.url == '/api/2.0/regions/geojson/'

    def test_counties_as_a_feature_collection(self):
        response, data = self.get({'type': 'county'})
        assert response.status_code == 200
        assert data['type'] == 'FeatureCollection'
        counties = Region.objects.filter(type=Region.Type.COUNTY).exclude(boundary=None)
        assert len(data['features']) == counties.count() > 0
        feature = data['features'][0]
        assert feature['type'] == 'Feature'
        assert feature['id'] == feature['properties']['id']
        assert set(feature['properties']) == {'id', 'name', 'slug', 'type'}
        assert feature['properties']['type'] == 'county'
        assert feature['geometry']['type'] == 'MultiPolygon'
        names = [f['properties']['name'] for f in data['features']]
        assert names == sorted(names)

    def test_coordinates_are_rounded(self):
        _, data = self.get({'type': 'county'})
        ring = data['features'][0]['geometry']['coordinates'][0][0]
        assert all(round(value, 5) == value for point in ring for value in point)

    def test_filters_are_the_region_lists(self):
        _, data = self.get({'type': 'county', 'slug': 'fresno'})
        assert [f['properties']['slug'] for f in data['features']] == ['fresno']

    def test_regions_without_a_boundary_are_left_out(self):
        Region.objects.create(name='Boundless County', slug='boundless', type=Region.Type.COUNTY)
        _, data = self.get({'type': 'county'})
        assert 'boundless' not in [f['properties']['slug'] for f in data['features']]

    def test_type_is_required(self):
        # Unfiltered, this would be every region in the database: thousands
        # of square-mile sections among them.
        response, data = self.get({})
        assert response.status_code == 400
        assert 'type' in str(data)

    def test_retired_tracts_are_left_out(self):
        current = make_tract('Tract 2020', FRESNO_TRACT_WKT)
        retired = make_tract('Tract 2010', KERN_TRACT_WKT)
        retired.boundary.version = '2010'
        retired.boundary.save(update_fields=['version'])
        _, data = self.get({'type': 'tract'})
        slugs = {f['properties']['slug'] for f in data['features']}
        assert current.slug in slugs and retired.slug not in slugs

    def test_simplified_shapes_share_their_borders(self):
        # Two tracts sharing the edge x = -120.1: simplified together, the
        # shared edge must come out identical on both sides (no gap, no
        # doubled line), and the result is lighter than the input.
        left = 'MULTIPOLYGON(((-120.2 36.8, -120.1 36.8, ' + ', '.join(
            f'-120.1 {36.8 + i * 0.0001:.4f}' for i in range(1, 2000)) + ', -120.1 37.0, -120.2 37.0, -120.2 36.8)))'
        right = 'MULTIPOLYGON(((-120.1 36.8, -120.0 36.8, -120.0 37.0, -120.1 37.0, ' + ', '.join(
            f'-120.1 {37.0 - i * 0.0001:.4f}' for i in range(1, 2000)) + ', -120.1 36.8)))'
        make_tract('Left', left)
        make_tract('Right', right)
        _, data = self.get({'type': 'tract', 'simplify': '1'})
        rings = {f['properties']['slug']: f['geometry']['coordinates'][0][0] for f in data['features']}
        on_edge = lambda ring: sorted({tuple(p) for p in ring if p[0] == -120.1})
        assert on_edge(rings['left']) == on_edge(rings['right'])
        assert len(rings['left']) < 100

    def test_simplified_keeps_the_filters(self):
        _, data = self.get({'type': 'county', 'slug': 'fresno', 'simplify': '1'})
        assert [f['properties']['slug'] for f in data['features']] == ['fresno']
        assert data['features'][0]['geometry']['type'] == 'MultiPolygon'


class RegionWithinFilterTests(TestCase):
    def setUp(self):
        self.parent_a = make_county('Fresno County', FRESNO_COUNTY_WKT)
        self.parent_b = make_county('Kern County', KERN_COUNTY_WKT)
        self.inside_a = make_tract('Tract inside Fresno', FRESNO_TRACT_WKT)
        self.inside_b = make_tract('Tract inside Kern', KERN_TRACT_WKT)
        self.outside = make_tract('Tract elsewhere', ELSEWHERE_WKT)

    def _ids(self, *params):
        request = RequestFactory().get('/', list(params))
        response = region_list(request)
        assert response.status_code == 200
        data = get_response_data(response)
        return {r['id'] for r in data['data']}

    def test_within_single_parent_narrows_to_contained_regions(self):
        ids = self._ids(('type', 'tract'), ('within', self.parent_a.sqid))
        assert ids == {self.inside_a.sqid}

    def test_within_multiple_parents_unions_geometries(self):
        ids = self._ids(('type', 'tract'), ('within', self.parent_a.sqid), ('within', self.parent_b.sqid))
        assert ids == {self.inside_a.sqid, self.inside_b.sqid}

    def test_within_unknown_id_returns_nothing(self):
        # Nothing can be inside a parent that doesn't exist. Falling back to
        # the unnarrowed list would hand back every region in the database.
        ids = self._ids(('type', 'tract'), ('within', 'not-a-real-sqid'))
        assert ids == set()

    def test_within_parent_without_boundary_returns_nothing(self):
        no_boundary = Region.objects.create(name='Boundless', slug='boundless', type=Region.Type.COUNTY)
        ids = self._ids(('type', 'tract'), ('within', no_boundary.sqid))
        assert ids == set()

    def test_within_blank_value_is_ignored(self):
        ids = self._ids(('type', 'tract'), ('within', ''))
        assert ids == {self.inside_a.sqid, self.inside_b.sqid, self.outside.sqid}

    def test_no_within_param_returns_unnarrowed_list(self):
        ids = self._ids(('type', 'tract'))
        assert ids == {self.inside_a.sqid, self.inside_b.sqid, self.outside.sqid}

    def test_within_excludes_a_region_that_only_touches_the_border(self):
        # Shares the exact edge (x=-119.0) with FRESNO_COUNTY_WKT's eastern
        # boundary but has zero interior overlap with it. ST_Intersects (plain
        # `.intersects()`) matches boundary-only touching, which `within=`
        # must not treat as "inside" the selected parent region.
        touching_neighbor = make_tract(
            'Tract touching Fresno border',
            'MULTIPOLYGON(((-119.0 36.8, -118.8 36.8, -118.8 37.0, -119.0 37.0, -119.0 36.8)))',
        )
        ids = self._ids(('type', 'tract'), ('within', self.parent_a.sqid))
        assert ids == {self.inside_a.sqid}
        assert touching_neighbor.sqid not in ids

    def test_within_excludes_a_neighbor_overlapping_by_a_sliver(self):
        # Real tract/ZIP boundaries come from different sources than county
        # boundaries and overlap neighbors by hairline slivers - genuine area,
        # so NOT ST_Touches doesn't help. This 0.2 x 0.2 tract pokes 0.0001
        # (0.05% of its area) across Fresno's eastern edge at x=-119.0; the
        # real-world case is a Kings/Madera/Tulare tract along the county line.
        sliver_neighbor = make_tract(
            'Tract overlapping Fresno by a sliver',
            'MULTIPOLYGON(((-119.0001 36.8, -118.8001 36.8, -118.8001 37.0, -119.0001 37.0, -119.0001 36.8)))',
        )
        ids = self._ids(('type', 'tract'), ('within', self.parent_a.sqid))
        assert ids == {self.inside_a.sqid}
        assert sliver_neighbor.sqid not in ids

    def test_within_excludes_a_region_that_only_partially_overlaps(self):
        # Straddles FRESNO_COUNTY_WKT's eastern boundary (x=-119.0) with
        # substantial area on both sides (roughly half inside, half outside)
        # - the real-world case is a congressional district crossing a
        # county line: it genuinely intersects Fresno County, but it is not
        # *within* it, so within= must exclude it too.
        straddling_district = make_tract(
            'District straddling Fresno border',
            'MULTIPOLYGON(((-119.3 36.8, -118.7 36.8, -118.7 37.0, -119.3 37.0, -119.3 36.8)))',
        )
        ids = self._ids(('type', 'tract'), ('within', self.parent_a.sqid))
        assert ids == {self.inside_a.sqid}
        assert straddling_district.sqid not in ids

    def test_within_includes_a_region_poking_a_sliver_outside(self):
        # The mirror of the sliver-neighbor case: a tract that is
        # unambiguously inside Fresno but whose boundary disagrees with the
        # county's by a hairline, poking 0.0001 (0.05% of its area) past the
        # county line at x=-119.0. Strict ST_Within would drop it; on real
        # data that loses ~15% of a county's tracts.
        sliver_out = make_tract(
            'Tract inside Fresno poking out',
            'MULTIPOLYGON(((-119.2 36.8, -118.9999 36.8, -118.9999 37.0, -119.2 37.0, -119.2 36.8)))',
        )
        ids = self._ids(('type', 'tract'), ('within', self.parent_a.sqid))
        assert ids == {self.inside_a.sqid, sliver_out.sqid}
