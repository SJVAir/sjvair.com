from resticus import serializers

from camp.apps.alerts.models import Subscription


class SubscriptionSerializer(serializers.Serializer):
    fields = ['monitor', 'level']
