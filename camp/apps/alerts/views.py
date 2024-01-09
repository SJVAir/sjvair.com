from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.utils.decorators import method_decorator

import vanilla

from camp.apps.alerts.models import Alert, Subscription
from camp.apps.monitors.models import Monitor
from camp.utils.counties import County


class AlertList(LoginRequiredMixin, vanilla.ListView):
    model = Alert
    template_name = 'account/alerts.html'

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = (queryset
            .filter(
                monitor__subscriptions__user_id=self.request.user.pk,
                end_time__isnull=True
            )
            .select_related('monitor')
            .distinct()
        )
        return queryset


class SubscriptionList(LoginRequiredMixin, vanilla.ListView):
    model = Subscription
    template_name = 'account/subscriptions.html'

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = (queryset
            .filter(user_id=self.request.user.pk)
            .select_related('monitor')
            .distinct()
        )
        return queryset


@method_decorator(staff_member_required, name='dispatch')
class SubscriptionCountyStats(vanilla.TemplateView):
    model = Subscription
    template_name = 'admin/alerts/subscription/county_stats.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return {
            **super().get_context_data(**kwargs),
            **admin.site.each_context(self.request),
            'opts': self.model._meta,
            'title': 'Subscription Stats by County',
            'stats': self.get_county_stats(),
        }

    def get_county_stats(self):
        stats = []

        monitor_lookup = {}
        subscription_lookup = {}
        for key, county in County.keys.items():
            monitor_lookup[f'{key}_total_monitors'] = Count('pk', filter=Q(county=county))
            monitor_lookup[f'{key}_subscription_monitors'] = Count('pk',
                filter=Q(county=county, subscriptions__isnull=False), distinct=True)
            subscription_lookup[f'{key}_total_subscriptions'] = Count('pk', filter=Q(monitor__county=county))

        monitor_stats = Monitor.objects.aggregate(**monitor_lookup)
        subscription_stats = Subscription.objects.aggregate(**subscription_lookup)

        for key, county in County.keys.items():
            stats.append({
                'name': county,
                'total_monitors': monitor_stats[f'{key}_total_monitors'],
                'subscription_monitors': monitor_stats[f'{key}_subscription_monitors'],
                'total_subscriptions': subscription_stats[f'{key}_total_subscriptions'],
            })

        return stats
