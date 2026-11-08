from datetime import datetime

from resticus import generics, http

from camp.api.v1.endpoints import FormEndpoint
from camp.apps.alerts import current
from camp.apps.alerts.models import Subscription
from camp.apps.monitors.models import Monitor
from camp.utils.datetime import localtime

from .forms import SubscribeForm
from .serializers import SubscriptionSerializer


class SubscriptionList(generics.ListEndpoint):
    documented = False
    login_required = True
    model = Subscription
    serializer_class = SubscriptionSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(user_id=self.request.user.pk)
        return queryset


class Subscribe(generics.UpdateEndpoint):
    documented = False
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

    def form_valid(self, form):
        # Write only `level` on an existing subscription: a full save would
        # overwrite notification state a concurrent alert run just updated.
        subscription = form.save(commit=False)
        if subscription._state.adding:
            subscription.save()
        else:
            subscription.save(update_fields=['level', 'modified'])
        self.object = subscription
        return {'data': self.serialize(subscription)}

    def post(self, request, monitor_id):
        return self.put(request, monitor_id)


class Unsubscribe(FormEndpoint):
    documented = False
    login_required = True

    def form_valid(self, form):
        Subscription.objects.filter(
            user_id=self.request.user.pk,
            monitor_id=self.request.monitor.pk,
        ).delete()
        return {'success': True}


def _pacific(value):
    # The JSON encoder writes UTC datetimes as "Z"; clients want the Pacific offset.
    if isinstance(value, datetime):
        return localtime(value).isoformat()
    if isinstance(value, dict):
        return {key: _pacific(item) for key, item in value.items()}
    return value


class CurrentAlertValues(generics.Endpoint):
    """The SMS alert evaluator's latest result for a monitor, keyed by entry
    type: status, value and level over the trailing hour, the reading count,
    and the previous hour. Hidden monitors are served. Before the first run
    each entry type is `pending` (the monitor is reporting) or `no_data`."""

    def get(self, request, *args, **kwargs):
        monitor = request.monitor
        # The wrapped monitor can be a lazy proxy; _meta.model is the concrete class.
        model = monitor._meta.model
        entry_types = {entry_model.entry_type for entry_model in model.alertable_entry_types}

        stored = current.load(monitor.pk)
        if stored is not None:
            data = {key: _pacific(value) for key, value in stored.items() if key in entry_types}
        else:
            # Not monitor.is_active: it can be stale on the middleware's cached monitor.
            active = model.objects.filter(pk=monitor.pk).get_active().exists()
            status = 'pending' if active else 'no_data'
            fields = ('value', 'level', 'window', 'latest_timestamp', 'readings', 'required', 'previous', 'evaluated_at')
            data = {
                entry_type: {'status': status, **dict.fromkeys(fields)}
                for entry_type in sorted(entry_types)
            }

        response = http.Http200({'data': data})
        response['Cache-Control'] = 'public, max-age=60'
        return response
