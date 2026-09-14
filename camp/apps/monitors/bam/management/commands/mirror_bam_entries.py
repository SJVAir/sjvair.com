from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from camp.apps.monitors.bam.mirror import MirrorDisabled, mirror_bam_data
from camp.utils.datetime import make_aware

DEFAULT_HOURS = 1


class Command(BaseCommand):
    help = (
        'Mirror BAM 1022 monitors and their RAW entries from production, '
        'then run the processing pipeline. Staging / local dev only '
        '(BAM_MIRROR_ENABLED=1). Defaults to the most recent hour.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--start',
            help='ISO timestamp (e.g. 2025-07-04T14:00). Naive values are treated as UTC. Defaults to --end minus 1 hour.',
        )
        parser.add_argument(
            '--end',
            help='ISO timestamp (exclusive). Defaults to now.',
        )
        parser.add_argument(
            '--monitor-id',
            action='append',
            dest='monitor_ids',
            help='Only mirror this monitor ID (repeatable). Defaults to all BAM 1022 monitors.',
        )

    def handle(self, *args, **options):
        end = self.parse_timestamp(options['end']) or timezone.now()
        start = self.parse_timestamp(options['start']) or end - timedelta(hours=DEFAULT_HOURS)

        if start >= end:
            raise CommandError('--start must be before --end')

        try:
            results = mirror_bam_data(
                start=start,
                end=end,
                monitor_ids=options['monitor_ids'],
                log=self.stdout.write,
            )
        except MirrorDisabled as err:
            raise CommandError(str(err))

        total = sum(count for _, _, count in results)
        self.stdout.write(self.style.SUCCESS(
            f'Done: {len(results)} monitor{"s" if len(results) != 1 else ""}, {total} raw entries.'
        ))

    def parse_timestamp(self, value):
        if not value:
            return None
        try:
            return make_aware(datetime.fromisoformat(value))
        except ValueError:
            raise CommandError(f'Invalid timestamp: {value}')
