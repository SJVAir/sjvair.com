from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from camp.utils.datetime import make_aware


class ScopeMixin:
    """Shared date and monitor/region scope parsing for the summaries commands."""

    def _monitor_ids(self, pks, types):
        from camp.apps.monitors.models import Monitor

        ids = []
        for pk in pks:
            try:
                found = Monitor.objects.filter(pk=pk).values_list('pk', flat=True).first()
            except (ValueError, TypeError, ValidationError):
                found = None
            if found is None:
                raise CommandError(f'Monitor not found: {pk}')
            ids.append(found)

        valid = sorted({sub.monitor_type for sub in Monitor.get_subclasses()})
        for monitor_type in types:
            if monitor_type not in valid:
                raise CommandError(f'Unknown monitor type: {monitor_type} (valid: {", ".join(valid)})')
            ids.extend(
                Monitor.objects
                .filter(**{f'{monitor_type}__isnull': False})
                .values_list('pk', flat=True)
            )
        return list(dict.fromkeys(ids))

    def _region_ids(self, pks, types):
        from camp.apps.regions.models import Region

        ids = []
        for pk in pks:
            try:
                found = Region.all_objects.filter(pk=pk).values_list('pk', flat=True).first()
            except (ValueError, TypeError, ValidationError):
                found = None
            if found is None:
                raise CommandError(f'Region not found: {pk}')
            ids.append(found)

        valid = list(Region.Type.values)
        for region_type in types:
            if region_type not in valid:
                raise CommandError(f'Unknown region type: {region_type} (valid: {", ".join(valid)})')
            ids.extend(
                Region.objects
                .filter(type=region_type, boundary__isnull=False)
                .values_list('pk', flat=True)
            )
        return list(dict.fromkeys(ids))

    def _parse_date(self, value):
        d = parse_date(value)
        if d is None:
            raise CommandError(f'Invalid date: {value!r}. Use YYYY-MM-DD.')
        return make_aware(datetime(d.year, d.month, d.day), settings.DEFAULT_TIMEZONE)

    def _fmt(self, ts):
        return timezone.localtime(ts, settings.DEFAULT_TIMEZONE).isoformat()
