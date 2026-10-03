"""
Matching a greenhouse-gas program's row (GHGRP, MRR) to a CEIDARS facility,
for import_ghgrp and import_mrr.
"""
import difflib
import re

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db.models import Q

from camp.apps.emissions.importers import ghg_crosswalk, icis
from camp.apps.emissions.models import Facility, GHGReport

# The auto match: best candidate's name similarity, and how far ahead of the
# runner-up it must be. Conservative on purpose: a wrong match puts one
# company's emissions on another's page; an unmatched row still shows on
# the county page.
AUTO_RATIO = 0.8
AUTO_MARGIN = 0.05
MATCH_KM = 1.0
# Corporate noise that names differ on between programs.
STOPWORDS = frozenset({
    'INC', 'LLC', 'LP', 'LTD', 'CO', 'CORP', 'CORPORATION', 'COMPANY', 'THE', 'OF', 'DBA',
})
_NON_ALNUM = re.compile(r'[^A-Z0-9 ]+')


def name_key(name):
    text = (name or '').upper().replace('&', ' AND ')
    text = _NON_ALNUM.sub(' ', text)
    return ' '.join(token for token in text.split() if token not in STOPWORDS)


def similarity(a, b):
    return difflib.SequenceMatcher(None, name_key(a), name_key(b)).ratio()


def facility_for_key(key):
    """The facility for a crosswalk key, or None when the key is None or stale."""
    if not key:
        return None
    county_code, district, facid = key
    return Facility.objects.filter(county_code=county_code, air_district__external_id=district, facid=facid).first()


def candidates_near(point, km=MATCH_KM):
    """Facilities with a trusted point within `km` of `point`, nearest first (geodetic, metres on a sphere)."""
    return (
        Facility.objects
        .filter(point__isnull=False, point_source__in=Facility.TRUSTED_POINT_SOURCES)
        .filter(point__dwithin=(point, 0.02), point__distance_lte=(point, D(km=km)))
        .annotate(distance=Distance('point', point))
        .order_by('distance')
    )


def candidates_in_zip(zipcode):
    zip5 = (zipcode or '').strip()[:5]
    if not zip5.isdigit():
        return Facility.objects.none()
    return Facility.objects.filter(Q(zipcode__external_id=zip5) | Q(address__zipcode=zip5))


def best_match(name, candidates):
    """The one candidate whose name clearly matches, or None."""
    scored = sorted(((similarity(name, f.name), f) for f in candidates), key=lambda pair: -pair[0])
    if not scored or scored[0][0] < AUTO_RATIO:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < AUTO_MARGIN:
        return None
    return scored[0][1]


def resolve(program, external_id, *, name, frs_air_id=None, point=None, zipcode=''):
    """
    (facility, match_method) for one program row: the FRS AIR id when it parses
    to a facility we have; else the crosswalk (which may pin None); else the
    auto match near the point (GHGRP) or in the ZIP (MRR); else (None, '').
    """
    if frs_air_id:
        parsed = icis.parse_pgm_sys_id(frs_air_id)
        if parsed:
            facility = facility_for_key(parsed)
            if facility is not None:
                return facility, GHGReport.MatchMethod.FRS
    table = ghg_crosswalk.GHGRP if program == GHGReport.Program.GHGRP else ghg_crosswalk.MRR
    if str(external_id) in table:
        key = table[str(external_id)]
        if key is None:
            return None, GHGReport.MatchMethod.CROSSWALK
        facility = facility_for_key(key)
        if facility is not None:
            return facility, GHGReport.MatchMethod.CROSSWALK
    candidates = candidates_near(point) if point is not None else candidates_in_zip(zipcode)
    facility = best_match(name, candidates)
    if facility is not None:
        return facility, GHGReport.MatchMethod.AUTO
    return None, GHGReport.MatchMethod.NONE
