"""
`pesticides/meta/`: labels and short descriptions for the values the pesticide endpoints
filter on, so clients don't hardcode them. Built from the same sources the explorer
uses (model choices, `stats`, the health notes), read here and never changed.
"""
from resticus import generics, http

from camp.apps.pesticides import maps, notes, stats
from camp.apps.pesticides.badges import BADGES
from camp.apps.pesticides.forms import UNASSIGNED_CATEGORIES
from camp.apps.pesticides.links import LINK_PARAMS, explorer_links
from camp.apps.pesticides.models import Chemical
from camp.apps.pesticides.scales import get_spray_notice_scale
from camp.apps.pesticides.places import SPRAYDAYS_URL

from .endpoints import NO_METHOD
from .sections import NOTICE_VALUE_FILTERS

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
    unnamed ingredient). Also the server-owned explainer text: `notes` (key -> `{key, title,
    summary, detail, source_url}`), the classification `badges` (`{key, label, note}` in
    display order; `note` is a key of `notes`) and `links`, and `notice_filters`: the value filters the notice endpoints accept (they record no
    commodity). Also `years` (years with data, newest first) and `ramp` (`colors`,
    `no_data`: the map's shade colors). Keys are permanent; labels may change.

    `links`: `spraydays_signup`, and the explorer pages as absolute URL templates on the
    request's origin: `section_page`, `section_records`, `section_notices`,
    `section_notices_past` and `chemical_page` (the bare-sqid redirect, which carries the
    query along to the slugged page). `{id}` is the section's or chemical's sqid. `link_params`
    (same keys, minus `spraydays_signup`) lists the query params a client may add, each
    `{param, from}`. Fill rule: replace `{id}`, then append `&param=value` (`?` when the
    template has no query) for each entry whose `from` value the client has, URL-encoded.
    The `from` values: `year` (`all` for all years; records needs it as well as the dates),
    `month_start`/`month_end` (first and last Pacific day of a month period, `YYYY-MM-DD`;
    leave off for a year period), `chemical_id`, `product_id`, `commodity_id`,
    `aerial_ground` and `narrow` (the values sent to `sections/`, under the same names),
    `notices_year` and `notices_month` (year and month 1-12 of the notices layer's day).
    Use `section_notices_past` when the notices layer shows a past day, else
    `section_notices`. Left off because no explorer page takes them: `category` and
    `iarc_group` everywhere, `month` on the section and chemical pages, `aerial_ground` and
    `commodity_id` on the notices links, and `county` everywhere.
    """

    def get(self, request):
        response = http.Http200({'data': {
            'categories': categories(),
            'iarc_groups': iarc_groups(),
            'methods': methods(),
            'narrows': narrows(),
            'placeholder_chemicals': placeholder_chemicals(),
            'notes': dict(notes.all_notes()),
            'badges': BADGES,
            'links': {'spraydays_signup': SPRAYDAYS_URL, **explorer_links(request)},
            'link_params': LINK_PARAMS,
            'notice_filters': list(NOTICE_VALUE_FILTERS),
            'years': list(reversed(stats.available_years())),
            'ramp': {'colors': maps.RAMP, 'no_data': maps.NO_DATA},
            # Keyed by catalog entry-type id, like hms/meta/'s.
            'scales': {scale.id: scale.to_json() for scale in (get_spray_notice_scale(),)},
        }})
        response['Cache-Control'] = 'public, max-age=86400'
        return response
