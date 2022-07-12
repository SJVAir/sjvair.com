import json
import os
import string
import urllib.parse

from pprint import pprint

import requests
import thingspeak

from camp.utils.datetime import parse_datetime

PURPLE_API_URL = 'https://api.purpleair.com/'


def compare_datetimes(dt1, dt2):
    '''
        Returns whether or not two datetimes
        are within 60 seconds of one another.
    '''
    return abs((dt2 - dt1).total_seconds()) < 60


class NewPurpleAirAPI:
    API_URL = 'https://api.purpleair.com'
    READ_KEY = os.environ.get('PURPLEAIR_READ_KEY')
    WRITE_KEY = os.environ.get('PURPLEAIR_WRITE_KEY')

    MONITOR_FIELDS = ['name', 'private', 'date_created', 'last_modified',
        'model', 'hardware', 'firmware_version', 'firmware_upgrade', 'rssi',
        'location_type', 'latitude', 'longitude', 'altitude',
        'confidence_manual', 'confidence_auto', 'confidence',
        'primary_id_a', 'primary_key_a', 'secondary_id_a', 'secondary_key_a',
        'primary_id_b', 'primary_key_b', 'secondary_id_b', 'secondary_key_b',
    ]

    def get_headers(self, api_key=None, **kwargs):
        headers = {}
        if api_key is not None:
            headers['X-API-Key'] = api_key
        headers.update(kwargs)
        return headers

    def build_url(self, path):
        return urllib.parse.urljoin(self.API_URL, path)

    def decode(self, content):
        return json.JSONDecoder().decode(content.decode('utf-8'))

    def encode(self, obj):
        return json.JSONEncoder().encode(obj)

    def request(self, path, method=None, **kwargs):
        method = method or 'get'
        url = self.build_url(path)
        headers = self.get_headers(
            api_key=kwargs.pop('api_key', None),
            **kwargs.pop('headers', {})
        )

        data = kwargs.pop('json', None)
        if data is not None:
            kwargs['data'] = self.encode(data)
            headers['Content-Type'] = 'application/json'

        return requests.request(method, url, headers=headers, **kwargs)

    def get(self, path, **kwargs):
        api_key = kwargs.pop('api_key', self.READ_KEY)
        return self.request(path, 'get', api_key=api_key, **kwargs)

    def post(self, path, **kwargs):
        api_key = kwargs.pop('api_key', self.WRITE_KEY)
        return self.request(path, 'post', api_key=api_key, **kwargs)

    def check_key(self, api_key=None):
        ''' Check the validity of an API key '''
        api_key = api_key or self.READ_KEY
        response = self.get('/v1/keys')
        return response.json()

    def get_monitors(self, fields=None):
        ''' Get a list of all monitors '''
        fields = fields or self.MONITOR_FIELDS
        response = self.get('/v1/sensors', params={
            'fields': ','.join(fields)
        })
        data = response.json()
        return [dict(zip(data['fields'], monitor)) for monitor in data['data']]

    def get_monitor(self, sensor_index, read_key=None):
        ''' Get a monitor by sensor_index '''
        params = {'fields': ','.join(self.MONITOR_FIELDS)}
        if read_key is not None:
            params['read_key'] = read_key

        response = self.get(f'/v1/sensors/{sensor_index}', params=params)
        data = response.json()
        return data['sensor']

    def find_monitor(self, name):
        ''' Lookup a monitor by name '''
        name = name.lower().strip()
        for monitor in self.get_monitors():
            if monitor['name'].lower().strip() == name:
                monitor

    def get_channels(self, data):
        return {
            device: {
                'primary': thingspeak.Channel(
                    id=data[f'primary_id_{device}'],
                    api_key=data[f'primary_key_{device}'],
                ),
                'secondary': thingspeak.Channel(
                    id=data[f'secondary_id_{device}'],
                    api_key=data[f'secondary_key_{device}'],
                )
            }
            for device in ('a', 'b')
        }


    def get_feed(self, channel, **options):
        try:
            response = json.loads(channel.get(options=options))
        except json.decoder.JSONDecodeError:
            return []

        for entry in response['feeds']:
            data = dict(
                entry_id=entry['entry_id'],
                created_at=parse_datetime(entry['created_at']),
                **dict((
                    (response['channel'][f'field{x}'], entry[f'field{x}'])
                    for x in range(1, 9)
                ))
            )

            yield data

    def get_feeds(self, channels, **options):
        return zip(
            self.get_feed(channels['primary'], **options),
            self.get_feed(channels['secondary'], **options),
        )


purpleair_api = NewPurpleAirAPI()
