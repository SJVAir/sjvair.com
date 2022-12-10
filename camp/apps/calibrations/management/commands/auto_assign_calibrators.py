from django.contrib.gis.db.models.functions import Distance
from django.core.management.base import BaseCommand, CommandError

from camp.apps.calibrations.models import Calibrator
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.purpleair.models import PurpleAir

class Command(BaseCommand):
    help = 'Automatically assign missing calibrators for AirNow monitors'

    def handle(self, *args, **options):
        for airnow in AirNow.objects.filter(reference_calibrator__isnull=True):
            # Get the closest PurpleAir. We don't care about activity,
            # we're just looking to set something up and will hand-curate.
            purpleair = (PurpleAir.objects
                .annotate(distance=Distance("position", airnow.position))
                .order_by('distance')
            ).first()

            # If distance > .5mi, continue
            if purpleair.distance.mi > .5:
                print(f'Colocated monitor "{purpleair.name}" is too far from reference monitor "{airnow.name}": {purpleair.distance.mi} mi.')
                continue

            calibrator = Calibrator.objects.create(
                reference=airnow,
                colocated=purpleair,
                is_enabled=True,
            )
            calibrator.calibrate()
