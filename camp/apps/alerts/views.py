from django.contrib.auth.mixins import LoginRequiredMixin

import vanilla

from camp.apps.alerts.models import Alert, Subscription
from camp.apps.monitors.models import Monitor


class SubscriptionList(LoginRequiredMixin, vanilla.TemplateView):
    template_name = 'account/subscriptions.html'

    def get_queryset(self):
        return (Subscription.objects
            .filter(user=self.request.user)
        )

    def get_subscription_list(self):
        queryset = self.get_queryset()
        monitor_ids = queryset.values_list('monitor_id', flat=True)
        monitors = {m.pk: m for m in Monitor.objects.filter(pk__in=monitor_ids)}

        subscription_list = []
        for subscription in queryset:
            subscription.monitor = monitors[subscription.monitor_id]
            subscription_list.append(subscription)

        return subscription_list

    def get_current_alerts(self):
        alerts = Alert.objects.filter(
            monitor__subscriptions__user=self.request.user,
            end_time__isnull=True
        ).select_related('monitor').distinct()
        return alerts

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context['alert_list'] = self.get_current_alerts()
        context['subscription_list'] = self.get_subscription_list()
        return context
