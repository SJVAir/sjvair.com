from datetime import timedelta
from decimal import Decimal
from random import randint

from django.db.models import Count, Max, Prefetch
from django.test import TestCase
from django.utils import timezone

from camp.apps.entries import models as entry_models

from .api import purpleair_api
from .models import PurpleAir


class PurpleAirTests(TestCase):
    fixtures = ['purple-air.yaml']
    def setUp(self):
        self.monitor = PurpleAir.objects.get(purple_id=8892)

    def test_create_entry_legacy(self):
        payload = purpleair_api.get_sensor(self.monitor.purple_id)
        (a, b) = self.monitor.create_entries_legacy(payload)
        self.monitor.check_latest(a)
        self.monitor.check_latest(b)

        assert a.sensor == 'a'
        assert a.position == self.monitor.position
        assert a.fahrenheit == payload['temperature']

    def test_probable_location_marked_inside(self):
        payload = {'name': 'test', 'location_type': 1}
        assert PurpleAir().get_probable_location(payload) == PurpleAir.LOCATION.inside

    def test_probable_location_marked_outside_name_implies_inside(self):
        payload = {'name': 'test indoor', 'location_type': 0}
        assert PurpleAir().get_probable_location(payload) == PurpleAir.LOCATION.inside

    def test_probable_location_marked_outside(self):
        payload = {'name': 'test outdoor', 'location_type': 0}
        assert PurpleAir().get_probable_location(payload) == PurpleAir.LOCATION.outside

    def test_pipeline_runs_all_stages(self):
        now = timezone.now()

        # Create 3 entries, spaced 1 minute apart, and process them.
        timestamps = [now - timedelta(minutes=(60 - i)) for i in range(-3, 0)]
        for i, ts in enumerate(timestamps):
            rh = self.monitor.create_entry(entry_models.Humidity, timestamp=ts, value=Decimal('45.0'))
            pm25 = self.monitor.create_entry(entry_models.PM25, timestamp=ts, sensor='a', value=Decimal('10') + (i * randint(-1, 1)))
            self.monitor.process_entry_pipeline(rh)
            self.monitor.process_entry_pipeline(pm25)

        entries = entry_models.PM25.objects.filter(monitor_id=self.monitor.pk)
        stages = list(entries.values_list('stage', flat=True))

        # At minimum, expect:
        # - 3 RAW
        # - 3 CORRECTED
        # - 2 CLEANED (only possible for entries 1 and 2)
        # - 2 CALIBRATED (coloc_linreg won't run because we have no sites in the fixtures)
        assert stages.count(entry_models.PM25.Stage.RAW) == 3
        assert stages.count(entry_models.PM25.Stage.CORRECTED) == 3
        assert stages.count(entry_models.PM25.Stage.CLEANED) == 2
        assert stages.count(entry_models.PM25.Stage.CALIBRATED) == 2

        # Make sure the lineage is correctly set.
        for e in entries:
            match e.stage:
                case entry_models.PM25.Stage.RAW:
                    assert e.origin is None

                case entry_models.PM25.Stage.CORRECTED:
                    assert e.origin is not None
                    assert e.origin.stage == entry_models.PM25.Stage.RAW

                case entry_models.PM25.Stage.CLEANED:
                    assert e.origin is not None
                    assert e.origin.stage == entry_models.PM25.Stage.CORRECTED

                case entry_models.PM25.Stage.CALIBRATED:
                    assert e.origin is not None
                    assert e.origin.stage == entry_models.PM25.Stage.CLEANED

    def test_pipeline_handles_filtered_entries(self):
        now = timezone.now()

        # Create 3 minutes of PM2.5 data: the middle one will be filtered out
        timestamps = [now - timedelta(minutes=(60 - i)) for i in range(-3, 0)]
        values = [Decimal('10.0'), Decimal('-999.0'), Decimal('12.0')]  # -999 should be filtered

        for ts, val in zip(timestamps, values):
            rh = self.monitor.create_entry(entry_models.Humidity, timestamp=ts, value=Decimal('45.0'))
            pm25 = self.monitor.create_entry(entry_models.PM25, timestamp=ts, sensor='a', value=val)
            self.monitor.process_entry_pipeline(rh)
            self.monitor.process_entry_pipeline(pm25)

        # Gather all entries
        entries = entry_models.PM25.objects.filter(monitor_id=self.monitor.pk)
        stages = list(entries.values_list('stage', flat=True))

        # We expect:
        # - 3 RAW entries
        # - 2 CORRECTED entries (middle entry filtered out at stage 1)
        # - 1 CLEANED entry (only the final one can be cleaned using its previous)
        # - 1 CALIBRATED entry (from the cleaned one)

        assert stages.count(entry_models.PM25.Stage.RAW) == 3
        assert stages.count(entry_models.PM25.Stage.CORRECTED) == 2
        assert stages.count(entry_models.PM25.Stage.CLEANED) == 1
        assert stages.count(entry_models.PM25.Stage.CALIBRATED) == 1

        # Check lineage
        for e in entries:
            match e.stage:
                case entry_models.PM25.Stage.RAW:
                    assert e.origin is None

                case entry_models.PM25.Stage.CORRECTED:
                    assert e.origin is not None
                    assert e.origin.stage == entry_models.PM25.Stage.RAW

                case entry_models.PM25.Stage.CLEANED:
                    assert e.origin is not None
                    assert e.origin.stage == entry_models.PM25.Stage.CORRECTED

                case entry_models.PM25.Stage.CALIBRATED:
                    assert e.origin is not None
                    assert e.origin.stage == entry_models.PM25.Stage.CLEANED
