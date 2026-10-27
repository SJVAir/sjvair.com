"""
Keeps the emissions explorer's busiest pages cached, so a visitor never waits
on the valley-wide aggregates behind them. The pages are rendered once per
cache version -- every module's generation together, since any import bumps
one -- and see camp.utils.warm for the rest.
"""
from django.urls import reverse

from camp.apps.emissions import compliance, dairies, methane, stats, wells
from camp.apps.emissions.models import Facility
from camp.apps.regions.models import Region
from camp.utils import warm as utils_warm

WARMED_KEY = 'emissions:warmed'
# A county's page and every tab of it.
COUNTY_TABS = ('region', 'region-dairies', 'region-facilities', 'region-oil-gas', 'region-methane', 'region-schools')


def version():
    return ':'.join(str(part) for part in (
        stats.CACHE_VERSION, stats.generation(), dairies.generation(),
        wells.generation(), methane.generation(), compliance.generation(),
    ))


def warm_paths():
    """Every page the warmer keeps cached."""
    paths = [reverse(f'emissions:{name}') for name in (
        'home', 'map', 'oil-gas', 'methane', 'facility-list', 'sector-list', 'dairy-list',
    )]
    counties = Region.objects.filter(
        type=Region.Type.COUNTY, pk__in=Facility.objects.values('county')).order_by('name')
    paths += [
        reverse(f'emissions:{name}', kwargs={'sqid': county.sqid, 'slug': county.slug})
        for county in counties for name in COUNTY_TABS
    ]
    cities = Region.objects.filter(type=Region.Type.CITY, boundary__isnull=False).order_by('name')
    paths += [reverse('emissions:region', kwargs={'sqid': city.sqid, 'slug': city.slug}) for city in cities]
    # Every facility page reads the same valley-wide ZIP and tract lookups
    # (areas.region_index) -- seconds to build -- so one page warms them all.
    facility = Facility.objects.filter(point__isnull=False).order_by('pk').first()
    if facility is not None:
        paths.append(facility.get_absolute_url())
    return paths


def warm():
    """Render every warm path not yet rendered under the current cache version."""
    return utils_warm.warm(warm_paths(), version(), WARMED_KEY)
