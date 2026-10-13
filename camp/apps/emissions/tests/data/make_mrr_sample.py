"""Builds mrr-sample.xlsx, a six-reporter stand-in for CARB's MRR workbook with its real layout. Run from the repo root inside the web container."""
from pathlib import Path

import openpyxl

OUT = Path(__file__).with_name('mrr-sample.xlsx')
wb = openpyxl.Workbook()
intro = wb.active
intro.title = 'Introduction'
intro['B1'] = 'Sample built for tests; layout of the 2024 file released November 4, 2025.'
wb.create_sheet('Column Descriptions')['B1'] = 'See the real workbook.'

data = wb.create_sheet('2024 GHG Data')
data['B1'] = 'Released November 4, 2025. '
data['B3'] = 'California Air Resources Board'
data['B5'] = 'Annual Summary of GHG Mandatory Reporting\nNon-Confidential Data for Calendar Year 2024'
data['F7'] = 'Total Emissions\n(metric tons CO2e)'
data['I7'] = 'Entity-Reported GHG Data\n(metric tons CO2e)'
header = {
    'B': 'ARB ID', 'C': 'Facility Name', 'D': 'Report\nYear', 'F': 'Total CO2e \n(combustion, process, vented, and supplier)', 'G': 'AEL',
    'I': 'Emitter CO2e from Non-Biogenic Sources and CH4 and N2O from Biogenic Fuels', 'J': 'Emitter CO2 from Biogenic Fuels',
    'K': 'Emitter CO2 from Non-Exempt Biogenic Fuels', 'L': 'Fuel Supplier CO2e from Non-Biogenic Fuels and CH4 and N2O from Biogenic Fuels',
    'M': 'Fuel Supplier CO2 from Biogenic Fuels', 'N': 'Fuel Supplier CO2 from Non-Exempt Biogenic Fuels', 'O': 'Electricity Importer CO2e ',
    'Q': 'Emitter Covered\nEmissions', 'R': 'Fuel Supplier Covered\nEmissions', 'S': 'Electricity Importer Covered Emissions',
    'T': 'Total Covered Emissions', 'U': 'Total Non-Covered Emissions ', 'W': 'Emissions Data', 'X': 'Product Data', 'Y': 'Verification Body',
    'AA': 'City', 'AB': 'State', 'AC': 'Zip Code', 'AD': 'North American Industry Classification System (NAICS) \nCode and Description',
    'AE': 'U.S.EPA/ARB Subparts', 'AF': 'Industry Sector',
}
for col, text in header.items():
    data[f'{col}8'] = text
# (arb_id, name, total, emitter, biogenic, supplier, city, zip, naics, subparts, sector)
reporters = [
    ('900001', 'Test Plant Inc.', 87635.27178, 87635.27178, 0, 0, 'Fresno', '93728', '327213 - Glass Container Manufacturing', 'C,N', 'Other Combustion Source'),
    ('900002', 'Valley Oil - San Joaquin Valley Basin 745', 2898915.199, 2898915.199, 0, 0, 'Bakersfield', '93728', '211111 - Crude Petroleum and Natural Gas Extraction', 'C,W', 'Oil and Gas Production'),
    ('900003', 'Valley Fuel Supplier', 1554865.449, 0, 0, 1455571.071, 'FRESNO', '93728', '447190 - Other Gasoline Stations', 'MM', 'Transportation Fuel Supplier'),
    ('900004', 'Mojave Kiln Partners', 360659.6584, 351466.6584, 9193, 0, 'Fresno', '93728-1234', '327310 - Cement Manufacturing', 'C,H', 'Cement Plant'),
    ('900005', 'Biomass Cogen', 208512.8079, 7543.573321, 200969.2346, 0, 'Fresno', 93728, '221117 - Biomass Electric Power Generation', 'C', 'Cogeneration'),
    ('900006', 'Coastal Refinery', 113292.6515, 112309.8365, 982.8150558, 0, 'El Segundo', '90245', '324110 - Petroleum Refineries', 'C,Y', 'Refinery'),
]
for i, (arb_id, name, total, emitter, bio, supplier, city, zipcode, naics, subparts, sector) in enumerate(reporters, start=9):
    for col, value in zip(('B', 'C', 'D', 'F', 'G', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'W', 'X', 'AA', 'AB', 'AC', 'AD', 'AE', 'AF'),
                          (arb_id, name, 2024, total, 'No', emitter, bio, 0, supplier, 0, 0, 0, 'Positive', 'N/A', city, 'CA', zipcode, naics, subparts, sector)):
        data[f'{col}{i}'] = value

gas = wb.create_sheet('2024 Emissions by GHG')
gas['B1'] = 'Released November 4, 2025.'
gas['F2'] = '* Entities with Assigned Emissions Levels (AEL) are not assigned individual GHG emissions (i.e., CO2, CH4, and N2O), only Total CO2e emissions.'
gas['B4'] = 'GHG Mandatory Reporting\nEmission Totals by GHG for Calendar Year 2024'
gas['F5'] = 'Total Emissions\n(metric tons)'
for col, text in {'B': 'ARB ID', 'C': 'Facility Name', 'D': 'Reporting Year', 'F': 'CO2', 'G': ' CH4', 'H': 'N2O', 'I': 'AEL*'}.items():
    gas[f'{col}6'] = text
gases = [
    ('900001', 'Test Plant Inc.', 87571.545182, 1.1628941, 0.11628941),
    ('900002', 'Valley Oil - San Joaquin Valley Basin 745', 2860465.0792, 1477.8195, 5.0491),
    ('900003', 'Valley Fuel Supplier', 1527961.6064, 87.212241, 82.964889),
    ('900004', 'Mojave Kiln Partners', 359593.8313, 15.6239017, 2.2658709),
    ('900005', 'Biomass Cogen', 204742.8005, 58.8133385, 7.7170265),
    ('900006', 'Coastal Refinery', 112644.7513, 14.1644386, 0.98587),
]
for i, (arb_id, name, co2, ch4, n2o) in enumerate(gases, start=7):
    for col, value in zip(('B', 'C', 'D', 'F', 'G', 'H', 'I'), (arb_id, name, 2024, co2, ch4, n2o, 'No')):
        gas[f'{col}{i}'] = value
wb.save(OUT)
print(OUT, OUT.stat().st_size, 'bytes')
