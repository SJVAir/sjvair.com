from django.contrib.auth.mixins import LoginRequiredMixin

import vanilla

from camp.apps.alerts.models import Subscription
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


    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context['subscription_list'] = self.get_subscription_list()
        return context
