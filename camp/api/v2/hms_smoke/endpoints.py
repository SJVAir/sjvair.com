from datetime import timedelta

from resticus import generics

from django.conf import settings
from django.utils import timezone

from camp.apps.integrate.hms_smoke.models import Smoke

from .filters import SmokeFilter
from .serializers import SmokeSerializer


class SmokeMixin:
    model = Smoke
    serializer_class = SmokeSerializer
    paginate = True  #defaults to page_size=100
    def get_queryset(self):
        return (
            super().get_queryset().order_by('-date')
        )


class SmokeList(SmokeMixin, generics.ListEndpoint):
    filter_class = SmokeFilter


class SmokeListOngoing(SmokeMixin, generics.ListEndpoint):
    filter_class = SmokeFilter

    def get_queryset(self):
        '''
        Return the current set of HMS smoke plumes for the "ongoing" endpoint.

        The default behavior is to return plumes from today's HMS shapefile
        (localized to DEFAULT_TIMEZONE). However, HMS typically does not publish
        the first plumes until mid-morning local time. To avoid returning an empty
        set during the overnight and early-morning hours, a fallback is applied:

            - If the current local time is before 12:00 (noon) AND there are no
              plumes yet for today, the query will instead return yesterday's
              plumes.
            - Once today's plumes are available, they will be used immediately,
              regardless of the time of day.

        This ensures that the endpoint always returns a meaningful plume set
        during the overnight/morning "gap" before NOAA's first daily updates.
        '''
        now = timezone.now().astimezone(settings.DEFAULT_TIMEZONE)

        queryset = super().get_queryset().filter(date=now.date())
        if now.hour < 12 and not queryset.exists():
            yesterday = now - timedelta(days=1)
            queryset = super().get_queryset().filter(date=yesterday.date())

        return queryset


class SmokeDetail(SmokeMixin, generics.DetailEndpoint):
    lookup_field = 'id'
    lookup_url_kwarg = 'smoke_id'
