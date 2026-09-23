"""
Whether a facility's geocoded point can be believed.

CEIDARS addresses include portable equipment ("VARIOUS LOCATIONS, SJVAPCD")
and oil-field names ("LIGHT OIL WESTERN") rather than street addresses, and a
geocoder will place those anywhere -- Slovakia, Cape Cod, Barstow. So
"various locations" placeholders and blank streets aren't geocoded, and a point
is only kept when it lands in (or just outside) the facility's own county.
Street-only addresses ("EUCLID AVE, DINUBA") are kept: approximate, but the
county check catches the ones that land somewhere absurd.
"""

import re

# Addresses on a county line can geocode just across it (~2 km).
COUNTY_BUFFER_DEGREES = 0.02

_NOT_A_SITE_RE = re.compile(r'various\s+locations?', re.IGNORECASE)


def is_geocodable(address):
    """A street that isn't blank or a "various locations" placeholder."""
    street = (address.get('street') or '').strip()
    city = (address.get('city') or '').strip()
    if _NOT_A_SITE_RE.search(street) or _NOT_A_SITE_RE.search(city):
        return False
    return bool(street)


def county_area(county):
    """The county's boundary, buffered for border addresses; None when it has no boundary."""
    if county is None or county.boundary is None:
        return None
    return county.boundary.geometry.buffer(COUNTY_BUFFER_DEGREES)


def plausible(point, area):
    """Is `point` inside `area`? With no area to check against, trust the point."""
    if point is None:
        return False
    return area is None or area.contains(point)
