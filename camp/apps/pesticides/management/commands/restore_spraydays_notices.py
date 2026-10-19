import csv
import re
import sys
from collections import defaultdict

from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from camp.apps.pesticides.models import Chemical, PesticideNotice, Product
from camp.apps.pesticides.spraydays import _MTRS_RE
from camp.apps.regions.models import Region

# SprayDays only serves active notices, so the past ones exist nowhere but
# our own table: a reset of the pesticides app (`migrate pesticides zero`)
# would lose them for good. Export them first with this query, against the
# database as it stands -- it reads only columns every version of the app has
# had -- and reload them with this command once the re-import has products
# and chemicals again. Products and chemicals travel as CDPR's codes (prodno,
# chem_code), since their ids change on a re-import. Sections and counties are
# found again from the COMTRS code, not the exported ids: a rebuild from
# scratch re-imports regions under new ids. (The export keeps mtrs_id and
# county_id only so older exports still load; they are ignored.)
#
#   heroku pg:psql -a <app> -c "\copy (<EXPORT_SQL>) TO 'notices.csv' WITH CSV HEADER"
EXPORT_SQL = (
    "SELECT n.application_id, n.comtrs, n.mtrs_id, n.county_id, ST_AsText(n.point) AS point, "
    "n.scheduled_application, n.treated_amount, n.treated_units, n.application_method, n.created, "
    "(SELECT string_agg(p.prodno::text, '|' ORDER BY p.prodno) FROM pesticides_pesticidenotice_products np "
    "JOIN pesticides_product p ON p.id = np.product_id WHERE np.pesticidenotice_id = n.id) AS prodnos, "
    "(SELECT string_agg(c.chem_code::text, '|' ORDER BY c.chem_code) FROM pesticides_pesticidenotice_chemicals nc "
    "JOIN pesticides_chemical c ON c.id = nc.chemical_id WHERE nc.pesticidenotice_id = n.id) AS chem_codes "
    "FROM pesticides_pesticidenotice n ORDER BY n.application_id"
)


def codes(value):
    return [int(code) for code in (value or '').split('|') if code]


def optional_float(value):
    return float(value) if value not in (None, '') else None


# County, optional meridian letter (PUR has it, SprayDays leaves it out),
# township, range, section: "10M14S20E01" or "1014S20E01".
COMTRS_RE = re.compile(r'^(\d{2})([A-Z]?)(\d{2})([NS])(\d{2})([EW])(\d{2})$')


class SectionFinder:
    """Find a notice's county and MTRS section from its COMTRS code."""

    def __init__(self):
        self.counties = {
            metadata.get('ca_county_code'): pk
            for pk, metadata in Region.objects.filter(type=Region.Type.COUNTY).values_list('pk', 'metadata')
            if metadata
        }
        # (township, N/S, range, E/W, section) -> [(meridian letter, pk)]
        self.sections = defaultdict(list)
        for pk, external_id in Region.objects.filter(type=Region.Type.MTRS).values_list('pk', 'external_id'):
            match = _MTRS_RE.match(external_id or '')
            if match:
                township, ns, range_, ew, section = match.groups()
                key = (int(township), ns, int(range_), ew, int(section))
                self.sections[key].append((external_id[0], pk))

    def county(self, comtrs):
        return self.counties.get((comtrs or '')[:2])

    def section(self, comtrs, point):
        match = COMTRS_RE.match(comtrs or '')
        if not match:
            return None
        _, meridian, township, ns, range_, ew, section = match.groups()
        candidates = self.sections.get((int(township), ns, int(range_), ew, int(section)), [])
        if meridian:
            candidates = [c for c in candidates if c[0] == meridian]
        if len(candidates) == 1:
            return candidates[0][1]
        if candidates and point is not None:
            # The same township/range/section under two meridians: the one the pin is in.
            return Region.objects.filter(
                pk__in=[pk for _, pk in candidates], boundary__geometry__covers=point,
            ).values_list('pk', flat=True).first()
        return None


class Command(BaseCommand):
    help = 'Reload SprayDays notices exported before a pesticides reset (see EXPORT_SQL in this module).'

    def add_arguments(self, parser):
        parser.add_argument('--path', required=True, help="The exported CSV, or '-' to read it from stdin.")
        parser.add_argument('--print-export-sql', action='store_true', help='Print the export query and exit.')

    def handle(self, *args, **options):
        if options['print_export_sql']:
            self.stdout.write(EXPORT_SQL)
            return
        if options['path'] == '-':
            rows = list(csv.DictReader(sys.stdin))
        else:
            try:
                with open(options['path'], newline='') as handle:
                    rows = list(csv.DictReader(handle))
            except OSError as error:
                raise CommandError(f'Cannot read {options["path"]}: {error}')
        if rows and 'application_id' not in rows[0]:
            raise CommandError('Not a notices export: no application_id column (see --print-export-sql).')

        products = dict(Product.objects.values_list('prodno', 'pk'))
        chemicals = dict(Chemical.objects.values_list('chem_code', 'pk'))
        existing = set(PesticideNotice.objects.values_list('application_id', flat=True))
        finder = SectionFinder()
        created = skipped = unplaced = 0
        missing_products, missing_chemicals = set(), set()

        with transaction.atomic():
            for row in rows:
                application_id = int(row['application_id'])
                # A notice SprayDays still serves was fetched afresh after the
                # reset; its live copy wins over the export.
                if application_id in existing:
                    skipped += 1
                    continue
                point = GEOSGeometry(row['point'], srid=4326) if row['point'] else None
                mtrs_id = finder.section(row['comtrs'], point)
                # A notice exported without a section stays without one, unremarked.
                if mtrs_id is None and row['mtrs_id']:
                    unplaced += 1
                notice = PesticideNotice.objects.create(
                    application_id=application_id,
                    comtrs=row['comtrs'],
                    mtrs_id=mtrs_id,
                    county_id=finder.county(row['comtrs']),
                    point=point,
                    scheduled_application=parse_datetime(row['scheduled_application']),
                    treated_amount=optional_float(row['treated_amount']),
                    treated_units=row['treated_units'] or '',
                    application_method=row['application_method'] or '',
                )
                if row.get('created'):
                    # Keep when it was first seen; create() stamped it now.
                    PesticideNotice.objects.filter(pk=notice.pk).update(created=parse_datetime(row['created']))
                product_codes, chemical_codes = codes(row['prodnos']), codes(row['chem_codes'])
                notice.products.set([products[code] for code in product_codes if code in products])
                notice.chemicals.set([chemicals[code] for code in chemical_codes if code in chemicals])
                missing_products.update(code for code in product_codes if code not in products)
                missing_chemicals.update(code for code in chemical_codes if code not in chemicals)
                created += 1

        self.stdout.write(f'Restored {created} notices; skipped {skipped} already present.')
        if unplaced:
            self.stdout.write(self.style.WARNING(
                f'Unplaced: {unplaced} notice(s) with no matching section -- import_mtrs first.'
            ))
        if missing_products or missing_chemicals:
            self.stdout.write(self.style.WARNING(
                f'Unlinked: {len(missing_products)} product number(s) and {len(missing_chemicals)} '
                'chemical code(s) not in the database -- import_pur first, with lookups.'
            ))
