from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO

import pytest

from django.core.management import call_command, CommandError
from django.test import TestCase
from django.utils import timezone

from camp.apps.entries import models as entry_models
from django.contrib.admin import site as admin_site

from camp.apps.monitors.bam.admin import BAM1022Admin
from camp.apps.monitors.bam.models import BAM1022, BAMStatus
from camp.apps.monitors.models import LatestEntry
from camp.utils.datetime import parse_datetime

StatusCode = BAM1022.StatusCode


def utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


def local(*args):
    '''A moment as handle_payload reads a payload's Time (naive, treated as UTC).'''
    return parse_datetime(datetime(*args).strftime('%Y-%m-%d %H:%M:%S'))


def payload(moment, status=None, pm25='12.5'):
    moment = timezone.localtime(moment)
    data = {
        'Time': moment.strftime('%Y-%m-%d %H:%M:%S'),
        'AT(C)': '20.0',
        'RH(%)': '30.0',
        'BP(mmHg)': '760.0',
        'ConcHR(ug/m3)': pm25,
    }
    if status is not None:
        data['Status'] = status
    return data


class StatusCodeTests(TestCase):
    def test_bits_and_labels(self):
        assert StatusCode.TAPE_BREAK == 1
        assert StatusCode.MAINTENANCE == 512
        assert str(StatusCode.POWER_FAILURE.label) == 'Power failure'

    def test_decode_sum_of_bits(self):
        status = BAMStatus(code=StatusCode(264))
        assert status.codes == [StatusCode.TAPE_ADVANCE, StatusCode.SHORT_SAMPLE]
        assert status.labels == ['Tape advance', 'Short sample']

    def test_zero_has_no_labels(self):
        assert BAMStatus(code=StatusCode(0)).labels == []

    def test_holdoff_codes(self):
        holdoff = BAM1022.HOLDOFF_CODES
        for code in (StatusCode.TAPE_BREAK, StatusCode.POWER_FAILURE, StatusCode.SHORT_SAMPLE, StatusCode.MAINTENANCE):
            assert code & holdoff
        assert not (StatusCode.TAPE_ADVANCE & holdoff)
        assert BAM1022.HOLDOFF_HOURS == 2

    def test_persisted_roundtrip_and_undefined_bits(self):
        monitor = BAM1022.objects.create(name='Test BAM', position='POINT(0 0)', county='Fresno')
        now = utc(2026, 3, 1, 12)
        BAMStatus.objects.create(monitor=monitor, timestamp=now, code=StatusCode(264))
        status = BAMStatus.objects.get(monitor=monitor, timestamp=now)
        assert status.codes == [StatusCode.TAPE_ADVANCE, StatusCode.SHORT_SAMPLE]
        assert BAMStatus.objects.filter(code__has_any=StatusCode.SHORT_SAMPLE).count() == 1
        assert BAMStatus.objects.filter(code__has_any=StatusCode.MAINTENANCE).count() == 0


class HandlePayloadTests(TestCase):
    def setUp(self):
        self.monitor = BAM1022.objects.create(name='Test BAM', position='POINT(0 0)', county='Fresno')
        self.t0 = local(2026, 3, 1, 12)

    def test_zero_status_creates_nothing(self):
        self.monitor.handle_payload(payload(self.t0, '00000'))
        assert not BAMStatus.objects.exists()
        self.monitor.refresh_from_db()
        assert self.monitor.status is None

    def test_missing_blank_and_garbage_status_skipped(self):
        for value in (None, '', '  ', 'abc', '-5'):
            self.monitor.handle_payload(payload(self.t0, value))
        assert not BAMStatus.objects.exists()
        self.monitor.refresh_from_db()
        assert self.monitor.status is None

    def test_nonzero_status_creates_row_and_pointer(self):
        self.monitor.handle_payload(payload(self.t0, '00512'))
        status = BAMStatus.objects.get()
        assert status.timestamp == self.t0
        assert status.code == StatusCode.MAINTENANCE
        self.monitor.refresh_from_db()
        assert self.monitor.status == status

    def test_combined_status(self):
        self.monitor.handle_payload(payload(self.t0, '00264'))
        assert BAMStatus.objects.get().codes == [StatusCode.TAPE_ADVANCE, StatusCode.SHORT_SAMPLE]

    def test_pointer_moves_to_newer_and_clears_on_ok(self):
        self.monitor.handle_payload(payload(self.t0, '00512'))
        self.monitor.handle_payload(payload(self.t0 + timedelta(hours=1), '00128'))
        self.monitor.refresh_from_db()
        assert self.monitor.status.code == StatusCode.POWER_FAILURE

        self.monitor.handle_payload(payload(self.t0 + timedelta(hours=2), '00000'))
        self.monitor.refresh_from_db()
        assert self.monitor.status is None
        assert BAMStatus.objects.count() == 2

    def test_backfill_does_not_move_pointer(self):
        self.monitor.handle_payload(payload(self.t0 + timedelta(hours=5), '00128'))
        self.monitor.handle_payload(payload(self.t0, '00512'))
        self.monitor.refresh_from_db()
        assert self.monitor.status.code == StatusCode.POWER_FAILURE
        assert BAMStatus.objects.count() == 2  # the backfilled row is still stored

    def test_backfill_ok_does_not_clear_pointer(self):
        self.monitor.handle_payload(payload(self.t0 + timedelta(hours=5), '00128'))
        self.monitor.handle_payload(payload(self.t0, '00000'))
        self.monitor.refresh_from_db()
        assert self.monitor.status is not None

    def test_pointer_not_moved_without_status_field(self):
        self.monitor.handle_payload(payload(self.t0, '00512'))
        self.monitor.handle_payload(payload(self.t0 + timedelta(hours=1)))
        self.monitor.refresh_from_db()
        assert self.monitor.status is not None

    def test_ok_reupload_deletes_existing_row(self):
        self.monitor.handle_payload(payload(self.t0, '00512'))
        self.monitor.handle_payload(payload(self.t0, '00000'))
        assert not BAMStatus.objects.exists()
        self.monitor.refresh_from_db()
        assert self.monitor.status is None

    def test_reupload_updates_code_in_place(self):
        self.monitor.handle_payload(payload(self.t0, '00512'))
        self.monitor.handle_payload(payload(self.t0, '00128'))
        assert BAMStatus.objects.get().code == StatusCode.POWER_FAILURE

    def test_status_exists_before_entries_are_processed(self):
        entries = self.monitor.handle_payload(payload(self.t0, '00512'))
        assert BAMStatus.objects.filter(monitor=self.monitor, timestamp=self.t0).exists()
        pm25 = next(e for e in entries if isinstance(e, entry_models.PM25))
        results = self.monitor.process_entry_pipeline(pm25)
        assert not [e for e in results if e.stage == entry_models.PM25.Stage.CLEANED]


class AdminTests(TestCase):
    def test_current_status_display(self):
        monitor = BAM1022.objects.create(name='Test BAM', position='POINT(0 0)', county='Fresno')
        model_admin = BAM1022Admin(BAM1022, admin_site=admin_site)
        assert model_admin.get_status(monitor) == 'OK'

        monitor.handle_payload(payload(local(2026, 3, 1, 12), '00640'))
        assert model_admin.get_status(monitor).startswith('Power failure, Maintenance')


class ReprocessCommandTests(TestCase):
    '''
    Eight hourly RAW rows with stale CLEANED copies (as the old cleaner left
    them) and a maintenance alarm at hour 2. Rebuilt: hours 0-1 drop (no prior
    history), 2 drops (alarm), 3-4 drop (holdoff), 5-7 are kept.
    '''

    def setUp(self):
        self.monitor = BAM1022.objects.create(name='Test BAM', position='POINT(0 0)', county='Fresno')
        self.t0 = utc(2026, 3, 1, 12)
        self.hours = [self.t0 + timedelta(hours=h) for h in range(8)]
        for moment in self.hours:
            for stage, processor in ((entry_models.PM25.Stage.RAW, ''), (entry_models.PM25.Stage.CLEANED, 'PM25_FEM_Cleaner')):
                entry_models.PM25.objects.create(
                    monitor=self.monitor, timestamp=moment, value=Decimal('40'),
                    stage=stage, processor=processor,
                )
        BAMStatus.objects.create(monitor=self.monitor, timestamp=self.hours[2], code=StatusCode.MAINTENANCE)

    def cleaned_hours(self):
        return list(entry_models.PM25.objects
            .filter(monitor=self.monitor, stage=entry_models.PM25.Stage.CLEANED)
            .order_by('timestamp')
            .values_list('timestamp', flat=True)
        )

    def run_command(self, *extra):
        out = StringIO()
        call_command('reprocess_bam_pm25', f'--monitor-id={self.monitor.pk}', *extra, stdout=out)
        return out.getvalue()

    def test_rebuilds_cleaned_with_current_rules(self):
        output = self.run_command()
        assert self.cleaned_hours() == self.hours[5:]
        assert '8 hours, kept 3, dropped 5' in output

    def test_dry_run_writes_nothing(self):
        output = self.run_command('--dry-run')
        assert self.cleaned_hours() == self.hours
        assert 'would keep 3, dropped 5' in output

    def test_idempotent(self):
        self.run_command()
        self.run_command()
        assert self.cleaned_hours() == self.hours[5:]

    def test_range_limits_what_is_rebuilt(self):
        self.run_command(f'--start={self.hours[3].isoformat()}', f'--end={self.hours[5].isoformat()}')
        assert self.cleaned_hours() == self.hours[:3] + self.hours[5:]

    def test_latest_entry_repointed_when_newest_hour_dropped(self):
        BAMStatus.objects.create(monitor=self.monitor, timestamp=self.hours[7], code=StatusCode.FLOW_FAILURE)
        self.run_command()
        latest = LatestEntry.objects.get(
            monitor_id=self.monitor.pk, entry_type=entry_models.PM25.entry_type,
            stage=entry_models.PM25.Stage.CLEANED,
        )
        assert latest.timestamp == self.hours[6]
        assert latest.entry.timestamp == self.hours[6]

    def test_unknown_monitor(self):
        with pytest.raises(CommandError):
            call_command('reprocess_bam_pm25', '--monitor-id=nope', stdout=StringIO())
