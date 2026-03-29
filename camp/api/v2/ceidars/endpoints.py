from django.db.models import Prefetch
from resticus import generics
from resticus.views import Endpoint

from camp.apps.ceidars.models import EmissionsRecord, Facility

from .filters import FacilityFilter
from .serializers import EmissionsSerializer, FacilitySerializer


class YearList(Endpoint):
    """List all years for which CEIDARS emissions data is available."""

    def get(self, request):
        years = (
            EmissionsRecord.objects
            .values_list('year', flat=True)
            .distinct()
            .order_by('-year')
        )
        return {'data': list(years)}


class FacilityList(generics.ListEndpoint):
    """List CEIDARS permitted facilities with their most recent annual emissions data."""

    model = Facility
    serializer_class = FacilitySerializer
    filter_class = FacilityFilter
    paginate = False

    def get_queryset(self):
        return Facility.objects.filter(point__isnull=False)

    def serialize(self, queryset, **kwargs):
        results = []
        for facility in queryset:
            data = self.serializer_class(facility).serialize()
            data['emissions'] = EmissionsSerializer(facility.emissions.all()[0]).serialize()
            results.append(data)
        return results


class FacilityDetail(generics.DetailEndpoint):
    """Retrieve a single CEIDARS facility with its full emissions history."""

    model = Facility
    serializer_class = FacilitySerializer
    lookup_field = 'sqid'

    def get_queryset(self):
        return Facility.objects.prefetch_related(
            Prefetch('emissions', queryset=EmissionsRecord.objects.order_by('-year'))
        )

    def serialize(self, instance, **kwargs):
        data = self.serializer_class(instance).serialize()
        data['emissions'] = EmissionsSerializer(instance.emissions.all()).serialize()
        return data
