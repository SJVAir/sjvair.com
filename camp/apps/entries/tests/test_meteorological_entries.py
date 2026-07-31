from decimal import Decimal

from django.test import TestCase

from camp.apps.entries import models as entry_models
from camp.apps.monitors.aqview.models import AQview
from django.contrib.gis.geos import Point


class MeteorologicalEntryTests(TestCase):
    def setUp(self):
        self.monitor = AQview.objects.create(
            name='Test Station',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=AQview.LOCATION.outside,
        )

    def test_dew_point_fahrenheit_celsius_conversion(self):
        entry = self.monitor.create_entry(entry_models.DewPoint, timestamp=self.monitor.created, value=Decimal('50.0'))
        assert entry.fahrenheit == Decimal('50.0')
        assert entry.celsius == Decimal('10.0')

    def test_soil_temperature_fahrenheit_celsius_conversion(self):
        entry = self.monitor.create_entry(entry_models.SoilTemperature, timestamp=self.monitor.created, value=Decimal('68.0'))
        assert entry.fahrenheit == Decimal('68.0')
        assert entry.celsius == Decimal('20.0')

    def test_plain_value_entry_types_store_and_serialize(self):
        cases = [
            (entry_models.WindSpeed, Decimal('12.3')),
            (entry_models.WindDirection, Decimal('270.0')),
            (entry_models.Precipitation, Decimal('0.05')),
            (entry_models.SolarRadiation, Decimal('450.2')),
            (entry_models.NetRadiation, Decimal('-15.3')),
            (entry_models.VaporPressure, Decimal('1.25')),
            (entry_models.ETo, Decimal('0.012')),
            (entry_models.ETr, Decimal('0.015')),
        ]
        for EntryModel, value in cases:
            entry = self.monitor.create_entry(EntryModel, timestamp=self.monitor.created, value=value)
            assert entry.value == value
            assert entry.declared_data()['value'] == value
