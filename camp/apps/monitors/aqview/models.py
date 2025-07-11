import pytz

from datetime import datetime, timedelta

from camp.apps.calibrations import processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor
from camp.utils.datetime import make_aware


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

    class Meta:
        verbose_name = 'AQview'

    def handle_payload(self, payload):
        timestamp = make_aware(
            datetime.fromtimestamp(payload['maptime'] / 1000) - timedelta(hours=payload['hourindex']),
            pytz.timezone('America/Los_Angeles')
        )
        return super().create_entry(entry_models.PM25,
            timestamp=timestamp,
            value=payload['aobs'],
        )


    # Legacy
    def process_entry(self, entry, payload):
        entry.timestamp = make_aware(
            datetime.fromtimestamp(payload['maptime'] / 1000) - timedelta(hours=payload['hourindex']),
            pytz.timezone('America/Los_Angeles')
        )
        entry.pm25 = payload['aobs']
        entry.pm25_reported = payload['aobs']
        return super().process_entry(entry, payload)
