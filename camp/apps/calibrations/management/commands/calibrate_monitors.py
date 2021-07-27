from django.contrib.gis.db.models.functions import Distance
from django.core.management.base import BaseCommand, CommandError

from camp.apps.calibrations.models import Calibrator
from camp.apps.calibrations.tasks import calibrate_monitors


class Command(BaseCommand):
    help = 'Run calibrations for all monitors'

    def handle(self, *args, **options):
        calibrate_monitors.call_local()
