from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import TestCase

from camp.apps.regions.headers import point_kind, region_header
from camp.apps.regions.models import Boundary, Region


def square(west, south, size=0.1):
    return MultiPolygon(Polygon.from_bbox((west, south, west + size, south + size)), srid=4326)


def make(name, kind, geometry, **metadata):
    region = Region.objects.create(name=name, slug=f'{name.lower()}-{kind}', type=kind, external_id=f'{name}-{kind}', metadata=metadata)
    region.boundary = Boundary.objects.create(region=region, version='t', geometry=geometry)
    region.save()
    return region


class RegionHeaderTests(TestCase):
    """The area header's gray line and links, the same in both explorers."""

    def setUp(self):
        self.county = make('Fresno County', Region.Type.COUNTY, square(-120.0, 36.0, 1), population=1016725)
        self.city = make('Selma', Region.Type.CITY, square(-119.6, 36.5), population=24674.4)
        self.urban = make('Selma', Region.Type.URBAN_AREA, square(-119.6, 36.5))

    def header(self, region, **kwargs):
        return region_header(region, url_method='get_pesticides_tab_url', **kwargs)

    def test_a_county_leaves_out_its_type(self):
        header = self.header(self.county)
        assert header['kind'] == '1,016,725 people'
        assert header['county'] is None

    def test_type_county_and_population(self):
        header = self.header(self.city)
        assert header['kind'] == 'City · Fresno County · 24,674 people'
        assert header['county'] == self.county

    def test_no_population_no_figure(self):
        assert self.header(self.urban)['kind'] == 'Urban area · Fresno County'

    def test_the_switch_keeps_the_tab_and_scope(self):
        links = self.header(self.city, tab='notices', scope_qs='?year=2022')['header_links']
        assert links == [{'label': 'Switch to urban area', 'internal': True,
                          'url': f"{self.urban.get_pesticides_tab_url('notices')}?year=2022"}]
        links = self.header(self.urban)['header_links']
        assert links == [{'label': 'Switch to city limits', 'internal': True, 'url': self.city.get_pesticides_tab_url('overview')}]

    def test_ab617_year_and_links(self):
        community = make('South Central Fresno', Region.Type.AB617_COMMUNITY, square(-119.8, 36.6),
                         cerp_selected_year=2017, community_url='https://valleyair.org/x', storymaps_url='https://arcg.is/y')
        header = self.header(community)
        assert header['kind'] == 'AB 617 Community · selected by CARB in 2017 · Fresno County'
        assert header['header_links'] == [
            {'label': 'Community page', 'url': 'https://valleyair.org/x'},
            {'label': 'CARB story map', 'url': 'https://arcg.is/y'},
        ]

    def test_point_kind(self):
        assert point_kind(1) == 'Within 1 mile' and point_kind(3) == 'Within 3 miles'
