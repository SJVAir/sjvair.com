import json
import urllib.parse

import requests


class AirGradientAPI:
    API_URL = 'https://api.airgradient.com/public/api/v1/'

    def __init__(self, token):
        self.token = token

    # Request Construction

    def build_url(self, path):
        return urllib.parse.urljoin(self.API_URL, path)

    def build_headers(self, headers=None):
        defaults = {'Accept': 'application/json'}
        if headers:
            defaults.update(headers)
        return defaults

    def decode(self, content):
        return json.JSONDecoder().decode(content.decode('utf-8'))

    def encode(self, obj):
        return json.JSONEncoder().encode(obj)

    def request(self, path, method=None, **kwargs):
        method = method or 'get'
        url = self.build_url(path)
        headers = self.build_headers(kwargs.pop('headers', None))

        # Inject token if auth is required
        if kwargs.pop('auth', False) is True:
            params = kwargs.pop('params', {})
            params['token'] = self.token
            kwargs['params'] = params

        return requests.request(method, url, headers=headers, **kwargs)

    # HTTP Methods

    def get(self, path, **kwargs):
        return self.request(path, 'get', **kwargs)

    def post(self, path, **kwargs):
        return self.request(path, 'post', **kwargs)

    def put(self, path, **kwargs):
        return self.request(path, 'put', **kwargs)

    def delete(self, path, **kwargs):
        return self.request(path, 'delete', **kwargs)

    # API Endpoints

    def ping(self):
        '''Ping the AirGradient server'''
        response = self.get('ping')
        return response.ok

    def get_world_current_measures(self):
        '''Gets the current measures of all locations that are made public to the world'''
        response = self.get('world/locations/measures/current')
        return response.json()

    def get_world_current_measures_by_location(self, location_id: int):
        '''Gets the current measures of a certain location that is made public to the world'''
        response = self.get(f'world/locations/{location_id}/measures/current')
        return response.json()

    def get_current_measures(self, location_id: int):
        '''Gets the current measures of a location'''
        response = self.get(f'locations/{location_id}/measures/current', auth=True)
        return response.json()

    def get_all_current_measures(self):
        '''Gets all current measures of the place'''
        response = self.get('locations/measures/current', auth=True)
        return response.json()

    def get_raw_measures(self, location_id: int, from_time: str = None, to_time: str = None):
        '''
        Gets the 200 most recent raw measures of a location or from a certain date range.
        The records are ordered by date descending
        '''
        params = {}
        if from_time:
            params['from'] = from_time
        if to_time:
            params['to'] = to_time
        response = self.get(f'locations/{location_id}/measures/raw', auth=True, params=params)
        return response.json()

    def get_past_measures(self, location_id: int, from_time: str, to_time: str):
        '''
        Gets past measures of a location in 5 minute buckets or 60 minute buckets
        (depending on what is available)
        '''
        params = {
            'from': from_time,
            'to': to_time,
        }
        response = self.get(f'locations/{location_id}/measures/past', auth=True, params=params)
        return response.json()

    def get_average_measures(self, location_ids: list[int], bucket_size: int):
        '''Gets the average values across a set of locations in buckets'''
        ids = ','.join(str(id) for id in location_ids)
        response = self.get(f'locations/{ids}/measures/buckets/{bucket_size}', auth=True)
        return response.json()

    # CO2 Calibrations

    def calibrate_co2_by_location(self, location_id: int):
        '''
        Triggers calibration of the CO2 sensor by location.
        Note that the sensor has to be in a 400ppm environment when calibration is performed.
        '''
        response = self.post(f'locations/{location_id}/sensor/co2/calibration', auth=True)
        return response.json()

    def calibrate_co2_by_serial(self, serialno: str):
        '''
        Triggers calibration of the CO2 sensor by serial number.
        Note that the sensor has to be in a 400ppm environment when calibration is performed.
        '''
        response = self.post(f'sensors/{serialno}/co2/calibration', auth=True)
        return response.json()

    # LED Configuration

    def get_led_mode_by_location(self, location_id: int):
        '''Gets the LED mode for a location'''
        response = self.get(f'locations/{location_id}/sensor/config/leds/mode', auth=True)
        return response.json()

    def update_led_mode_by_location(self, location_id: int, mode: str):
        '''Updates the LED mode for a location'''
        body = {'mode': mode}
        response = self.put(f'locations/{location_id}/sensor/config/leds/mode', auth=True, json=body)
        return response.json()

    def get_led_mode_by_serial(self, serialno: str):
        '''Gets the LED mode for a sensor by serial number'''
        response = self.get(f'sensors/{serialno}/config/leds/mode', auth=True)
        return response.json()

    def update_led_mode_by_serial(self, serialno: str, mode: str):
        '''Updates the LED mode for a sensor by serial number'''
        body = {'mode': mode}
        response = self.put(f'sensors/{serialno}/config/leds/mode', auth=True, json=body)
        return response.json()
