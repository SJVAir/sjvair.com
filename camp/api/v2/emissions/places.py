from django.db.models import Case, Q, When
from resticus import generics

from camp.apps.emissions.areas import FILTER_REGION_TYPES
from camp.apps.regions.models import Region

MIN_LENGTH = 2
DEFAULT_LIMIT = 10
MAX_LIMIT = 25


class PlaceSearch(generics.Endpoint):
    """
    Autocomplete for the facility list's region filter: cities, places and ZIP
    codes whose name contains `q` (two characters or more), prefix matches
    first. `limit` defaults to 10, capped at 25. Each result is the region's
    `id` (sqid, the list's ?region=), `name`, and `detail` (City, Place or ZIP).
    Takes the entity picker's `type` and scope params and ignores them.
    """

    def get(self, request):
        query = (request.GET.get('q') or '').strip()
        if len(query) < MIN_LENGTH:
            return {'results': []}
        try:
            limit = max(1, min(int(request.GET.get('limit') or DEFAULT_LIMIT), MAX_LIMIT))
        except ValueError:
            limit = DEFAULT_LIMIT
        regions = (
            Region.objects.filter(type__in=FILTER_REGION_TYPES, boundary__isnull=False, name__icontains=query)
            # A place shares its name with the city it was built from; "Selma"
            # twice only confuses, so offer the city.
            .exclude(type=Region.Type.PLACE, name__in=Region.objects.filter(type=Region.Type.CITY).values('name'))
            .annotate(prefix=Case(When(Q(name__istartswith=query), then=0), default=1))
            .order_by('prefix', 'name', 'type')
            .values_list('sqid', 'name', 'type')[:limit]
        )
        return {'results': [
            {'id': sqid, 'name': name, 'detail': FILTER_REGION_TYPES[region_type]}
            for sqid, name, region_type in regions
        ]}
