from django.contrib.gis.geos import Point
from django.test import TestCase

from camp.apps.entries import models as entry_models
from camp.apps.monitors.cimis.models import CIMIS


class CIMISModelTests(TestCase):
    def test_entry_config_maps_all_twelve_fields(self):
        assert len(CIMIS.ENTRY_CONFIG) == 12
        assert CIMIS.ENTRY_MAP['HlyAirTmp'] is entry_models.Temperature
        assert CIMIS.ENTRY_MAP['HlyAsceEto'] is entry_models.ETo

    def test_station_number_is_unique(self):
        CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        with self.assertRaises(Exception):
            CIMIS.objects.create(
                name='Station B',
                station_number='2',
                position=Point(-119.0, 36.0, srid=4326),
                location=CIMIS.LOCATION.outside,
            )

    def test_supports_health_checks_is_false(self):
        monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        assert monitor.supports_health_checks() is False
