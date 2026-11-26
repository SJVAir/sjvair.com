from datetime import timedelta

from resticus import generics, http

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from camp.apps.hms.models import Fire, Smoke
from camp.apps.hms.place import is_day_settled, smoke_days
from camp.apps.hms.scales import get_fire_scale, get_smoke_scale
from camp.apps.regions.resolve import (
    CACHE_TIMEOUT, PlaceError, PlaceNotFound, _place_geometry, _place_key, place_json, resolve_place)

from .filters import FireFilter, SmokeFilter
from .forms import SmokePlaceForm
from .serializers import FireSerializer, SmokeSerializer


def get_default_date_queryset(queryset):
    '''
    Returns records for today's date, falling back to yesterday if it's
    before noon and no records exist yet for today. This handles the gap
    before NOAA publishes the first daily update.
    '''
    now = timezone.now().astimezone(settings.DEFAULT_TIMEZONE)
    qs = queryset.filter(date=now.date())
    if now.hour < 12 and not qs.exists():
        qs = queryset.filter(date=(now - timedelta(days=1)).date())
    return qs


DATE_FILTERS = ('date', 'date__gt', 'date__gte', 'date__lt', 'date__lte')


def has_date_filter(params):
    '''True when the request filters by date at all (an exact date or a range).'''
    return any(params.get(name) for name in DATE_FILTERS)


class SmokeMixin:
    model = Smoke
    serializer_class = SmokeSerializer
    paginate = True

    def get_queryset(self):
        # id breaks ties within a day, so pages never repeat or skip rows.
        return super().get_queryset().order_by('-date', 'id')


class SmokeList(SmokeMixin, generics.ListEndpoint):
    """List HMS smoke plumes. Without a date filter (date, or a date__gte/date__lte range), defaults to today's data, falling back to yesterday before noon if today's data isn't yet available."""

    filter_class = SmokeFilter

    def get_queryset(self):
        if not has_date_filter(self.request.GET):
            return get_default_date_queryset(super().get_queryset())
        return super().get_queryset()


class SmokeDetail(SmokeMixin, generics.DetailEndpoint):
    """Retrieve a single HMS smoke plume record."""
    lookup_field = 'id'
    lookup_url_kwarg = 'smoke_id'


SMOKE_PLACE_SETTLED_MAX_AGE = 86400
SMOKE_PLACE_MAX_AGE = 900


def _no_cache(response):
    response['Cache-Control'] = 'no-cache'
    return response


class SmokePlace(generics.Endpoint):
    """Per-day smoke over a place: the heaviest density that day and the share
    of the place under at least each level (?region_type= & ?region=, or
    ?monitor=; ?date__gte= and ?date__lte=, at most 366 days; defaults to the
    last 30 days through today). A day with no smoke has a null density."""

    def get(self, request, *args, **kwargs):
        try:
            place = resolve_place(request.GET)
        except PlaceNotFound as err:
            return _no_cache(http.Http404({'error': str(err)}))
        except PlaceError as err:
            return _no_cache(http.Http400({'error': str(err)}))

        form = SmokePlaceForm(request.GET)
        if not form.is_valid():
            return _no_cache(http.Http400({'errors': form.errors.get_json_data()}))
        start, end = form.cleaned_data['range']

        settled = is_day_settled(end)
        key = f"{_place_key('smoke_days', place)}:{start}:{end}"
        days = cache.get(key) if settled else None
        if days is None:
            days = smoke_days(_place_geometry(place), start, end)
            if settled:
                cache.set(key, days, CACHE_TIMEOUT)

        response = http.Http200({'data': {'place': place_json(place), 'days': days}})
        max_age = SMOKE_PLACE_SETTLED_MAX_AGE if settled else SMOKE_PLACE_MAX_AGE
        response['Cache-Control'] = f'public, max-age={max_age}'
        return response


class FireMixin:
    model = Fire
    serializer_class = FireSerializer
    paginate = True

    def get_queryset(self):
        # id breaks ties within a day, so pages never repeat or skip rows.
        return super().get_queryset().order_by('-date', 'id')


class FireList(FireMixin, generics.ListEndpoint):
    """List HMS active fire detections. Without a date filter (date, or a date__gte/date__lte range), defaults to today's data, falling back to yesterday before noon."""

    filter_class = FireFilter

    def get_queryset(self):
        if not has_date_filter(self.request.GET):
            return get_default_date_queryset(super().get_queryset())
        return super().get_queryset()


class FireDetail(FireMixin, generics.DetailEndpoint):
    """Retrieve a single HMS fire detection record."""
    lookup_field = 'id'
    lookup_url_kwarg = 'fire_id'


class HMSMeta(generics.Endpoint):
    """The smoke density and fire intensity scales."""

    def get(self, request, *args, **kwargs):
        scales = [get_smoke_scale(), get_fire_scale()]
        response = http.Http200({'data': {'scales': {s.id: s.to_json() for s in scales}}})
        response['Cache-Control'] = 'public, max-age=3600'
        return response
