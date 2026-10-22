from datetime import date
from types import SimpleNamespace

from django.contrib.gis.geos import Polygon
from django.test import TestCase
from django.utils import timezone

from camp.apps.regions.management.commands.import_cities import import_place_row
from camp.apps.regions.models import Region


def place_row(classfp, geoid='0612345', name='Newtown'):
    return SimpleNamespace(
        CLASSFP=classfp, GEOID=geoid, NAME=name, NAMELSAD=f'{name} city',
        STATEFP='06', PLACEFP=geoid[2:], ALAND=1, AWATER=0,
        geometry=Polygon(((0, 0), (0, 1), (1, 1), (1, 0), (0, 0))),
    )


class CdpIncorporationTests(TestCase):
    def test_city_import_retires_cdp_with_same_geoid(self):
        cdp = import_place_row(place_row('U2'))
        assert cdp.type == Region.Type.CDP
        assert cdp.retired_at is None

        city = import_place_row(place_row('C1'))
        assert city.type == Region.Type.CITY

        cdp = Region.all_objects.get(pk=cdp.pk)
        assert cdp.retired_at == timezone.localdate()
        assert cdp.replaced_by == city
        assert city.retired_at is None

    def test_rerun_does_not_move_retired_at(self):
        import_place_row(place_row('U2'))
        city = import_place_row(place_row('C1'))
        earlier = date(2020, 1, 1)
        Region.all_objects.filter(type=Region.Type.CDP).update(retired_at=earlier)

        import_place_row(place_row('C1'))

        cdp = Region.all_objects.get(type=Region.Type.CDP, external_id='0612345')
        assert cdp.retired_at == earlier
        assert cdp.replaced_by == city

    def test_city_without_cdp_and_unrelated_cdp_untouched(self):
        other = import_place_row(place_row('U2', geoid='0699999', name='Other'))
        import_place_row(place_row('C1'))
        other = Region.all_objects.get(pk=other.pk)
        assert other.retired_at is None
        assert other.replaced_by is None

    def test_cdp_import_retires_nothing(self):
        cdp = import_place_row(place_row('U1'))
        assert cdp.retired_at is None
        assert import_place_row(place_row('S1')) is None
