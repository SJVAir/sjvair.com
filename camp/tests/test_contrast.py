import re
from pathlib import Path

from django.test import SimpleTestCase

SASS = Path(__file__).resolve().parents[2] / 'assets' / 'sass' / 'sjvair'


def sass_var(name):
    return re.search(rf'^\${name}:\s*(#[0-9a-fA-F]{{6}})', (SASS / 'variables.sass').read_text(), re.M).group(1)


def luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class TextContrastTests(SimpleTestCase):
    def test_link_blue_passes_on_page_backgrounds(self):
        link = sass_var('link-blue')
        for background in ('#ffffff', '#fafafa', '#ededed'):
            assert contrast(link, background) >= 4.5, background

    def test_white_on_link_blue_passes(self):
        assert contrast('#ffffff', sass_var('link-blue')) >= 4.5

    def test_grey_text_passes(self):
        grey = sass_var('text-grey')
        for background in ('#ffffff', '#fafafa'):
            assert contrast(grey, background) >= 4.5, background

    def test_flag_tags_pass(self):
        # Colours set in pages/pesticides.sass under `.tag`.
        sass = (SASS / 'pages' / 'pesticides.sass').read_text()
        for color in ('#a84300', '#735c00', '#b94800'):
            assert color in sass
        assert contrast('#a84300', '#fff3eb') >= 4.5  # Prop 65
        assert contrast('#735c00', '#fefaec') >= 4.5  # Fumigant, Restricted, TAC
        assert contrast('#ffffff', '#b94800') >= 4.5  # IARC
