from datetime import timedelta

from resticus import generics, http

from django.conf import settings
from django.utils import timezone

from camp.apps.hms.models import Fire, Smoke
from camp.apps.hms.scales import get_fire_scale, get_smoke_scale

from .filters import FireFilter, SmokeFilter
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
