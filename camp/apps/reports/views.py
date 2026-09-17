from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncQuarter
from django.utils import timezone

from camp.apps.alerts.models import Subscription
from camp.apps.monitors.models import Monitor
from camp.apps.reports.base import BaseReport, register
from camp.utils.counties import County


@register
class SubscriptionCountyStats(BaseReport):
    slug = 'subscription-county-stats'
    title = 'Subscription Stats by County'
    description = 'Monitors, monitors with at least one subscriber, and total subscriptions, per county.'
    template_name = 'admin/reports/subscription_county_stats.html'

    def get_rows(self):
        monitor_lookup = {}
        subscription_lookup = {}
        for key, county in County.keys.items():
            monitor_lookup[f'{key}_total_monitors'] = Count('pk', filter=Q(county=county))
            monitor_lookup[f'{key}_subscription_monitors'] = Count('pk',
                filter=Q(county=county, subscriptions__isnull=False), distinct=True)
            subscription_lookup[f'{key}_total_subscriptions'] = Count('pk', filter=Q(monitor__county=county))

        monitor_stats = Monitor.objects.aggregate(**monitor_lookup)
        subscription_stats = Subscription.objects.aggregate(**subscription_lookup)

        return [{
            'county': county,
            'total_monitors': monitor_stats[f'{key}_total_monitors'],
            'subscription_monitors': monitor_stats[f'{key}_subscription_monitors'],
            'total_subscriptions': subscription_stats[f'{key}_total_subscriptions'],
        } for key, county in County.keys.items()]


def monitor_types():
    """Concrete Monitor subclasses, sorted by class name."""
    return Monitor.get_subclasses()


def type_label(cls):
    return cls.__name__


def quarter_label(dt):
    return f'{dt.year} Q{(dt.month - 1) // 3 + 1}'


def next_quarter(dt):
    month = dt.month + 3
    year = dt.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return dt.replace(year=year, month=month, day=1)


@register
class NetworkOverview(BaseReport):
    slug = 'network-overview'
    title = 'Network Overview'
    description = 'Monitor counts by type and county, and deployments per quarter. Hidden monitors are excluded unless requested.'
    template_name = 'admin/reports/network_overview.html'

    @property
    def include_hidden(self):
        return self.request.GET.get('include_hidden') == '1'

    def base_queryset(self):
        queryset = Monitor.objects.all()
        if not self.include_hidden:
            queryset = queryset.filter(is_hidden=False)
        return queryset

    def get_rows(self):
        counts = {}
        for cls in monitor_types():
            queryset = cls.objects.all()
            if not self.include_hidden:
                queryset = queryset.filter(is_hidden=False)
            for item in queryset.values('county').annotate(n=Count('pk')):
                counts[(type_label(cls), item['county'])] = item['n']

        rows = []
        totals = {county: 0 for county in County.names}
        for cls in monitor_types():
            label = type_label(cls)
            row = {'type': label}
            for county in County.names:
                row[county] = counts.get((label, county), 0)
                totals[county] += row[county]
            row['total'] = sum(row[county] for county in County.names)
            rows.append(row)

        rows.append({'type': 'All types', **totals, 'total': sum(totals.values())})
        return rows

    def get_tiles(self):
        cutoff = timezone.now() - timedelta(seconds=Monitor.LAST_ACTIVE_LIMIT)
        queryset = self.base_queryset()
        total = queryset.count()
        sjvair = queryset.filter(is_sjvair=True).count()
        active = queryset.with_last_entry_timestamp().filter(last_entry_timestamp__gte=cutoff).count()
        return {'total': total, 'active': active, 'sjvair': sjvair, 'partner': total - sjvair}

    def get_deployments(self):
        per_quarter = {
            item['quarter']: item['n']
            for item in (self.base_queryset()
                .annotate(quarter=TruncQuarter('created'))
                .values('quarter')
                .annotate(n=Count('pk'))
                .order_by('quarter'))
        }
        if not per_quarter:
            return []

        rows = []
        cumulative = 0
        quarter = min(per_quarter)
        last = max(max(per_quarter), timezone.now())
        while quarter <= last:
            new = per_quarter.get(quarter, 0)
            cumulative += new
            rows.append({'quarter': quarter_label(quarter), 'new': new, 'cumulative': cumulative})
            quarter = next_quarter(quarter)
        return rows

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            'counties': County.names,
            'include_hidden': self.include_hidden,
            'tiles': self.get_tiles(),
            'deployments': self.get_deployments(),
        }
