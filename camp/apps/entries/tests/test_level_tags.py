from django.test import TestCase

from camp.apps.entries import levels
from camp.apps.entries.templatetags.level_tags import level_range, level_style


class LevelRangeTests(TestCase):
    def test_pm25_ranges(self):
        assert level_range(levels.PM25, 1) == [
            '0.0 – 9.0', '9.1 – 35.4', '35.5 – 55.4', '55.5 – 125.4', '125.5 – 225.4', '≥225.5',
        ]

    def test_aqi_ranges(self):
        assert level_range(levels.AQI, 0) == [
            '0 – 50', '51 – 100', '101 – 150', '151 – 200', '201 – 300', '≥301',
        ]


class LevelStyleTests(TestCase):
    def test_level_style_contrast(self):
        for level in (levels.PM25.GOOD, levels.PM25.MODERATE):
            assert level_style(level) == f'background-color: {level.color}; color: #363636'
        for level in (levels.PM25.UNHEALTHY_SENSITIVE, levels.PM100.VERY_HAZARDOUS):
            assert level_style(level) == f'background-color: {level.color}; color: #fff'
        assert level_style(None) == ''
