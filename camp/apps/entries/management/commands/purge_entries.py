import os
from datetime import timedelta

import tqdm

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from camp.apps.entries.models import BaseEntry


class Command(BaseCommand):
    help = 'Delete raw entries older than a given number of days. Staging only.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='Delete entries older than this many days (default: 90)',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=5000,
            help='Number of rows to delete per batch (default: 5000)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be deleted without actually deleting',
        )

    def handle(self, *args, **options):
        if not os.environ.get('ALLOW_ENTRY_PURGE'):
            raise CommandError(
                'This command is disabled in this environment.\n'
                'Set ALLOW_ENTRY_PURGE=true to enable it.'
            )

        days = options['days']
        batch_size = options['batch_size']
        dry_run = options['dry_run']
        cutoff = timezone.now() - timedelta(days=days)

        self.stdout.write(
            f'{"[DRY RUN] " if dry_run else ""}'
            f'Purging entries older than {days} days (before {cutoff:%Y-%m-%d %H:%M %Z})'
        )

        grand_total = 0

        for Model in sorted(BaseEntry.get_subclasses(), key=lambda m: m.__name__):
            count = Model.objects.filter(timestamp__lt=cutoff).count()
            if count == 0:
                self.stdout.write(f'  {Model.__name__}: nothing to delete')
                continue

            self.stdout.write(f'\n  {Model.__name__}: {count:,} rows to delete')

            if dry_run:
                grand_total += count
                continue

            deleted_total = 0
            with tqdm.tqdm(total=count, file=self.stdout, dynamic_ncols=True) as bar:
                while True:
                    ids = list(
                        Model.objects
                        .filter(timestamp__lt=cutoff)
                        .values_list('pk', flat=True)[:batch_size]
                    )
                    if not ids:
                        break
                    deleted, _ = Model.objects.filter(pk__in=ids).delete()
                    deleted_total += deleted
                    grand_total += deleted
                    bar.update(deleted)

            self.stdout.write(f'  {Model.__name__}: {deleted_total:,} deleted')

        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"Would delete" if dry_run else "Deleted"} {grand_total:,} entries total.'
            )
        )
