from django.test import SimpleTestCase

from camp.apps.pesticides.templatetags.pesticides_explorer import lbs


class LbsFilterTests(SimpleTestCase):
    def test_whole_pounds_with_commas(self):
        assert lbs(26299290.4) == '26,299,290'
        assert lbs(12) == '12'
        assert lbs(0) == '0'
        assert lbs(None) == '—'

    def test_small_amounts_keep_their_decimals(self):
        # A bait at 0.1% active ingredient applies fractions of a pound; that isn't nothing.
        assert lbs(0.186) == '0.19'
        assert lbs(0.0082) == '0.01'
        assert lbs(1.25) == '1.2'
        assert lbs(9.96) == '10.0'
