from django.conf import settings
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import vanilla

from twilio.request_validator import RequestValidator

from camp.apps.alerts.models import Alert, Notification, Subscription
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


@method_decorator(csrf_exempt, name='dispatch')
class TwilioStatusCallback(View):
    STATUS_MAP = {
        'delivered': Notification.Status.DELIVERED,
        'undelivered': Notification.Status.UNDELIVERED,
        'failed': Notification.Status.FAILED,
    }

    def post(self, request, *args, **kwargs):
        validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
        signature = request.META.get('HTTP_X_TWILIO_SIGNATURE', '')
        url = request.build_absolute_uri()

        if not validator.validate(url, request.POST, signature):
            return HttpResponseForbidden()

        status = self.STATUS_MAP.get(request.POST.get('MessageStatus'))
        if status is None:
            return HttpResponse(status=200)

        message_sid = request.POST.get('MessageSid')
        if not message_sid:
            return HttpResponse(status=200)

        # Exclude notifications already in a terminal state: Twilio status
        # callbacks can arrive out of order or be retried, and a stale
        # callback shouldn't revert an already-delivered notification.
        # Backfill sent_at too, in case this callback beat our own SENT
        # write (e.g. a delayed/queued send task).
        Notification.objects.filter(
            provider_id=message_sid
        ).exclude(
            status__in=[
                Notification.Status.DELIVERED,
                Notification.Status.UNDELIVERED,
                Notification.Status.FAILED,
            ]
        ).update(
            status=status,
            sent_at=Coalesce('sent_at', timezone.now()),
        )

        return HttpResponse(status=200)
