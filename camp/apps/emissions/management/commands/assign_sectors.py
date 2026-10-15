from django.core.management.base import BaseCommand

from camp.apps.emissions.models import Facility
from camp.apps.emissions.sectors import sector_for_sic


class Command(BaseCommand):
    help = "Re-apply sectors.py's SIC -> sector map to every facility (run after editing sectors.py)."

    def handle(self, *args, **options):
        changed = []
        facilities = Facility.objects.select_related(None).only('id', 'sic_code', 'sector').iterator()
        for facility in facilities:
            sector = sector_for_sic(facility.sic_code)
            if facility.sector != sector:
                facility.sector = sector
                changed.append(facility)
        Facility.objects.bulk_update(changed, ['sector'], batch_size=1000)
        self.stdout.write(f'{len(changed)} facilities updated.')
