import re

import requests

from django.conf import settings


def _to_data_item_code(name):
    """
    CIMIS's hourly-data response keys each field by PascalCase (e.g.
    'HlyAirTmp'), and CIMIS.ENTRY_MAP uses that same casing so response
    parsing and field lookup share one name. But the live
    GetDataByStationNumber endpoint's `dataItems` query param rejects
    PascalCase -- confirmed live 2026-07-31: 'HlyAirTmp' -> 404
    ERR1035-DATA ITEM NOT FOUND, 'hly-air-tmp' -> 200 with data. Converts
    on the way out so callers can keep using the PascalCase names.
    """
    return re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower()


class CIMISAPI:
    base_url = 'https://et.water.ca.gov'

    def __init__(self, app_key=None):
        self.app_key = app_key or settings.CIMIS_API_KEY
        self.session = requests.Session()
        self.session.headers.update({
            'Ocp-Apim-Subscription-Key': self.app_key,
        })

    def get_stations(self):
        response = self.session.get(f'{self.base_url}/StationWeb/GetAllStations')
        response.raise_for_status()
        return response.json()['Stations']

    def get_hourly_data(self, station_numbers, start_date, end_date, data_items):
        params = {
            'stationNbrs': ','.join(str(n) for n in station_numbers),
            'startDate': start_date.strftime('%Y-%m-%d'),
            'endDate': end_date.strftime('%Y-%m-%d'),
            'dataItems': ','.join(_to_data_item_code(item) for item in data_items),
            'unitOfMeasure': 'E',
            'isHourly': 'true',
        }
        response = self.session.get(f'{self.base_url}/StationWeb/GetDataByStationNumber', params=params)
        response.raise_for_status()
        return response.json()['Data']['Providers']
