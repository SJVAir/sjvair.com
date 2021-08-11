from datetime import timedelta

from django.db import models
from django.db.models import Avg
from django.utils import timezone

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices
from model_utils.models import TimeStampedModel

LEVELS = Choices(
    ('unhealthy_sensitive', 'Unhealthy for Sensitive Groups'),
    ('unhealthy', 'Unhealthy'),
    ('very_unhealthy', 'Very Unhealthy'),
    ('hazardous', 'Hazardous'),
    # (35, 'unhealthy_sensitive', 'Unhealthy for Sensitive Groups'),
    # (55, 'unhealthy', 'Unhealthy'),
    # (150, 'very_unhealthy', 'Very Unhealthy'),
    # (250, 'hazardous', 'Hazardous'),
)

PM25_LEVELS = (
    (250, LEVELS.hazardous),
    (150, LEVELS.very_unhealthy),
    (55, LEVELS.unhealthy),
    (30, LEVELS.unhealthy_sensitive),
)

class Subscription(TimeStampedModel):
    LEVELS = LEVELS

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    user = models.ForeignKey('accounts.User',
        related_name='subscriptions',
        on_delete=models.CASCADE,
    )

    monitor = models.ForeignKey('monitors.Monitor',
        related_name='subscriptions',
        on_delete=models.CASCADE,
    )

    level = models.CharField(max_length=25, choices=LEVELS)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'monitor'],
                name='user_subscriptions'
            )
        ]

        ordering = ['monitor__name']

    def __str__(self):
        return f'{self.user_id} : {self.monitor_id} @ {self.level}'


class Alert(TimeStampedModel):
    LEVELS = LEVELS

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    start_time = models.DateTimeField()
    end_time = models.DateTimeField(blank=True, null=True)
    monitor = models.ForeignKey('monitors.Monitor', related_name='alerts', on_delete=models.CASCADE)
    pm25_average = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    level = models.CharField(max_length=25, choices=LEVELS)

    def __str__(self):
        return f'{self.monitor_d} : {self.get_level_display}'

    def get_average(self, hours=1):
        end_time = timezone.now()
        start_time = end_time - timedelta(hours=hours)
        return (self.monitor.entries
            .filter(timestamp__range=(start_time, end_time))
            .aggregate(average=Avg('pm25_env'))['average']
        )

    def send_notifications(self):
        values = [level[0] for level in LEVELS]
        notification_levels = values[:values.index(self.level) + 1]

        message = '\n'.join([
            f'SJVAir.com - Air Quality Alert in {self.monitor.county} County',
            '',
            f'Air Monitor: {self.monitor.name}',
            f'Air Quality: {self.get_level_display()}',
            '',
            f'https://sjvair.com{self.monitor.get_absolute_url()}',
        ])

        subscription_list = (Subscription.objects
            .filter(
                monitor_id=self.monitor.pk,
                level__in=notification_levels,
            )
            .select_related('user')
        )
        for subscription in subscription_list:
            subscription.user.send_sms(message)
