import json
import string

from datetime import datetime, timedelta

import requests
import thingspeak

from django import forms

PURPLE_API_URL = 'https://www.purpleair.com/json'


def parse_datetime(dt, required=False):
    if isinstance(dt, datetime):
        return dt
    return (forms.DateTimeField(required=required)
        .clean(dt.replace('T', ' ').strip('Z')))


def compare_datetimes(dt1, dt2):
    '''
        Returns whether or note two datetimes
        are within 60 seconds of one another.
    '''
    dt1, dt2 = sorted((dt1, dt2), reverse=True)
    return ((dt1 - dt2).seconds) < 60


def get_monitors(**kwargs):
    data = requests.get(PURPLE_API_URL, kwargs).json()
    return data['results']


def lookup_device(label):
    label = label.lower().strip()
    for monitor in get_monitors():
        if monitor['Label'].lower().strip() == label:
            return get_devices(monitor['ID'], device['THINGSPEAK_PRIMARY_ID_READ_KEY'])


def get_devices(device_id, thingspeak_key=None):
    kwargs = {'show': device_id}
    if thingspeak_key is not None:
        kwargs['key'] = thingspeak_key

    try:
        return get_monitors(**kwargs) or None
    except (KeyError, json.decoder.JSONDecodeError):
        return None


def get_channels(device_list):
    return {
        string.ascii_lowercase[idx]: {
            'primary': thingspeak.Channel(
                id=device['THINGSPEAK_PRIMARY_ID'],
                api_key=device['THINGSPEAK_PRIMARY_ID_READ_KEY'],
            ),
            'secondary': thingspeak.Channel(
                id=device['THINGSPEAK_SECONDARY_ID'],
                api_key=device['THINGSPEAK_SECONDARY_ID_READ_KEY'],
            )
        }
        for idx, device in enumerate(device_list)
    }


def get_feed(channel, **options):
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


def get_feeds(channels, **options):
    return zip(
        get_feed(channels['primary'], **options),
        get_feed(channels['secondary'], **options),
    )
