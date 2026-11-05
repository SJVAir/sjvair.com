from resticus import generics, http

from camp.apps.monitors.models import Monitor
from camp.apps.regions.resolve import PlaceError, PlaceNotFound, place_json, resolve_place, weather_stations_for

from .serializers import MonitorSerializer


def _error(response):
    response['Cache-Control'] = 'no-cache'
    return response


class WeatherStationsPlace(generics.Endpoint):
    """Weather stations at or near a place: those inside it first, then the
    nearest outside it (?region_type= & ?region=, or ?monitor=). `distance`
    is in miles."""

    def get(self, request, *args, **kwargs):
        try:
            place = resolve_place(request.GET)
        except PlaceNotFound as err:
            return _error(http.Http404({'error': str(err)}))
        except PlaceError as err:
            return _error(http.Http400({'error': str(err)}))

        # The selection is cached; the rows are read fresh. A station hidden
        # since then is dropped.
        rows = weather_stations_for(place)
        monitors = {
            str(monitor.pk): monitor
            for monitor in (Monitor.objects
                .filter(pk__in=[pk for pk, _, _ in rows], is_hidden=False)
                .select_related('health')
                .prefetch_related('latest_entries')
                .with_last_entry_timestamp())
        }
        stations = []
        for pk, distance, inside in rows:
            monitor = monitors.get(pk)
            if monitor is None:
                continue
            station = MonitorSerializer(monitor).serialize()
            station['distance'] = distance
            station['inside'] = inside
            stations.append(station)

        response = http.Http200({'data': {'place': place_json(place), 'stations': stations}})
        response['Cache-Control'] = 'public, max-age=900'
        return response
