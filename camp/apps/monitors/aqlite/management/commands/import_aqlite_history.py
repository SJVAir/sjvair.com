from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from camp.apps.calibrations.core.processors.o3.aqlite import AQLiteHourlyAggregator
from camp.apps.monitors.aqlite.models import AQLite
from camp.utils.datetime import make_aware


class Command(BaseCommand):
    help = 'Import historical AQLite data and run the O3 pipeline (RAW → CLEANED → CALIBRATED)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--start',
            type=str,
            default=None,
            help='Start date YYYY-MM-DD in local time (default: 7 days ago)',
        )
        parser.add_argument(
            '--end',
            type=str,
            default=None,
            help='End date YYYY-MM-DD in local time (default: now)',
        )
        parser.add_argument(
            '--device-id',
            type=str,
            action='append',
            dest='device_ids',
            metavar='DEVICE_ID',
            help='Limit to a specific device ID, e.g. AQLite-1608 (repeatable)',
        )

    def handle(self, *args, **options):
        now = timezone.now()

        try:
            end = (
                make_aware(datetime.strptime(options['end'], '%Y-%m-%d'))
                if options['end']
                else now
            )
            start = (
                make_aware(datetime.strptime(options['start'], '%Y-%m-%d'))
                if options['start']
                else end - timedelta(days=7)
            )
        except ValueError:
            raise CommandError('Dates must be in YYYY-MM-DD format.')

        monitors = AQLite.objects.select_related('organization').filter(
            organization__isnull=False,
            organization__is_enabled=True,
        )
        if options['device_ids']:
            monitors = monitors.filter(device_id__in=options['device_ids'])

        if not monitors.exists():
            self.stdout.write(self.style.WARNING('No matching monitors found.'))
            return

        self.stdout.write(self.style.NOTICE(
            f'Importing {monitors.count()} monitor(s): {start.date()} → {end.date()}'
        ))

        for monitor in monitors:
            self._import_monitor(monitor, start, end, now)

    def _import_monitor(self, monitor, start, end, now):
        self.stdout.write(f'\n{monitor.device_id}')

        records = 0
        created = 0
        for payload in monitor.organization.api.get_time_series(
            device_id=monitor.device_id,
            start=start,
            end=end,
            average=0,
        ):
            records += 1
            entries = monitor.create_entries(payload)
            for entry in entries:
                monitor.process_entry_pipeline(entry)
                created += 1

        if records:
            monitor.save()
        self.stdout.write(f'  {records} raw records, {created} entries created')

        # Aggregate each complete hour in the range.
        # Start at the first full hour boundary after `start`.
        hour_end = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        cutoff = min(end, now).replace(minute=0, second=0, microsecond=0)

        aggregated = 0
        while hour_end <= cutoff:
            hour_start = hour_end - timedelta(hours=1)
            result = AQLiteHourlyAggregator.aggregate(monitor, hour_start, hour_end)
            if result:
                aggregated += 1
            hour_end += timedelta(hours=1)

        self.stdout.write(f'  {aggregated} hourly CALIBRATED entries created')
