"""
The CARB/OEHHA Consolidated Table of health values (contable.pdf): the
acute and chronic reference exposure levels, inhalation unit risk and
molecular-weight adjustment factor behind ToxicPollutant's weights.

PDF only. pdfplumber's extract_table() gives 16-cell rows; the columns used
are named below. An id cell can list several ids (a CAS and CARB's own
code, plus a bracketed retired code) that all take the row's values.
"""
import re
from datetime import datetime

import pdfplumber

from camp.apps.emissions.models import ToxicPollutant, UNWEIGHTED_IDS

CONTABLE_URL = 'https://ww2.arb.ca.gov/sites/default/files/classic/toxics/healthval/contable.pdf'

ROW_WIDTH = 16
COL_NAME = 0
COL_ID = 1
COL_ACUTE = 2
COL_CHRONIC = 6
COL_IUR = 10
COL_MWAF = 15

# The table's names are uppercase, marked and footnoted; these read better.
NAME_OVERRIDES = {
    '9901': 'Diesel PM',
    '18540299': 'Hexavalent chromium',
    '1150': 'PAHs (total, components also reported)',
    '1151': 'PAHs (total)',
    '1016': 'Arsenic (inorganic)',
}
# An id that takes another's IUR when the table gives it none: PAHs with no
# components reported are weighted as benzo(a)pyrene.
IUR_FALLBACKS = {'1151': '50328'}

_CAS_RE = re.compile(r'^\d{2,7}-\d{2}-\d$')
_CODE_RE = re.compile(r'^\[?(\d{4})\]?$')
_NUMBER_RE = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')
_DATE_RE = re.compile(r'last updated:?\s*([A-Z][a-z]+ \d{1,2}, \d{4})')


def ids(cell):
    """The CARB pollutant ids in an id cell: a dashed CAS without its dashes, or a 4-digit code (bracketed or not)."""
    result = []
    for token in (cell or '').split():
        token = token.strip()
        if _CAS_RE.match(token):
            result.append(token.replace('-', ''))
        else:
            match = _CODE_RE.match(token)
            if match:
                result.append(match.group(1))
    return result


def number(cell):
    """The first number in a value cell ('2.9E-05TAC', '1.5E-01\\nTAC', '7.7E-3'), or None for a blank."""
    match = _NUMBER_RE.search(cell or '')
    return float(match.group(0)) if match else None


def clean_name(cell):
    """One line, without the TAC marker, the 'values also apply to' tail or a footnote letter; sentence case when the table shouts."""
    name = ' '.join((cell or '').split())
    name = re.sub(r'\s*values also apply to:.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'TAC\b', '', name)
    name = re.sub(r',\s*[a-z]$', '', name)            # ', i'
    name = re.sub(r'(?<=[A-Z)\]])[a-z]$', '', name)   # 'BENZO(A)PYRENEl'
    name = ' '.join(name.split()).strip(' ,')
    if name.isupper():
        name = name.capitalize()
    return name


def parse(path):
    """([row dicts], last-updated date or None) from the PDF at `path`."""
    rows = []
    date = None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            if date is None:
                match = _DATE_RE.search(page.extract_text() or '')
                if match:
                    date = datetime.strptime(match.group(1), '%B %d, %Y').date()
            for row in page.extract_table() or []:
                if len(row) < ROW_WIDTH:
                    continue
                carb_ids = ids(row[COL_ID])
                if not carb_ids:
                    continue
                mwaf = number(row[COL_MWAF])
                for carb_id in carb_ids:
                    rows.append({
                        'carb_id': carb_id,
                        'cas_number': ToxicPollutant.cas_from_carb_id(carb_id),
                        'name': clean_name(row[COL_NAME]),
                        'acute_rel': number(row[COL_ACUTE]),
                        'chronic_rel': number(row[COL_CHRONIC]),
                        'iur': number(row[COL_IUR]),
                        'mwaf': mwaf if mwaf is not None else 1.0,
                    })
    return rows, date


def apply(rows, date):
    """
    Upsert ToxicPollutant from parsed rows: create a row for every table
    entry (so the picker can name a pollutant before any facility reports
    it), set the health values, apply the name overrides and IUR fallbacks,
    recompute the weights. The first of two rows for the same id wins.
    Returns {'created', 'updated'}.
    """
    by_id = {}
    for row in rows:
        by_id.setdefault(row['carb_id'], row)
    for carb_id, source in IUR_FALLBACKS.items():
        if carb_id in by_id and by_id[carb_id]['iur'] is None and source in by_id:
            by_id[carb_id]['iur'] = by_id[source]['iur']
    created = updated = 0
    for carb_id, row in by_id.items():
        name = NAME_OVERRIDES.get(carb_id, row['name'])
        pollutant = ToxicPollutant.objects.filter(carb_id=carb_id).first()
        if pollutant is None:
            pollutant = ToxicPollutant.create_for(carb_id, name)
            created += 1
        else:
            updated += 1
        pollutant.name = name
        pollutant.cas_number = row['cas_number']
        pollutant.iur = row['iur']
        pollutant.chronic_rel = row['chronic_rel']
        pollutant.acute_rel = row['acute_rel']
        pollutant.mwaf = row['mwaf']
        pollutant.weighted = carb_id not in UNWEIGHTED_IDS
        pollutant.health_values_date = date
        pollutant.set_weights()
        pollutant.save()
    return {'created': created, 'updated': updated}
