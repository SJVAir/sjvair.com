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
    def test_as_dict_keeps_shape_and_adds_tier(self):
        assert levels.PM25.as_dict()['MODERATE'] == {
            'name': 'moderate',
            'label': 'Moderate',
            'color': '#ffff00',
            'range': (9.1, 35.4),
            'guidance': 'Highly sensitive groups should stay indoors and avoid outdoor activities.',
            'tier': 1,
        }

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

    def test_scale_and_dict_agree(self):
        for name, levelset in SETS.items():
            s = levelset.to_scale(name.lower(), name, 'x')
            by_key = {l.key: l for l in s.levels}
            for entry in levelset.as_dict().values():
                lvl = by_key[entry['name']]
                assert entry['range'][0] == lvl.min
                assert entry['color'] == lvl.color
                assert entry['label'] == lvl.label
                assert entry['tier'] == lvl.tier

    def test_epa_descriptions(self):
        s = levels.PM100.to_scale('pm100', 'PM10', 'µg/m³')
        by_key = {l.key: l for l in s.levels}
        assert by_key['good'].description == 'Air quality is satisfactory, and air pollution poses little or no risk.'
        assert by_key['good'].guidance == ''
        assert by_key['very_hazardous'].description == by_key['hazardous'].description

    def test_to_json_keys(self):
        s = levels.PM25.to_scale('pm25', 'PM2.5', 'µg/m³')
        data = s.to_json()
        assert set(data['levels'][0]) == {
            'key', 'label', 'color', 'opacity', 'tier', 'description',
            'guidance', 'min', 'max', 'value',
        }
        assert data['source'] == levels.EPA_SOURCE
