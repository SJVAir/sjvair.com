from django.conf import settings
from django.utils import timezone

from resticus import generics

from camp.apps.calheatscore.models import CalHeatScore

from .filters import CalHeatScoreFilter
from .serializers import CalHeatScoreSerializer


class CalHeatScoreList(generics.ListEndpoint):
    """Today's CalHeatScore for every SJV ZIP code (filterable by ?date=)."""

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
    """All stored CalHeatScore dates (past actuals + forecast) for one ZIP code."""

    model = CalHeatScore
    serializer_class = CalHeatScoreSerializer
    paginate = True

    def get_queryset(self):
        return (
            super().get_queryset()
            .select_related('region')
            .filter(region__external_id=self.kwargs['zipcode'])
        )
