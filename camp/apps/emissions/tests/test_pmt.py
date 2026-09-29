from unittest.mock import MagicMock, patch

from django.test import TestCase

from camp.apps.emissions.importers import pmt

COMMA = (
    '"CO","AB","DIS","FACID","FACILITY","LATITUDE","LONGITUDE"\r\n'
    '10,"SJV","SJU",1,"TEST PLANT",36.74,-119.79\r\n'
    '15,"MD","KER",2,"TEST CEMENT",35.06,-118.16\r\n'
    '15,"SJV","SJU",99,"BAD ROW",,\r\n'
)
TAB = (
    '"CO"\t"AB"\t"DIS"\t"FACID"\t"FACILITY"\t"LATITUDE"\t"LONGITUDE"\r\n'
    '10\t"SJV"\t"SJU"\t1\t"TEST PLANT"\t36.70\t-119.70\r\n'
    '15\t"SJV"\t"SJU"\t2\t"TEST GAS STATION"\t35.37\t-119.02\r\n'
)


def response(status, text=''):
    mock = MagicMock()
    mock.status_code = status
    mock.text = text
    return mock


class ParseMarkersTests(TestCase):
    def test_comma_file(self):
        markers = pmt.parse_markers(COMMA)
        assert set(markers) == {(10, 'SJU', 1), (15, 'KER', 2)}  # the blank-coordinate row is skipped
        point = markers[(10, 'SJU', 1)]
        assert (point.x, point.y, point.srid) == (-119.79, 36.74, 4326)

    def test_tab_file(self):
        # The 2022 file is tab-delimited; the later ones use commas.
        markers = pmt.parse_markers(TAB)
        assert set(markers) == {(10, 'SJU', 1), (15, 'SJU', 2)}


class FetchMarkersTests(TestCase):
    def test_newest_year_wins_and_missing_years_are_skipped(self):
        files = {2022: response(200, TAB), 2023: response(301), 2024: response(200, COMMA)}

        def get(url, **kwargs):
            assert kwargs.get('allow_redirects') is False
            year = int(url.rsplit('ceifacmarkerdata', 1)[1][:4])
            return files.get(year, response(404))

        with patch('requests.get', side_effect=get):
            markers, years = pmt.fetch_markers(range(2022, 2026))
        assert years == [2022, 2024]
        assert markers[(10, 'SJU', 1)].y == 36.74       # 2024's point, over 2022's
        assert markers[(15, 'SJU', 2)].y == 35.37       # only in 2022
        assert (15, 'KER', 2) in markers

