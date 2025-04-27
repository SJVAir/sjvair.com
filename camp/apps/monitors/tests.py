from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import LatestEntry
from camp.apps.monitors.purpleair.models import PurpleAir


class MonitorTests(TestCase):
    fixtures = ['purple-air.yaml']

    def get_purpleair(self):
        return PurpleAir.objects.get(purple_id=8892)

    # Create your tests here.
    def test_latest_entry_entry_property_and_setter(self):
        monitor = self.get_purpleair()

        # Create a fake PM2.5 entry
        entry = entry_models.PM25.objects.create(
            monitor_id=monitor.pk,
            timestamp='2025-04-27T00:00:00Z',
            sensor='a',
            location='outside',
            stage=entry_models.PM25.Stage.CLEANED,
            processor='PM25_Cleaner',
            value=12.34,
        )

        # Create a LatestEntry and assign the entry
        latest = LatestEntry(monitor_id=entry.monitor_id)
        latest.entry = entry  # triggers the setter

        # Check that fields synced properly
        assert latest.entry_type == entry._meta.model_name
        assert latest.entry_id == entry.pk
        assert latest.stage == entry.stage
        assert latest.processor == entry.processor
        assert latest.timestamp == entry.timestamp

        # Check that the getter returns the same object without re-query
        assert latest.entry.pk == entry.pk
        assert latest.entry is latest._entry  # cached!
