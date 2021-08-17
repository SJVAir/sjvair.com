from django.contrib.auth.mixins import LoginRequiredMixin

import vanilla

from camp.apps.alerts.models import Alert, Subscription
from camp.apps.monitors.models import Monitor


class AlertList(LoginRequiredMixin, vanilla.ListView):
    model = Alert
    template_name = 'account/alerts.html'

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = (queryset
            .filter(
                monitor__subscriptions__user=self.request.user,
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
            .filter(user=self.request.user)
            .select_related('monitor')
            .distinct()
        )
        return queryset
