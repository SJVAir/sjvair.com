from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO

import pytest

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from camp.apps.entries import models as entry_models
from camp.apps.monitors.legacy_backfill import LEGACY_BACKFILL_MAP, find_missing_raw_entries
from camp.apps.monitors.legacy_verify import verify
from camp.apps.monitors.models import Entry
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.datetime import make_aware


def _ts(*args):
    return make_aware(datetime(*args), settings.DEFAULT_TIMEZONE)


def _backfill(monitor, start, end):
    for entry_model, mapping in LEGACY_BACKFILL_MAP[type(monitor)].items():
        missing = find_missing_raw_entries(monitor, entry_model, mapping, start, end)
        entry_model.objects.bulk_create(missing)


class VerifyPurpleAirTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.start = _ts(2023, 1, 1)
        self.end = _ts(2023, 1, 2)
        self.ts = self.start + timedelta(hours=1)
        for sensor, pm25 in (('a', '5.00'), ('b', '6.00')):
            Entry.objects.create(
                monitor=self.monitor, sensor=sensor, timestamp=self.ts,
                location=self.monitor.location, position=self.monitor.position,
                pm25_reported=Decimal(pm25), pm10=Decimal('3.00'), fahrenheit=Decimal('70.5'),
                humidity=Decimal('40.0'), pressure=Decimal('1013.25'),
            )

    def _counts(self, report, entry_type):
        return report.counts[('PurpleAir', entry_type)]

    def test_clean_backfill_passes(self):
        _backfill(self.monitor, self.start, self.end)
        report = verify([self.monitor], self.start, self.end)
        assert not report.failed
        assert self._counts(report, 'PM25')['matched'] == 2
        assert self._counts(report, 'Temperature')['matched'] == 1
        assert self._counts(report, 'Pressure')['matched'] == 1

    def test_missing_row_fails(self):
        _backfill(self.monitor, self.start, self.end)
        entry_models.PM25.objects.filter(monitor=self.monitor, sensor='b').delete()
        report = verify([self.monitor], self.start, self.end)
        assert report.failed
        assert self._counts(report, 'PM25')['missing'] == 1
        assert report.examples[0].kind == 'missing'

    def test_wrong_value_on_backfilled_row(self):
        _backfill(self.monitor, self.start, self.end)
        # Pressure stored as raw hPa instead of mmHg -- the bug fix_purpleair_pressure repairs
        entry_models.Pressure.objects.filter(monitor=self.monitor).update(value=Decimal('1013.25'))
        report = verify([self.monitor], self.start, self.end)
        assert self._counts(report, 'Pressure')['mismatch_backfilled'] == 1
        assert self._counts(report, 'Pressure')['mismatch_live'] == 0

    def test_wrong_value_on_live_row_is_classified_live(self):
        ts = timezone.now().replace(microsecond=0) - timedelta(hours=1)
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=ts,
            location=self.monitor.location, position=self.monitor.position,
            pm25_reported=Decimal('5.00'),
        )
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=ts,
            location=self.monitor.location, position=self.monitor.position,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('7.00'),
        )
        report = verify([self.monitor], ts - timedelta(hours=1), ts + timedelta(hours=1))
        assert self._counts(report, 'PM25')['mismatch_live'] == 1

    def test_near_miss_timestamp(self):
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts + timedelta(seconds=30),
            location=self.monitor.location, position=self.monitor.position,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.00'),
        )
        report = verify([self.monitor], self.start, self.end)
        counts = self._counts(report, 'PM25')
        assert counts['near_miss'] == 1
        assert counts['missing'] == 1  # sensor b has nothing nearby
        assert counts['extra'] == 0

    def test_near_miss_alone_does_not_fail(self):
        # The backfill deliberately skips a legacy row covered by a RAW row within 60s.
        _backfill(self.monitor, self.start, self.end)
        entry_models.PM25.objects.filter(monitor=self.monitor, sensor='a').update(
            timestamp=self.ts + timedelta(seconds=30),
        )
        report = verify([self.monitor], self.start, self.end)
        assert self._counts(report, 'PM25')['near_miss'] == 1
        assert not report.failed

    def test_unknown_sensor_rows_are_skipped_not_missing(self):
        Entry.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts + timedelta(hours=1),
            location=self.monitor.location, position=self.monitor.position,
            pm25_reported=Decimal('5.00'),
        )
        _backfill(self.monitor, self.start, self.end)
        report = verify([self.monitor], self.start, self.end)
        assert self._counts(report, 'PM25')['skipped'] == 1
        assert self._counts(report, 'PM25')['missing'] == 0

    def test_location_mismatch(self):
        _backfill(self.monitor, self.start, self.end)
        entry_models.Humidity.objects.filter(monitor=self.monitor).update(location='inside')
        report = verify([self.monitor], self.start, self.end)
        assert self._counts(report, 'Humidity')['meta_mismatch'] == 1

    def test_ab_disagreement_on_shared_field_is_counted_not_failed(self):
        Entry.objects.filter(monitor=self.monitor, sensor='b').update(humidity=Decimal('41.0'))
        _backfill(self.monitor, self.start, self.end)
        report = verify([self.monitor], self.start, self.end)
        assert self._counts(report, 'Humidity')['legacy_ab_disagree'] == 1
        assert self._counts(report, 'Humidity')['matched'] == 1
        assert not report.failed

    def test_unprocessed_pipeline_rows_counted(self):
        _backfill(self.monitor, self.start, self.end)
        report = verify([self.monitor], self.start, self.end)
        assert self._counts(report, 'PM25')['unprocessed'] == 2
        # PM10 has no processors, so it isn't counted as unprocessed
        assert self._counts(report, 'PM10')['unprocessed'] == 0


class VerifyBamTests(TestCase):
    fixtures = ['bam1022.yaml']

    def setUp(self):
        self.monitor = BAM1022.objects.first()
        self.start = _ts(2023, 1, 1)
        self.end = _ts(2023, 1, 2)

    def test_sentinel_skipped_and_celsius_converted(self):
        Entry.objects.create(
            monitor=self.monitor, timestamp=self.start + timedelta(hours=1),
            location=self.monitor.location, position=self.monitor.position,
            pm25=Decimal('99999'), celsius=Decimal('21.0'),
        )
        _backfill(self.monitor, self.start, self.end)
        report = verify([self.monitor], self.start, self.end)
        assert report.counts[('BAM1022', 'PM25')]['skipped'] == 1
        assert report.counts[('BAM1022', 'PM25')]['missing'] == 0
        assert report.counts[('BAM1022', 'Temperature')]['matched'] == 1
        assert entry_models.Temperature.objects.get(monitor=self.monitor).value == Decimal('69.8')
        assert not report.failed


class VerifyLegacyBackfillCommandTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=_ts(2023, 1, 1, 1),
            location=self.monitor.location, position=self.monitor.position,
            pm25_reported=Decimal('5.00'),
        )

    def test_passes_after_backfill(self):
        _backfill(self.monitor, _ts(2023, 1, 1), _ts(2023, 1, 2))
        out = StringIO()
        call_command('verify_legacy_backfill', '--from', '2023-01-01', '--to', '2023-01-02',
            '--type', 'purpleair', stdout=out)
        assert 'PASS' in out.getvalue()
        assert 'PurpleAir: verifying 1 monitor(s)' in out.getvalue()

    def test_fails_when_rows_missing(self):
        out = StringIO()
        with pytest.raises(CommandError):
            call_command('verify_legacy_backfill', '--from', '2023-01-01', '--to', '2023-01-02',
                '--monitor', str(self.monitor.pk), stdout=out)
        assert '[missing]' in out.getvalue()

    def test_rejects_unknown_monitor(self):
        with pytest.raises(CommandError):
            call_command('verify_legacy_backfill', '--from', '2023-01-01', '--monitor', 'nope',
                stdout=StringIO())
