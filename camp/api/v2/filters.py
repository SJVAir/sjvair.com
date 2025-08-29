import datetime

from django.conf import settings
from django.utils import timezone

from django_filters import filters

from camp.utils.datetime import make_aware
from camp.apps.regions.models import Region
from camp.utils.geodata import query_by_overlap
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
    def __init__(self, *args, threshold=0.5, **kwargs):
        self.threshold = threshold
        super().__init__(*args, **kwargs)
    
    def filter(self, qs, value):
        if value is None:
            return qs
        try:
            county = Region.objects.get(type=Region.Type.COUNTY, name=value)
        except Region.DoesNotExist:
            return qs.none()
        value = county.boundary.geometry
        return query_by_overlap(qs, self.field_name, value, self.threshold)
