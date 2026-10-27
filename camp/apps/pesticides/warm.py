"""
Keeps the pesticides explorer's busiest pages cached, so a visitor never
waits on the rollup for them. The pages are rendered once per data version
(stats.data_version, bumped by every rollup rebuild); see camp.utils.warm.
"""
from django.db.models import Sum
from django.urls import reverse

from camp.apps.pesticides import stats
from camp.apps.pesticides.models import Chemical, Commodity, PesticideUseTotal, Product
from camp.apps.regions.models import Region
from camp.utils import warm as utils_warm

# How many of each kind of entity page to keep warm: the heaviest in the
# latest year, which are both the most visited and the slowest to build.
WARM_ENTITY_LIMIT = 20
WARMED_KEY = 'pesticides:warmed'


def top_entities(model, field, lbs_field, year):
    """The `WARM_ENTITY_LIMIT` heaviest `model`s in `year`, by `lbs_field`."""
    pks = list(PesticideUseTotal.objects
        .filter(year=year, **{f'{field}__isnull': False})
        .values(field)
        .annotate(lbs=Sum(lbs_field))
        .order_by('-lbs')
        .values_list(field, flat=True)[:WARM_ENTITY_LIMIT]
    )
    return model.objects.filter(pk__in=pks)


def warm_paths():
    """Every page the warmer keeps cached, latest year and all years each."""
    year = stats.latest_year()
    if year is None:
        return []
    pages = [
        reverse('pesticides:home'),
        reverse('pesticides:map'),
        reverse('pesticides:chemical-list'),
        reverse('pesticides:product-list'),
        reverse('pesticides:commodity-list'),
    ]
    counties = Region.objects.filter(
        type=Region.Type.COUNTY, pk__in=PesticideUseTotal.objects.values('county'))
    cities = Region.objects.filter(type=Region.Type.CITY, boundary__isnull=False)
    pages += [
        reverse('pesticides:region', kwargs={'sqid': region.sqid, 'slug': region.slug})
        for region in [*counties.order_by('name'), *cities.order_by('name')]
    ]
    pages += [entity.get_absolute_url() for entity in [
        *top_entities(Chemical, 'chemical', 'lbs_chemical', year),
        *top_entities(Product, 'product', 'lbs_product_once', year),
        *top_entities(Commodity, 'commodity', 'lbs_chemical', year),
    ]]
    paths = [path for page in pages for path in (page, f'{page}?year={stats.ALL_YEARS}')]
    # Years aren't a parameter of the township outlines.
    return [*paths, reverse('api:v2:pesticides:township-list')]


def warm():
    """Render every warm path not yet rendered under the current data version (see camp.utils.warm)."""
    return utils_warm.warm(warm_paths(), stats.data_version(), WARMED_KEY)
