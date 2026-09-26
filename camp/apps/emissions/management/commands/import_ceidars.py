import time

import requests

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import carb, ceidars, locations
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
        parser.add_argument('--regeocode', action='store_true', help='Re-geocode all facilities, not just new ones')

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

        total_facilities = total_records = total_geocode_failures = 0
        failed = []
        start_time = time.monotonic()

        for county_code, county in counties:
            label = f'{county.name} ({county_code})'
            created_count = updated_count = record_count = geocode_failures = 0
            county_start = time.monotonic()

            self.status(f'{label}: fetching...')
            try:
                merged, toxic_ems = ceidars.fetch_county(
                    year, county_code,
                    on_error=lambda field, exc: self.stderr.write(f'{label}: {field} fetch failed -- {exc}'),
                )
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

            # Determine which facilities need geocoding.
            all_facids = [int(row['FACID']) for _, row in merged.iterrows()]
            existing_keys = set(
                Facility.objects.filter(county_code=county_code, facid__in=all_facids)
                .values_list('air_district__external_id', 'facid')
            )

            geocode_index = []  # [((district, facid), address_dict), ...] in batch order
            for _, row in merged.iterrows():
                key = (row['DIS'], int(row['FACID']))
                if key not in existing_keys or regeocode:
                    address = {
                        'street': row.get('FSTREET', '').strip(),
                        'city': row.get('FCITY', '').strip(),
                        'state': 'CA',
                        'zipcode': row.get('FZIP', '').strip(),
                    }
                    # Portable equipment and oil-field names aren't places;
                    # a geocoder would put them anywhere.
                    if locations.is_geocodable(address):
                        geocode_index.append((key, address))

            # Batch geocode upfront via Census, falling back to MapTiler for
            # failures. A point outside the facility's county is a bad match
            # and is dropped.
            positions = {}
            if geocode_index:
                self.status(f'{label}: geocoding {len(geocode_index)} facilities...')
                area = locations.county_area(county)
                addr_to_key = {id(addr): key for key, addr in geocode_index}
                for addr, point in geocode.resolve_batch([addr for _, addr in geocode_index]):
                    if locations.plausible(point, area):
                        positions[addr_to_key[id(addr)]] = point

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

                if created:
                    created_count += 1
                    facility.point = positions.get(key)
                    if facility.point is None:
                        geocode_failures += 1
                    facility.save()
                else:
                    updated_count += 1
                    if regeocode:
                        facility.point = positions.get(key)
                        if facility.point is None:
                            geocode_failures += 1

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
                emissions_data.update(toxic_ems.get(key, {}))

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
