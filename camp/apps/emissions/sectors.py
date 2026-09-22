"""
SIC code -> Facility.Sector, and SIC titles.

SECTORS is walked in order and the first match wins, so a specific sector
(glass, cement, refining, wineries) sits ahead of the broad range that
contains it (manufacturing, food processing). SIC codes are ints (0723 is
723); a tuple is an inclusive (low, high) range. Built from the 2024 SIC
distribution across the covered counties.
"""

import csv
import io
from functools import lru_cache

from camp.apps.emissions.models import Facility
from camp.utils.datafiles import datafile

S = Facility.Sector

SECTORS = [
    (S.DAIRIES_LIVESTOCK, [(200, 299)],
     'Dairies, cattle feedlots, poultry and other animal operations.'),
    (S.FARMS, [(100, 199)],
     'Crop farms and orchards with permitted equipment, such as irrigation pump engines.'),
    (S.CROP_PROCESSING, [(700, 799)],
     'Cotton gins, nut hullers and other operations that prepare crops for market.'),
    (S.OIL_GAS, [(1300, 1399)],
     'Oil and natural gas fields and the services that support them.'),
    (S.MINING, [(1000, 1299), (1400, 1499)],
     'Quarries, sand and gravel pits, and mineral mines.'),
    (S.GLASS, [3211, 3221, 3229, 3231],
     'Plants that make flat glass, bottles and jars, and other glass products.'),
    (S.CEMENT_MINERALS, [(3240, 3299)],
     'Cement kilns, concrete plants and other stone, clay and mineral products.'),
    (S.REFINING_FUELS, [2911, (2950, 2999), (4610, 4619), (4922, 4925), 5171, 5172],
     'Petroleum refineries, asphalt plants, fuel terminals and pipelines.'),
    (S.WINERIES_BEVERAGES, [(2080, 2087)],
     'Wineries, breweries, distilleries and soft drink plants.'),
    (S.FOOD_PROCESSING, [(2000, 2099)],
     'Canneries, dairy processors, fruit and nut processing, and animal feed mills.'),
    (S.CHEMICALS, [(2800, 2899)],
     'Chemical plants and fertilizer and compost operations.'),
    (S.POWER_PLANTS, [4911, 4931, 4939, 4961],
     'Power plants and cogeneration facilities that make electricity or steam.'),
    (S.WASTE_WATER, [(4940, 4959), 4971, 5093, 9511],
     'Landfills, sewage treatment, water systems and recycling yards.'),
    (S.TELECOM, [(4800, 4899)],
     'Phone, cell and broadcast sites, mostly for their backup generators.'),
    (S.TRANSPORTATION, [(4000, 4799)],
     'Railroads, trucking, airports and warehouses.'),
    (S.GAS_STATIONS, [5541],
     'Gasoline stations.'),
    (S.AUTO_REPAIR, [7532, 7538],
     'Auto body, paint and repair shops.'),
    (S.DRY_CLEANERS, [7216],
     'Dry cleaners.'),
    (S.MANUFACTURING, [(2100, 2799), (3000, 3999)],
     'Other manufacturing: metal, plastics, wood, paper, printing and more.'),
    (S.HOSPITALS_SCHOOLS, [(8000, 8099), (8200, 8299)],
     'Hospitals, clinics, schools, colleges and universities.'),
    (S.GOVERNMENT_MILITARY, [(9100, 9999)],
     'Government facilities, prisons, fire stations and military bases.'),
    (S.COMMERCIAL, [(5000, 5999), (6000, 6999), (7000, 7999), (8100, 8199), (8300, 8999)],
     'Stores, restaurants, offices and other businesses.'),
]

OTHER_DESCRIPTION = "Facilities whose industry code doesn't fit another sector."

_DESCRIPTIONS = {sector: description for sector, _codes, description in SECTORS}


def _matches(sic, codes):
    for code in codes:
        if isinstance(code, tuple):
            if code[0] <= sic <= code[1]:
                return True
        elif sic == code:
            return True
    return False


def sector_for_sic(sic):
    if sic is None:
        return S.OTHER
    for sector, codes, _description in SECTORS:
        if _matches(sic, codes):
            return sector
    return S.OTHER


def sector_description(sector):
    return _DESCRIPTIONS.get(sector, OTHER_DESCRIPTION)


@lru_cache(maxsize=1)
def _sic_titles():
    text = datafile('sic-codes.csv')
    lines = [line for line in text.splitlines() if not line.startswith('#')]
    return {int(row['SIC']): row['Description'] for row in csv.DictReader(io.StringIO('\n'.join(lines)))}


def sic_title(sic):
    if sic is None:
        return None
    return _sic_titles().get(int(sic))
