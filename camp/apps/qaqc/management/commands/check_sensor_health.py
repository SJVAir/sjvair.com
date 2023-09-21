from django.core.management.base import BaseCommand, CommandError

from camp.apps.qaqc.tasks import ab_regression


class Command(BaseCommand):
    help = 'Run linear regressions against sensors for multisensor monitors'

    def handle(self, *args, **options):
        ab_regression.call_local()
