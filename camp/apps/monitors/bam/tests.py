import importlib
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch

import pytest

from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django_huey import get_queue

from camp.apps.entries import models as entry_models
from camp.apps.monitors.bam import tasks as bam_tasks
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.bam.mirror import MirrorDisabled, check_enabled, mirror_bam_data


MONITOR_ID = 'GgeFGbo-Tjy3YYQqY0DLyA'

MONITOR_PAYLOAD = {
    'id': MONITOR_ID,
    'name': 'CCAC BAM - Avenal',
    'type': 'bam1022',
    'device': 'BAM 1022',
    'is_active': True,
    'is_sjvair': True,
    'position': {'type': 'Point', 'coordinates': [-120.13, 36.01]},
    'location': 'outside',
    'county': 'Kings',
}


def entry(entry_type, timestamp, **data):
    return {
        'timestamp': timestamp,
        'sensor': '',
        'stage': 'raw',
        'processor': '',
        'entry_type': entry_type,
        **data,
    }


ENTRIES = {
    'pm25': [
        entry('pm25', '2026-09-14T09:00:00-07:00', value='6.70'),
        entry('pm25', '2026-09-14T08:00:00-07:00', value='-2.00'),
    ],
    'temperature': [
        entry('temperature', '2026-09-14T09:00:00-07:00', temperature_f='63.0', temperature_c='17.2'),
    ],
    'humidity': [
        entry('humidity', '2026-09-14T09:00:00-07:00', value='45.0'),
    ],
    'pressure': [
        entry('pressure', '2026-09-14T09:00:00-07:00', pressure_mmhg='736.80', pressure_hpa='982.3'),
    ],
}


class FakeMonitorsResource:
    def list(self, **params):
        FakeClient.monitor_calls.append(params)
        yield MONITOR_PAYLOAD

    def entries(self, monitor_id, entry_type, **params):
        FakeClient.entry_calls.append((monitor_id, entry_type, params))
        yield from ENTRIES.get(entry_type, [])


class FakeClient:
    '''Stands in for sjvair.SJVAirClient (the PyPI package).'''
    monitor_calls = []
    entry_calls = []

    def __init__(self, base_url=None, **kwargs):
        self.base_url = base_url
        self.monitors = FakeMonitorsResource()
        FakeClient.monitor_calls = []
        FakeClient.entry_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


START = datetime(2026, 9, 14, 15, 0, tzinfo=dt_timezone.utc)
END = START + timedelta(hours=3)


@override_settings(BAM_MIRROR_ENABLED=True, DOMAIN='https://staging.sjvair.com')
@patch('camp.apps.monitors.bam.mirror.SJVAirClient', FakeClient)
class MirrorBamDataTests(TestCase):
    def test_creates_monitor_with_source_id(self):
        results = mirror_bam_data(START, END)

        monitor = BAM1022.objects.get(pk=MONITOR_ID)
        assert monitor.name == 'CCAC BAM - Avenal'
        assert monitor.county == 'Kings'
        assert monitor.location == 'outside'
        assert monitor.is_sjvair is True
        assert monitor.position.x == pytest.approx(-120.13)
        assert len(results) == 1
        assert str(results[0][0].pk) == str(monitor.pk)
        assert results[0][1:] == (True, 5)

    def test_requests_bam_monitors_and_raw_entries_in_range(self):
        mirror_bam_data(START, END)

        assert FakeClient.monitor_calls == [{'device': 'BAM1022'}]
        assert len(FakeClient.entry_calls) == 4
        monitor_id, entry_type, params = FakeClient.entry_calls[0]
        assert str(monitor_id) == MONITOR_ID
        assert params == {'stage': 'raw', 'timestamp__gte': START.isoformat(), 'timestamp__lt': END.isoformat()}
        assert {c[1] for c in FakeClient.entry_calls} == {'pm25', 'temperature', 'humidity', 'pressure'}

    def test_imports_raw_entries_and_runs_pipeline(self):
        mirror_bam_data(START, END)
        monitor = BAM1022.objects.get(pk=MONITOR_ID)

        raw = entry_models.PM25.objects.filter(monitor=monitor, stage='raw').order_by('timestamp')
        assert [str(e.value) for e in raw] == ['-2.00', '6.70']

        cleaned = entry_models.PM25.objects.filter(monitor=monitor, stage='cleaned').order_by('timestamp')
        assert [str(e.value) for e in cleaned] == ['0.00', '6.70']

        temperature = entry_models.Temperature.objects.get(monitor=monitor)
        assert str(temperature.celsius) == '17.2'
        assert temperature.stage == 'raw'

        assert entry_models.Humidity.objects.get(monitor=monitor).value == 45
        assert str(entry_models.Pressure.objects.get(monitor=monitor).mmhg) == '736.80'

        # Latest entry should point at the CLEANED pm25 value (the default stage)
        latest = monitor.latest_entries.get(entry_type='pm25')
        assert latest.entry.stage == 'cleaned'
        assert str(latest.entry.value) == '6.70'

    def test_rerun_is_idempotent(self):
        mirror_bam_data(START, END)
        results = mirror_bam_data(START, END)

        assert results[0][1] is False
        assert results[0][2] == 0
        assert entry_models.PM25.objects.filter(monitor_id=MONITOR_ID).count() == 4

    def test_updates_existing_monitor(self):
        BAM1022.objects.create(id=MONITOR_ID, name='Old name', location='outside')
        mirror_bam_data(START, END)
        assert BAM1022.objects.get(pk=MONITOR_ID).name == 'CCAC BAM - Avenal'

    def test_monitor_ids_filter(self):
        results = mirror_bam_data(START, END, monitor_ids=['nope'])
        assert results == []
        assert not BAM1022.objects.filter(pk=MONITOR_ID).exists()


class CheckEnabledTests(TestCase):
    def test_disabled_by_default(self):
        with pytest.raises(MirrorDisabled, match='disabled'):
            check_enabled()

    @override_settings(BAM_MIRROR_ENABLED=True, DOMAIN='https://www.sjvair.com')
    def test_refuses_to_mirror_from_self(self):
        with pytest.raises(MirrorDisabled, match='itself'):
            check_enabled()

    @override_settings(BAM_MIRROR_ENABLED=True, DOMAIN='https://staging.sjvair.com')
    def test_enabled_on_staging(self):
        check_enabled()


@override_settings(BAM_MIRROR_ENABLED=True, DOMAIN='https://staging.sjvair.com')
class MirrorBamEntriesCommandTests(TestCase):
    @patch('camp.apps.monitors.bam.mirror.SJVAirClient', FakeClient)
    def test_command_with_range(self):
        out = StringIO()
        call_command('mirror_bam_entries', start='2026-09-14T15:00', end='2026-09-14T18:00', stdout=out)
        assert BAM1022.objects.filter(pk=MONITOR_ID).exists()
        assert 'Done: 1 monitor, 5 raw entries.' in out.getvalue()
        _, _, params = FakeClient.entry_calls[0]
        assert params['timestamp__gte'] == START.isoformat()
        assert params['timestamp__lt'] == END.isoformat()

    @patch('camp.apps.monitors.bam.management.commands.mirror_bam_entries.mirror_bam_data')
    def test_command_defaults_to_most_recent_hour(self, mock_mirror):
        mock_mirror.return_value = []
        now = datetime(2026, 9, 14, 18, 30, tzinfo=dt_timezone.utc)
        with patch('camp.apps.monitors.bam.management.commands.mirror_bam_entries.timezone.now', return_value=now):
            call_command('mirror_bam_entries', stdout=StringIO())
        kwargs = mock_mirror.call_args.kwargs
        assert kwargs['end'] == now
        assert kwargs['start'] == now - timedelta(hours=1)

    @patch('camp.apps.monitors.bam.management.commands.mirror_bam_entries.mirror_bam_data')
    def test_command_start_only_ends_now(self, mock_mirror):
        mock_mirror.return_value = []
        now = datetime(2026, 9, 14, 18, 30, tzinfo=dt_timezone.utc)
        with patch('camp.apps.monitors.bam.management.commands.mirror_bam_entries.timezone.now', return_value=now):
            call_command('mirror_bam_entries', start='2026-09-14T10:00', stdout=StringIO())
        kwargs = mock_mirror.call_args.kwargs
        assert kwargs['start'] == datetime(2026, 9, 14, 10, 0, tzinfo=dt_timezone.utc)
        assert kwargs['end'] == now

    def test_command_rejects_inverted_range(self):
        with pytest.raises(CommandError):
            call_command('mirror_bam_entries', start='2026-09-14T18:00', end='2026-09-14T15:00')

    def test_command_rejects_bad_timestamp(self):
        with pytest.raises(CommandError):
            call_command('mirror_bam_entries', start='yesterday')

    @override_settings(BAM_MIRROR_ENABLED=False)
    def test_command_disabled_by_default(self):
        with pytest.raises(CommandError, match='disabled'):
            call_command('mirror_bam_entries')


def reload_tasks(enabled):
    """
    The task is registered at import time, so re-import the tasks module
    under the given setting. Huey refuses duplicate registrations, so any
    existing task is unregistered first.
    """
    task = getattr(bam_tasks, 'mirror_bam_entries', None)
    if task is not None:
        get_queue('primary')._registry.unregister(task.task_class)
    with override_settings(BAM_MIRROR_ENABLED=enabled):
        importlib.reload(bam_tasks)


class MirrorBamEntriesTaskTests(TestCase):
    def tearDown(self):
        reload_tasks(enabled=False)

    def test_task_not_registered_when_disabled(self):
        reload_tasks(enabled=False)
        assert not hasattr(bam_tasks, 'mirror_bam_entries')
        assert 'camp.apps.monitors.bam.tasks.mirror_bam_entries' not in get_queue('primary')._registry._registry

    def test_task_registered_when_enabled(self):
        reload_tasks(enabled=True)
        assert hasattr(bam_tasks, 'mirror_bam_entries')
        assert 'camp.apps.monitors.bam.tasks.mirror_bam_entries' in get_queue('primary')._registry._registry

    def test_task_passes_explicit_three_hour_range(self):
        reload_tasks(enabled=True)
        now = datetime(2026, 9, 14, 18, 20, tzinfo=dt_timezone.utc)
        with patch('camp.apps.monitors.bam.tasks.call_command') as mock_call, \
             patch('camp.apps.monitors.bam.tasks.timezone.now', return_value=now):
            bam_tasks.mirror_bam_entries.call_local()
        mock_call.assert_called_once_with(
            'mirror_bam_entries',
            start='2026-09-14T15:20:00+00:00',
            end='2026-09-14T18:20:00+00:00',
        )
