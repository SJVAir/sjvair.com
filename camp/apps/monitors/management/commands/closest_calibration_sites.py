import csv
from django.core.management.base import BaseCommand
from django.contrib.gis.db.models.functions import Distance

from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.airgradient.models import AirGradient
from camp.apps.calibrations.models import CalibrationPair


class Command(BaseCommand):
    help = 'Prints a CSV of the three closest calibration sites for SJVAir PurpleAir and AirGradient monitors.'

    def handle(self, *args, **options):
        self.csv = []
        self.write_rows(PurpleAir.objects.filter(is_sjvair=True, position__isnull=False))
        self.write_rows(AirGradient.objects.filter(is_sjvair=True, position__isnull=False))

        writer = csv.writer(self.stdout)
        writer.writerow([
            'monitor_id', 'monitor_name', 'location_id', 'monitor_type', 'monitor_lat', 'monitor_lon',
            'ref_1_id', 'ref_1_name', 'ref_1_lat', 'ref_1_lon', 'ref_1_distance',
            'ref_2_id', 'ref_2_name', 'ref_2_lat', 'ref_2_lon', 'ref_2_distance',
            'ref_3_id', 'ref_3_name', 'ref_3_lat', 'ref_3_lon', 'ref_3_distance',
        ])
        writer.writerows(self.csv)

    def write_rows(self, queryset):
        for monitor in queryset:
            calibration_pairs = (
                CalibrationPair.objects
                .filter(reference__position__isnull=False, is_enabled=True, entry_type='pm25')
                .annotate(dist=Distance('reference__position', monitor.position))
                .select_related('reference')
                .order_by('dist')[:3]
            )

            location_id = getattr(monitor, 'purple_id', None) or getattr(monitor, 'location_id', None)

            row = [
                monitor.id,
                monitor.name,
                location_id,
                monitor.monitor_type,
                monitor.position.y,
                monitor.position.x,
            ]

            for pair in calibration_pairs:
                row.extend([
                    pair.reference.id,
                    pair.reference.name,
                    pair.reference.position.y,
                    pair.reference.position.x,
                    round(pair.dist.mi, 2),
                ])

            while len(row) < 24:
                row.extend(['', '', '', '', ''])

            self.csv.append(row)
