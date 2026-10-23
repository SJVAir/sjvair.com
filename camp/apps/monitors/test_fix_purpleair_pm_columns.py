from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.entries import models as entry_models
from camp.apps.monitors.legacy_backfill import PM_COLUMN_CUTOVER
from camp.apps.monitors.purpleair.models import PurpleAir

RAW = entry_models.PM10.Stage.RAW
OLD = datetime(2019, 6, 1, 12, tzinfo=dt_timezone.utc)


def _make(model, monitor, timestamp, value, sensor='a'):
    return model.objects.create(
        monitor=monitor, sensor=sensor, timestamp=timestamp, location=monitor.location,
        stage=RAW, processor='', value=Decimal(value),
    )


def _value(model, monitor, timestamp, sensor='a'):
    return model.objects.get(monitor=monitor, sensor=sensor, timestamp=timestamp, stage=RAW).value


def _run(*args):
    out = StringIO()
    call_command('fix_purpleair_pm_columns', *args, stdout=out)
    return out.getvalue()


class FixPurpleAirPmColumnsTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()

    def _pair(self, timestamp, pm10, pm100, monitor=None, sensor='a'):
        monitor = monitor or self.monitor
        _make(entry_models.PM10, monitor, timestamp, pm10, sensor)
        _make(entry_models.PM100, monitor, timestamp, pm100, sensor)

    def test_swaps_reversed_pre_cutover_pair(self):
        self._pair(OLD, '9', '3')
        output = _run()
        assert _value(entry_models.PM10, self.monitor, OLD) == Decimal('3')
        assert _value(entry_models.PM100, self.monitor, OLD) == Decimal('9')
        assert 'Swapped 1 of 1 pairs' in output

    def test_leaves_ordered_pair(self):
        self._pair(OLD, '3', '9')
        output = _run()
        assert _value(entry_models.PM10, self.monitor, OLD) == Decimal('3')
        assert _value(entry_models.PM100, self.monitor, OLD) == Decimal('9')
        assert 'Checked 1 pairs: nothing to do' in output

    def test_leaves_post_cutover_pair(self):
        self._pair(PM_COLUMN_CUTOVER, '9', '3')
        _run()
        assert _value(entry_models.PM10, self.monitor, PM_COLUMN_CUTOVER) == Decimal('9')
        assert _value(entry_models.PM100, self.monitor, PM_COLUMN_CUTOVER) == Decimal('3')

    def test_leaves_unpaired_rows(self):
        _make(entry_models.PM10, self.monitor, OLD, '9')
        _make(entry_models.PM100, self.monitor, OLD + timedelta(hours=1), '3')
        # Same timestamp but a different sensor is not a pair either
        _make(entry_models.PM10, self.monitor, OLD + timedelta(hours=2), '9', sensor='a')
        _make(entry_models.PM100, self.monitor, OLD + timedelta(hours=2), '3', sensor='b')
        output = _run()
        assert _value(entry_models.PM10, self.monitor, OLD) == Decimal('9')
        assert _value(entry_models.PM100, self.monitor, OLD + timedelta(hours=1)) == Decimal('3')
        assert _value(entry_models.PM10, self.monitor, OLD + timedelta(hours=2)) == Decimal('9')
        assert 'Checked 0 pairs: nothing to do' in output

    def test_pairs_each_sensor_independently(self):
        self._pair(OLD, '9', '3', sensor='a')
        self._pair(OLD, '2', '5', sensor='b')
        _run()
        assert _value(entry_models.PM10, self.monitor, OLD, 'a') == Decimal('3')
        assert _value(entry_models.PM10, self.monitor, OLD, 'b') == Decimal('2')

    def test_spans_multiple_windows(self):
        later = OLD + timedelta(days=100)
        self._pair(OLD, '9', '3')
        self._pair(later, '8', '4')
        _run('--window-days', '10')
        assert _value(entry_models.PM10, self.monitor, OLD) == Decimal('3')
        assert _value(entry_models.PM10, self.monitor, later) == Decimal('4')

    def test_dry_run_writes_nothing(self):
        self._pair(OLD, '9', '3')
        output = _run('--dry-run')
        assert _value(entry_models.PM10, self.monitor, OLD) == Decimal('9')
        assert _value(entry_models.PM100, self.monitor, OLD) == Decimal('3')
        assert 'Would swap 1 of 1 pairs' in output

    def test_second_run_has_nothing_to_do(self):
        self._pair(OLD, '9', '3')
        _run()
        output = _run()
        assert 'nothing to do' in output
        assert _value(entry_models.PM10, self.monitor, OLD) == Decimal('3')

    def test_monitor_id_scopes_the_repair(self):
        other = PurpleAir.objects.create(name='Other', sensor_id=987654, location='outside')
        self._pair(OLD, '9', '3')
        self._pair(OLD, '9', '3', monitor=other)
        _run('--monitor-id', str(self.monitor.pk))
        assert _value(entry_models.PM10, self.monitor, OLD) == Decimal('3')
        assert _value(entry_models.PM10, other, OLD) == Decimal('9')

    def test_unknown_monitor_id_errors(self):
        with pytest.raises(CommandError):
            _run('--monitor-id', 'AAAAAAAAAAAAAAAAAAAAAA')
