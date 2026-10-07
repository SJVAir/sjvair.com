from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models.functions import Coalesce
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import vanilla

from camp.apps.alerts.models import Alert, Notification, Subscription
from camp.utils.twilio_signature import is_valid_twilio_request


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


@method_decorator(csrf_exempt, name='dispatch')
class TwilioStatusCallback(View):
    STATUS_MAP = {
        'delivered': Notification.Status.DELIVERED,
        'undelivered': Notification.Status.UNDELIVERED,
        'failed': Notification.Status.FAILED,
    }

    def post(self, request, *args, **kwargs):
        if not is_valid_twilio_request(request):
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
