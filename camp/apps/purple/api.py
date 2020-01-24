import json

from datetime import timedelta

import requests
import thingspeak

from django import forms

PURPLE_API_URL = 'https://www.purpleair.com/json'

def parse_datetime(dt):
    return (forms.DateTimeField()
        .clean(dt.replace('T', ' ').strip('Z')))


def round_datetime(dt):
    seconds = dt.second + (dt.microsecond / 1000000)
    dt = dt.replace(second=0, microsecond=0)
    if round(seconds * (1. / 60)):
        dt += timedelta(seconds=60)
    return dt


def floor_datetime(dt):
    return dt.replace(second=0, microsecond=0)


def lookup_device(label):
    label = label.lower().strip()
    data = requests.get(PURPLE_API_URL).json()
    for device in data['results']:
        if device['Label'].lower().strip() == label:
            return device


def get_devices(device_id, thingspeak_key=None):
    kwargs = {'show': device_id}
    if thingspeak_key is not None:
        kwargs['key'] = thingspeak_key

    try:
        return requests.get(PURPLE_API_URL, kwargs).json()['results'] or None
    except (KeyError, json.decoder.JSONDecodeError):
        return None


def get_channels(device_list):
    return [thingspeak.Channel(
        id=device['THINGSPEAK_PRIMARY_ID'],
        api_key=device['THINGSPEAK_PRIMARY_ID_READ_KEY']
    ) for device in device_list]


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


def get_correlated_feed(channel_list, **options):
    '''
        Entries are not related to one another across channels, so we round
        the `created_at` fields to the nearest minute to try and find a
        correlation between entries from different channels to create a
        singlular entry.
    '''
    feeds = [get_feed(channel, **options) for channel in channel_list]
    for item in feeds[0]:
        entries = [item]
        rounded = round_datetime(item['created_at'])
        for feed in feeds[1:]:
            try:
                entries.append(next((item for item in feed if round_datetime(item['created_at']) == rounded)))
            except StopIteration:
                continue
        yield entries

