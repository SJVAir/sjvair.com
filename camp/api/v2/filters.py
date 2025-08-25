import datetime

from django.conf import settings
from django.utils import timezone

from django_filters import filters

from camp.utils.datetime import make_aware
from camp.apps.regions.models import Region

class TimezoneDateTimeFilter(filters.DateTimeFilter):
    def filter(self, qs, value):
        if value is None:
            return qs

        # If it's naive, assume PST
        if isinstance(value, datetime.datetime) and timezone.is_naive(value):
            value = make_aware(value, timezone=settings.DEFAULT_TIMEZONE)

        # Convert to UTC for database comparison
        value = value.astimezone(timezone.utc)

        return super().filter(qs, value)

class CountyFilter(filters.Filter):
    def filter(self, qs, value):
        if value is None:
            return qs
        try:
            county = Region.objects.get(type=Region.Type.COUNTY, name=value)
        except Region.DoesNotExist:
            return qs.none()
        value = county.boundary.geometry
        return super().filter(qs, value)        
