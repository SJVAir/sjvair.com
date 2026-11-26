from datetime import date
from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest import mock

from django.contrib.gis.geos import Polygon
from django.test import TestCase
from django.utils import timezone

from camp.apps.regions.management.commands.import_cities import import_place_row
from camp.apps.regions.models import Region


def quiet(message):
    pass


def place_row(classfp, geoid='0612345', name='Newtown'):
    return SimpleNamespace(
        CLASSFP=classfp, GEOID=geoid, NAME=name, NAMELSAD=f'{name} city',
        STATEFP='06', PLACEFP=geoid[2:], ALAND=1, AWATER=0,
        geometry=Polygon(((0, 0), (0, 1), (1, 1), (1, 0), (0, 0))),
    )


class CdpIncorporationTests(TestCase):
    def test_city_import_retires_cdp_with_same_geoid(self):
        cdp = import_place_row(place_row('U2'), write=quiet)
        assert cdp.type == Region.Type.CDP
        assert cdp.retired_at is None

        # 03:00 UTC on the 23rd is still the 22nd in Pacific time.
        # A management command runs with the settings TIME_ZONE (UTC), not the
        # Pacific zone conftest activates, so override it the same way.
        now = datetime(2026, 10, 23, 3, 0, tzinfo=dt_timezone.utc)
        with timezone.override(None), mock.patch('django.utils.timezone.now', return_value=now):
            city = import_place_row(place_row('C1'), write=quiet)
        assert city.type == Region.Type.CITY

        cdp = Region.all_objects.get(pk=cdp.pk)
        assert cdp.retired_at == date(2026, 10, 22)
        assert cdp.replaced_by == city
        assert city.retired_at is None

    def test_rerun_does_not_move_retired_at(self):
        import_place_row(place_row('U2'), write=quiet)
        city = import_place_row(place_row('C1'), write=quiet)
        earlier = date(2020, 1, 1)
        Region.all_objects.filter(type=Region.Type.CDP).update(retired_at=earlier)

        import_place_row(place_row('C1'), write=quiet)

        cdp = Region.all_objects.get(type=Region.Type.CDP, external_id='0612345')
        assert cdp.retired_at == earlier
        assert cdp.replaced_by == city

    def test_city_without_cdp_and_unrelated_cdp_untouched(self):
        other = import_place_row(place_row('U2', geoid='0699999', name='Other'), write=quiet)
        import_place_row(place_row('C1'), write=quiet)
        other = Region.all_objects.get(pk=other.pk)
        assert other.retired_at is None
        assert other.replaced_by is None

    def test_cdp_import_retires_nothing(self):
        cdp = import_place_row(place_row('U1'), write=quiet)
        assert cdp.retired_at is None
        assert import_place_row(place_row('S1'), write=quiet) is None
