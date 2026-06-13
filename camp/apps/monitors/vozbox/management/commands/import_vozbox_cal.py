from datetime import date

from django.core.management.base import BaseCommand

from camp.apps.entries import models as entry_models
from camp.apps.monitors.vozbox.api import VozBoxClient
from camp.apps.monitors.vozbox.models import VOZBox


class Command(BaseCommand):
    help = 'Backfill calibrated O3 data from moospmV3_cal CSVs on GitHub'

    def add_arguments(self, parser):
        parser.add_argument('--start', type=str, default=None, help='Start date YYYY-MM-DD (inclusive)')
        parser.add_argument('--end', type=str, default=None, help='End date YYYY-MM-DD (inclusive)')

    def handle(self, *args, **options):
        start = date.fromisoformat(options['start']) if options['start'] else None
        end = date.fromisoformat(options['end']) if options['end'] else None

        with VozBoxClient() as client:
            cal_files = client.list_cal_files()

            for cal_date, hour_utc in sorted(cal_files):
                if start and cal_date < start:
                    continue
                if end and cal_date > end:
                    continue

                data = client.get_cal_data(cal_date, hour_utc)
                if not data:
                    continue

                self.stdout.write(f'Processing {cal_date} T{hour_utc:02d}...')

                for coreid, rows in data.items():
                    try:
                        monitor = VOZBox.objects.get(sensor_id=coreid)
                    except VOZBox.DoesNotExist:
                        self.stdout.write(f'  Skipping unknown coreid: {coreid}')
                        continue

                    for row in rows:
                        o3_cal = row.get('o3_cal')
                        if o3_cal is None:
                            continue
                        monitor.create_entry(
                            entry_models.O3,
                            timestamp=row['timestamp'],
                            sensor='1',
                            stage=entry_models.O3.Stage.CALIBRATED,
                            value=o3_cal,
                        )

                    monitor.save()
