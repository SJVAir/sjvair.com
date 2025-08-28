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
        # Return smoke for today.
        today = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()
        return super().get_queryset().filter(date=today)


class SmokeDetail(SmokeMixin, generics.DetailEndpoint):
    lookup_field = 'id'
    lookup_url_kwarg = 'smoke_id'
