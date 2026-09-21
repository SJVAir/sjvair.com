from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from camp.apps.regions.models import Boundary, Location, Region


SELMA_SQUARE = 'SRID=4326;MULTIPOLYGON (((-119.85 36.65, -119.75 36.65, -119.75 36.75, -119.85 36.75, -119.85 36.65)))'


def make_district(name, slug, external_id, geometry=SELMA_SQUARE, **metadata):
    region = Region.objects.create(
        name=name,
        slug=slug,
        type=Region.Type.SCHOOL_DISTRICT,
        external_id=external_id,
        metadata=metadata,
    )
    region.boundary = Boundary.objects.create(region=region, version='t', geometry=geometry)
    region.save()
    return region


class LocationTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        # Inside the fixture's Fresno County square (-120.5 36.0 → -119.0 37.0)
        self.inside = Point(-119.79, 36.71, srid=4326)
        # Well outside both county squares
        self.outside = Point(-121.5, 38.5, srid=4326)

    def test_create_location_gets_a_sqid(self):
        location = Location.objects.create(
            type=Location.Type.PUBLIC_SCHOOL,
            name='Selma High',
            external_id='10621170000000',
            source='cde-public',
            city='Selma',
            point=self.inside,
        )
        location.refresh_from_db()
        assert location.sqid
        assert str(location) == 'Selma High'

    def test_county_for_returns_the_containing_county(self):
        assert Location.county_for(self.inside) == Region.objects.get(pk=9001)

    def test_county_for_returns_none_outside_any_county(self):
        assert Location.county_for(self.outside) is None

    def test_district_for_prefers_the_cds_code_prefix(self):
        match = make_district('Selma Unified', 'selma-unified', '10621170000000')
        make_district('Fowler Unified', 'fowler-unified', '10621250000000')
        # The point isn't in any district boundary, so only the code can match.
        assert Location.district_for(self.outside, cds_code='10621176059453') == match

    def test_district_for_falls_back_to_the_containing_boundary(self):
        district = make_district('Selma Unified', 'selma-unified', '10621170000000')
        assert Location.district_for(self.inside) == district

    def test_district_for_prefers_unified_over_elementary(self):
        # The elementary district carries the wider span here, so only the
        # "Unified" preference can explain picking the unified one.
        make_district('Selma Elementary', 'selma-elementary', '10621180000000',
            grade_low='P', grade_high='12')
        unified = make_district('Selma Unified', 'selma-unified', '10621170000000',
            grade_low='K', grade_high='12')
        assert Location.district_for(self.inside) == unified

    def test_district_for_prefers_the_widest_grade_span(self):
        make_district('Selma Elementary', 'selma-elementary', '10621180000000',
            grade_low='K', grade_high='6')
        widest = make_district('Selma Joint', 'selma-joint', '10621190000000',
            grade_low='P', grade_high='12')
        assert Location.district_for(self.inside) == widest

    def test_district_for_returns_none_when_nothing_contains_the_point(self):
        make_district('Selma Unified', 'selma-unified', '10621170000000')
        assert Location.district_for(self.outside) is None

    def test_short_type(self):
        assert Location(type=Location.Type.PUBLIC_SCHOOL).short_type == 'Public school'
        assert Location(type=Location.Type.PRIVATE_SCHOOL).short_type == 'Private school'
        assert Location(type=Location.Type.CHILD_CARE).short_type == 'Child care'

    def test_get_absolute_url_is_the_districts_page(self):
        district = make_district('Selma Unified', 'selma-unified', '10621170000000')
        location = Location.objects.create(
            type=Location.Type.PUBLIC_SCHOOL,
            name='Selma High',
            external_id='10621176059453',
            source='cde-public',
            point=self.inside,
            district=district,
        )
        assert location.get_absolute_url() == reverse('pesticides:region',
            kwargs={'sqid': district.sqid, 'slug': district.slug})

    def test_get_absolute_url_is_empty_without_a_district(self):
        location = Location.objects.create(
            type=Location.Type.CHILD_CARE,
            name='Little Sprouts',
            external_id='100400001',
            source='cdss-ccl',
            point=self.inside,
        )
        assert location.get_absolute_url() == ''
