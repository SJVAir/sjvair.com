from django.db import models

from model_utils import Choices
from model_utils.models import TimeStampedModel


class Subscription(TimeStampedModel):
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
