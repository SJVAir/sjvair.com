from django.contrib.gis.geos import Polygon
from django.db.models import Max
from django.http import HttpResponse

from resticus import generics
from resticus.http import Http400, Http404

from camp.apps.ceidars.models import EmissionsRecord, Facility
from camp.apps.regions.models import Region

from .serializers import FacilitySerializer


EMISSIONS_FIELDS = ['tog', 'rog', 'co', 'nox', 'sox', 'pm25', 'pm10',
                    'total_score', 'hra', 'chindex', 'ahindex']


class CeidarsEndpoint(generics.ListEndpoint):
    model = Facility
    serializer_class = FacilitySerializer
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

        bbox = self.request.GET.get('bbox')
        region_slug = self.request.GET.get('region')

        if bbox and region_slug:
            return Http400('Provide either bbox or region, not both.')

        qs = (
            Facility.objects
            .exclude(position=None)
            .filter(emissions__year=self.year)
            .prefetch_related('emissions')
        )

        if bbox:
            try:
                west, south, east, north = [float(x) for x in bbox.split(',')]
                qs = qs.filter(position__within=Polygon.from_bbox((west, south, east, north)))
            except (ValueError, TypeError):
                return Http400('Invalid bbox format. Expected: west,south,east,north')

        elif region_slug:
            region_type = self.request.GET.get('region_type')
            regions = Region.objects.filter(slug=region_slug)
            if region_type:
                regions = regions.filter(type=region_type)
            regions = list(regions.select_related('boundary'))

            if not regions:
                return Http404('Region not found.')
            if len(regions) > 1:
                return Http400('Multiple regions match this slug. Provide region_type to disambiguate.')

            region = regions[0]
            if not region.boundary:
                return Facility.objects.none()

            qs = qs.filter(position__within=region.boundary.geometry)

        return qs

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        if isinstance(queryset, HttpResponse):
            return queryset
        queryset = self.filter_queryset(queryset)
        queryset = self.paginate_queryset(queryset)
        return {'data': self.serialize(queryset)}

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
