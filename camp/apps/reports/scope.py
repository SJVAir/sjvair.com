"""
Which monitors count toward coverage. Shared by the coverage reports and the
region admin panels, so a place's numbers agree wherever they are shown.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from camp.apps.monitors.models import Monitor


def enabled_only(queryset):
    """Restrict a base-Monitor queryset to enabled types, as get_public() does."""
    enabled = Monitor.get_enabled_subclasses()
    if len(enabled) >= len(Monitor.get_subclasses()):
        return queryset

    lookup = Q()
    for subclass in enabled:
        lookup |= Q(**subclass.type_queryset_filter())
    return queryset.filter(lookup) if enabled else queryset.none()


class MonitorScope:
    """
    Query-param toggles: `include_hidden=1`, `include_inactive=1`,
    `sjvair_only=1`. By default only outdoor monitors that reported within
    the last hour count toward coverage; a dead monitor does not cover anyone.
    """

    PARAMS = ('include_hidden', 'include_inactive', 'sjvair_only')

    def __init__(self, params):
        self.params = params

    @property
    def include_hidden(self):
        return self.params.get('include_hidden') == '1'

    @property
    def include_inactive(self):
        return self.params.get('include_inactive') == '1'

    @property
    def sjvair_only(self):
        return self.params.get('sjvair_only') == '1'

    def monitors(self):
        """
        Positioned outdoor monitors of enabled types that count under this
        scope. Indoor monitors never count toward coverage: the reports are
        about outdoor air quality.
        """
        queryset = enabled_only(Monitor.objects.filter(position__isnull=False).exclude(location=Monitor.LOCATION.inside))
        if not self.include_hidden:
            queryset = queryset.filter(is_hidden=False)
        if self.sjvair_only:
            queryset = queryset.filter(is_sjvair=True)
        if not self.include_inactive:
            cutoff = timezone.now() - timedelta(seconds=Monitor.LAST_ACTIVE_LIMIT)
            queryset = queryset.with_last_entry_timestamp().filter(last_entry_timestamp__gte=cutoff)
        return queryset

    def context(self):
        return {name: getattr(self, name) for name in self.PARAMS}

    def toggle_links(self, base=''):
        """
        (label, url, on) for each toggle, flipping just that one and keeping
        the rest. For pages that cannot host a form (the admin change page).
        """
        labels = {
            'sjvair_only': 'SJVAir monitors only',
            'include_hidden': 'Include hidden monitors',
            'include_inactive': 'Include inactive monitors',
        }
        links = []
        for name in self.PARAMS:
            on = getattr(self, name)
            query = self.params.copy()
            if on:
                query.pop(name, None)
            else:
                query[name] = '1'
            querystring = query.urlencode()
            links.append((labels[name], f'{base}?{querystring}' if querystring else base or '?', on))
        return links
