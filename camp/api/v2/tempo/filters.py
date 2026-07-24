from datetime import timedelta

import django_filters
from django.conf import settings
from django.db.models.functions import TruncDate
from resticus.filters import FilterSet

from camp.apps.tempo.models import Granule
from camp.utils.datetime import localtime


def filter_local_date(queryset, date):
    """Filters to Granules whose timestamp falls on `date` in America/Los_Angeles -- not the
    connection's default timezone, which `timestamp__date` would otherwise use."""
    return queryset.annotate(
        local_date=TruncDate('timestamp', tzinfo=settings.DEFAULT_TIMEZONE)
    ).filter(local_date=date)


def default_to_today(queryset):
    """
    Returns granules for today's LA-calendar date, falling back to
    yesterday if it's before noon and none exist yet for today --
    mirrors camp/api/v2/hms/endpoints.py's get_default_date_queryset,
    adapted for Granule's timestamp-only schema (no separate `date` field
    to filter on, unlike Fire/Smoke).
    """
    now = localtime()
    qs = filter_local_date(queryset, now.date())
    if now.hour < 12 and not qs.exists():
        qs = filter_local_date(queryset, (now - timedelta(days=1)).date())
    return qs


class GranuleFilter(FilterSet):
    date = django_filters.DateFilter(method='filter_date')

    def filter_date(self, queryset, name, value):
        return filter_local_date(queryset, value)

    class Meta:
        model = Granule
        fields = {
            'timestamp': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'is_final': ['exact'],
            'version': ['exact', 'iexact'],
        }
