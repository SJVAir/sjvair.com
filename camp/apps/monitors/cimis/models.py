from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.gis.db import models

from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor


# CIMIS labels each hourly reading with the hour it ends, in fixed PST
# (no daylight saving), so 0100 is 00:00-01:00 PST and 2400 is 23:00-24:00.
CIMIS_TZ = timezone(timedelta(hours=-8), 'PST')


class CIMIS(Monitor):
    # Readings are stamped at the start of their hour, one hour earlier than
    # the old end-of-hour stamps in PST, so 4h keeps the old 3h lag tolerance.
    LAST_ACTIVE_LIMIT = int(60 * 60 * 4)

    DATA_PROVIDERS = [{
        'name': 'California Department of Water Resources',
        'url': 'https://water.ca.gov',
    }]
    DATA_SOURCE = {
        'name': 'CIMIS',
        'url': 'https://cimis.water.ca.gov/',
    }
    DEVICE = 'CIMIS Weather Station'

    EXPECTED_INTERVAL = '1h'

    # 'summarize': True opts a type into CIMIS monitor summaries (see
    # camp/apps/summaries/selection.py). Wind direction is circular, so a
    # mean of it means nothing: it stays raw-only.
    ENTRY_CONFIG = {
        entry_models.Temperature: {
            'fields': {'value': 'HlyAirTmp'},
            'allowed_stages': [entry_models.Temperature.Stage.RAW],
            'default_stage': entry_models.Temperature.Stage.RAW,
            'summarize': True,
        },
        entry_models.Humidity: {
            'fields': {'value': 'HlyRelHum'},
            'allowed_stages': [entry_models.Humidity.Stage.RAW],
            'default_stage': entry_models.Humidity.Stage.RAW,
            'summarize': True,
        },
        entry_models.DewPoint: {
            'fields': {'value': 'HlyDewPnt'},
            'allowed_stages': [entry_models.DewPoint.Stage.RAW],
            'default_stage': entry_models.DewPoint.Stage.RAW,
            'summarize': True,
        },
        entry_models.SoilTemperature: {
            'fields': {'value': 'HlySoilTmp'},
            'allowed_stages': [entry_models.SoilTemperature.Stage.RAW],
            'default_stage': entry_models.SoilTemperature.Stage.RAW,
            'summarize': True,
        },
        entry_models.WindSpeed: {
            'fields': {'value': 'HlyWindSpd'},
            'allowed_stages': [entry_models.WindSpeed.Stage.RAW],
            'default_stage': entry_models.WindSpeed.Stage.RAW,
            'summarize': True,
        },
        entry_models.WindDirection: {
            'fields': {'value': 'HlyWindDir'},
            'allowed_stages': [entry_models.WindDirection.Stage.RAW],
            'default_stage': entry_models.WindDirection.Stage.RAW,
        },
        entry_models.Precipitation: {
            'fields': {'value': 'HlyPrecip'},
            'allowed_stages': [entry_models.Precipitation.Stage.RAW],
            'default_stage': entry_models.Precipitation.Stage.RAW,
            'summarize': True,
        },
        entry_models.SolarRadiation: {
            'fields': {'value': 'HlySolRad'},
            'allowed_stages': [entry_models.SolarRadiation.Stage.RAW],
            'default_stage': entry_models.SolarRadiation.Stage.RAW,
            'summarize': True,
        },
        entry_models.NetRadiation: {
            'fields': {'value': 'HlyNetRad'},
            'allowed_stages': [entry_models.NetRadiation.Stage.RAW],
            'default_stage': entry_models.NetRadiation.Stage.RAW,
            'summarize': True,
        },
        entry_models.VaporPressure: {
            'fields': {'value': 'HlyVapPres'},
            'allowed_stages': [entry_models.VaporPressure.Stage.RAW],
            'default_stage': entry_models.VaporPressure.Stage.RAW,
            'summarize': True,
        },
        entry_models.ETo: {
            'fields': {'value': 'HlyAsceEto'},
            'allowed_stages': [entry_models.ETo.Stage.RAW],
            'default_stage': entry_models.ETo.Stage.RAW,
            'summarize': True,
        },
        entry_models.ETr: {
            'fields': {'value': 'HlyAsceEtr'},
            'allowed_stages': [entry_models.ETr.Stage.RAW],
            'default_stage': entry_models.ETr.Stage.RAW,
            'summarize': True,
        },
    }

    GRADE = None

    station_number = models.CharField(max_length=20, unique=True)

    class Meta:
        verbose_name = 'CIMIS'

    ENTRY_MAP = {
        config['fields']['value']: EntryModel
        for EntryModel, config in ENTRY_CONFIG.items()
    }

    def parse_timestamp(self, record):
        '''
        The start of the hour the record covers. CIMIS hour labels are
        hour-ending in fixed PST, so 2400 is 23:00 on the record's own date.
        '''
        day = datetime.strptime(record['Date'], '%Y-%m-%d').replace(tzinfo=CIMIS_TZ)
        hour = int(record['Hour'].zfill(4)[:2])
        return day + timedelta(hours=hour - 1)

    def legacy_timestamp(self, record):
        '''
        How readings were stamped before parse_timestamp: the end of the hour
        on the Pacific wall clock. Only for finding those old rows.
        '''
        date_str = record['Date']
        hour_str = record['Hour'].zfill(4)

        if hour_str == '2400':
            base = datetime.strptime(date_str, '%Y-%m-%d') + timedelta(days=1)
            naive = base.replace(hour=0, minute=0)
        else:
            naive = datetime.strptime(f'{date_str} {hour_str}', '%Y-%m-%d %H%M')

        return naive.replace(tzinfo=settings.DEFAULT_TIMEZONE)

    @staticmethod
    def fits_field(EntryModel, value):
        '''
        Whether `value` fits the entry's value column. CIMIS sometimes sends a
        wild reading (e.g. 8460 mbar of vapor pressure); saving one would
        raise and end the rest of the import.
        '''
        field = EntryModel._meta.get_field('value')
        try:
            value = Decimal(value).quantize(Decimal(1).scaleb(-field.decimal_places))
        except InvalidOperation:
            return False
        return abs(value) < 10 ** (field.max_digits - field.decimal_places)

    def handle_payload(self, record):
        timestamp = self.parse_timestamp(record)
        entries = []

        for field_name, EntryModel in self.ENTRY_MAP.items():
            item = record.get(field_name)
            if not item:
                continue

            if item.get('Qc') == 'N':
                continue

            value = item.get('Value')
            if value in (None, '') or not self.fits_field(EntryModel, value):
                continue

            entry = self.create_entry(EntryModel, timestamp=timestamp, value=value)
            if entry:
                entries.append(entry)

        return entries
