from django.db.models import Count, Q

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
