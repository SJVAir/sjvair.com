from django.contrib.gis.geos import Point
from django.test import TestCase

from camp.apps.regions.models import Location


def place(name, lng, lat, type=Location.Type.CHILD_CARE, n=[0]):
    n[0] += 1
    return Location.objects.create(name=name, type=type, source='test', external_id=str(n[0]), point=Point(lng, lat, srid=4326))


class OnePerPlaceTests(TestCase):
    """Location.objects.one_per_place(): a child-care center's several state licenses are one place."""

    def setUp(self):
        self.day_care = place('CHILD LIFE LEARNING CENTER', -118.9651, 35.4102)
        self.school_age = place('Child Life Learning Center ', -118.9651, 35.4102)  # the same place, another license
        self.next_door = place('CHILD LIFE LEARNING CENTER', -118.9656, 35.4105)  # ~60 m off: the same place
        self.across_town = place('CHILD LIFE LEARNING CENTER', -118.9651, 35.4002)  # ~1 km: another place
        self.academy = place('CHILD LIFE LEARNING CENTER', -118.9651, 35.4102, type=Location.Type.PRIVATE_SCHOOL)

    def test_licenses_at_one_place_are_one_row(self):
        rows = {row.pk: row.licenses for row in Location.objects.one_per_place()}
        # The first license stands for the three at the place; the far one is its own;
        # a school on the same site stays a school.
        assert rows == {self.day_care.pk: 3, self.across_town.pk: 1, self.academy.pk: 1}

    def test_it_chains_after_a_filter(self):
        rows = Location.objects.filter(type=Location.Type.CHILD_CARE).one_per_place()
        assert sorted(row.pk for row in rows) == [self.day_care.pk, self.across_town.pk]
