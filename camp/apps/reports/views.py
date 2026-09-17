from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncQuarter
from django.urls import reverse
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


@register
class FleetHealth(BaseReport):
    slug = 'fleet-health'
    title = 'Fleet Health'
    description = 'How recently each monitor type reported, and the current health grade distribution for dual-channel monitors.'
    template_name = 'admin/reports/fleet_health.html'

    @property
    def county(self):
        county = self.request.GET.get('county', '')
        return county if county in County.names else ''

    def scoped(self, queryset):
        if self.county:
            queryset = queryset.filter(county=self.county)
        return queryset

    def get_rows(self):
        now = timezone.now()
        hour = now - timedelta(hours=1)
        day = now - timedelta(days=1)
        week = now - timedelta(days=7)
        visible = Q(is_hidden=False)

        rows = []
        for cls in monitor_types():
            stats = self.scoped(cls.objects.get_queryset().with_last_entry_timestamp()).aggregate(
                active=Count('pk', filter=visible & Q(last_entry_timestamp__gte=hour)),
                silent_1d=Count('pk', filter=visible & Q(last_entry_timestamp__lt=hour, last_entry_timestamp__gte=day)),
                silent_7d=Count('pk', filter=visible & Q(last_entry_timestamp__lt=day, last_entry_timestamp__gte=week)),
                silent_long=Count('pk', filter=visible & Q(last_entry_timestamp__lt=week)),
                never=Count('pk', filter=visible & Q(last_entry_timestamp__isnull=True)),
                hidden=Count('pk', filter=Q(is_hidden=True)),
                total=Count('pk'),
            )
            rows.append({'type': type_label(cls), **stats})
        return rows

    def get_grades(self):
        eligible = Monitor.objects.get_for_health_checks()
        rows = []
        for cls in monitor_types():
            queryset = self.scoped(eligible.filter(**cls.health_check_queryset_filter()))
            if not queryset.exists():
                continue
            stats = queryset.aggregate(
                A=Count('pk', filter=Q(health__score=3)),
                B=Count('pk', filter=Q(health__score=2)),
                C=Count('pk', filter=Q(health__score=1)),
                F=Count('pk', filter=Q(health__score=0)),
                none=Count('pk', filter=Q(health__isnull=True)),
            )
            rows.append({'type': type_label(cls), **stats})
        return rows

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            'counties': County.names,
            'county': self.county,
            'grades': self.get_grades(),
        }


@register
class DegradedMonitors(BaseReport):
    slug = 'degraded-monitors'
    title = 'Degraded Monitors'
    description = 'Monitors graded C or F, flatlined on a channel, or silent for more than 24 hours. Worst first.'
    template_name = 'admin/reports/degraded_monitors.html'
    csv_columns = ['name', 'type', 'county', 'host', 'grade', 'last_seen', 'condition']

    @property
    def include_hidden(self):
        return self.request.GET.get('include_hidden') == '1'

    @property
    def county(self):
        county = self.request.GET.get('county', '')
        return county if county in County.names else ''

    @property
    def monitor_type(self):
        wanted = self.request.GET.get('type', '')
        return wanted if wanted in {cls.monitor_type for cls in monitor_types()} else ''

    def get_csv_columns(self, rows):
        return self.csv_columns

    def get_rows(self):
        now = timezone.now()
        day = now - timedelta(days=1)
        degraded = (
            Q(health__score__lte=1)
            | Q(health__sanity_flatline_a=False)
            | Q(health__sanity_flatline_b=False)
            | Q(last_entry_timestamp__lt=day)
            | Q(last_entry_timestamp__isnull=True)
        )

        rows = []
        for cls in monitor_types():
            if self.monitor_type and cls.monitor_type != self.monitor_type:
                continue
            queryset = (cls.objects
                .get_queryset()
                .with_last_entry_timestamp()
                .select_related('health', 'host')
                .filter(degraded)
            )
            if not self.include_hidden:
                queryset = queryset.filter(is_hidden=False)
            if self.county:
                queryset = queryset.filter(county=self.county)

            for monitor in queryset:
                rows.append(self.build_row(cls, monitor, now))

        rows.sort(key=lambda row: row['sort_key'])
        return rows

    def build_row(self, cls, monitor, now):
        health = monitor.health
        last_seen = monitor.last_entry_timestamp
        conditions = []
        # sort_key: lower sorts first. (0, -silence) silent, (1,) grade F, (2,) grade C, (3,) flatline only
        sort_key = (4, 0)

        if last_seen is None:
            conditions.append('Never reported')
            sort_key = (0, -float('inf'))
        elif last_seen < now - timedelta(days=1):
            silence = now - last_seen
            conditions.append(f'Silent {silence.days}d')
            sort_key = (0, -silence.total_seconds())

        if health is not None:
            if health.score == 0:
                conditions.append('Grade F')
                sort_key = min(sort_key, (1, 0))
            elif health.score == 1:
                conditions.append('Grade C')
                sort_key = min(sort_key, (2, 0))
            if health.sanity_flatline_a is False:
                conditions.append('Flatline A')
                sort_key = min(sort_key, (3, 0))
            if health.sanity_flatline_b is False:
                conditions.append('Flatline B')
                sort_key = min(sort_key, (3, 0))

        return {
            'name': monitor.name,
            'type': type_label(cls),
            'county': monitor.county,
            'host': monitor.host.name if monitor.host_id else '',
            'grade': health.grade if health is not None else '',
            'last_seen': last_seen,
            'condition': ', '.join(conditions),
            'admin_url': reverse(f'admin:{cls._meta.app_label}_{cls._meta.model_name}_change', args=[monitor.pk]),
            'sort_key': sort_key,
        }

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            'counties': County.names,
            'county': self.county,
            'monitor_type': self.monitor_type,
            'types': [(cls.monitor_type, type_label(cls)) for cls in monitor_types()],
            'include_hidden': self.include_hidden,
        }
