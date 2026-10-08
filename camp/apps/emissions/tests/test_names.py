from django.test import SimpleTestCase

from camp.apps.emissions.names import facility_name


CASES = (
    # Acronyms and initialisms stay capitals.
    ('MRP SAN JOAQUIN ENERGY, LLC', 'MRP San Joaquin Energy, LLC'),
    ('NATIONAL CEMENT CO', 'National Cement Co'),
    ('EDWARDS AFB', 'Edwards AFB'),
    ('NAS LEMOORE', 'NAS Lemoore'),
    ('DTE STOCKTON', 'DTE Stockton'),
    # LLC / USA / Inc and friends.
    ('WESTERN MILLING LLC', 'Western Milling LLC'),
    ('ACME USA INC', 'Acme USA Inc'),
    ('VALLEY COLD STORAGE, LTD', 'Valley Cold Storage, Ltd'),
    # Initials with dots.
    ('J.P. MORGAN FACILITY', 'J.P. Morgan Facility'),
    # Short ampersand pairs.
    ('E&B NATURAL RESOURCES', 'E&B Natural Resources'),
    ('PG&E HUMBOLDT BAY', 'PG&E Humboldt Bay'),
    # Brand casing.
    ('CALPORTLAND CEMENT', 'CalPortland Cement'),
    ('T-MOBILE SITE 4521', 'T-Mobile Site 4521'),
    # LLC/DBA combos split on the slash.
    ('ACME LLC/DBA WESTSIDE DAIRY', 'Acme LLC/DBA Westside Dairy'),
    # Anything with a digit stays as-is for that word.
    ('PLANT #2319', 'Plant #2319'),
    ('HIGHWAY 6TH AVENUE YARD', 'Highway 6TH Avenue Yard'),
    # Possessives and names with apostrophes.
    ("O'NEILL DAIRY", "O'Neill Dairy"),
    ("JIM'S AUTO BODY", "Jim's Auto Body"),
    # "City of X" and a leading "The".
    ('CITY OF FRESNO WWTP', 'City of Fresno WWTP'),
    ('THE BOEING COMPANY', 'The Boeing Company'),
    # Already mixed-case names are left alone.
    ('Test Plant Inc.', 'Test Plant Inc.'),
    ('McDonald Farms', 'McDonald Farms'),
    # Empty and None input.
    ('', ''),
    (None, ''),
)


class FacilityNameTests(SimpleTestCase):
    def test_cases(self):
        for raw, expected in CASES:
            assert facility_name(raw) == expected, (raw, facility_name(raw), expected)

    def test_collapses_whitespace(self):
        assert facility_name('NATIONAL   CEMENT  CO') == 'National Cement Co'

    def test_idempotent(self):
        # Running the cased result back through doesn't change it further.
        for raw, expected in CASES:
            assert facility_name(expected) == expected
