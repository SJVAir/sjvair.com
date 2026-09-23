"""
Whether a facility's geocoded point can be believed.

CEIDARS addresses include portable equipment ("VARIOUS LOCATIONS, SJVAPCD")
and oil-field names ("LIGHT OIL WESTERN") rather than street addresses, and a
geocoder will place those anywhere -- Slovakia, Cape Cod, Barstow. So
"various locations" placeholders and blank streets aren't geocoded, and a point
is only kept when it lands in (or just outside) the facility's own county.
Street-only addresses ("EUCLID AVE, DINUBA") are kept: approximate, but the
county check catches the ones that land somewhere absurd.

choose_point decides between a Census street match, CARB's own coordinates
(pmt.py) and the point a facility already has; import_carb_locations applies it.
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


_HIGHWAY_RE = re.compile(r'\b(?:highway|hwy|state\s+route|route|sr)\b', re.IGNORECASE)


def is_highway_address(address):
    """A numbered address on a highway or route, which the Census geocoder places loosely."""
    return bool(_HIGHWAY_RE.search(address.get('street') or ''))


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


def choose_point(address, *, census, carb, current, area):
    """
    The point to keep for a facility, from the candidates it has:

    1. A Census street match -- the address's own place on its street -- unless
       the address is on a highway, where Census interpolates loosely.
    2. CARB's point (pmt.py) -- usually tens of meters from the street match,
       sometimes kilometers off, and the only point a facility with no street
       address can have.
    3. The point it already has (a highway Census match, or a MapTiler result,
       which can be a city or county centroid).

    Candidates outside the facility's county area are skipped. A facility with
    no geocodable address takes only CARB's point: anything geocoded from a
    non-address is a guess.
    """
    geocodable = is_geocodable(address)
    candidates = []
    if geocodable and not is_highway_address(address):
        candidates.append(census)
    candidates.append(carb)
    if geocodable:
        candidates.extend([census, current])
    for point in candidates:
        if plausible(point, area):
            return point
    return None
