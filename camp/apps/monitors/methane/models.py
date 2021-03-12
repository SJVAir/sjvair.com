import time
import uuid

from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from resticus.encoders import JSONEncoder

from camp.apps.monitors.models import Monitor, Entry
from camp.utils.datetime import parse_datetime

# id
# bin1
# bin2
# bin3
# bin4
# temp
# rh
# CO_we
# CO_aux
# Figaro2600
# Figaro2602
# Plantower1_pm1_mass
# Plantower1_pm2_5_mass
# Plantower1_pm10_mass
# Plantower1_pm0_3_count
# Plantower1_pm0_5_count
# Plantower1_pm1_count
# Plantower1_pm2_5_count
# Plantower1_pm5_count
# Plantower1_pm10_count
# Plantower2_pm1_mass
# Plantower2_pm2_5_mass
# Plantower2_pm10_mass
# Plantower2_pm0_3_count
# Plantower2_pm0_5_count
# Plantower2_pm1_count
# Plantower2_pm2_5_count
# Plantower2_pm5_count
# Plantower2_pm10_count

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
