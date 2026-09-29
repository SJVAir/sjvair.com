"""
Hand-curated links from a GHG program's id to a CEIDARS facility key
(county_code, district_code, facid), for the reporters the automatic match
gets wrong or can't reach. A value of None pins the id to *no* facility:
basin-wide oil & gas reports, and known false positives of the name match.
Checked against the dev DB on the date beside each entry. Curated for the
top ~40 MRR emitters in Task 6; keep it sorted by CO2e, largest first.

Facility keys: `Facility.objects.get(county_code=c, air_district__external_id=d, facid=f)`.
County codes: Fresno 10, Kern 15, Kings 16, Madera 20, Merced 24, San Joaquin 39,
Stanislaus 50, Tulare 54. Districts: 'SJU' (Valley Air District), 'KER' (Eastern Kern).
"""

# CARB MRR "ARB ID" -> facility key or None.
MRR = {
    '104030': None,               # California Resources Production Corp - San Joaquin Valley Basin 745: basin-wide
    '101342': (20, 'SJU', 801),   # Ardagh Glass Inc., Madera (FRS AIR id CASJV00006039C0801), 2026-09-28
}

# EPA GHGRP facility_id -> facility key or None. Most GHGRP rows resolve
# through FRS; this is for the rest (field-level oil & gas ids stay None).
GHGRP = {}
