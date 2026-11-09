import pytest
from django.test import TestCase

from camp.apps.entries import levels

SETS = {
    'PM25': levels.PM25, 'PM100': levels.PM100, 'CO': levels.CO, 'NO2': levels.NO2,
    'O3': levels.O3, 'SO2': levels.SO2, 'AQI': levels.AQI,
}

TIERS = {
    'good': 0, 'moderate': 1, 'unhealthy_sensitive': 2, 'unhealthy': 3,
    'very_unhealthy': 4, 'hazardous': 4, 'very_hazardous': 4,
}


def level_for(scale, v):
    for lvl in scale.levels:
        if lvl.min <= v and (lvl.max is None or v < lvl.max):
            return lvl


class ScaleTests(TestCase):
    def test_aq_tiers(self):
        for name, levelset in SETS.items():
            for lvl in levelset:
                assert lvl.tier == TIERS[lvl.key], (name, lvl.key)

    def test_to_scale_half_open(self):
        s = levels.PM25.to_scale('pm25', 'PM2.5', 'µg/m³')
        assert s.kind == 'range'
        by_key = {l.key: l for l in s.levels}
        assert (by_key['good'].min, by_key['good'].max) == (0.0, 9.1)
        assert (by_key['hazardous'].min, by_key['hazardous'].max) == (225.5, None)
        assert level_for(s, 9.1).key == 'moderate'
        assert level_for(s, 9.0999).key == 'good'
        assert level_for(s, 600).key == 'hazardous'

    def test_epa_descriptions(self):
        s = levels.PM100.to_scale('pm100', 'PM10', 'µg/m³')
        by_key = {l.key: l for l in s.levels}
        assert by_key['good'].description == 'Air quality is satisfactory, and air pollution poses little or no risk.'
        assert by_key['good'].guidance == ''
        assert by_key['very_hazardous'].description == by_key['hazardous'].description

    def test_averaging_hours_declared(self):
        assert levels.PM25.averaging_hours == 24 and levels.PM100.averaging_hours == 24
        assert levels.O3.averaging_hours == 1 and levels.NO2.averaging_hours == 1
        assert levels.SO2.averaging_hours == 1 and levels.CO.averaging_hours == 8
        assert levels.AQI.averaging_hours is None

    def test_daily_statistic(self):
        assert levels.PM25.daily_statistic == 'mean_24h'
        assert levels.O3.daily_statistic == 'max_1h'
        assert levels.CO.daily_statistic == 'max_8h'
        assert levels.AQI.daily_statistic is None

    def test_averaging_hours_is_not_a_level(self):
        assert 'averaging_hours' not in [lvl.key for lvl in levels.O3]

    def test_invalid_averaging_hours(self):
        with pytest.raises(ValueError):
            levels.LevelSet(levels.AQLevel.GOOD(0), averaging_hours=3)

    def test_to_json_carries_averaging(self):
        data = levels.O3.to_scale('o3', 'Ozone', 'ppb').to_json()
        assert data['averaging_hours'] == 1 and data['daily_statistic'] == 'max_1h'
        aqi = levels.AQI.to_scale('aqi', 'AQI', 'AQI').to_json()
        assert aqi['averaging_hours'] is None and aqi['daily_statistic'] is None

    def test_to_json_keys(self):
        s = levels.PM25.to_scale('pm25', 'PM2.5', 'µg/m³')
        data = s.to_json()
        assert set(data['levels'][0]) == {
            'key', 'label', 'color', 'opacity', 'tier', 'description',
            'guidance', 'min', 'max', 'value',
        }
        assert data['source'] == levels.EPA_SOURCE
        assert {'averaging_hours', 'daily_statistic', 'daily_statistic_label'} <= set(data)


class DailyStatisticLabelTests(TestCase):
    def test_labels(self):
        assert levels.PM25.daily_statistic_label == '24-hour average'
        assert levels.O3.daily_statistic_label == 'Highest 1-hour average'
        assert levels.CO.daily_statistic_label == 'Highest 8-hour average'

    def test_none_without_averaging(self):
        assert levels.AQI.daily_statistic_label is None
        assert levels.AQI.to_scale('aqi', 'AQI', 'AQI').to_json()['daily_statistic_label'] is None

    def test_to_json_is_a_plain_string(self):
        data = levels.O3.to_scale('o3', 'Ozone', 'ppb').to_json()
        assert data['daily_statistic_label'] == 'Highest 1-hour average'
        assert type(data['daily_statistic_label']) is str
