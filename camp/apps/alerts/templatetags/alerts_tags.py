from django import template

from camp.apps.alerts.models import Alert, Subscription

register = template.Library()


@register.simple_tag(takes_context=True)
def get_user_alert_count(context):
    user = context['user']
    if user.is_authenticated:
        return (Alert.objects
            .filter(
                monitor__subscriptions__user_id=user.pk,
                end_time__isnull=True
            )
            .distinct()
            .count()
        )
    return 0


@register.simple_tag(takes_context=True)
def get_user_subscription_count(context):
    user = context['user']
    if user.is_authenticated:
        return (Subscription.objects
            .filter(user_id=user.pk)
            .distinct()
            .count()
        )
    return 0
