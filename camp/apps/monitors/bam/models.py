import statistics
import time
import uuid

from datetime import datetime, timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from django_enum import EnumField
from django_enum.choices import FlagChoices
from django_sqids import SqidsField, shuffle_alphabet

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

    GRADE = Monitor.Grade.FEM

    class StatusCode(FlagChoices):
        '''
        The BAM's `Status` field is the sum of its active alarm bits
        (Met One manual 1022-9805 Rev G, p.64).
        '''
        TAPE_BREAK = 1, _('Tape break')
        BETA_DETECTOR = 2, _('Beta detector failure')
        SENSOR_RANGE = 4, _('Sensor out of range')
        TAPE_ADVANCE = 8, _('Tape advance')
        FLOW_FAILURE = 16, _('Flow failure')
        NOZZLE_FAILURE = 32, _('Nozzle failure')
        DIGITAL_LINK = 64, _('Digital link failure')
        POWER_FAILURE = 128, _('Power failure')
        SHORT_SAMPLE = 256, _('Short sample')
        MAINTENANCE = 512, _('Maintenance')

    # Alarms after which the instrument reads falsely high while it settles.
    # Met One: "disregard the first two hourly PM data sets after power is restored."
    HOLDOFF_CODES = (
        StatusCode.TAPE_BREAK
        | StatusCode.POWER_FAILURE
        | StatusCode.SHORT_SAMPLE
        | StatusCode.MAINTENANCE
    )
    HOLDOFF_HOURS = 2

    # Null means OK; otherwise the latest nonzero status we've received.
    status = models.ForeignKey(
        'bam.BAMStatus',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    class Meta:
        verbose_name = 'BAM 1022'

    def is_disturbed(self, timestamp):
        '''
        True if the PM2.5 record ending at `timestamp` should not be trusted:
        - the record itself carries an alarm,
        - a holdoff alarm fired within the previous HOLDOFF_HOURS, or
        - one of the previous HOLDOFF_HOURS hourly RAW records is missing
          (the instrument was down or skipped; treated like a restart).
        '''
        window = timedelta(hours=self.HOLDOFF_HOURS)
        statuses = self.statuses.filter(timestamp__range=(timestamp - window, timestamp))
        for status_time, code in statuses.values_list('timestamp', 'code'):
            if status_time == timestamp:
                if code:
                    return True
            elif code & self.HOLDOFF_CODES:
                return True

        previous = [timestamp - timedelta(hours=h) for h in range(1, self.HOLDOFF_HOURS + 1)]
        present = (entry_models.PM25.objects
            .filter(monitor=self, stage=entry_models.PM25.Stage.RAW, timestamp__in=previous)
            .values('timestamp').distinct().count()
        )
        return present < len(previous)

    def latest_known_timestamp(self):
        '''
        Timestamp of the newest data we hold for this monitor (latest RAW PM2.5
        entry or recorded status), or None if we hold none.
        '''
        latest = (entry_models.PM25.objects
            .filter(monitor=self, stage=entry_models.PM25.Stage.RAW)
            .order_by('-timestamp')
            .values_list('timestamp', flat=True)
            .first()
        )
        status_time = self.statuses.order_by('-timestamp').values_list('timestamp', flat=True).first()
        return max((t for t in (latest, status_time) if t is not None), default=None)

    def parse_status(self, payload):
        '''Returns the payload's Status as an int, or None if absent or unparseable.'''
        raw = payload.get('Status')
        if raw is None or isinstance(raw, bool):
            return None
        try:
            value = int(str(raw).strip())
        except ValueError:
            return None
        return value if value >= 0 else None

    def record_status(self, timestamp, value):
        '''
        Stores the alarm state for the record ending at `timestamp`. A zero
        value clears any row for that exact timestamp (a re-upload saying OK wins).
        Returns the BAMStatus, or None for OK.
        '''
        if value:
            status, _created = BAMStatus.objects.update_or_create(
                monitor=self,
                timestamp=timestamp,
                defaults={'code': self.StatusCode(value)},
            )
            return status
        BAMStatus.objects.filter(monitor=self, timestamp=timestamp).delete()
        return None

    def handle_status(self, payload, timestamp):
        '''
        Persist the payload's status and move `self.status` if this is the newest
        data. "Newest" means the timestamp is at or after the latest RAW PM2.5
        entry or recorded status already held, so backfills never move the pointer.
        Must run before the payload's entries are created and processed.
        '''
        value = self.parse_status(payload)
        if value is None:
            return

        known = self.latest_known_timestamp()
        is_newest = known is None or timestamp >= known

        status = self.record_status(timestamp, value)
        if is_newest:
            self.status = status
            self.save(update_fields=['status'])

    def handle_payload(self, payload):
        entries = []
        timestamp = parse_datetime(payload['Time'])

        # The status row must exist before the cleaner runs on this hour.
        self.handle_status(payload, timestamp)

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


class BAMStatus(models.Model):
    sqid = SqidsField(alphabet=shuffle_alphabet('bam.BAMStatus'))
    monitor = models.ForeignKey(BAM1022, related_name='statuses', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(_('Timestamp'), help_text=_('End of the hour the record covers.'))
    code = EnumField(BAM1022.StatusCode, verbose_name=_('Status code'))

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'BAM status'
        verbose_name_plural = 'BAM statuses'
        constraints = [
            models.UniqueConstraint(fields=['monitor', 'timestamp'], name='bam_status_unique_monitor_timestamp'),
        ]

    def __str__(self):
        return f'{self.monitor_id} {self.timestamp:%Y-%m-%d %H:%M}: {", ".join(self.labels) or "OK"}'

    @property
    def codes(self):
        return list(self.code)

    @property
    def labels(self):
        return [str(code.label) for code in self.codes]
