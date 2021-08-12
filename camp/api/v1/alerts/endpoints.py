from resticus import generics

from camp.api.v1.endpoints import FormEndpoint
from camp.apps.alerts.models import Subscription
from camp.apps.monitors.models import Monitor

from .forms import SubscribeForm
from .serializers import SubscriptionSerializer


class SubscriptionList(generics.ListEndpoint):
    login_required = True
    model = Subscription
    serializer_class = SubscriptionSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(user_id=self.request.user.pk)
        return queryset


class Subscribe(generics.UpdateEndpoint):
    login_required = True
    form_class = SubscribeForm
    model = Subscription
    serializer_class = SubscriptionSerializer

    def get_object(self):
        try:
            return Subscription.objects.get(
                user_id=self.request.user.pk,
                monitor_id=self.request.monitor.pk,
            )
        except Subscription.DoesNotExist:
            return Subscription(
                user=self.request.user,
                monitor=self.request.monitor
            )

    def post(self, request, monitor_id):
        return self.put(request, monitor_id)


class Unsubscribe(FormEndpoint):
    login_required = True

    def form_valid(self, form):
        Subscription.objects.filter(
            user_id=self.request.user.pk,
            monitor_id=self.request.monitor.pk,
        ).delete()
        return {'success': True}
