import time
from concurrent.futures import ThreadPoolExecutor

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from camp.apps.emissions import stats
from camp.apps.emissions.importers import carb, ceidars
from camp.apps.emissions.models import Facility, SourceImport, ToxicEmission, ToxicPollutant

# CARB's names are abbreviations in mixed case ('1,2,4TriMeBenze'); shouting
# ones are sentence-cased. import_health_values replaces them where the
# Consolidated Table has the pollutant.
def tidy_name(name):
    name = ' '.join(str(name).split())
    return name.capitalize() if name.isupper() else name


def parse_rows(frame):
    """[(carb_id, name, lbs)] from a facdet CSV frame, skipping blank ids and blank or non-positive pounds."""
    rows = []
    if frame.empty:
        return rows
    for _, row in frame.iterrows():
        carb_id = str(row.get('POLLUTANT_ID', '')).strip()
        lbs = ceidars.decimal_or_none(row.get('EMISSIONS_LBS_YR', ''))
        if not carb_id or lbs is None:
            continue
        try:
            if float(lbs) <= 0:
                continue
        except ValueError:
            continue
        rows.append((carb_id, tidy_name(row.get('POLLUTANT', '')) or carb_id, lbs))
    return rows


class Command(BaseCommand):
    help = "Import every toxic air contaminant each CEIDARS facility reported for one year, from CARB's per-facility detail CSVs."

    def status(self, msg):
        self.stdout.write(f'{msg}\033[K', ending='\r')

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True, help='Inventory year (e.g. 2024)')
        parser.add_argument('--county', help='Limit to one covered county, by slug (e.g. fresno)')
        parser.add_argument('--workers', type=int, default=8, help='Parallel requests to CARB (default 8)')

    def handle(self, *args, **options):
        year = options['year']
        try:
            counties = carb.carb_counties(options.get('county'))
        except carb.CountyConfigError as exc:
            raise CommandError(str(exc))

        pollutants = {p.carb_id: p for p in ToxicPollutant.objects.all()}
        total_facilities = total_rows = total_failed = 0
        start = time.monotonic()

        for county_code, county in counties:
            label = f'{county.name} ({county_code})'
            facilities = list(
                Facility.objects.filter(county_code=county_code, emissions__year=year)
                .distinct().select_related('air_district').order_by('facid')
            )
            if not facilities:
                self.stdout.write(f'{label}: no facilities for {year}')
                continue

            def fetch(facility):
                url = ceidars.facdet_url(year, facility.county_code, facility.air_district.external_id, facility.facid)
                try:
                    return facility, ceidars.fetch_csv(url), None
                except requests.RequestException as exc:
                    return facility, None, exc

            self.status(f'{label}: fetching {len(facilities)} facilities...')
            with ThreadPoolExecutor(max_workers=options['workers']) as pool:
                results = list(pool.map(fetch, facilities))

            fetched = failed = rows_written = 0
            with transaction.atomic():
                for facility, frame, exc in results:
                    if exc is not None:
                        failed += 1
                        self.stderr.write(f'{label}: {facility.name} (facid {facility.facid}) fetch failed -- {exc}; kept its existing rows')
                        continue
                    fetched += 1
                    rows = parse_rows(frame)
                    ToxicEmission.objects.filter(facility=facility, year=year).delete()
                    batch = []
                    for carb_id, name, lbs in rows:
                        pollutant = pollutants.get(carb_id)
                        if pollutant is None:
                            pollutant = ToxicPollutant.create_for(carb_id, name)
                            pollutants[carb_id] = pollutant
                        batch.append(ToxicEmission(facility=facility, year=year, pollutant=pollutant, lbs=lbs))
                    ToxicEmission.objects.bulk_create(batch, ignore_conflicts=True)
                    rows_written += len(batch)

            self.stdout.write(f'{label}: {fetched} facilities, {rows_written} toxic rows, {failed} failed')
            total_facilities += fetched
            total_rows += rows_written
            total_failed += failed

        SourceImport.objects.create(
            source='ceidars-toxics', version=str(year),
            notes={'facilities': total_facilities, 'rows': total_rows, 'failed': total_failed},
        )
        stats.clear_caches()
        self.stdout.write(f'\nDone. {total_facilities} facilities, {total_rows} toxic rows, {total_failed} failed [{time.monotonic() - start:.1f}s]')
        if total_failed:
            raise CommandError(f'{total_failed} facilities could not be fetched; re-run for their counties.')
