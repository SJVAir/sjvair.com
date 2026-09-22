import requests

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from camp.apps.emissions import carb, cepam
from camp.apps.emissions.models import CountyInventory


class Command(BaseCommand):
    help = "Import CARB's county emission inventory (CEPAM) by EIC for the covered counties."

    def add_arguments(self, parser):
        parser.add_argument('--year', required=True, help='A year (2024) or an inclusive range (2010-2024)')
        parser.add_argument('--county', help='Limit to one covered county, by slug (e.g. fresno)')

    def handle(self, *args, **options):
        try:
            years = carb.parse_years(options['year'])
            counties = carb.carb_counties(options.get('county'))
        except (ValueError, carb.CountyConfigError) as exc:
            raise CommandError(str(exc))

        failed = []
        for year in years:
            for county_code, county in counties:
                label = f'{county.name} {year}'
                try:
                    rows = cepam.parse(cepam.fetch_text(year, county_code), county, year)
                except (requests.RequestException, ValueError) as exc:
                    self.stderr.write(f'{label}: {exc}')
                    failed.append(label)
                    continue
                if not rows:
                    self.stderr.write(f'{label}: no rows returned; existing rows kept.')
                    continue
                with transaction.atomic():
                    CountyInventory.objects.filter(county=county, year=year, inventory=cepam.INVENTORY).delete()
                    CountyInventory.objects.bulk_create(rows, batch_size=1000)
                self.stdout.write(f'{label}: {len(rows)} EIC rows')

        if failed:
            raise CommandError(f'Import incomplete for: {", ".join(failed)}')
