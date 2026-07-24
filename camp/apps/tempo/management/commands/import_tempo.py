from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils.timezone import make_aware

from camp.apps.tempo.models import Granule
from camp.apps.tempo.sync import sync_granule


class Command(BaseCommand):
    help = (
        'Backfills or re-syncs TEMPO granules for a date range. Safe to '
        're-run: sync_granule skips any hour that is already up to date, '
        'so this also serves as the periodic reprocessing-catch-up job '
        '(re-run over a range to pick up NASA V03->V04 reprocessing).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--start', required=True, type=lambda s: datetime.strptime(s, '%Y-%m-%d').date())
        parser.add_argument('--end', required=True, type=lambda s: datetime.strptime(s, '%Y-%m-%d').date())
        parser.add_argument(
            '--product', choices=[choice[0] for choice in Granule.Product.choices],
            help='Limit to a single product. Defaults to all products.',
        )

    def handle(self, *args, **options):
        products = [options['product']] if options['product'] else [c[0] for c in Granule.Product.choices]

        day = options['start']
        while day <= options['end']:
            day_start = make_aware(datetime.combine(day, datetime.min.time()))
            for hour in range(24):
                timestamp = day_start + timedelta(hours=hour)
                for product in products:
                    try:
                        sync_granule(product, timestamp)
                    except Exception as exc:
                        self.stderr.write(self.style.WARNING(
                            f'{product} @ {timestamp}: {exc}'
                        ))
            self.stdout.write(f'{day}: done ({len(products)} product(s) x 24 hours)')
            day += timedelta(days=1)
