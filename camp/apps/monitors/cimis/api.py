import requests

from django.conf import settings


class CIMISAPI:
    base_url = 'https://et.water.ca.gov/api'

    def __init__(self, app_key=None):
        self.app_key = app_key or settings.CIMIS_API_KEY
        self.session = requests.Session()

    def get_stations(self):
        response = self.session.get(f'{self.base_url}/station', params={
            'appKey': self.app_key,
        })
        response.raise_for_status()
        return response.json()['Stations']

    def get_hourly_data(self, station_numbers, start_date, end_date, data_items):
        params = {
            'appKey': self.app_key,
            'targets': ','.join(str(n) for n in station_numbers),
            'startDate': start_date.strftime('%Y-%m-%d'),
            'endDate': end_date.strftime('%Y-%m-%d'),
            'dataItems': ','.join(data_items),
            'unitOfMeasure': 'E',
        }
        response = self.session.get(f'{self.base_url}/data', params=params)
        response.raise_for_status()
        return response.json()['Data']['Providers']
