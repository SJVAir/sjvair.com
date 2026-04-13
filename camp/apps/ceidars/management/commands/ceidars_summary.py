from django.core.management.base import BaseCommand, CommandError
from django.db.models import Avg, Count, F, Q, Sum

from camp.apps.ceidars.models import EmissionsRecord, Facility
from camp.apps.ceidars.management.commands.import_ceidars import COUNTY_CODES


CRITERIA_FIELDS = ['tog', 'rog', 'co', 'nox', 'sox', 'pm25', 'pm10']

TOXIC_FIELDS = [
    'acetaldehyde', 'benzene', 'butadiene', 'carbon_tetrachloride',
    'chromium_hexavalent', 'dichlorobenzene', 'formaldehyde',
    'methylene_chloride', 'naphthalene', 'perchloroethylene',
]

COUNTY_NAMES = {v: k for k, v in COUNTY_CODES.items()}  # name → code


class Command(BaseCommand):
    help = 'Print a summary table of CEIDARS emissions data.'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int)
        parser.add_argument('--county', type=int, help='County code (e.g. 10 for Fresno)')
        parser.add_argument('--toxics', action='store_true', help='Include named toxic air contaminants')

    def handle(self, *args, **options):
        year = options['year']
        county = options['county']
        show_toxics = options['toxics']

        if county and county not in COUNTY_CODES:
            raise CommandError(f'Unknown county code: {county}. Valid codes: {list(COUNTY_CODES)}')

        # Base queryset
        qs = EmissionsRecord.objects.select_related('facility')
        if year:
            qs = qs.filter(year=year)
        if county:
            qs = qs.filter(facility__county_code=county)

        # Determine grouping: if one dimension is fixed, group by the other
        if county and not year:
            group_by = ['year']
            label_field = 'year'
        else:
            group_by = ['facility__county_code']
            label_field = 'county'

        # Aggregate emissions and facility counts
        agg = {f: Sum(f) for f in CRITERIA_FIELDS}
        if show_toxics:
            agg.update({f: Sum(f) for f in TOXIC_FIELDS})

        rows = (
            qs
            .values(*group_by)
            .annotate(
                facility_count=Count('facility', distinct=True),
                geocoded_count=Count('facility', distinct=True, filter=Q(facility__point__isnull=False)),
                **agg,
            )
            .order_by(*group_by)
        )

        if not rows:
            self.stdout.write('No data found.')
            return

        # Build display rows
        display_fields = CRITERIA_FIELDS + (TOXIC_FIELDS if show_toxics else [])

        data = []
        for row in rows:
            if label_field == 'year':
                label = str(row['year'])
            else:
                code = row['facility__county_code']
                label = f'{COUNTY_CODES.get(code, "?")} ({code})'

            geocoded_pct = (row['geocoded_count'] / row['facility_count'] * 100) if row['facility_count'] else 0
            data.append({
                'label': label,
                'facilities': row['facility_count'],
                'geocoded': f"{row['geocoded_count']} ({geocoded_pct:.0f}%)",
                **{f: row[f] for f in display_fields},
            })

        # Totals row
        totals = {
            'label': 'TOTAL',
            'facilities': sum(r['facilities'] for r in data),
            'geocoded': '',
        }
        for f in display_fields:
            vals = [r[f] for r in data if r[f] is not None]
            totals[f] = sum(vals) if vals else None

        self._print_table(data, totals, display_fields, label_field, year, county)

    def _print_table(self, data, totals, fields, label_field, year, county):
        # Header
        if year and county:
            self.stdout.write(f'\n{COUNTY_CODES[county]} — {year}\n')
        elif year:
            self.stdout.write(f'\nAll counties — {year}\n')
        elif county:
            self.stdout.write(f'\n{COUNTY_CODES[county]} — all years\n')
        else:
            self.stdout.write('\nAll counties — all years\n')

        col_label = 'Year' if label_field == 'year' else 'County'
        headers = [col_label, 'Facilities', 'Geocoded'] + [f.upper().replace('_', ' ') for f in fields]

        # Format numeric values
        def fmt(val):
            if val is None:
                return '—'
            return f'{float(val):,.2f}'

        def row_values(r):
            return [r['label'], str(r['facilities']), r['geocoded']] + [fmt(r[f]) for f in fields]

        all_rows = [row_values(r) for r in data] + [row_values(totals)]

        # Column widths
        widths = [len(h) for h in headers]
        for row in all_rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))

        sep = '  '
        fmt_row = lambda cells: sep.join(c.ljust(widths[i]) if i < 2 else c.rjust(widths[i]) for i, c in enumerate(cells))
        divider = '-' * (sum(widths) + len(sep) * (len(widths) - 1))

        self.stdout.write(fmt_row(headers))
        self.stdout.write(divider)
        for row in all_rows[:-1]:
            self.stdout.write(fmt_row(row))
        self.stdout.write(divider)
        self.stdout.write(fmt_row(all_rows[-1]))
        self.stdout.write('')
