import statistics
import time
import uuid

from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from camp.apps.calibrations import processors
from camp.apps.entries import models as entry_models
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
    LAST_ACTIVE_LIMIT = int(60 * 60 * 1.5)
    ENTRY_UPLOAD_ENABLED = True

    DATA_PROVIDERS = [{
        'name': 'Central California Asthma Collaborative',
        'url': 'https://cencalasthma.org'
    }]

    DATA_SOURCE = {
        'name': 'Central California Asthma Collaborative',
        'url': 'https://cencalasthma.org'
    }

    EXPECTED_INTERVAL = '1 hour'
    ENTRY_CONFIG = {
        entry_models.Temperature: {
            'fields': {'celsius': 'AT(C)'},
            'allowed_stages': [entry_models.Temperature.Stage.RAW],
            'default_stage': entry_models.Temperature.Stage.RAW,
        },
        entry_models.Humidity: {
            'fields': {'value': 'RH(%)'},
            'allowed_stages': [entry_models.Humidity.Stage.RAW],
            'default_stage': entry_models.Humidity.Stage.RAW,
        },
        entry_models.Pressure: {
            'fields': {'mmhg': 'BP(mmHg)'},
            'allowed_stages': [entry_models.Pressure.Stage.RAW],
            'default_stage': entry_models.Pressure.Stage.RAW,
        },
        entry_models.PM25: {
            'fields': {'value': 'ConcHR(ug/m3)'},
            'allowed_stages': [
                entry_models.PM25.Stage.RAW,
                entry_models.PM25.Stage.CLEANED,
            ],
            'default_stage': entry_models.PM25.Stage.CLEANED,
            'processors': {
                entry_models.PM25.Stage.RAW: [processors.PM25_FEM_Cleaner]
            },
            'alerts': {
                'stage': entry_models.PM25.Stage.CLEANED,
                'processor': processors.PM25_FEM_Cleaner,
            }
        },
    }

    grade = Monitor.Grade.FEM

    class Meta:
        verbose_name = 'BAM 1022'

    def handle_payload(self, payload):
        entries = []
        timestamp = parse_datetime(payload['Time'])
        for EntryModel, config in self.ENTRY_CONFIG.items():
            data = {attr: payload[key] for attr, key in config['fields'].items() if key in payload}
            if not data:
                continue

            if entry := self.create_entry(EntryModel, timestamp=timestamp, **data):
                entries.append(entry)

        return entries

    def create_entry_legacy(self, payload, sensor=None):
        timestamp = parse_datetime(payload['Time'])
        try:
            entry = self.entries.get(timestamp=timestamp)
            entry = self.process_entry(entry, payload)
            entry.save()
            return entry
        except Entry.DoesNotExist:
            return super().create_entry_legacy(payload, sensor=sensor)

    def process_entry(self, entry, payload):
        attr_map = {
            'celsius': 'AT(C)',
            'humidity': 'RH(%)',
            'pressure': 'BP(mmHg)',
            'pm25': 'ConcHR(ug/m3)',
            'pm25_reported': 'ConcHR(ug/m3)',
        }

        for attr, key in attr_map.items():
            setattr(entry, attr, payload[key])

        entry.timestamp = parse_datetime(payload['Time'])

        if entry.pm25 == 99999:
            # Bad entry, don't save the error state.
            return

        return super().process_entry(entry, payload)

    def calculate_mass_offset(self, end_time=None):
        '''
            This method analyze the previous 72 hours of data for a
            background determination mass offset. This assumes the
            BAM has been running with the Zero Filter installed for
            the duration of the test.
        '''
        end_time = end_time or timezone.now()
        start_time = end_time - timedelta(hours=72)
        values = list((self.entries
            .filter(timestamp__range=(start_time, end_time))
            .values_list('pm25_reported', flat=True)
        ))
        return {
            'mass_offset': round((statistics.mean(values) * -1) * Decimal('0.001'), 4),
            'stdev': statistics.pstdev(values),
            'variance': statistics.pvariance(values),
            'len': len(values),
            'min': min(values),
            'max': max(values),
            'data': values,
        }
