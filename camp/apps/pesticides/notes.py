"""
Plain-language health notes for the pesticides explorer.

Each note (title/summary/detail/source_url) lives in a single datafile so the
copy that explains a badge, a category, or a piece of jargon is written once
and reused everywhere it shows up -- badge tooltips, the "What this means"
block on detail/notice/section/place pages, the landing page's "About this
data" explainer, and the "How to read this page" callout.
"""
from functools import lru_cache

from django.core.exceptions import ImproperlyConfigured

from camp.utils.datafiles import datafile

NOTES_FILE = 'pesticide-health-notes.yaml'

REQUIRED_KEYS = (
    'prop65', 'iarc_1', 'iarc_2a', 'iarc_2b', 'iarc_3', 'carb_tac',
    'fumigant', 'cholinesterase_inhibitor', 'groundwater_contaminant', 'biopesticide', 'oil',
    'california_restricted', 'restricted_material', 'noi_meaning', 'pur_lag', 'shades', 'badges',
)

# Chemical.Category values (other than the Prop 65 / CARB TAC categories,
# which are already covered by is_prop65 / is_tac) that have their own note.
_CATEGORY_NOTE_KEYS = ('fumigant', 'cholinesterase_inhibitor', 'groundwater_contaminant', 'biopesticide', 'oil',
    'california_restricted')


@lru_cache(maxsize=1)
def all_notes():
    """key -> {'key', 'title', 'summary', 'detail' (str|None), 'source_url'}."""
    data = datafile(NOTES_FILE) or {}
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        raise ImproperlyConfigured(
            f'{NOTES_FILE} is missing required note(s): {", ".join(missing)}'
        )
    notes = {}
    for key, entry in data.items():
        notes[key] = {
            'key': key,
            'title': entry.get('title', ''),
            'summary': entry.get('summary', ''),
            'detail': entry.get('detail'),
            'source_url': entry.get('source_url', ''),
        }
    return notes


def note(key):
    return all_notes().get(key)


def keys_for_chemical(chemical):
    keys = []
    if chemical.is_prop65:
        keys.append('prop65')
    if chemical.is_tac:
        keys.append('carb_tac')
    if chemical.iarc_group:
        keys.append(f'iarc_{chemical.iarc_group.lower()}')
    for category in chemical.other_categories:
        if category in _CATEGORY_NOTE_KEYS and category not in keys:
            keys.append(category)
    return keys


def keys_for_product(product):
    keys = []
    if product.fumigant:
        keys.append('fumigant')
    # From the active ingredients, not the deprecated product flag: 3 CCR
    # 6400 names ingredients, and nothing ever set the flag.
    if product.is_restricted:
        keys.append('restricted_material')
    return keys


def keys_for_chemicals(chemicals):
    """Ordered, deduplicated union of keys_for_chemical() over an iterable of chemicals."""
    keys = []
    for chemical in chemicals:
        for key in keys_for_chemical(chemical):
            if key not in keys:
                keys.append(key)
    return keys


def keys_for_notice(notice):
    keys = ['noi_meaning', 'restricted_material']
    # Sorted by pk (not the related models' default name ordering) so the
    # result is stable and reflects the order chemicals/products were added
    # to the notice, not alphabetical happenstance. Uses the prefetch cache
    # via `.all()` -- the sort is done in Python, not a new query.
    for key in keys_for_chemicals(sorted(notice.chemicals.all(), key=lambda c: c.pk)):
        if key not in keys:
            keys.append(key)
    for product in sorted(notice.products.all(), key=lambda p: p.pk):
        for key in keys_for_product(product):
            if key not in keys:
                keys.append(key)
    return keys


def notes_for(keys):
    data = all_notes()
    seen = set()
    result = []
    for key in keys:
        if key in seen or key not in data:
            continue
        seen.add(key)
        result.append(data[key])
    return result
