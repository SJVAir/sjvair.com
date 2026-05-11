from datetime import timedelta

from resticus import generics

from django.conf import settings
from django.utils import timezone

from camp.apps.hms.models import Fire, Smoke

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


class SmokeMixin:
    model = Smoke
    serializer_class = SmokeSerializer
    paginate = True

    def get_queryset(self):
        return super().get_queryset().order_by('-date')


class SmokeList(SmokeMixin, generics.ListEndpoint):
    """List HMS smoke plumes. Defaults to today's data, falling back to yesterday before noon if today's data isn't yet available."""

    filter_class = SmokeFilter

    def get_queryset(self):
        if 'date' not in self.request.GET:
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
        return super().get_queryset().order_by('-date')


class FireList(FireMixin, generics.ListEndpoint):
    """List HMS active fire detections. Defaults to today's data, falling back to yesterday before noon."""

    filter_class = FireFilter

    def get_queryset(self):
        if 'date' not in self.request.GET:
            return get_default_date_queryset(super().get_queryset())
        return super().get_queryset()


class FireDetail(FireMixin, generics.DetailEndpoint):
    """Retrieve a single HMS fire detection record."""
    lookup_field = 'id'
    lookup_url_kwarg = 'fire_id'
