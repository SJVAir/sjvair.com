from django.contrib.gis.db.models.functions import Distance
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Prefetch

from camp.apps.calibrations.models import Calibrator
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.models import Monitor
from camp.apps.monitors.purpleair.models import PurpleAir


class Command(BaseCommand):
    help = 'Automatically assign missing calibrators for AirNow monitors'

    def get_closest_purpleair(self, point):
        queryset = (PurpleAir.objects
            .select_related('latest')
            .annotate(distance=Distance("position", point))
            .order_by('distance')
        )

        for purpleair in queryset:
            # If distance > .5mi, continue
            if purpleair.distance.mi > 1:
                return

            if purpleair.is_active:
                return purpleair

    def handle(self, *args, **options):
        print('CREATING CALIBRATORS')
        for airnow in AirNow.objects.filter(reference_calibrator__isnull=True):
            print(airnow.name)
            if not airnow.is_active:
                print('- Inactive.')

            purpleair = self.get_closest_purpleair(airnow.position)
            if purpleair is None:
                print('- Isolated.')
                continue

            print(f'- Assigned: {purpleair.name}')

            calibrator = Calibrator.objects.create(
                reference=airnow,
                colocated=purpleair,
                is_enabled=True,
            )

        print('CHECK FOR NEARBY, ACTIVE COLOCATED.')
        monitor_queryset = Monitor.objects.all().select_related('latest')
        queryset = (Calibrator.objects.all()
            .prefetch_related(
                Prefetch('reference', monitor_queryset),
                Prefetch('colocated', monitor_queryset),
            )
        )
        for calibrator in queryset:
            purpleair = self.get_closest_purpleair(calibrator.reference.position)
            if purpleair is None:
                print(f'{calibrator.reference.name}: Isolated.')
                continue
            print(f'{calibrator.reference.name} / {calibrator.colocated.name}')
            calibrator.colocated = purpleair
            calibrator.save()


