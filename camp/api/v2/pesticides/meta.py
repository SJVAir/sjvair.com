"""
`pesticides/meta/`: labels and short descriptions for the values the pesticide endpoints
filter on, so clients don't hardcode them. Built from the same sources the explorer
uses (model choices, `stats`, the health notes), read here and never changed.
"""
from resticus import generics, http

from camp.apps.pesticides import notes, stats
from camp.apps.pesticides.forms import UNASSIGNED_CATEGORIES
from camp.apps.pesticides.models import Chemical

from .endpoints import NO_METHOD

# The health note that explains each category. The three Prop 65 lists share one note,
# and CARB's Toxic Air Contaminants have theirs; every other category has its own.
CATEGORY_NOTES = {
    Chemical.Category.CARCINOGEN: 'prop65',
    Chemical.Category.REPRODUCTIVE_TOXIN: 'prop65',
    Chemical.Category.DEVELOPMENTAL_TOXIN: 'prop65',
    Chemical.Category.TOXIC_AIR_CONTAMINANT: 'carb_tac',
}

# What each narrowing keeps (see stats.narrow_rows). Restricted and fumigant are about the
# product applied, not the chemical: the `category` filter's values of the same name
# test the chemical's own categories and can give different numbers.
NARROW_DESCRIPTIONS = {
    stats.NARROW_CONCERN: (
        'Chemicals on a Prop 65 list (carcinogen, reproductive or developmental toxin), '
        "CARB's Toxic Air Contaminants, California's restricted materials, or IARC groups "
        '1, 2A and 2B.'),
    stats.NARROW_RESTRICTED: (
        "Products California restricts (CDPR's per-product restricted-material flag, or a "
        'restricted ingredient when CDPR does not list the product). A property of the '
        'product, unlike category=california_restricted.'),
    stats.NARROW_FUMIGANT: (
        'Products classified as fumigants. A property of the product, unlike '
        'category=fumigant.'),
    stats.NARROW_AERIAL: stats.NARROW_HELP[stats.NARROW_AERIAL],
}


def categories():
    unused = {str(value) for value in UNASSIGNED_CATEGORIES}
    return [
        {
            'key': value,
            'label': str(label),
            'description': notes.note(CATEGORY_NOTES.get(value, value))['summary'],
            'in_use': value not in unused,
        }
        for value, label in Chemical.Category.choices
    ]


def iarc_groups():
    groups = []
    for value, label in Chemical.IARCGroup.choices:
        # The model's label is "Group 2A – Probably carcinogenic to humans".
        name, _, description = str(label).partition(' – ')
        groups.append({'key': value, 'label': name, 'description': description})
    return groups


def methods():
    return [
        {'key': method or NO_METHOD, 'label': stats.METHOD_LABELS[method]}
        for method in stats.METHOD_ORDER
    ]


def narrows():
    return [
        {'key': key, 'label': label, 'description': NARROW_DESCRIPTIONS[key]}
        for key, label in stats.NARROW_CHOICES
    ]


def placeholder_chemicals():
    rows = Chemical.objects.filter(chem_code__in=Chemical.PLACEHOLDER_CODES).order_by('chem_code')
    return [{'id': chemical.sqid, 'name': chemical.name} for chemical in rows]


class PesticidesMeta(generics.Endpoint):
    """
    Labels for the pesticide filters: chemical `categories` (with `in_use`, false for the
    ones no import assigns), `iarc_groups`, application `methods` (the use records' codes;
    spray notices name their methods in SprayDays' own words, which this doesn't cover),
    the `narrows` (`?narrow=`), and the `placeholder_chemicals` (CDPR's stand-ins for an
    unnamed ingredient). Keys are permanent; labels may change.
    """

    def get(self, request):
        response = http.Http200({'data': {
            'categories': categories(),
            'iarc_groups': iarc_groups(),
            'methods': methods(),
            'narrows': narrows(),
            'placeholder_chemicals': placeholder_chemicals(),
        }})
        response['Cache-Control'] = 'public, max-age=86400'
        return response
