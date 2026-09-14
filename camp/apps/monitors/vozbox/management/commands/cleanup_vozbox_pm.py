import time

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Exists, OuterRef

from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import LatestEntry
from camp.apps.monitors.vozbox.models import VOZBox
from camp.apps.qaqc.models import HealthCheck


class Command(BaseCommand):
    help = (
        "Bring VOZbox PM data into the current single-track shape. The old "
        "config treated the Plantower PMS and Sensirion SEN5x as a matched "
        "A/B pair; they aren't, so this (1) renames PM1/PM2.5/PM10 sensors "
        "from 'a'/'b' to 'plantower'/'sensirion', (2) removes the CORRECTED/"
        "CLEANED/CALIBRATED PM2.5 entries and LatestEntry rows the A/B "
        "pipeline produced, and (3) removes the monitors' HealthCheck rows "
        "(monitor.health is SET_NULL). Runs in small, separately-committed "
        "batches so it never holds a long lock on the (large, shared) entry "
        "tables, and prints progress per batch so a Heroku one-off dyno "
        "isn't killed for silence. Idempotent and resumable. A legacy row "
        "whose renamed twin already exists (same monitor, timestamp, stage, "
        "processor) is a duplicate of the same reading and is deleted "
        "instead, so the unique constraint can't trip."
    )

    LEGACY_STAGES = [
        entry_models.PM25.Stage.CORRECTED,
        entry_models.PM25.Stage.CLEANED,
        entry_models.PM25.Stage.CALIBRATED,
    ]

    RENAMES = {'a': 'plantower', 'b': 'sensirion'}
    ENTRY_MODELS = [entry_models.PM10, entry_models.PM25, entry_models.PM100]

    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=5000,
            help='Rows per UPDATE / transaction (default: 5000).')
        parser.add_argument('--sleep', type=float, default=0.0,
            help='Seconds to pause between batches to ease load (default: 0).')
        parser.add_argument('--monitor-id', dest='monitor_ids', action='append', default=[],
            help='Restrict to this VOZbox sensor_id (coreid). Repeatable.')
        parser.add_argument('--dry-run', action='store_true',
            help='Count what would change; write nothing.')

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        sleep = options['sleep']
        dry_run = options['dry_run']

        monitors = VOZBox.objects.order_by('sensor_id')
        if options['monitor_ids']:
            monitors = monitors.filter(sensor_id__in=options['monitor_ids'])

        started = time.monotonic()
        renamed = removed = 0
        for monitor in monitors:
            for EntryModel in self.ENTRY_MODELS:
                for old, new in self.RENAMES.items():
                    renamed += self.rename(monitor, EntryModel, old, new, batch_size, sleep, dry_run)
            removed += self.remove_legacy_stages(monitor, batch_size, sleep, dry_run)
            removed += self.remove_health_checks(monitor, dry_run)

        verb = 'Would rename' if dry_run else 'Renamed'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {renamed} rows, removed {removed} legacy rows in {time.monotonic() - started:.0f}s'
        ))

    def delete_batched(self, label, queryset, batch_size, sleep, dry_run):
        if dry_run:
            count = queryset.count()
            self.stdout.write(f'{label}: {count} rows')
            return count

        deleted = 0
        while True:
            pks = list(queryset.values_list('pk', flat=True)[:batch_size])
            if not pks:
                break
            with transaction.atomic():
                count, _ = queryset.model.objects.filter(pk__in=pks).delete()
            deleted += count
            self.stdout.write(f'{label}: {deleted} removed')
            self.stdout.flush()
            if count < batch_size:
                break
            if sleep:
                time.sleep(sleep)

        if deleted == 0:
            self.stdout.write(f'{label}: nothing to do')
        return deleted

    def remove_legacy_stages(self, monitor, batch_size, sleep, dry_run):
        PM25 = entry_models.PM25
        removed = self.delete_batched(
            f'{monitor.sensor_id} pm25 legacy stages',
            PM25.objects.filter(monitor=monitor, stage__in=self.LEGACY_STAGES),
            batch_size, sleep, dry_run,
        )
        removed += self.delete_batched(
            f'{monitor.sensor_id} pm25 legacy LatestEntry',
            LatestEntry.objects.filter(monitor=monitor, entry_type=PM25.entry_type).exclude(stage=PM25.Stage.RAW),
            batch_size, sleep, dry_run,
        )
        return removed

    def remove_health_checks(self, monitor, dry_run):
        queryset = HealthCheck.objects.filter(monitor=monitor)
        label = f'{monitor.sensor_id} health checks'
        if dry_run:
            count = queryset.count()
            self.stdout.write(f'{label}: {count} rows')
            return count
        with transaction.atomic():
            count, _ = queryset.delete()
        self.stdout.write(f'{label}: {count} removed' if count else f'{label}: nothing to do')
        return count

    def rename(self, monitor, EntryModel, old, new, batch_size, sleep, dry_run):
        label = f'{monitor.sensor_id} {EntryModel.entry_type} {old!r}->{new!r}'
        queryset = EntryModel.objects.filter(monitor=monitor, sensor=old)

        if dry_run:
            count = queryset.count()
            self.stdout.write(f'{label}: {count} rows')
            return count

        twin_exists = Exists(EntryModel.objects.filter(
            monitor=OuterRef('monitor'),
            timestamp=OuterRef('timestamp'),
            stage=OuterRef('stage'),
            processor=OuterRef('processor'),
            sensor=new,
        ))

        renamed = deleted = 0
        while True:
            pks = list(queryset.values_list('pk', flat=True)[:batch_size])
            if not pks:
                break
            with transaction.atomic():
                batch = EntryModel.objects.filter(pk__in=pks)
                dupes, _ = batch.filter(twin_exists).delete()
                updated = batch.update(sensor=new)
            renamed += updated
            deleted += dupes
            self.stdout.write(f'{label}: {renamed} renamed, {deleted} duplicates removed')
            self.stdout.flush()
            if updated + dupes < batch_size:
                break
            if sleep:
                time.sleep(sleep)

        if renamed == 0 and deleted == 0:
            self.stdout.write(f'{label}: nothing to do')
        return renamed
