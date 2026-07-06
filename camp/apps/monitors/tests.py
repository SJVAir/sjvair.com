from datetime import datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from decimal import Decimal
from unittest.mock import patch

from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import LatestEntry, Monitor
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.datetime import make_aware


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

    def test_filter_healthy_as_of_excludes_future_health_checks(self):
        from camp.apps.qaqc.models import HealthCheck

        monitor = self.get_purpleair()
        as_of = make_aware(datetime(2026, 1, 1, 12, 0))

        # A passing HealthCheck *before* as_of should count...
        HealthCheck.objects.create(monitor=monitor, hour=as_of - timedelta(hours=1), score=3)
        # ...but one *after* as_of must not count toward the as_of query.
        HealthCheck.objects.create(monitor=monitor, hour=as_of + timedelta(hours=1), score=3)

        # threshold=1.0 over 1 hour requires exactly 1 passing check in-window.
        # (filter_healthy/select_health live on MonitorQuerySet, not the manager,
        # so go through get_queryset() the same way MonitorManager.get_active does.)
        healthy_ids = set(Monitor.objects.get_queryset().filter_healthy(
            hours=1, min_score=1, threshold=1.0, as_of=as_of,
        ).values_list('pk', flat=True))

        assert monitor.pk in healthy_ids

        # Now push as_of back before either HealthCheck exists — should be excluded.
        earlier = as_of - timedelta(hours=3)
        healthy_ids = set(Monitor.objects.get_queryset().filter_healthy(
            hours=1, min_score=1, threshold=1.0, as_of=earlier,
        ).values_list('pk', flat=True))

        assert monitor.pk not in healthy_ids
