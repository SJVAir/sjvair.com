import time
import uuid

from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import models

from resticus.encoders import JSONEncoder

from camp.apps.monitors.models import Monitor, Entry
from camp.utils.datetime import parse_datetime

# ConcRT(ug/m3): real-time PM2.5 concentration (measurements are recorded every minute, but the ConcRT can be set at 5, 10, 15 minute intervals, in which case RT becomes an average of the previous 5, 10 or 15 minutes)
# ConcHR(ug/m3): average hourly PM2.5 concentration (see attached graph of RT (15 min) vs HR values)
# ConcS(ug/m3): not sure (it may be the Span Scale setting)
# AT(C): external ambient temp (C)
# RH(%): external relative humidity
# BP(mmHg): external barometric pressure
# FT(C): filter temperature (C)
# FRH(%): filter relative humidity

class BAM1022(Monitor):
    class Meta:
        verbose_name = 'BAM 1022'

    def create_entry(self, payload, sensor=None):
        timestamp = parse_datetime(payload['Time'])
        if self.entries.filter(timestamp=timestamp).exists():
            raise ValidationError('An entry for this timestamp has already been recorded.')
        return super().create_entry(payload=payload, sensor=sensor)

    def process_entry(self, entry):
        attr_map = {
            'celcius': 'AT(C)',
            'humidity': 'RH(%)',
            'pressure': 'BP(mmHg)',
            'pm25_env': 'ConcRT(ug/m3)',
        }

        for attr, key in attr_map.items():
            setattr(entry, attr, entry.payload[key])

        entry.timestamp = parse_datetime(entry.payload['Time'])
        return super().process_entry(entry)


