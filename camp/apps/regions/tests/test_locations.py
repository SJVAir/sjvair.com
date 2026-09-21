from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from camp.apps.regions.models import Boundary, Location, Region


SELMA_SQUARE = 'SRID=4326;MULTIPOLYGON (((-119.85 36.65, -119.75 36.65, -119.75 36.75, -119.85 36.75, -119.85 36.65)))'
# A smaller square inside SELMA_SQUARE, for the city/CDP/ZIP regions.
TOWN_SQUARE = 'SRID=4326;MULTIPOLYGON (((-119.82 36.68, -119.76 36.68, -119.76 36.74, -119.82 36.74, -119.82 36.68)))'


def make_region(type, name, slug, external_id, geometry=None, **metadata):
    region = Region.objects.create(
        name=name,
        slug=slug,
        type=type,
        external_id=external_id,
        metadata=metadata,
    )
    if geometry is not None:
        region.boundary = Boundary.objects.create(region=region, version='t', geometry=geometry)
        region.save()
    return region


def make_district(name, slug, external_id, geometry=SELMA_SQUARE, **metadata):
    return make_region(Region.Type.SCHOOL_DISTRICT, name, slug, external_id,
        geometry=geometry, **metadata)


class LocationRegionResolutionTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        # Inside the fixture's Fresno County square (-120.5 36.0 → -119.0 37.0)
        self.inside = Point(-119.79, 36.71, srid=4326)
        # Well outside both county squares
        self.outside = Point(-121.5, 38.5, srid=4326)

    def location(self, point=None, **kwargs):
        """An unsaved Location, so resolve_regions() can be exercised alone."""
        kwargs.setdefault('type', Location.Type.PUBLIC_SCHOOL)
        kwargs.setdefault('name', 'Selma High')
        kwargs.setdefault('external_id', '10621176059453')
        kwargs.setdefault('source', 'cde-public')
        return Location(point=point or self.inside, **kwargs)

    def test_resolve_regions_sets_all_four_links(self):
        city = make_region(Region.Type.CITY, 'Selma', 'selma', '0670098', TOWN_SQUARE)
        zipcode = make_region(Region.Type.ZIPCODE, '93662', '93662', '93662', TOWN_SQUARE)
        district = make_district('Selma Unified', 'selma-unified', '10621170000000')

        location = self.location().resolve_regions()

        assert location.county == Region.objects.get(pk=9001)
        assert location.city == city
        assert location.zipcode == zipcode
        assert location.school_district == district

    def test_resolve_regions_returns_the_instance_without_saving(self):
        make_district('Selma Unified', 'selma-unified', '10621170000000')
        location = self.location()

        assert location.resolve_regions() is location
        assert location.pk is None

    def test_resolve_regions_leaves_everything_none_outside_any_boundary(self):
        make_district('Selma Unified', 'selma-unified', '10621170000000')
        location = self.location(point=self.outside).resolve_regions()

        assert location.county is None
        assert location.city is None
        assert location.zipcode is None
        assert location.school_district is None

    def test_resolve_regions_prefers_a_city_over_a_cdp(self):
        make_region(Region.Type.CDP, 'Selma Place', 'selma-place', 'cdp1', SELMA_SQUARE)
        city = make_region(Region.Type.CITY, 'Selma', 'selma', '0670098', TOWN_SQUARE)

        assert self.location().resolve_regions().city == city

    def test_resolve_regions_falls_back_to_a_cdp(self):
        cdp = make_region(Region.Type.CDP, 'Selma Place', 'selma-place', 'cdp1', SELMA_SQUARE)

        assert self.location().resolve_regions().city == cdp

    def test_resolve_regions_only_touches_the_fields_it_was_given(self):
        make_region(Region.Type.CITY, 'Selma', 'selma', '0670098', TOWN_SQUARE)
        make_district('Selma Unified', 'selma-unified', '10621170000000')

        location = self.location().resolve_regions(fields=['school_district'])

        assert location.school_district is not None
        assert location.county is None
        assert location.city is None

    def test_resolve_regions_prefers_the_cds_code_prefix(self):
        match = make_district('Selma Unified', 'selma-unified', '10621170000000')
        make_district('Fowler Unified', 'fowler-unified', '10621250000000')
        # The point isn't in any district boundary, so only the code can match.
        location = self.location(point=self.outside).resolve_regions(cds_code='10621176059453')

        assert location.school_district == match

    def test_resolve_regions_prefers_unified_over_elementary(self):
        # The elementary district carries the wider span here, so only the
        # "Unified" preference can explain picking the unified one.
        make_district('Selma Elementary', 'selma-elementary', '10621180000000',
            grade_low='P', grade_high='12')
        unified = make_district('Selma Unified', 'selma-unified', '10621170000000',
            grade_low='K', grade_high='12')

        assert self.location().resolve_regions().school_district == unified

    def test_resolve_regions_prefers_the_widest_grade_span(self):
        make_district('Selma Elementary', 'selma-elementary', '10621180000000',
            grade_low='K', grade_high='6')
        widest = make_district('Selma Joint', 'selma-joint', '10621190000000',
            grade_low='P', grade_high='12')

        assert self.location().resolve_regions().school_district == widest


class LocationSaveTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        self.inside = Point(-119.79, 36.71, srid=4326)
        self.outside = Point(-121.5, 38.5, srid=4326)
        self.district = make_district('Selma Unified', 'selma-unified', '10621170000000')
        self.city = make_region(Region.Type.CITY, 'Selma', 'selma', '0670098', TOWN_SQUARE)

    def create(self, **kwargs):
        kwargs.setdefault('type', Location.Type.PUBLIC_SCHOOL)
        kwargs.setdefault('name', 'Selma High')
        kwargs.setdefault('external_id', '10621176059453')
        kwargs.setdefault('source', 'cde-public')
        kwargs.setdefault('point', self.inside)
        return Location.objects.create(**kwargs)

    def test_a_new_location_resolves_its_links(self):
        location = self.create()

        assert location.county_id == 9001
        assert location.city == self.city
        assert location.school_district == self.district

    def test_a_new_location_keeps_the_links_it_was_given(self):
        # The point is outside every boundary, so a link that survives can
        # only have come from the caller.
        elsewhere = make_district('Elsewhere Unified', 'elsewhere-unified', '55555550000000',
            geometry=None)
        location = self.create(point=self.outside, school_district=elsewhere)

        assert location.school_district == elsewhere
        assert location.county is None

    def test_saving_an_unmoved_location_does_no_spatial_work(self):
        location = self.create()
        location = Location.objects.get(pk=location.pk)
        location.name = 'Selma Senior High'

        # One UPDATE, and nothing else: no boundary lookups.
        with self.assertNumQueries(1):
            location.save()

        assert Location.objects.get(pk=location.pk).school_district == self.district

    def test_moving_a_location_re_resolves_its_links(self):
        location = self.create()
        location = Location.objects.get(pk=location.pk)
        location.point = self.outside
        location.save()

        location.refresh_from_db()
        assert location.county is None
        assert location.city is None
        assert location.school_district is None

    def test_moving_a_location_back_into_a_boundary_re_links_it(self):
        location = self.create(point=self.outside)
        location = Location.objects.get(pk=location.pk)
        location.point = self.inside
        location.save()

        location.refresh_from_db()
        assert location.school_district == self.district
        assert location.county_id == 9001


class LocationAccessorTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        self.point = Point(-119.79, 36.71, srid=4326)

    def test_create_location_gets_a_sqid(self):
        location = Location.objects.create(
            type=Location.Type.PUBLIC_SCHOOL,
            name='Selma High',
            external_id='10621170000000',
            source='cde-public',
            city_name='Selma',
            point=self.point,
        )
        location.refresh_from_db()
        assert location.sqid
        assert str(location) == 'Selma High'

    def test_accessors_prefer_the_linked_regions(self):
        location = Location(
            type=Location.Type.PUBLIC_SCHOOL,
            name='Selma High',
            point=self.point,
            city_name='SELMA',
            zip='93662-1000',
            county=Region.objects.get(pk=9001),
            city=make_region(Region.Type.CITY, 'Selma', 'selma', '0670098'),
            zipcode=make_region(Region.Type.ZIPCODE, '93662', '93662', '93662'),
            school_district=make_district('Selma Unified', 'selma-unified',
                '10621170000000', geometry=None),
        )

        assert location.get_county() == 'Fresno County'
        assert location.get_city() == 'Selma'
        assert location.get_zipcode() == '93662'
        assert location.get_school_district() == 'Selma Unified'

    def test_accessors_fall_back_to_the_source_strings(self):
        location = Location(city_name='Selma', zip='93662-1000')

        assert location.get_county() is None
        assert location.get_city() == 'Selma'
        assert location.get_zipcode() == '93662-1000'
        assert location.get_school_district() is None

    def test_short_type(self):
        assert Location(type=Location.Type.PUBLIC_SCHOOL).short_type == 'Public school'
        assert Location(type=Location.Type.PRIVATE_SCHOOL).short_type == 'Private school'
        assert Location(type=Location.Type.CHILD_CARE).short_type == 'Child care'

    def test_get_pesticides_url_is_the_districts_page(self):
        district = make_district('Selma Unified', 'selma-unified', '10621170000000')
        location = Location.objects.create(
            type=Location.Type.PUBLIC_SCHOOL,
            name='Selma High',
            external_id='10621176059453',
            source='cde-public',
            point=self.point,
            school_district=district,
        )
        assert location.get_pesticides_url() == reverse('pesticides:region',
            kwargs={'sqid': district.sqid, 'slug': district.slug})

    def test_get_pesticides_url_is_empty_without_a_district(self):
        location = Location.objects.create(
            type=Location.Type.CHILD_CARE,
            name='Little Sprouts',
            external_id='100400001',
            source='cdss-ccl',
            point=self.point,
        )
        assert location.get_pesticides_url() == ''
