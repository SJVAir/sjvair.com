"""
A dairy's mailing city, resolved to the community region it names.

One resolver serves the CADD import (the display name kept in
Dairy.address['city']), the Dairies table's city links (dairies.city_url())
and region membership (areas.RegionArea.dairy_q(), dairies.dairy_areas()),
so the three can't disagree.

A name resolves against CITY regions first, then CDPs; within a type the
lowest pk wins, so the result never depends on database row order. Urban
areas are never matched by name (they count dairies by point alone).

CITY_ALIASES covers mailing names whose CDP is spelled differently: the post
office says "Hilmar", the Census says "Hilmar-Irwin". An alias only steers
the lookup (the link target and membership); the displayed city stays the
CADD name ("Hilmar"), since that is what the dairy's address reads. Aliases
apply to the stored name, i.e. after cadd.CITY_FIXES.
"""
from camp.apps.regions.models import Region

# {upper-cased mailing name: the region name it resolves to}.
CITY_ALIASES = {
    'HILMAR': 'Hilmar-Irwin',
}
# Name-matched types, in precedence order.
TYPES = (Region.Type.CITY, Region.Type.CDP)


def regions_by_name():
    """{lowercased region name: Region} over TYPES: CITY before CDP, lowest pk first. Built once per use."""
    index = {}
    for region_type in TYPES:
        for region in Region.objects.filter(type=region_type).order_by('pk').only('name', 'slug', 'sqid', 'type', 'boundary'):
            index.setdefault(region.name.lower(), region)
    return index


def lookup_key(name):
    """The index key a mailing city resolves under: its alias, if it has one, lowercased."""
    name = (name or '').strip()
    return CITY_ALIASES.get(name.upper(), name).lower()


def resolve(name, index):
    """The Region a mailing city names, or None."""
    return index.get(lookup_key(name)) if name else None


def mailing_names(region, index):
    """
    The lowercased mailing-city names that resolve() to `region`: its own name
    (unless a same-name region wins, or an alias takes the name elsewhere) and
    every alias pointing at it. Empty for a type that isn't name-matched.
    """
    names = {alias.lower() for alias in CITY_ALIASES if index.get(lookup_key(alias)) == region}
    own = region.name.lower()
    if index.get(own) == region and lookup_key(own) == own:
        names.add(own)
    return sorted(names)
