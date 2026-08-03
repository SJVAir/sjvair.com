from django.core.management.base import BaseCommand

from camp.apps.calheatscore.tasks import import_calheatscore


class Command(BaseCommand):
    help = 'Import CalHeatScore heat-risk data for San Joaquin Valley ZIP codes.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--local',
            action='store_true',
            help='Run synchronously via call_local() instead of enqueueing.',
        )

    def handle(self, *args, **options):
        if options['local']:
            import_calheatscore.call_local()
        else:
            import_calheatscore()
