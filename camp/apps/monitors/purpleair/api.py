import datetime
import json
import os
from random import random
import time
import urllib.parse

from django.utils import timezone

import requests


def compare_datetimes(dt1, dt2):
    '''
        Returns whether or not two datetimes
        are within 60 seconds of one another.
    '''
    return abs((dt2 - dt1).total_seconds()) < 60


def chunk_date_range(start_date, end_date):
    '''Splits a date range into chunks, each 28 days long.'''

    chunks = []
    current_date = start_date
    while current_date <= end_date:
        period_end_date = current_date + datetime.timedelta(days=27)
        chunk_end_date = min(period_end_date, end_date)
        chunks.append((current_date, chunk_end_date))
        current_date = chunk_end_date + datetime.timedelta(days=1)

    chunks = [(
        datetime.datetime.combine(start_date, datetime.time.min),
        datetime.datetime.combine(end_date, datetime.time.max),
    ) for (start_date, end_date) in chunks]

    return chunks


class PurpleAirAPI:
    API_URL = 'https://api.purpleair.com'
    READ_KEY = os.environ.get('PURPLEAIR_READ_KEY')
    WRITE_KEY = os.environ.get('PURPLEAIR_WRITE_KEY')

    MONITOR_FIELDS = [
        'name', 'private', 'date_created', 'last_modified',
        'model', 'hardware', 'firmware_version', 'firmware_upgrade', 'rssi',
        'location_type', 'latitude', 'longitude', 'altitude',
        'confidence_manual', 'confidence_auto', 'confidence',

        'primary_id_a', 'primary_key_a', 'secondary_id_a', 'secondary_key_a',
        'primary_id_b', 'primary_key_b', 'secondary_id_b', 'secondary_key_b',

        'humidity', 'temperature', 'pressure', 'last_seen',

        'pm1.0_atm_a', 'pm2.5_atm_a', 'pm10.0_atm_a',
        '0.3_um_count_a', '0.5_um_count_a', '1.0_um_count_a',
        '2.5_um_count_a', '5.0_um_count_a', '10.0_um_count_a',

        'pm1.0_atm_b', 'pm2.5_atm_b', 'pm10.0_atm_b',
        '0.3_um_count_b', '0.5_um_count_b', '1.0_um_count_b',
        '2.5_um_count_b', '5.0_um_count_b', '10.0_um_count_b',
    ]

    HISTORY_FIELDS = [
        'humidity', 'temperature', 'pressure',

        'pm1.0_atm_a', 'pm2.5_atm_a', 'pm10.0_atm_a',
        '0.3_um_count_a', '0.5_um_count_a', '1.0_um_count_a',
        '2.5_um_count_a', '5.0_um_count_a', '10.0_um_count_a',

        'pm1.0_atm_b', 'pm2.5_atm_b', 'pm10.0_atm_b',
        '0.3_um_count_b', '0.5_um_count_b', '1.0_um_count_b',
        '2.5_um_count_b', '5.0_um_count_b', '10.0_um_count_b',
    ]

    # Request Construction

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

    # HTTP Methods

    def get(self, path, **kwargs):
        api_key = kwargs.pop('api_key', self.READ_KEY)
        return self.request(path, 'get', api_key=api_key, **kwargs)

    def post(self, path, **kwargs):
        api_key = kwargs.pop('api_key', self.WRITE_KEY)
        return self.request(path, 'post', api_key=api_key, **kwargs)

    def delete(self, path, **kwargs):
        api_key = kwargs.pop('api_key', self.WRITE_KEY)
        return self.request(path, 'delete', api_key=api_key, **kwargs)

    # API Endpoints

    def check_key(self, api_key=None):
        ''' Check the validity of an API key '''
        api_key = api_key or self.READ_KEY
        response = self.get('/v1/keys', api_key=api_key)
        return response.json()

    # Sensors

    def list_sensors(self, fields=None):
        ''' Get a list of all sensors '''
        fields = fields or self.MONITOR_FIELDS
        response = self.get('/v1/sensors', params={
            'fields': ','.join(fields)
        })
        data = response.json()
        return [dict(zip(data['fields'], sensor)) for sensor in data['data']]

    def get_sensor(self, sensor_index, fields=None):
        ''' Get a sensor by sensor_index '''
        fields = fields or self.MONITOR_FIELDS
        response = self.get(f'/v1/sensors/{sensor_index}', params={
            'fields': ','.join(fields)
        })
        data = response.json()
        try:
            return data['sensor']
        except KeyError:
            return None

    def get_sensor_history(self, sensor_index, start_date=None, end_date=None, fields=None):
        ''' Get a sensor's historical entries, batching the
            requests and yielding entries as an iterator.
        '''
        start_date = start_date or (timezone.now().date() - datetime.timedelta(days=28))
        end_date = end_date or timezone.now().date()
        timestamp_chunks = chunk_date_range(start_date, end_date)
        chunk_count = len(timestamp_chunks)

        for i, (start_timestamp, end_timestamp) in enumerate(timestamp_chunks):
            response = self.get(f'/v1/sensors/{sensor_index}/history', params={
                'fields': ','.join(fields or self.HISTORY_FIELDS),
                'start_timestamp': int(start_timestamp.timestamp()),
                'end_timestamp': int(end_timestamp.timestamp()),
                'average': 0,
            })
            data = response.json()

            if data.get('error') == 'RateLimitExceededError':
                print('Rate limit exceeded. Waiting a few seconds...')
                time.sleep(max(1, random() * 10)) # Wait 1-10 seconds
                yield from self.get_sensor_history(sensor_index, start_date, end_date, fields)
                return
            elif data.get('error'):
                print('\n'.join([
                    f'[ERROR] purpleair_api.get_sensor_history({sensor_index}, {start_date}, {end_date}, {fields})',
                    f'\t -> {data}'
                ]))
                return

            # Construct, sort, and yield the results
            timestamp_index = data['fields'].index('time_stamp')
            entries = sorted(data['data'], key=lambda entry: entry[timestamp_index])
            for entry in entries:
                payload = dict(zip(data['fields'], entry))
                payload['sensor_index'] = sensor_index
                yield payload

            # Sleep for an extra second between each
            # request to avoid rate limiting
            if i + 1 < chunk_count:
                time.sleep(1)

    def find_sensor(self, name):
        ''' Lookup a sensor by name '''
        name = name.lower().strip()
        for monitor in self.list_sensors():
            if monitor['name'].lower().strip() == name:
                return monitor

    # Groups

    def list_groups(self):
        response = self.get('/v1/groups')
        return response.json()

    def create_group(self, name):
        response = self.post('/v1/groups', json={'name': name})
        return response.json()

    def get_group(self, group_id):
        response = self.get(f'/v1/groups/{group_id}')
        return response.json()

    def delete_group(self, group_id):
        response = self.delete(f'/v1/groups/{group_id}')
        if not response.ok:
            return response.json()
        return True

    # Group Members

    def list_group_members(self, group_id, fields=None):
        fields = fields or self.MONITOR_FIELDS
        response = self.get(f'/v1/groups/{group_id}/members', params={
            'fields': ','.join(fields)
        })
        data = response.json()
        return [dict(zip(data['fields'], sensor)) for sensor in data['data']]

    def create_group_member(self, group_id, sensor_index):
        response = self.post(f'/v1/groups/{group_id}/members',
            json={'sensor_index': sensor_index})
        return response.json()

    def get_group_member(self, group_id, member_id):
        response = self.get(f'/v1/groups/{group_id}/members/{member_id}')
        return response.json()

    def delete_group_member(self, group_id, member_id):
        response = self.delete(f'/v1/groups/{group_id}/members/{member_id}')
        if not response.ok:
            return response.json()
        return True


purpleair_api = PurpleAirAPI()
