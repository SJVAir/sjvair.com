"""
CDFA's Dairy Digester Research and Development Program (DDRDP) project-level
PDF, parsed into DigesterGrant rows: which dairy each grant went to, the
developer, the award, the biogas end use and CDFA's own estimate of the
annual GHG reduction. The PDF carries no separate "dairy name" column --
only "Project Title" (usually a dairy's name plus "Digester"/"Biogas..."),
so `dairy_name` is a copy of `project_name`; normalise_name() strips the
generic words so name variants ("Lakeside Dairy, LLC", "Lakeside Digester")
can meet.

Matching (match()) tries, in order: the project's or the dairy's normalised
name plus its mailing city against a CADD Dairy's name and city; failing
that, a normalised name that's unique Valley-wide; failing that,
ddrdp_crosswalk.CROSSWALK (hand-kept, extended from import_ddrdp's
unmatched-projects printout). Unmatched rows are kept, not dropped -- their
county still counts toward county_totals().

Manual: CDFA updates the PDF a few times a year, so there's no periodic
task; re-run `import_ddrdp` when it changes (the "Updated <date>" line on
the PDF becomes the SourceImport's version).
"""
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pdfplumber
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Sum

from camp.apps.emissions import cities, ddrdp_crosswalk
from camp.apps.emissions.models import Dairy, DigesterGrant, SourceImport

URL = 'https://www.cdfa.ca.gov/oefi/DDRDP/docs/DDRDP_Project_Level_Data.pdf'
SOURCE = 'ddrdp'
CACHE_TIMEOUT = 60 * 60 * 24

# Words normalise_name() drops so name variants ("Lakeside Dairy, LLC",
# "LAKESIDE DAIRY") meet -- unless dropping them would leave nothing, in
# which case the full word list is kept. "digester" is deliberately NOT
# here: a project title is often just a dairy's given name plus "Digester"
# (no separate dairy name in the PDF at all -- see the module docstring),
# and keeping "digester" in the normalised form is what lets a crosswalk
# entry keyed on the full project title ("mystery digester") find it.
STOP_WORDS = {'dairy', 'dairies', 'farm', 'farms', 'ranch', 'llc', 'inc', 'lp', 'and', 'the', 'of'}

# The model field each column maps to, by a keyword found (case-insensitively,
# whitespace-collapsed) in the header cell. Every page of the PDF repeats the
# header, but pdfplumber's line-detection inserts a different number of
# spurious empty columns on different pages, so columns are found by keyword
# per page, never by a fixed index.
_COLUMN_KEYWORDS = {
    'project_name': 'project title',
    'developer': 'developer',
    'grant_amount': 'grant amount',
    'end_use': 'biogas end',
    'est_reduction_tco2e': 'estimated annual ghg',
    'city': 'city',
    'county': 'county',
    'awarded': 'start date',
    'operational': 'completion date',
}


class DDRDPFormatError(Exception):
    """The PDF's layout doesn't match what parse() expects."""


def normalise_name(name):
    words = re.sub(r'[^a-z0-9 ]', ' ', (name or '').lower().replace('&', ' ')).split()
    core = [w for w in words if w not in STOP_WORDS]
    return ' '.join(core) if core else ' '.join(words)


def _clean_header(text):
    return re.sub(r'\s+', ' ', (text or '')).strip().lower()


def _money(text):
    if not text:
        return None
    text = text.replace('$', '').replace(',', '').strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _float(text):
    if not text:
        return None
    text = text.replace(',', '').strip()
    try:
        return float(text)
    except ValueError:
        return None


def _date(text):
    if not text:
        return None
    text = text.strip()
    for fmt in ('%m/%d/%Y', '%m/%d/%y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _map_columns(header):
    """{field: column index} for one page's header row, raising DDRDPFormatError if a column can't be found."""
    cleaned = [_clean_header(cell) for cell in header]
    mapping = {}
    for field, keyword in _COLUMN_KEYWORDS.items():
        idx = next((i for i, cell in enumerate(cleaned) if keyword in cell), None)
        if idx is None:
            raise DDRDPFormatError(f"expected column not found: '{keyword}' (for {field})")
        mapping[field] = idx
    return mapping


def parse(path):
    """
    (rows, version). `rows`: one dict per project, keyed to DigesterGrant's
    field names (project_name, dairy_name, city, county, developer,
    grant_amount, end_use, est_reduction_tco2e, awarded, operational).
    `version`: the PDF's own "Updated <date>" line on page 1, ISO, or '' if
    it can't be found. A handful of terminated/cancelled projects carry a
    note instead of a GHG figure and have no city/county/dates -- they're
    kept (grant_amount and the project/dairy name are still there; only
    county_totals(), which needs county, leaves them out).
    """
    with pdfplumber.open(str(path)) as pdf:
        if not pdf.pages:
            raise DDRDPFormatError('empty PDF')

        version = ''
        first_text = pdf.pages[0].extract_text() or ''
        found = re.search(r'updated\s+(\d{1,2}/\d{1,2}/\d{4})', first_text, re.IGNORECASE)
        if found:
            parsed = _date(found.group(1))
            version = parsed.isoformat() if parsed else ''

        rows = []
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            header, *body = table
            mapping = _map_columns(header)
            for raw in body:
                project_name = (raw[mapping['project_name']] or '').strip()
                if not project_name or _clean_header(project_name) == 'project title':
                    continue  # a repeated header row pdfplumber counted as data
                rows.append({
                    'project_name': project_name,
                    'dairy_name': project_name,
                    'city': (raw[mapping['city']] or '').strip(),
                    'county': (raw[mapping['county']] or '').strip(),
                    'developer': (raw[mapping['developer']] or '').strip(),
                    'grant_amount': _money(raw[mapping['grant_amount']]),
                    'end_use': (raw[mapping['end_use']] or '').strip(),
                    'est_reduction_tco2e': _float(raw[mapping['est_reduction_tco2e']]),
                    'awarded': _date(raw[mapping['awarded']]),
                    'operational': _date(raw[mapping['operational']]),
                })
    if not rows:
        raise DDRDPFormatError('no project rows found')
    return rows, version


def match(rows):
    """
    `rows` with 'dairy' (a Dairy or None) and 'match_method' ('auto' |
    'manual' | '') filled in. Tried in order: the project's or the dairy's
    normalised name plus its mailing city against a Dairy's name and
    mailing city (both exactly); a normalised name that's unique
    Valley-wide; ddrdp_crosswalk.CROSSWALK, keyed by the normalised project
    or dairy name, to a CADD id.
    """
    by_name_city = {}
    by_name = {}
    for dairy in Dairy.objects.all():
        key_name = normalise_name(dairy.name)
        key_city = cities.lookup_key(dairy.address.get('city'))
        by_name_city.setdefault((key_name, key_city), dairy)
        by_name.setdefault(key_name, []).append(dairy)

    matched = []
    for row in rows:
        row = dict(row)
        project_key = normalise_name(row['project_name'])
        dairy_key = normalise_name(row['dairy_name'])
        city_key = cities.lookup_key(row.get('city'))

        dairy = by_name_city.get((project_key, city_key)) or by_name_city.get((dairy_key, city_key))
        method = 'auto' if dairy is not None else ''

        if dairy is None:
            for key in (project_key, dairy_key):
                candidates = by_name.get(key)
                if candidates and len(candidates) == 1:
                    dairy = candidates[0]
                    method = 'auto'
                    break

        if dairy is None:
            cadd_id = ddrdp_crosswalk.CROSSWALK.get(project_key) or ddrdp_crosswalk.CROSSWALK.get(dairy_key)
            if cadd_id is not None:
                dairy = Dairy.objects.filter(cadd_id=cadd_id).first()
                if dairy is not None:
                    method = 'manual'

        row['dairy'] = dairy
        row['match_method'] = method
        matched.append(row)
    return matched


@dataclass
class Report:
    parsed: int = 0
    matched_auto: int = 0
    matched_manual: int = 0
    unmatched: int = 0

    def lines(self):
        return [
            f'DDRDP: {self.parsed:,} projects; {self.matched_auto:,} matched by name/city, '
            f'{self.matched_manual:,} by crosswalk, {self.unmatched:,} unmatched.',
        ]


def _version_date(version):
    try:
        return date.fromisoformat(version) if version else None
    except ValueError:
        return None


def apply(rows, version):
    """
    One transaction: replace every DigesterGrant with `rows` (as match()
    returns them), stamp SourceImport(SOURCE, version), and bump the
    dairies cache generation (county_totals() is cached under it, same
    pattern as the rest of dairies.py -- there's no separate ddrdp
    generation).
    """
    from camp.apps.emissions import dairies

    report = Report(
        parsed=len(rows),
        matched_auto=sum(1 for r in rows if r['match_method'] == 'auto'),
        matched_manual=sum(1 for r in rows if r['match_method'] == 'manual'),
        unmatched=sum(1 for r in rows if not r['match_method']),
    )
    with transaction.atomic():
        DigesterGrant.objects.all().delete()
        DigesterGrant.objects.bulk_create([
            DigesterGrant(
                dairy=row.get('dairy'),
                project_name=row['project_name'],
                dairy_name=row['dairy_name'],
                city=row.get('city') or '',
                county=row.get('county') or '',
                developer=row.get('developer') or '',
                grant_amount=row.get('grant_amount'),
                end_use=row.get('end_use') or '',
                est_reduction_tco2e=row.get('est_reduction_tco2e'),
                awarded=row.get('awarded'),
                operational=row.get('operational'),
                match_method=row.get('match_method') or '',
            )
            for row in rows
        ])
        SourceImport.objects.create(source=SOURCE, version=version or '', data_through=_version_date(version))
    dairies.clear_caches()
    return report


def stamp():
    return SourceImport.latest(SOURCE)


def county_totals(county):
    """
    {'grants', 'amount', 'reduction'} over a county's DigesterGrant rows
    (matched to `county` by CDFA's own county text, case-insensitively
    against the Region's short_name), or None with no rows. Cached under
    dairies.key('ddrdp', county.pk); apply()'s dairies.clear_caches()
    invalidates it, same as every other dairies.py aggregate.
    """
    from camp.apps.emissions import dairies

    def compute():
        agg = DigesterGrant.objects.filter(county__iexact=county.short_name).aggregate(
            grants=Count('pk'), amount=Sum('grant_amount'), reduction=Sum('est_reduction_tco2e'),
        )
        if not agg['grants']:
            return None
        return {'grants': agg['grants'], 'amount': agg['amount'], 'reduction': agg['reduction']}
    return cache.get_or_set(dairies.key('ddrdp', county.pk), compute, CACHE_TIMEOUT)
