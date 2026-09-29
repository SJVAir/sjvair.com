import datetime
import time

import requests

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import carb, ceidars, locations, pmt
from camp.apps.emissions.models import EmissionsRecord, Facility
from camp.apps.emissions.sectors import sector_for_sic
from camp.apps.regions.models import Region
from camp.utils import geocode


class Command(BaseCommand):
    help = 'Import CEIDARS facility emissions for the covered counties and one inventory year.'

    def status(self, msg):
        """Write an overwriting status line, clearing any leftover characters."""
        self.stdout.write(f'{msg}\033[K', ending='\r')

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True, help='Inventory year (e.g. 2024)')
        parser.add_argument('--county', help='Limit to one covered county, by slug (e.g. fresno)')
        parser.add_argument(
            '--regeocode', action='store_true',
            help="Re-locate every facility in the year's inventory, not just new ones and ones without a trusted point",
        )

    def handle(self, *args, **options):
        year = options['year']
        regeocode = options['regeocode']
        try:
            counties = carb.carb_counties(options.get('county'))
        except carb.CountyConfigError as exc:
            raise CommandError(str(exc))

        # Pre-load region lookups once for the entire import.
        districts = {
            region.external_id: region
            for region in Region.objects.filter(type=Region.Type.AIR_DISTRICT)
        }
        zipcode_regions = {r.name: r for r in Region.objects.filter(type=Region.Type.ZIPCODE)}
        city_regions = {
            r.name.upper(): r
            for r in Region.objects.filter(type__in=[Region.Type.CITY, Region.Type.CDP])
        }

        # CARB's own coordinates for every facility (Pollution Mapping Tool),
        # the fallback between a Census street match and MapTiler.
        markers, marker_years = pmt.fetch_markers(range(pmt.FIRST_YEAR, datetime.date.today().year + 1))
        self.stdout.write(f'CARB coordinates: {", ".join(map(str, marker_years)) or "none"} ({len(markers)} facilities)')

        total_facilities = total_records = total_geocode_failures = 0
        failed = []
        start_time = time.monotonic()

        for county_code, county in counties:
            label = f'{county.name} ({county_code})'
            created_count = updated_count = record_count = geocode_failures = 0
            county_start = time.monotonic()

            self.status(f'{label}: fetching...')
            try:
                merged = ceidars.fetch_county(year, county_code)
            except requests.RequestException as exc:
                self.stderr.write(f'{label}: fetch failed -- {exc}')
                failed.append(county.name)
                continue

            if merged.empty:
                self.stdout.write(f'{label}: no facilities for {year}')
                continue

            # Every row's district must already exist as a Region: the FK is
            # part of the facility's identity. Write nothing for this county
            # rather than guess.
            unknown = sorted(set(merged['DIS']) - set(districts))
            if unknown:
                self.stderr.write(
                    f'{label}: no air district Region for {", ".join(unknown)}; '
                    f'run import_air_districts first. Nothing written for this county.'
                )
                failed.append(county.name)
                continue

            # Which facilities to locate: new ones, ones without a trusted
            # point (legacy, MapTiler, none), and every one with --regeocode.
            all_facids = [int(row['FACID']) for _, row in merged.iterrows()]
            existing = {
                (district, facid): (point, source)
                for district, facid, point, source in Facility.objects.filter(county_code=county_code, facid__in=all_facids)
                .values_list('air_district__external_id', 'facid', 'point', 'point_source')
            }
            to_locate = {}  # (district, facid) -> address
            for _, row in merged.iterrows():
                key = (row['DIS'], int(row['FACID']))
                if key in existing and not regeocode and existing[key][1] in Facility.TRUSTED_POINT_SOURCES:
                    continue
                to_locate[key] = {
                    'street': row.get('FSTREET', '').strip(),
                    'city': row.get('FCITY', '').strip(),
                    'state': 'CA',
                    'zipcode': row.get('FZIP', '').strip(),
                }

            # Census street matches in one batch, then CARB's coordinates;
            # MapTiler only for a new facility neither of those places.
            # Portable equipment and oil-field names aren't places: a
            # geocoder would put them anywhere, so they aren't geocoded.
            positions = {}  # (district, facid) -> (Point, source)
            if to_locate:
                self.status(f'{label}: locating {len(to_locate)} facilities...')
                area = locations.county_area(county)
                geocodable = [(key, address) for key, address in to_locate.items() if locations.is_geocodable(address)]
                by_id = {id(address): key for key, address in geocodable}
                census = {by_id[id(address)]: point for address, point in geocode.census_batch([a for _, a in geocodable])}
                carb_points = {key: markers.get((county_code, key[0], key[1])) for key in to_locate}
                misses = [
                    address for key, address in geocodable
                    if key not in existing
                    and not locations.plausible(census.get(key), area)
                    and not locations.plausible(carb_points[key], area)
                ]
                maptiler = {by_id[id(address)]: point for address, point in geocode.maptiler_batch(misses)}
                for key, address in to_locate.items():
                    current, current_source = existing.get(key, (None, ''))
                    if key in maptiler:
                        current, current_source = maptiler[key], Facility.PointSource.MAPTILER
                    positions[key] = locations.locate(
                        address, census=census.get(key), carb=carb_points[key],
                        current=current, current_source=current_source, area=area,
                    )

            total_rows = len(merged)
            seen_keys = set()
            for i, (_, row) in enumerate(merged.iterrows(), 1):
                self.status(f'{label}: {i}/{total_rows} facilities...')
                district = row['DIS']
                facid = int(row['FACID'])
                key = (district, facid)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                address = {
                    'street': row.get('FSTREET', '').strip(),
                    'city': row.get('FCITY', '').strip(),
                    'zipcode': row.get('FZIP', '').strip(),
                }
                zipcode_region = zipcode_regions.get(address['zipcode'])
                city_region = ceidars.normalize_city(address['city'], city_regions)
                sic_code = int(row['FSIC']) if row.get('FSIC') else None

                facility, created = Facility.objects.get_or_create(
                    county_code=county_code,
                    air_district=districts[district],
                    facid=facid,
                    defaults={
                        'name': row.get('FNAME', '').strip(),
                        'address': address,
                        'sic_code': sic_code,
                        'sector': sector_for_sic(sic_code),
                        'metadata_year': year,
                        'county': county,
                        'zipcode': zipcode_region,
                        'city': city_region,
                    },
                )

                if key in positions:
                    facility.point, facility.point_source = positions[key]
                    if facility.point is None:
                        geocode_failures += 1
                if created:
                    created_count += 1
                    facility.save()
                else:
                    updated_count += 1

                    if facility.metadata_year is None or year >= facility.metadata_year:
                        facility.name = row.get('FNAME', '').strip()
                        facility.address = address
                        facility.sic_code = sic_code
                        facility.sector = sector_for_sic(sic_code)
                        facility.metadata_year = year
                        facility.county = county
                        facility.zipcode = zipcode_region
                        facility.city = city_region

                    facility.save()

                emissions_data = {
                    col: ceidars.decimal_or_none(row.get(src))
                    for src, col in ceidars.CRITERIA_COLS.items()
                }
                emissions_data.update({
                    col: ceidars.decimal_or_none(row.get(src))
                    for src, col in ceidars.TOXICS_COLS.items()
                })
                if all(v is None for v in emissions_data.values()):
                    continue

                EmissionsRecord.objects.update_or_create(
                    facility=facility,
                    year=year,
                    defaults=emissions_data,
                )
                record_count += 1

            elapsed = time.monotonic() - county_start
            self.stdout.write(
                f'{label}: '
                f'{created_count + updated_count} facilities '
                f'({created_count} new, {updated_count} updated), '
                f'{record_count} emissions records upserted, '
                f'{geocode_failures} geocoding failures '
                f'[{elapsed:.1f}s]'
            )

            total_facilities += created_count + updated_count
            total_records += record_count
            total_geocode_failures += geocode_failures

        total_elapsed = time.monotonic() - start_time
        self.stdout.write(
            f'\nDone. {total_facilities} facilities, '
            f'{total_records} emissions records, '
            f'{total_geocode_failures} geocoding failures '
            f'[{total_elapsed:.1f}s]'
        )
        if failed:
            raise CommandError(f'Import incomplete for: {", ".join(failed)}')
