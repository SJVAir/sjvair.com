import time
import uuid

from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from resticus.encoders import JSONEncoder

from camp.apps.monitors.models import Monitor, Entry
from camp.utils.datetime import parse_datetime


class Methane(Monitor):
    LAST_ACTIVE_LIMIT = 60 * 10

    class Meta:
        verbose_name = 'Methane'

    def create_entry(self, payload, sensor=None):
        # These don't send a timestamp, so assume now.
        payload['timestamp'] = timezone.now()
        return super().create_entry(payload=payload, sensor=sensor)

    def process_entry(self, entry):
        attr_map = {
            # TODO: Figure out the rest of these.
            'celcius': 'temp',
            'humidity': 'rh',
        }

        for attr, key in attr_map.items():
            setattr(entry, attr, entry.payload[key])

        entry.timestamp = parse_datetime(entry.payload['timestamp'])
        return super().process_entry(entry)
