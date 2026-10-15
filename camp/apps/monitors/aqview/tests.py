from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from django.test import TestCase

from camp.apps.entries import models as entry_models
from camp.apps.monitors.aqview.models import AQview
from camp.apps.monitors.aqview.tasks import process_aqview_data
from camp.apps.monitors.models import Entry


class ProcessAqviewDataTests(TestCase):
    def test_writes_entries_app_only(self):
        payload = {
            'countyname': 'Fresno',
            'sitename': 'Fresno - Garland',
            'geometry': SimpleNamespace(x=-119.7729, y=36.7853),
            'externalmonitorid': 'BAM 1022',
            'maptime': datetime(2026, 10, 1, 12).timestamp() * 1000,
            'hourindex': 0,
            'aobs': 12.0,
        }

        process_aqview_data.call_local(payload)

        monitor = AQview.objects.get(name='Fresno - Garland')
        raw = entry_models.PM25.objects.get(monitor=monitor, stage=entry_models.PM25.Stage.RAW)
        assert raw.value == Decimal('12.0')
        assert not Entry.objects.filter(monitor=monitor).exists()
