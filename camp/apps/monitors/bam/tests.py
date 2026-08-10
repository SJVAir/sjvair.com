from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from camp.apps.entries import models as entry_models
from camp.apps.monitors.bam.models import BAM1022


class BamCreateEntrySentinelTests(TestCase):
    fixtures = ['bam1022.yaml']

    def setUp(self):
        self.monitor = BAM1022.objects.first()

    def test_skips_pm25_sentinel_value(self):
        entry = self.monitor.create_entry(
            entry_models.PM25, timestamp='2023-01-01T00:00:00Z', value=Decimal('99999'),
        )
        assert entry is None
        assert not entry_models.PM25.objects.filter(monitor=self.monitor).exists()

    def test_creates_valid_pm25_value(self):
        entry = self.monitor.create_entry(
            entry_models.PM25, timestamp='2023-01-01T00:00:00Z', value=Decimal('12.5'),
        )
        assert entry is not None
        assert entry.value == Decimal('12.5')

    def test_does_not_affect_other_entry_models(self):
        entry = self.monitor.create_entry(
            entry_models.Humidity, timestamp='2023-01-01T00:00:00Z', value=Decimal('50.0'),
        )
        assert entry is not None
        assert entry.value == Decimal('50.0')


class RemoveBamPm25SentinelsCommandTests(TestCase):
    fixtures = ['bam1022.yaml']

    def setUp(self):
        self.monitor = BAM1022.objects.first()

    def _make_chain(self, value, sensor=''):
        raw = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor=sensor, timestamp='2023-01-01T00:00:00Z',
            location=self.monitor.location, stage=entry_models.PM25.Stage.RAW,
            processor='', value=value,
        )
        cleaned = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor=sensor, timestamp=raw.timestamp,
            location=self.monitor.location, stage=entry_models.PM25.Stage.CLEANED,
            processor='PM25_FEM_Cleaner', value=value, origin=raw,
        )
        return raw, cleaned

    def test_removes_sentinel_raw_entry_and_its_descendants(self):
        raw, cleaned = self._make_chain(Decimal('99999'))
        out = StringIO()
        call_command('remove_bam_pm25_sentinels', stdout=out)
        assert not entry_models.PM25.objects.filter(pk=raw.pk).exists()
        assert not entry_models.PM25.objects.filter(pk=cleaned.pk).exists()
        assert 'Removed 2 entries' in out.getvalue()

    def test_leaves_valid_entries_untouched(self):
        raw, cleaned = self._make_chain(Decimal('12.5'))
        call_command('remove_bam_pm25_sentinels')
        assert entry_models.PM25.objects.filter(pk=raw.pk).exists()
        assert entry_models.PM25.objects.filter(pk=cleaned.pk).exists()

    def test_dry_run_does_not_delete(self):
        raw, cleaned = self._make_chain(Decimal('99999'))
        out = StringIO()
        call_command('remove_bam_pm25_sentinels', '--dry-run', stdout=out)
        assert entry_models.PM25.objects.filter(pk=raw.pk).exists()
        assert entry_models.PM25.objects.filter(pk=cleaned.pk).exists()
        assert 'Would remove 2 entries' in out.getvalue()
