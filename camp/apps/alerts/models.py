from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Avg
from django.utils import timezone
from django.utils.functional import cached_property

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices
from model_utils.models import TimeStampedModel

from camp.apps.entries.fields import EntryTypeField


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

# From Yanni:
# Level Moderate: "Highly sensitive groups should stay indoors and avoid outdoor activities"
# Level Unhealthy for Sensitive Groups: "Sensitive groups should stay indoors and avoid outdoor activities"
# Level Unhealthy: "Everyone should reduce prolonged or heavy exertion"
# Very Healthy: "Everyone should avoid prolonged or heavy exertion"
# Hazardous: "Everyone should stay indoors and avoid physical outdoor activities"

GUIDANCE = {
    LEVELS.unhealthy_sensitive: "Sensitive groups should stay indoors and avoid outdoor activities",
    LEVELS.unhealthy: "Everyone should reduce prolonged or heavy exertion",
    LEVELS.very_unhealthy: "Everyone should avoid prolonged or heavy exertion",
    LEVELS.hazardous: "Everyone should stay indoors and avoid physical outdoor activities",
}

class Subscription(TimeStampedModel):
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

    entry_type = EntryTypeField()
    level = models.CharField(max_length=25)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'monitor', 'entry_type'],
                name='user_subscriptions'
            )
        ]

        ordering = ['monitor__name']

    def __str__(self):
        return f'{self.user_id} : {self.monitor_id} ({self.entry_type.label}) @ {self.level}'

    @cached_property
    def entry_model(self):
        return EntryTypeField.get_model_map().get(self.entry_type)

    def clean(self):
        if not self.entry_model or not self.entry_model.Levels:
            raise ValidationError('This entry type does not support alert levels.')

        self.level = self.level.lower()
        if self.entry_model.Levels.lookup(self.level) is None:
            raise ValidationError(f'{self.level} is not a valid alert level for {self.entry_model.label}.')

        if self.entry_model not in self.monitor.entry_types:
            raise ValidationError(f'{self.monitor} does not support {self.entry_model.label}.')


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

    class Meta:
        ordering = ['-start_time']

    def __str__(self):
        return f'{self.monitor_id} : {self.get_level_display()}'

    def get_average(self, hours=1):
        end_time = timezone.now()
        start_time = end_time - timedelta(hours=hours)
        return (self.monitor.entries
            .filter(timestamp__range=(start_time, end_time))
            .aggregate(average=Avg('pm25'))['average']
        )

    def send_notifications(self):
        # If SMS alerts are disbaled, do nothing.
        if not settings.SEND_SMS_ALERTS:
            return

        values = [level[0] for level in LEVELS]
        notification_levels = values[:values.index(self.level) + 1]

        message = '\n'.join([
            f'Air Quality Alert in {self.monitor.county} County for {self.monitor.name} ({self.monitor.device})',
            '',
            f'{self.get_level_display()}: {GUIDANCE[self.level]}',
            '',
            f'https://sjvair.com{self.monitor.get_absolute_url()}',
        ])

        queryset = (Subscription.objects
            .filter(monitor_id=self.monitor.pk)
            .select_related('user')
        )

        # hazardous means everyone gets it. Evey other
        # level gets filtered.
        if self.level != LEVELS.hazardous:
            queryset = queryset.filter(level=self.level)

        for subscription in queryset:
            subscription.user.send_sms(message)
