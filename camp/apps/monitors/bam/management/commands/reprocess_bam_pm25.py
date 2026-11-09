from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from camp.apps.calibrations import processors
from camp.apps.entries.models import PM25
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.models import LatestEntry
from camp.utils.datetime import parse_datetime


class Command(BaseCommand):
    help = (
        'Rebuild CLEANED PM2.5 for BAM 1022 monitors from their RAW entries, so '
        'the current cleaner rules (alarm status, post-maintenance holdoff, gaps) '
        'apply to history. Run after backfilling statuses with the uploader\'s '
        '`send_report --type all`. Works one day at a time, each in its own '
        'transaction, oldest first.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--monitor-id', action='append', dest='monitor_ids',
            help='Only this monitor (repeatable). Defaults to all BAM 1022 monitors.')
        parser.add_argument('--start', help='Only RAW entries at or after this timestamp (UTC if naive).')
        parser.add_argument('--end', help='Only RAW entries before this timestamp (UTC if naive).')
        parser.add_argument('--dry-run', action='store_true',
            help='Report how many hours would be kept or dropped; write nothing.')

    def handle(self, *args, **options):
        start = self.parse(options['start'])
        end = self.parse(options['end'])
        if start and end and start >= end:
            raise CommandError('--start must be before --end')

        if options['monitor_ids']:
            monitors = [self.get_monitor(monitor_id) for monitor_id in options['monitor_ids']]
        else:
            monitors = BAM1022.objects.order_by('name')

        for monitor in monitors:
            raw = PM25.objects.filter(monitor=monitor, stage=PM25.Stage.RAW)
            if start:
                raw = raw.filter(timestamp__gte=start)
            if end:
                raw = raw.filter(timestamp__lt=end)

            kept = dropped = 0
            for day, entries in self.by_day(raw.order_by('timestamp')):
                if options['dry_run']:
                    results = [processors.PM25_FEM_Cleaner(entry).process() for entry in entries]
                    day_kept = sum(1 for result in results if result is not None)
                else:
                    day_kept = self.rebuild(monitor, entries)
                kept += day_kept
                dropped += len(entries) - day_kept

            if not options['dry_run']:
                self.refresh_latest(monitor)

            verb = 'would keep' if options['dry_run'] else 'kept'
            self.stdout.write(f'{monitor.name}: {kept + dropped} hours, {verb} {kept}, dropped {dropped}')

    def get_monitor(self, monitor_id):
        try:
            return BAM1022.objects.get(pk=monitor_id)
        except (BAM1022.DoesNotExist, ValidationError):
            raise CommandError(f'Unknown BAM 1022 monitor: {monitor_id}')

    def by_day(self, queryset):
        day, batch = None, []
        for entry in queryset.iterator():
            if day is not None and entry.timestamp.date() != day:
                yield day, batch
                batch = []
            day = entry.timestamp.date()
            batch.append(entry)
        if batch:
            yield day, batch

    @transaction.atomic
    def rebuild(self, monitor, entries):
        PM25.objects.filter(
            monitor=monitor,
            stage=PM25.Stage.CLEANED,
            timestamp__gte=entries[0].timestamp,
            timestamp__lte=entries[-1].timestamp,
        ).delete()

        kept = 0
        for entry in entries:
            entry.monitor = monitor
            if any(result.stage == PM25.Stage.CLEANED for result in monitor.process_entry_pipeline(entry)):
                kept += 1
        return kept

    def refresh_latest(self, monitor):
        '''Repoint the CLEANED PM2.5 LatestEntry; the row it named may have been deleted.'''
        lookup = {
            'monitor_id': monitor.pk,
            'entry_type': PM25.entry_type,
            'stage': PM25.Stage.CLEANED,
            'processor': processors.PM25_FEM_Cleaner.name,
        }
        latest = (PM25.objects
            .filter(monitor=monitor, stage=PM25.Stage.CLEANED, processor=processors.PM25_FEM_Cleaner.name)
            .order_by('-timestamp')
            .first()
        )
        if latest is None:
            LatestEntry.objects.filter(**lookup).delete()
            return
        LatestEntry.objects.update_or_create(
            defaults={'entry_id': latest.pk, 'timestamp': latest.timestamp},
            **lookup,
        )

    def parse(self, value):
        if not value:
            return None
        try:
            return parse_datetime(value)
        except Exception:
            raise CommandError(f'Invalid timestamp: {value}')
