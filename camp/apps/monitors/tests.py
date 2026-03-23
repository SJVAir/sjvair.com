from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from decimal import Decimal
from unittest.mock import patch

from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import LatestEntry, Monitor
from camp.apps.monitors.purpleair.models import PurpleAir


class MonitorTests(TestCase):
    fixtures = ['purple-air.yaml']

    def get_purpleair(self):
        return PurpleAir.objects.get(sensor_id=8892)

    def test_get_initial_stage_falls_back_to_raw_when_allowed_stages_missing(self):
        # ENTRY_CONFIG exists for PM25 but has no 'allowed_stages' key
        monitor = self.get_purpleair()
        config_without_stages = {entry_models.PM25: {}}
        with patch.object(type(monitor), 'ENTRY_CONFIG', config_without_stages):
            stage = monitor.get_initial_stage(entry_models.PM25)
        assert stage == entry_models.PM25.Stage.RAW

    def test_get_initial_stage_falls_back_to_raw_when_entry_not_in_config(self):
        # EntryModel is not in ENTRY_CONFIG at all
        monitor = self.get_purpleair()
        with patch.object(type(monitor), 'ENTRY_CONFIG', {}):
            stage = monitor.get_initial_stage(entry_models.PM25)
        assert stage == entry_models.PM25.Stage.RAW

    def test_get_latest_data_returns_entry_data(self):
        monitor = self.get_purpleair()

        entry = entry_models.PM25.objects.create(
            monitor_id=monitor.pk,
            timestamp='2025-04-27T00:00:00Z',
            sensor='a',
            location='outside',
            stage=entry_models.PM25.Stage.CLEANED,
            value=Decimal('12.34'),
        )
        monitor.update_latest_entry(entry)

        data = monitor.get_latest_data()

        assert 'pm25' in data
        assert data['pm25']['value'] == entry.value
        assert data['pm25']['sensor'] == entry.sensor
        assert data['pm25']['stage'] == entry.stage
        assert data['pm25']['processor'] == entry.processor

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
        assert latest.entry_type == entry.entry_type
        assert latest.entry_id == entry.pk
        assert latest.stage == entry.stage
        assert latest.processor == entry.processor
        assert latest.timestamp == entry.timestamp

        # Check that the getter returns the same object without re-query
        assert latest.entry.pk == entry.pk
        assert latest.entry is latest._entry  # cached!
