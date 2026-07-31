import requests

from django.conf import settings


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
            'dataItems': ','.join(data_items),
            'unitOfMeasure': 'E',
            'isHourly': 'true',
        }
        response = self.session.get(f'{self.base_url}/StationWeb/GetDataByStationNumber', params=params)
        response.raise_for_status()
        return response.json()['Data']['Providers']
