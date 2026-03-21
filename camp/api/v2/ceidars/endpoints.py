from django.db.models import Max

from resticus import generics

from camp.apps.ceidars.models import EmissionsRecord, Facility

from .filters import FacilityFilter
from .serializers import FacilitySerializer


EMISSIONS_FIELDS = [
    'tog', 'rog', 'co', 'nox', 'sox', 'pm25', 'pm10',
    'total_score', 'hra', 'chindex', 'ahindex',
    'acetaldehyde', 'benzene', 'butadiene', 'carbon_tetrachloride',
    'chromium_hexavalent', 'dichlorobenzene', 'formaldehyde',
    'methylene_chloride', 'naphthalene', 'perchloroethylene',
]


class CeidarsEndpoint(generics.ListEndpoint):
    model = Facility
    serializer_class = FacilitySerializer
    filter_class = FacilityFilter
    paginate = False

    @property
    def year(self):
        if not hasattr(self, '_year'):
            year = self.kwargs.get('year')
            if year:
                self._year = int(year)
            else:
                self._year = EmissionsRecord.objects.aggregate(Max('year'))['year__max']
        return self._year

    def get_queryset(self):
        if self.year is None:
            return Facility.objects.none()

        return (
            Facility.objects
            .filter(point__isnull=False)
            .filter(emissions__year=self.year)
            .prefetch_related('emissions')
        )

    def serialize(self, queryset, **kwargs):
        results = []
        for facility in queryset:
            data = self.serializer_class(facility).serialize()
            record = next((e for e in facility.emissions.all() if e.year == self.year), None)
            if record is None:
                continue
            data['year'] = self.year
            for field in EMISSIONS_FIELDS:
                data[field] = getattr(record, field)
            results.append(data)
        return results
