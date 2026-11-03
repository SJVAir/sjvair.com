from django.conf import settings
from django.utils import timezone

from resticus import generics, http

from camp.apps.calheatscore.models import CalHeatScore
from camp.apps.calheatscore.scales import get_heat_scale
from camp.apps.regions.models import Region
from camp.apps.regions.resolve import PlaceError, PlaceNotFound, resolve_place, zips_for

from .filters import CalHeatScoreFilter
from .serializers import CalHeatScoreSerializer


class CalHeatScoreList(generics.ListEndpoint):
    """Today's CalHeatScore for every SJV ZIP code (filterable by ?date=,
    ?zipcode=, and ?zipcode__in=)."""

    model = CalHeatScore
    serializer_class = CalHeatScoreSerializer
    filter_class = CalHeatScoreFilter
    paginate = True

    def get_queryset(self):
        queryset = super().get_queryset().select_related('region')
        if 'date' not in self.request.GET:
            today = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()
            queryset = queryset.filter(date=today)
        return queryset


class CalHeatScoreByZip(generics.ListEndpoint):
    """All stored CalHeatScore dates (past actuals + forecast) for one ZIP
    code (filterable by ?date=, ?date__gte=, ?date__lte=)."""

    model = CalHeatScore
    serializer_class = CalHeatScoreSerializer
    filter_class = CalHeatScoreFilter
    paginate = True

    def get_queryset(self):
        return (
            super().get_queryset()
            .select_related('region')
            .filter(region__external_id=self.kwargs['zipcode'])
        )


class CalHeatScoreMeta(generics.Endpoint):
    """The CalHeatScore scale: levels, colors, descriptions, and guidance."""

    def get(self, request, *args, **kwargs):
        scale = get_heat_scale()
        response = http.Http200({'data': {'scales': {scale.id: scale.to_json()}}})
        response['Cache-Control'] = 'public, max-age=3600'
        return response


class CalHeatScorePlace(generics.Endpoint):
    """The highest CalHeatScore among the ZIPs a place covers, per date, and
    the ZIP that set it (?region_type= & ?region=, or ?monitor=; filterable by
    ?date=, ?date__gte=, ?date__lte=; defaults to today onward)."""

    def get(self, request, *args, **kwargs):
        try:
            place = resolve_place(request.GET)
        except PlaceNotFound as err:
            return http.Http404({'error': str(err)})
        except PlaceError as err:
            return http.Http400({'error': str(err)})

        zips = zips_for(place)
        queryset = CalHeatScore.objects.filter(region__in=[z.pk for z in zips])
        if not any(key in request.GET for key in ('date', 'date__gte', 'date__lte')):
            queryset = queryset.filter(date__gte=timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date())
        queryset = CalHeatScoreFilter(request.GET, queryset=queryset).qs

        # One row per date: the highest score, ties to the lowest ZIP code.
        rows = (queryset.order_by('date', '-score', 'region__external_id')
            .distinct('date').values_list('date', 'score', 'region__external_id'))
        days = [{
            'date': day.isoformat(),
            'score': score,
            'score_display': CalHeatScore.Score(score).label,
            'zipcode': zipcode,
        } for day, score, zipcode in rows]

        if isinstance(place, Region):
            place_json = {'region': {
                'type': place.type, 'external_id': place.external_id, 'name': place.name,
            }}
        else:
            place_json = {'monitor': str(place.pk)}

        response = http.Http200({'data': {'place': place_json, 'zip_count': len(zips), 'days': days}})
        response['Cache-Control'] = 'public, max-age=900'
        return response
