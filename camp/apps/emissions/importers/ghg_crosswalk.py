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
    '100345': (15, 'SJU', 3636),  # Pastoria Energy Facility, LLC, Lebec, 2026-09-29
    '104014': (15, 'SJU', 9168),  # Elk Hills Power LLC (35R Gas Plant), Tupman, 2026-09-29
    '104094': None,                # Berry Petroleum Company - San Joaquin Basin: basin-wide, 2026-09-29
    '100339': (15, 'SJU', 3412),  # CXA La Paloma, LLC, McKittrick, 2026-09-29
    '104081': None,                # Sentinel Peak Resources CA LLC: multiple oil-field sites, not Seneca Resources, 2026-09-29
    '100371': (50, 'SJU', 7172),  # Walnut Energy Center Authority, Turlock, 2026-09-29
    '100358': (39, 'SJU', 4597),  # MRP San Joaquin Energy, LLC, Tracy, 2026-09-29
    '104215': None,                # E&B Natural Resources: multiple oil-field sites, 2026-09-29
    '100300': (15, 'KER', 28),    # US Borax, Boron, 2026-09-29
    '104488': None,                # Crimson Resource Management Corp: multiple oil-field sites, 2026-09-29
    '104172': (39, 'SJU', 2697),  # Northern California Power (Lodi Energy Center), Lodi, 2026-09-29
    '101028': (50, 'SJU', 3233),  # Modesto Irrigation District (Woodland Ave), Modesto, 2026-09-29
    '101507': (15, 'SJU', 37),    # Kern Energy, Bakersfield, 2026-09-29
    '101499': (24, 'SJU', 1399),  # Liberty Packing Co - The Morning Star Co, Los Banos, 2026-09-29
    '101721': (10, 'SJU', 598),   # Guardian Industries, LLC, Kingsburg, 2026-09-29
    '100111': (50, 'SJU', 3299),  # Turlock Irrigation District (Almond Power Plant), Ceres, 2026-09-29
    '101237': (15, 'SJU', 33),    # Alon Bakersfield Refining (Bakersfield Renewable Fuels), Bakersfield, 2026-09-29
    '101342': (20, 'SJU', 801),   # Ardagh Glass Inc., Madera (FRS AIR id CASJV00006039C0801), 2026-09-28
    '101498': (24, 'SJU', 1326),  # Morning Star Packing Company, Los Banos, 2026-09-29
    '101503': (50, 'SJU', 1976),  # ConAgra Foods, Oakdale, 2026-09-29
    '101186': (54, 'SJU', 1203),  # Saputo Cheese USA Inc, Tulare, 2026-09-29
    '101183': (39, 'SJU', 593),   # Owens-Brockway Glass Container, Tracy, 2026-09-29
    '100917': (20, 'SJU', 261),   # CertainTeed LLC, Chowchilla, 2026-09-29
    '101575': (24, 'SJU', 1248),  # Foster Poultry Farms-Kopro, Livingston, 2026-09-29
    '101716': (16, 'SJU', 3955),  # Leprino Foods Company (West), Lemoore, 2026-09-29
    '104005': (15, 'SJU', 44),    # Tricor Refining, LLC, Oildale, 2026-09-29
    '101705': (15, 'SJU', 3550),  # JG Boswell Tomato Company, Kern LLC, Buttonwillow, 2026-09-29
    '101235': (15, 'SJU', 2076),  # Frito-Lay, Inc., Bakersfield, 2026-09-29
}

# EPA GHGRP facility_id -> facility key or None. Most GHGRP rows resolve
# through FRS; this is for the rest (field-level oil & gas ids stay None).
GHGRP = {
    '1005164': (15, 'SJU', 9168),  # Elk Hills Power LLC (35R Gas Plant), Tupman, 2026-09-29
    '1005446': (15, 'SJU', 39),    # Midstream Energy Partners (USA) LLC (North Coles Levee Gas Plant), Tupman, 2026-09-29
    '1006642': (15, 'KER', 21),    # National Cement Co, Lebec, 2026-09-29
    '1002566': (15, 'KER', 20),    # Tehachapi Cement, Tehachapi, 2026-09-29
    '1001107': (50, 'SJU', 3233),  # Modesto Irrigation District (Woodland Ave), Modesto, 2026-09-29
    '1004417': (10, 'SJU', 3115),  # American Avenue Landfill, Kerman, 2026-09-29
    '1007904': (10, 'SJU', 598),   # Guardian Industries, LLC, Kingsburg, 2026-09-29
    '1005355': (15, 'SJU', 2592),  # Mid-Set Cogeneration Company, Fellows, 2026-09-29
    '1003202': (20, 'SJU', 2913),  # County of Madera - Fairmead Landfill, Chowchilla, 2026-09-29
    '1004262': (24, 'SJU', 1657),  # Sensient Natural Ingredients LLC, Livingston, 2026-09-29
    '1002896': (15, 'SJU', 3232),  # Bakersfield Metropolitan Landfill @Bena, Edison, 2026-09-29
    '1006594': (16, 'SJU', 3955),  # Leprino Foods Company (West), Lemoore, 2026-09-29
    '1004956': (15, 'SJU', 3550),  # JG Boswell Tomato Company, Kern LLC, Buttonwillow, 2026-09-29
    '1002394': (15, 'SJU', 2076),  # Frito-Lay, Inc. (Cogen Plant), Bakersfield, 2026-09-29
    '1003187': (15, 'SJU', 416),   # WM Bolthouse Farms, Inc., Bakersfield, 2026-09-29
    '1006750': (15, 'SJU', 3088),  # TRC Cypress Group LLC, Taft, 2026-09-29
    '1002759': (15, 'SJU', 723),   # Chalk Cliff Limited (Cogen), Bakersfield, 2026-09-29
    '1003689': (15, 'SJU', 33),    # Alon Bakersfield Refining, Bakersfield, 2026-09-29
}
