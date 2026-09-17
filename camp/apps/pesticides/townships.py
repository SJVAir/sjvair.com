"""
Township-level geometry for the explorer map.

A PLSS township is a 6x6 grid of one-square-mile MTRS sections, so the ~28k
section polygons in the valley collapse to a few hundred townships. Drawing
the township grid instead of the sections is what makes a zoomed-out map
affordable: one envelope per township rather than thousands of rings.

Township geometry is the *envelope* of its sections, not their union: the
grid is drawn as a reference overlay, so a rectangle is both what a township
is on the ground and far cheaper to build and serialize. Both lookups here
are whole-table and change only when the MTRS regions are reimported, so
they're cached for a day.
"""
import json

from django.contrib.gis.db.models import Collect
from django.contrib.gis.db.models.functions import Envelope
from django.core.cache import cache
from django.db.models import Count
from django.db.models.functions import Length, Substr

from camp.apps.regions.models import Region

TOWNSHIP_GEOMETRIES_KEY = 'pesticides:township-geometries'
TOWNSHIP_SECTIONS_KEY = 'pesticides:township-sections'
TOWNSHIP_TTL = 60 * 60 * 24
# Five decimals is a bit over a meter -- far finer than a square-mile grid
# needs, and roughly half the bytes of the raw geometry.
COORD_PRECISION = 5
# 'MDM-T14S-R20E-01' -> 'MDM-T14S-R20E': the trailing '-NN' section number.
SECTION_SUFFIX_LENGTH = 3


def _round(value, precision):
    if isinstance(value, (int, float)):
        return round(value, precision)
    return [_round(item, precision) for item in value]


def round_coords(geometry, precision=COORD_PRECISION):
    """
    Round a GeoJSON geometry dict's coordinates in place (and return it).
    Lives here rather than in the API module because both the section and
    township payloads use it and this module has no API-layer imports.
    """
    if geometry and geometry.get('coordinates') is not None:
        geometry['coordinates'] = _round(geometry['coordinates'], precision)
    return geometry


def township_of(mtrs_name):
    """'MDM-T14S-R20E-01' -> 'MDM-T14S-R20E'. Names with no section suffix pass through."""
    head, sep, section = mtrs_name.rpartition('-')
    if sep and section.isdigit():
        return head
    return mtrs_name


def _build_township_index():
    return {
        pk: township_of(name)
        for pk, name in Region.objects.filter(type=Region.Type.MTRS).values_list('pk', 'name')
    }


def township_index():
    """{mtrs_pk: township}, so section-level totals can be summed by township in Python."""
    data = cache.get(TOWNSHIP_SECTIONS_KEY)
    if data is None:
        data = _build_township_index()
        cache.set(TOWNSHIP_SECTIONS_KEY, data, TOWNSHIP_TTL)
    return data


def _build_township_geometries():
    # One GROUP BY: PostGIS builds each township's envelope, so no section
    # geometry is ever fetched into Python. Grouping on the name minus its
    # last three characters is township_of() expressed in SQL; every imported
    # MTRS region is named '<meridian>-T##S-R##E-##'.
    rows = (
        Region.objects
        .filter(type=Region.Type.MTRS, boundary__isnull=False)
        .annotate(township=Substr('name', 1, Length('name') - SECTION_SUFFIX_LENGTH))
        .values('township')
        .annotate(envelope=Envelope(Collect('boundary__geometry')), sections=Count('pk'))
        .order_by('township')
    )
    data = {}
    for row in rows:
        envelope = row['envelope']
        data[row['township']] = {
            'geometry': round_coords(json.loads(envelope.geojson)),
            'sections': row['sections'],
            'bbox': tuple(round(value, COORD_PRECISION) for value in envelope.extent),
        }
    return data


def township_geometries():
    """{township: {'geometry': <GeoJSON dict>, 'sections': <count>, 'bbox': (w, s, e, n)}}."""
    data = cache.get(TOWNSHIP_GEOMETRIES_KEY)
    if data is None:
        data = _build_township_geometries()
        cache.set(TOWNSHIP_GEOMETRIES_KEY, data, TOWNSHIP_TTL)
    return data
