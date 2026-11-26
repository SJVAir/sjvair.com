from decimal import Decimal

from django.test import TestCase

from camp.apps.entries import levels
from camp.apps.entries.models import CO, NO2, O3, PM25, PM100, SO2


class PM25BreakpointTests(TestCase):
    """
    PM2.5 levels follow EPA's 2024 AQI revision (89 FR 16202): Good 0.0-9.0,
    Moderate 9.1-35.4, USG 35.5-55.4, Unhealthy 55.5-125.4,
    Very Unhealthy 125.5-225.4, Hazardous 225.5+ (ug/m3).
    """

    def test_boundaries(self):
        cases = [
            ('0.0', 'good'),
            ('9.0', 'good'),
            ('9.1', 'moderate'),
            ('35.4', 'moderate'),
            ('35.5', 'unhealthy_sensitive'),
            ('55.4', 'unhealthy_sensitive'),
            ('55.5', 'unhealthy'),
            ('125.4', 'unhealthy'),
            ('125.5', 'very_unhealthy'),
            ('225.4', 'very_unhealthy'),
            ('225.5', 'hazardous'),
            ('500.0', 'hazardous'),
        ]
        for value, key in cases:
            assert PM25.Levels.get_level(Decimal(value)).key == key, value

    def test_served_ranges(self):
        # The ranges monitors/meta/ serves to every client, in its scale.
        scale = PM25.Levels.to_scale('pm25', 'PM2.5', 'µg/m³')
        by_key = {lvl.key: lvl for lvl in scale.levels}
        assert (by_key['unhealthy'].min, by_key['unhealthy'].max) == (55.5, 125.5)
        assert by_key['hazardous'].min == 225.5
        assert by_key['hazardous'].max is None


class EntryLevelsSourceTests(TestCase):
    """Each entry model uses the shared level set in levels.py, not a copy."""

    def test_models_use_shared_level_sets(self):
        assert PM25.Levels is levels.PM25
        assert PM100.Levels is levels.PM100
        assert O3.Levels is levels.O3
        assert CO.Levels is levels.CO
        assert NO2.Levels is levels.NO2
        assert SO2.Levels is levels.SO2
