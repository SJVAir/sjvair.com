import csv
import os
import time
from datetime import datetime, timezone as timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify
from django.utils.timezone import make_aware

from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.purpleair.api import purpleair_api
from camp.utils.datetime import chunk_date_range


class Command(BaseCommand):
    help = 'Download historical PurpleAir data and save to CSV with human-readable timestamps'

    def add_arguments(self, parser):
        parser.add_argument('-i', '--sensor_id', type=int, help='PurpleAir sensor index')
        parser.add_argument('-s', '--start_date', type=str, help='Start date (YYYY-MM-DD)')
        parser.add_argument('-e', '--end_date', type=str, help='End date (YYYY-MM-DD)')
        parser.add_argument(
            '-o', '--output',
            type=str,
            default=None,
            help='Optional output CSV path (default is based on sensor_id and date range)'
        )

    def handle(self, *args, **options):
        self.sensor_id = options['sensor_id']
        self.start_date_str = options['start_date']
        self.end_date_str = options['end_date']
        self.output_path = options['output']

        try:
            self.start = make_aware(datetime.strptime(self.start_date_str, '%Y-%m-%d'))
            self.end = make_aware(datetime.strptime(self.end_date_str, '%Y-%m-%d'))
        except ValueError:
            raise CommandError('Dates must be in YYYY-MM-DD format.')

        self.monitor = PurpleAir.objects.filter(sensor_id=self.sensor_id).first()

        if self.output_path is None:
            self.output_path = self.get_default_path()

        output_dir = os.path.dirname(self.output_path)
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except OSError as e:
                raise CommandError(f'Could not create output directory: {output_dir}\n{e}')

        self.print_summary()
        self.download_and_save()
        self.print_summary()

    def print_summary(self):
        self.stdout.write(self.style.NOTICE('Download Configuration:'))
        self.stdout.write(f'  PurpleAir ID: {self.sensor_id}')
        if self.monitor:
            self.stdout.write(f'  Monitor: {self.monitor.name} (pk={self.monitor.pk})')
        else:
            self.stdout.write('  Monitor: [not found in database]')
        self.stdout.write(f'  Date range: {self.start_date_str} → {self.end_date_str}')
        self.stdout.write(f'  Output file: {self.output_path}')

    def get_default_path(self):
        base = f'{self.sensor_id}_{self.start_date_str}_to_{self.end_date_str}.csv'
        prefix = slugify(self.monitor.name) if self.monitor else 'purpleair'
        return os.path.abspath(f'purpleair-export/{prefix}_{base}')

    def download_and_save(self):
        self.stdout.write(f'Downloading data for PurpleAir ID {self.sensor_id} from {self.start_date_str} to {self.end_date_str}')
        self.stdout.write(f'Saving to: {self.output_path}')

        header_written = False
        row_count = 0

        with open(self.output_path, 'w', newline='') as f:
            writer = None

            for chunk_start, chunk_end in chunk_date_range(self.start, self.end):
                label = f'Chunk: {chunk_start.date()} → {chunk_end.date()}'
                self.stdout.write(self.style.MIGRATE_HEADING(label))

                entries = purpleair_api.get_sensor_history(self.sensor_id, chunk_start, chunk_end)
                if not entries:
                    continue

                for entry in entries:
                    dt_utc = datetime.utcfromtimestamp(entry['time_stamp']).replace(tzinfo=timezone.utc)
                    dt_local = dt_utc.astimezone(settings.DEFAULT_TIMEZONE)
                    entry['datetime_utc'] = dt_utc.isoformat()
                    entry['datetime_local'] = dt_local.isoformat()

                    if not header_written:
                        fieldnames = ['time_stamp', 'datetime_utc', 'datetime_local'] + [
                            key for key in entry.keys()
                            if key not in ('time_stamp', 'datetime_utc', 'datetime_local')
                        ]
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        header_written = True

                    writer.writerow(entry)
                    row_count += 1

                time.sleep(1)

        if row_count > 0:
            self.stdout.write(self.style.SUCCESS(f'Saved {row_count} rows to {self.output_path}'))
        else:
            if os.path.exists(self.output_path):
                os.remove(self.output_path)
            self.stdout.write(self.style.WARNING('No data found for the given date range — no file was saved.'))
