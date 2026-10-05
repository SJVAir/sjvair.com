import csv
import datetime
import shutil
import tempfile
import zipfile
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from camp.apps.pesticides.models import (
    Chemical, Commodity, FumigationMethod, PesticideUse, Product, ProductChemical,
)
from camp.apps.regions.models import Region

CDPR_URL = 'https://files.cdpr.ca.gov/pub/outgoing/pur_archives/pur{year}.zip'

MERIDIAN_MAP = {'M': 'MDM', 'H': 'HBM', 'S': 'SBM'}
BATCH_SIZE = 5000
FUME_UPDATE_CHUNK = 5000

DATE_FORMATS = ('%m/%d/%Y', '%d-%b-%Y')


def parse_float(value):
    try:
        return float(value) if value and value.strip() else None
    except (ValueError, TypeError):
        return None


def parse_int(value):
    try:
        return int(value) if value and value.strip() else None
    except (ValueError, TypeError):
        return None


def parse_date(value):
    if not value or not value.strip():
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def clean(value):
    return (value or '').strip()


def make_mtrs_key(base_ln_mer, township, tship_dir, range_, range_dir, section):
    meridian = MERIDIAN_MAP.get(clean(base_ln_mer))
    if not meridian:
        return None
    try:
        t, r, s = int(township), int(range_), int(section)
    except (ValueError, TypeError):
        return None
    if t == 0 or r == 0 or s == 0:
        return None
    return f'{meridian}-T{t:02d}{clean(tship_dir)}-R{r:02d}{clean(range_dir)}-{s:02d}'


def read_csv(path):
    return csv.DictReader(open(path, encoding='utf-8', errors='replace'))


class Command(BaseCommand):
    help = 'Download and import PUR (Pesticide Use Report) data from CDPR.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            required=True,
            help='Year to import (e.g. 2023)',
        )
        parser.add_argument(
            '--skip-lookup',
            action='store_true',
            help='Skip importing reference tables (chemicals, products)',
        )
        parser.add_argument(
            '--fume-only',
            action='store_true',
            help=(
                "Only load CDPR's fumigation-method lookup and set each record's "
                'field-fumigation technique for --year; the records themselves are left alone'
            ),
        )

    def handle(self, *args, **options):
        year = options['year']
        tmp_dir = Path(tempfile.mkdtemp(prefix=f'pur{year}_'))
        try:
            zip_path = self._download(year, tmp_dir)
            year_dir = self._extract(zip_path, tmp_dir)
            paths = self._detect_paths(year_dir)

            if options['fume_only']:
                self.stdout.write(f'Importing {year} fumigation methods')
                if not options['skip_lookup']:
                    self._import_fumigation_methods(paths['lookup_dir'])
                if not FumigationMethod.objects.exists():
                    # Nothing to match codes to, and the pass clears the
                    # year's codes first: stop before it wipes anything.
                    self.stdout.write(
                        'No fumigation methods loaded; run without --skip-lookup first. Nothing changed.')
                    return
                self._import_fume_pass(paths, year)
                return

            self.stdout.write(f'Importing {year} PUR data')
            self.stdout.write('')

            if not options['skip_lookup']:
                self._import_chemicals(paths['lookup_dir'])
                self._import_commodities(paths['lookup_dir'])
                self._import_products(paths['lookup_dir'])
                self._import_product_chemicals(paths['lookup_dir'])
                self._import_fumigation_methods(paths['lookup_dir'])
                self.stdout.write('')

            self._import_use_records(paths, year)
            self._import_fume_pass(paths, year)

            from camp.apps.pesticides import fumigants, rollup, stats
            written = rollup.rebuild_year(year)
            self.stdout.write(f'Rollup: {written:,} rows for {year}')
            counts = fumigants.classify_fumigants()
            self.stdout.write(
                f"Fumigants: {counts['chemicals']:,} chemicals, {counts['products']:,} products "
                f"({counts['added']:,} not flagged by CDPR)"
            )
            stats.refresh_landing_stats()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # --- Download / extract ---

    def _download(self, year, tmp_dir):
        url = CDPR_URL.format(year=year)
        zip_path = tmp_dir / f'pur{year}.zip'
        self.stdout.write(f'Downloading {url}')
        with requests.get(url, stream=True, timeout=60) as r:
            if r.status_code == 404:
                raise CommandError(f'No PUR archive found for {year}: {url}')
            r.raise_for_status()
            total = int(r.headers.get('Content-Length', 0))
            downloaded = 0
            with open(zip_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        self.stdout.write(f'  {pct:.0f}%  ({downloaded // 1024 // 1024} MB)', ending='\r')
        self.stdout.write(f'  Downloaded {downloaded // 1024 // 1024} MB        ')
        return zip_path

    def _extract(self, zip_path, tmp_dir):
        self.stdout.write('Extracting...')
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_dir)
        # The zip typically contains a single top-level directory
        dirs = [p for p in tmp_dir.iterdir() if p.is_dir()]
        if len(dirs) == 1:
            return dirs[0]
        return tmp_dir

    def _detect_paths(self, year_dir):
        if (year_dir / 'pur_data').exists():
            return {
                'udc_dir': year_dir / 'pur_data',
                'lookup_dir': year_dir / 'lookup_tables',
            }
        return {
            'udc_dir': year_dir,
            'lookup_dir': year_dir,
        }

    def _find(self, directory, *names):
        for name in names:
            path = directory / name
            if path.exists():
                return path
        return None

    # --- Reference table imports ---

    def _import_chemicals(self, lookup_dir):
        path = self._find(lookup_dir, 'CHEMICAL.txt', 'chemical.txt')
        cas_path = self._find(lookup_dir, 'CHEM_CAS.txt', 'chem_cas.txt')

        if not path:
            self.stdout.write('  [chemicals] file not found, skipping')
            return

        cas_map = {}
        if cas_path:
            for row in read_csv(cas_path):
                code = parse_int(row.get('chem_code'))
                # CDPR has named the column both ways: `casnum` in chem_cas.txt
                # through 2022, `cas_number` in 2023's CHEM_CAS.txt. Reading
                # only one dropped every CAS number in the other's file
                # without a word.
                cas = clean(row.get('casnum') or row.get('cas_number'))
                if code and cas:
                    cas_map[code] = cas
            self.stdout.write(f'    {len(cas_map):,} CAS numbers from {cas_path.name}')
        else:
            self.stdout.write('    [chem_cas] file not found, no CAS numbers')

        self.stdout.write('  Importing chemicals...')
        created = updated = 0
        for row in read_csv(path):
            code = parse_int(row.get('chem_code'))
            name = clean(row.get('chemname'))
            if not code or not name:
                continue
            # Only a CAS number the file actually has: a missing row (or a
            # column read wrong) must never wipe one an earlier year, or
            # import_comptox, already stored -- import_carbtac and
            # import_prop65 match on it.
            defaults = {'name': name}
            if cas_map.get(code):
                defaults['cas_number'] = cas_map[code]
            _, was_created = Chemical.objects.update_or_create(chem_code=code, defaults=defaults)
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(f'    {created:,} created, {updated:,} updated')

    def _import_commodities(self, lookup_dir):
        path = self._find(lookup_dir, 'PUR_SITE.txt', 'site.txt')
        if not path:
            self.stdout.write('  [commodities] file not found, skipping')
            return

        self.stdout.write('  Importing commodities...')
        created = updated = 0
        for row in read_csv(path):
            code = clean(row.get('site_code'))
            name = clean(row.get('site_name'))
            if not code:
                continue
            _, was_created = Commodity.objects.update_or_create(
                site_code=code,
                defaults={'name': name},
            )
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(f'    {created:,} created, {updated:,} updated')

    def _import_products(self, lookup_dir):
        path = self._find(lookup_dir, 'PRODUCT.txt', 'product.txt')

        if not path:
            self.stdout.write('  [products] file not found, skipping')
            return

        self.stdout.write('  Importing products...')
        created = updated = skipped = 0
        for row in read_csv(path):
            prodno = parse_int(row.get('prodno'))
            reg_number = clean(row.get('show_regno'))
            name = clean(row.get('product_name'))
            if not prodno or not reg_number or not name:
                skipped += 1
                continue
            fumigant = clean(row.get('fumigant_sw')).upper() in ('Y', 'X')
            try:
                _, was_created = Product.objects.update_or_create(
                    prodno=prodno,
                    defaults={
                        'reg_number': reg_number,
                        'name': name,
                        'fumigant': fumigant,
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1
            except Exception:
                skipped += 1
        self.stdout.write(f'    {created:,} created, {updated:,} updated, {skipped:,} skipped')

    def _import_product_chemicals(self, lookup_dir):
        path = self._find(lookup_dir, 'PROD_CHEM.txt', 'prod_chem.txt')
        if not path:
            return  # Only in 2023+; older years derive from udc rows

        self.stdout.write('  Importing product-chemical associations...')
        product_map = {p.prodno: p.pk for p in Product.objects.only('id', 'prodno')}
        chemical_map = {c.chem_code: c.pk for c in Chemical.objects.only('id', 'chem_code')}

        to_create = []
        seen = set()
        for row in read_csv(path):
            prodno = parse_int(row.get('prodno'))
            chem_code = parse_int(row.get('chem_code'))
            if not prodno or not chem_code:
                continue
            product_id = product_map.get(prodno)
            chemical_id = chemical_map.get(chem_code)
            if not product_id or not chemical_id:
                continue
            key = (product_id, chemical_id)
            if key in seen:
                continue
            seen.add(key)
            to_create.append(ProductChemical(
                product_id=product_id,
                chemical_id=chemical_id,
                pct_active=parse_float(row.get('prodchem_pct')),
            ))

        ProductChemical.objects.bulk_create(to_create, ignore_conflicts=True, batch_size=BATCH_SIZE)
        self.stdout.write(f'    {len(to_create):,} associations loaded')

    def _import_fumigation_methods(self, lookup_dir):
        path = self._find(lookup_dir, 'FUMIGATION_METHODS.txt', 'fumigation_methods.txt')
        if not path:
            self.stdout.write('  [fumigation methods] file not found, skipping')
            return

        self.stdout.write('  Importing fumigation methods...')
        created = updated = 0
        for row in read_csv(path):
            code = parse_int(row.get('fume_cd'))
            name = clean(row.get('fume_method'))
            if not code or not name:
                continue
            active = clean(row.get('fume_active')).upper() == 'Y'
            existing = FumigationMethod.objects.filter(code=code).first()
            if existing is None:
                FumigationMethod.objects.create(code=code, name=name, active=active)
                created += 1
            else:
                # Each year's archive carries the whole table as of then, so an
                # older year's file still lists a code a newer one has ended.
                # A code only ever goes active -> ended, never back.
                existing.name = name
                existing.active = existing.active and active
                existing.save(update_fields=['name', 'active', 'modified'])
                updated += 1
        self.stdout.write(f'    {created:,} created, {updated:,} updated')

    # --- Use record import ---

    def _build_county_cache(self, lookup_dir):
        county_file = self._find(lookup_dir, 'COUNTY.txt', 'county.txt')
        cdpr_names = {}
        if county_file:
            for row in read_csv(county_file):
                cd = parse_int(row.get('county_cd'))
                name = clean(row.get('county') or row.get('couty_name')).title()
                if cd and name:
                    cdpr_names[cd] = name

        # Map CDPR county name → Region pk by stripping "County" suffix from Region names
        region_by_name = {
            r.name.replace(' County', ''): r.pk
            for r in Region.objects.counties()
        }

        cache = {}
        for cd, name in cdpr_names.items():
            region_id = region_by_name.get(name)
            if region_id:
                cache[cd] = region_id
        return cache

    def _build_mtrs_cache(self):
        return {
            row['external_id']: row['id']
            for row in Region.objects.filter(type=Region.Type.MTRS).values('external_id', 'id')
        }

    def _build_commodity_cache(self):
        return {c.site_code: c.pk for c in Commodity.objects.only('id', 'site_code')}

    def _import_use_records(self, paths, year):
        udc_dir = paths['udc_dir']
        lookup_dir = paths['lookup_dir']

        county_cache = self._build_county_cache(lookup_dir)
        mtrs_cache = self._build_mtrs_cache()
        commodity_cache = self._build_commodity_cache()
        product_map = {p.prodno: p.pk for p in Product.objects.only('id', 'prodno')}
        chemical_map = {c.chem_code: c.pk for c in Chemical.objects.only('id', 'chem_code')}

        suffix = str(year)[-2:]
        udc_files = sorted(udc_dir.glob(f'udc{suffix}_*.txt'))
        if not udc_files:
            self.stdout.write('  No udc files found.')
            return

        self.stdout.write(f'  Found {len(udc_files)} county files.')
        total_imported = 0

        for udc_path in udc_files:
            county_cd = parse_int(udc_path.stem.split('_')[1])
            county_id = county_cache.get(county_cd)
            if county_id is None:
                self.stdout.write(f'  County {county_cd:02d}: no matching Region, skipping')
                continue

            count = self._import_county_file(
                udc_path, year, county_cd, county_id,
                mtrs_cache, commodity_cache, product_map, chemical_map,
            )
            total_imported += count

        self.stdout.write(f'\nDone: {total_imported:,} records imported.')

    def _import_county_file(self, path, year, county_cd, county_id,
                            mtrs_cache, commodity_cache, product_map, chemical_map):
        with transaction.atomic():
            PesticideUse.objects.filter(year=year, county_id=county_id).delete()

            records = []
            count = 0

            with open(path, encoding='utf-8', errors='replace') as f:
                for row in csv.DictReader(f):
                    prodno = parse_int(row.get('prodno'))
                    chem_code = parse_int(row.get('chem_code'))
                    site_code = clean(row.get('site_code'))

                    mtrs_key = make_mtrs_key(
                        row.get('base_ln_mer', ''),
                        row.get('township', ''),
                        row.get('tship_dir', ''),
                        row.get('range', ''),
                        row.get('range_dir', ''),
                        row.get('section', ''),
                    )

                    records.append(PesticideUse(
                        year=year,
                        use_no=parse_int(row.get('use_no')),
                        county_id=county_id,
                        mtrs_id=mtrs_cache.get(mtrs_key) if mtrs_key else None,
                        comtrs=clean(row.get('comtrs')),
                        product_id=product_map.get(prodno) if prodno else None,
                        chemical_id=chemical_map.get(chem_code) if chem_code else None,
                        commodity_id=commodity_cache.get(site_code) if site_code else None,
                        site_code=site_code,
                        pct_active=parse_float(row.get('prodchem_pct')),
                        lbs_chemical=parse_float(row.get('lbs_chm_used')),
                        lbs_product=parse_float(row.get('lbs_prd_used')),
                        amount_product=parse_float(row.get('amt_prd_used')),
                        unit_product=clean(row.get('unit_of_meas')),
                        acres_planted=parse_float(row.get('acre_planted')),
                        unit_planted=clean(row.get('unit_planted')),
                        acres_treated=parse_float(row.get('acre_treated')),
                        unit_treated=clean(row.get('unit_treated')),
                        application_count=parse_int(row.get('applic_cnt')),
                        application_date=parse_date(row.get('applic_dt')),
                        aerial_ground=clean(row.get('aer_gnd_ind')),
                        record_id=clean(row.get('record_id')),
                    ))
                    count += 1

                    if len(records) >= BATCH_SIZE:
                        PesticideUse.objects.bulk_create(records)
                        records = []
                        self.stdout.write(
                            f'  County {county_cd:02d}: {count:,} rows...', ending='\r'
                        )

            if records:
                PesticideUse.objects.bulk_create(records)

        self.stdout.write(f'  County {county_cd:02d}: {count:,} rows imported         ')
        return count

    # --- Fumigation technique ---

    def _import_fume_pass(self, paths, year):
        """
        The field-fumigation technique (`fume_cd`) only exists in CDPR's
        statewide PUR{year}.txt, not in the per-county udc files the records
        come from, so it's laid onto the imported records by (year, use_no).
        """
        path = self._find(paths['udc_dir'], f'PUR{year}.txt', f'pur{year}.txt')
        if not path:
            self.stdout.write(f'  No PUR{year}.txt in the archive, fumigation methods not set.')
            return
        county_cache = self._build_county_cache(paths['lookup_dir'])
        coded, unknown = self._import_fume_codes(path, year, county_cache)
        self.stdout.write(f'  Fumigation methods: {coded:,} records coded')
        if self.fume_rows_skipped:
            self.stdout.write(f'    {self.fume_rows_skipped:,} short or malformed rows skipped')
        if unknown:
            skipped = sum(unknown.values())
            codes = ', '.join(str(code) for code in sorted(unknown))
            self.stdout.write(f'    {skipped:,} records skipped for codes not in the lookup ({codes})')

    def _read_fume_codes(self, path, county_cache):
        """{use_no: fume_cd} for the imported counties' rows that carry a code."""
        codes = {}
        self.fume_rows_skipped = 0
        with open(path, encoding='utf-8', errors='replace', newline='') as f:
            reader = csv.reader(f)
            header = [name.strip() for name in next(reader, [])]
            try:
                use_no_at, fume_at, county_at = (header.index(name) for name in ('use_no', 'fume_cd', 'county_cd'))
            except ValueError:
                raise CommandError(f'{Path(path).name} has no use_no, fume_cd and county_cd columns')
            widest = max(use_no_at, fume_at, county_at)
            for row in reader:
                if len(row) <= widest:
                    self.fume_rows_skipped += 1
                    continue
                code = parse_int(row[fume_at])
                if not code or parse_int(row[county_at]) not in county_cache:
                    continue
                use_no = parse_int(row[use_no_at])
                if use_no is not None:
                    codes[use_no] = code
        return codes

    def _import_fume_codes(self, path, year, county_cache):
        """
        Set `fume_method` on the year's records from the statewide PUR file:
        every ingredient row of a use_no gets its code. Returns (records
        coded, {unknown code: records}) -- a code with no row in
        FUMIGATION_METHODS is counted and skipped, never invented.
        """
        by_code = {}
        for use_no, code in self._read_fume_codes(path, county_cache).items():
            by_code.setdefault(code, []).append(use_no)

        methods = dict(FumigationMethod.objects.values_list('code', 'pk'))
        unknown = {code: len(use_nos) for code, use_nos in by_code.items() if code not in methods}
        coded = 0
        with transaction.atomic():
            # A re-run replaces the year's codes rather than adding to them.
            PesticideUse.objects.filter(year=year, fume_method__isnull=False).update(fume_method=None)
            for code, use_nos in by_code.items():
                if code in unknown:
                    continue
                for start in range(0, len(use_nos), FUME_UPDATE_CHUNK):
                    chunk = use_nos[start:start + FUME_UPDATE_CHUNK]
                    PesticideUse.objects.filter(year=year, use_no__in=chunk).update(fume_method_id=methods[code])
                coded += len(use_nos)
        return coded, unknown
