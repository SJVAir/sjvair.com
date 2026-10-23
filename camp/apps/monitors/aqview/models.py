from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from camp.apps.calibrations import processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor


class AQview(Monitor):
    LAST_ACTIVE_LIMIT = int(60 * 60 * 3)

    DATA_PROVIDERS = [{
        'name': 'California Air Resources Board',
        'url': 'https://arb.ca.gov'
    }]
    DATA_SOURCE = {
        'name': 'AQview',
        'url': 'https://aqview.arb.ca.gov/'
    }

    EXPECTED_INTERVAL = '1 hour'
    ENTRY_CONFIG = {
        entry_models.PM25: {
            'fields': {'value': 'aobs'},
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

    class Meta:
        verbose_name = 'AQview'

    @classmethod
    def get_timestamp(cls, payload):
        '''
        The start of the hour a row measures. `maptime` is the end of that
        hour on the local clock, encoded as epoch milliseconds as if the
        local clock were UTC. It already accounts for `hourindex` (each
        row's maptime is the feed's current hour minus its hourindex), so
        that isn't subtracted again. Checked against CARB's AQview download
        tool, whose MeasurementStartTime is the hour start in PST.
        '''
        wall_clock = datetime.fromtimestamp(payload['maptime'] / 1000, tz=dt_timezone.utc).replace(tzinfo=None)
        end = wall_clock.replace(tzinfo=ZoneInfo('America/Los_Angeles')).astimezone(dt_timezone.utc)
        return end - timedelta(hours=1)

    def handle_payload(self, payload):
        return super().create_entry(entry_models.PM25,
            timestamp=self.get_timestamp(payload),
            value=payload['aobs'],
        )


    # Legacy
    def process_entry(self, entry, payload):
        entry.timestamp = self.get_timestamp(payload)
        entry.pm25 = payload['aobs']
        entry.pm25_reported = payload['aobs']
        return super().process_entry(entry, payload)
