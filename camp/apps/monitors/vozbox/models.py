from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.utils.translation import gettext_lazy as _

from camp.apps.calibrations import processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor


class VOZBox(Monitor):
    DATA_PROVIDERS = [{'name': 'CCEJN', 'url': 'https://ccejn.org/'}]
    DATA_SOURCE = {'name': 'VOZbox', 'url': 'https://ccejn.org/'}

    # Devices genuinely report every 10 min -- this stays accurate for
    # expected_hourly_entries (QA completeness), alert window sizing, and
    # calibration training, which all need the true per-row cadence, not
    # how often we can actually fetch new data (see LAST_ACTIVE_LIMIT).
    EXPECTED_INTERVAL = '10 min'

    # Upstream (QuinnResearch's GitHub repo) only publishes once per hour,
    # ~5 min after the hour closes, and the published file is dated for
    # the *previous* hour's readings -- so a reading taken at :00 isn't
    # visible to us until ~65 min later. 1h (the base default) is too
    # tight and would flap "active" status on totally normal devices.
    LAST_ACTIVE_LIMIT = int(60 * 60 * 1.5)

    GRADE = Monitor.Grade.LCS

    ENTRY_CONFIG = {
        entry_models.PM10: {
            'sensors': ['plantower', 'sensirion'],
            'allowed_stages': [entry_models.PM10.Stage.RAW],
            'default_stage': entry_models.PM10.Stage.RAW,
        },
        # Two physical PM sensors -- a Plantower PMS (m_PM*_ATM columns) and
        # a Sensirion SEN5x (m_PM*_b columns). They are *not* a matched
        # A/B pair, so the PurpleAir-style A/B correction + spike cleaning
        # doesn't apply. Both are stored RAW only, for side-by-side
        # comparison; neither is published on the map (no DefaultCalibration
        # row for vozbox/pm25), and no health checks are scored.
        entry_models.PM25: {
            'sensors': ['plantower', 'sensirion'],
            'allowed_stages': [entry_models.PM25.Stage.RAW],
            'default_stage': entry_models.PM25.Stage.RAW,
        },
        entry_models.PM100: {
            'sensors': ['plantower', 'sensirion'],
            'allowed_stages': [entry_models.PM100.Stage.RAW],
            'default_stage': entry_models.PM100.Stage.RAW,
        },
        entry_models.Temperature: {
            'sensors': ['1'],
            'allowed_stages': [entry_models.Temperature.Stage.RAW],
            'default_stage': entry_models.Temperature.Stage.RAW,
        },
        entry_models.Humidity: {
            'sensors': ['1'],
            'allowed_stages': [entry_models.Humidity.Stage.RAW],
            'default_stage': entry_models.Humidity.Stage.RAW,
        },
        entry_models.O3: {
            'sensors': ['1'],
            'allowed_stages': [
                entry_models.O3.Stage.RAW,
                entry_models.O3.Stage.CALIBRATED,
            ],
            'default_stage': entry_models.O3.Stage.CALIBRATED,
            'processors': {
                entry_models.O3.Stage.RAW: [processors.O3_VOZBox],
            },
            # Calibrated entries created outside the per-entry pipeline
            # (QuinnResearch's own o3_cal); listed so DefaultCalibration
            # can offer it.
            'calibrations': [processors.VOZBox_QuinnCal],
        },
    }

    sensor_id = models.CharField(_('sensor ID'), max_length=64, unique=True)

    class Meta:
        verbose_name = 'VOZbox'

    def supports_health_checks(self):
        # Dual-channel health checks assume two identical PM2.5 sensors;
        # the Plantower/Sensirion pair here isn't one. See ENTRY_CONFIG.
        return False

    def update_data(self, row):
        if not self.name:
            self.name = self.sensor_id
        if row.get('latitude') is not None and row.get('longitude') is not None:
            self.position = Point(float(row['longitude']), float(row['latitude']), srid=4326)
        self.location = self.LOCATION.outside

    def create_entries(self, row):
        timestamp = row['timestamp']
        entries = []

        dual_channel = {
            'plantower': {
                entry_models.PM10: {'value': row.get('pm1_plantower')},
                entry_models.PM25: {'value': row.get('pm25_plantower')},
                entry_models.PM100: {'value': row.get('pm10_plantower')},
            },
            'sensirion': {
                entry_models.PM10: {'value': row.get('pm1_sensirion')},
                entry_models.PM25: {'value': row.get('pm25_sensirion')},
                entry_models.PM100: {'value': row.get('pm10_sensirion')},
            },
        }
        single_channel = {
            entry_models.Temperature: {'celsius': row.get('temperature')},
            entry_models.Humidity: {'value': row.get('humidity')},
            entry_models.O3: {'value': row.get('o3')},
        }

        for sensor, model_map in dual_channel.items():
            for EntryModel, data in model_map.items():
                entry = self.create_entry(EntryModel, timestamp=timestamp, sensor=sensor, **data)
                if entry is not None:
                    entries.append(entry)

        for EntryModel, data in single_channel.items():
            entry = self.create_entry(EntryModel, timestamp=timestamp, sensor='1', **data)
            if entry is not None:
                entries.append(entry)

        return entries

    def create_entry(self, EntryModel, **data):
        skip_keys = {'timestamp', 'sensor'}
        values = {k: v for k, v in data.items() if k not in skip_keys}
        if any(v is None for v in values.values()):
            return None
        return super().create_entry(EntryModel, **data)
