from datetime import date

from django.core.management.base import BaseCommand, CommandError

from camp.apps.monitors.vozbox.api import VozBoxClient
from camp.apps.monitors.vozbox.models import VOZBox
from camp.apps.monitors.vozbox.tasks import _bin_rows


class Command(BaseCommand):
    help = 'Backfill raw VOZbox sensor data (PM, temp/humidity, raw O3) from moospmV3_daily CSVs on GitHub'

    def add_arguments(self, parser):
        parser.add_argument('--start', type=str, default=None, help='Start date YYYY-MM-DD (inclusive)')
        parser.add_argument('--end', type=str, default=None, help='End date YYYY-MM-DD (inclusive)')

    def handle(self, *args, **options):
        try:
            start = date.fromisoformat(options['start']) if options['start'] else None
            end = date.fromisoformat(options['end']) if options['end'] else None
        except ValueError:
            raise CommandError('Dates must be in YYYY-MM-DD format.')

        with VozBoxClient() as client:
            days = client.list_daily_files()

            for d in days:
                if start and d < start:
                    continue
                if end and d > end:
                    continue

                data = client.get_daily_data(d)
                if not data:
                    continue

                self.stdout.write(f'{d}...')

                for coreid, rows in data.items():
                    rows = _bin_rows(rows)
                    if not rows:
                        continue

                    monitor, _created = VOZBox.objects.get_or_create(sensor_id=coreid)

                    entries_created = 0
                    for row in rows:
                        entries = monitor.create_entries(row)
                        for entry in entries:
                            monitor.process_entry_pipeline(entry)
                            entries_created += 1

                    latest_row = max(rows, key=lambda r: r['timestamp'])
                    monitor.update_data(latest_row)
                    monitor.save()

                    self.stdout.write(f'  {coreid}: {entries_created} entries')
