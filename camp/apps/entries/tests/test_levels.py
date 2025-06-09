import enum

from django.test import TestCase

from camp.apps.entries.levels import PollutantLevels, Lvl, AQLvl

class PM25Levels(PollutantLevels):
    HAZARDOUS = Lvl(
        value=250.5,
        label='Hazardous',
        color='#7e0023'
    )

    VERY_UNHEALTHY = Lvl(
        value=150.5,
        label='Very Unhealthy',
        color='#ff0000'
    )

    UNHEALTHY = Lvl(
        value=55.5,
        label='Unhealthy',
        color='#ff7e00'
    )

    UNHEALTHY_SENSITIVE = Lvl(
        value=35.5,
        label='Unhealthy for Sensitive Groups',
        color='#ffff00'
    )

    MODERATE = Lvl(
        value=9.1,
        label='Moderate',
        color='#00e400'
    )

    GOOD = Lvl(
        value=0,
        label='Good',
        color='#00ccff'
    )


class ColorLevels(PollutantLevels):
    WHITE = Lvl(255, 'White', '#ffffff')
    BLACK = Lvl(0, 'Black', '#000000')


class LevelsTests(TestCase):
    def test_from_aq_levels(self):
        AQLevels = PollutantLevels.from_aq_levels(
            AQLvl.HAZARDOUS(PM25Levels.HAZARDOUS.value),
            AQLvl.VERY_UNHEALTHY(PM25Levels.VERY_UNHEALTHY.value),
            AQLvl.UNHEALTHY(PM25Levels.UNHEALTHY.value),
            AQLvl.UNHEALTHY_SENSITIVE(PM25Levels.UNHEALTHY_SENSITIVE.value),
            AQLvl.MODERATE(PM25Levels.MODERATE.value),
            AQLvl.GOOD(PM25Levels.GOOD.value),
        )

        assert isinstance(AQLevels, enum.EnumType)
        assert AQLevels.GOOD.name == PM25Levels.GOOD.name
        assert AQLevels.GOOD.value == PM25Levels.GOOD.value
        assert AQLevels.GOOD.label == PM25Levels.GOOD.label


    def test_enum_fields(self):
        assert PM25Levels.MODERATE.value == 9.1
        assert PM25Levels.MODERATE.name == 'MODERATE'
        assert PM25Levels.MODERATE.label == 'Moderate'

    def test_choices_are_correct(self):
        assert PM25Levels.choices == [
            ('HAZARDOUS', 'Hazardous'),
            ('VERY_UNHEALTHY', 'Very Unhealthy'),
            ('UNHEALTHY', 'Unhealthy'),
            ('UNHEALTHY_SENSITIVE', 'Unhealthy for Sensitive Groups'),
            ('MODERATE', 'Moderate'),
            ('GOOD', 'Good'),
        ]

    def test_level_lookup(self):
        assert PM25Levels.get_level(300) == PM25Levels.HAZARDOUS
        assert PM25Levels.get_level(200) == PM25Levels.VERY_UNHEALTHY
        assert PM25Levels.get_level(100) == PM25Levels.UNHEALTHY
        assert PM25Levels.get_level(45) == PM25Levels.UNHEALTHY_SENSITIVE
        assert PM25Levels.get_level(15) == PM25Levels.MODERATE
        assert PM25Levels.get_level(5) is PM25Levels.GOOD
        assert PM25Levels.get_level(0) is PM25Levels.GOOD
        assert PM25Levels.get_level(-2) is PM25Levels.GOOD

        # Test on the cusp.
        assert PM25Levels.get_level(8.9) is PM25Levels.GOOD
        assert PM25Levels.get_level(9.0) is PM25Levels.GOOD
        assert PM25Levels.get_level(9.1) is PM25Levels.MODERATE
        assert PM25Levels.get_level(9.2) is PM25Levels.MODERATE

    def test_as_dict(self):
        d = PM25Levels.as_dict()
        assert d['MODERATE']['label'] == 'Moderate'
        assert d['MODERATE']['range'] == (9.1, 35.4)
        assert d['GOOD']['label'] == 'Good'
        assert d['GOOD']['range'] == (0, 9)

    def test_color_levels_exact_values(self):
        assert ColorLevels.get_color(0) == '#000000'
        assert ColorLevels.get_color(1) == '#010101'
        assert ColorLevels.get_color(10) == '#0a0a0a'
        assert ColorLevels.get_color(127) == '#7f7f7f'
        assert ColorLevels.get_color(128) == '#808080'
        assert ColorLevels.get_color(254) == '#fefefe'
        assert ColorLevels.get_color(255) == '#ffffff'

    def test_color_levels_bounds(self):
        # Test out-of-bounds inputs
        assert ColorLevels.get_color(-100) == '#000000'
        assert ColorLevels.get_color(999) == '#ffffff'

    def test_color_levels_monotonic_grayscale(self):
        # Verify each color is brighter than the previous one
        prev = (0, 0, 0)
        for v in range(1, 256):
            hex_color = ColorLevels.get_color(v)
            r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (1, 3, 5))
            assert r >= prev[0]
            assert g >= prev[1]
            assert b >= prev[2]
            prev = (r, g, b)
