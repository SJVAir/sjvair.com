import datetime

from django.conf import settings
from django.utils import timezone

from django_filters import filters

from camp.utils.datetime import make_aware

from .forms import PacificDateTimeField


class TimezoneDateTimeFilter(filters.DateTimeFilter):
    field_class = PacificDateTimeField

    def filter(self, qs, value):
        if value is None:
            return qs

        # If it's naive, assume PST
        if isinstance(value, datetime.datetime) and timezone.is_naive(value):
            value = make_aware(value, tz=settings.DEFAULT_TIMEZONE)

        # Convert to UTC for database comparison
        value = value.astimezone(datetime.timezone.utc)

        return super().filter(qs, value)
