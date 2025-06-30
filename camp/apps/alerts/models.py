from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Avg
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext as _

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices
from model_utils.models import TimeStampedModel

from camp.apps.entries.fields import EntryTypeField
from camp.apps.entries.levels import AQLevel


class Subscription(TimeStampedModel):
    LEVELS = Choices(  # Legacy
        ('unhealthy_sensitive', 'Unhealthy for Sensitive Groups'),
        ('unhealthy', 'Unhealthy'),
        ('very_unhealthy', 'Very Unhealthy'),
        ('hazardous', 'Hazardous'),
    )

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

    level = models.CharField(max_length=25, choices=AQLevel.choices)

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

    def clean(self):
        super().clean()
        self.level = self.level.lower()


class Alert(TimeStampedModel):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    monitor = models.ForeignKey('monitors.Monitor', related_name='alerts', on_delete=models.CASCADE)
    entry_type = EntryTypeField()

    start_time = models.DateTimeField()
    end_time = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-start_time']

    def __str__(self):
        return f'Alert for {self.monitor_id} ({self.entry_type}) @ {self.start_time}'

    @cached_property
    def entry_model(self):
        return EntryTypeField.get_model_map().get(self.entry_type)

    def get_average(self, hours=1):
        end_time = timezone.now()
        start_time = end_time - timedelta(hours=hours)
        return (self.monitor.entries
            .filter(timestamp__range=(start_time, end_time))
            .aggregate(average=Avg('pm25'))['average']
        )

    def create_update(self, level, **kwargs):
        update = AlertUpdate.objects.create(
            alert_id=self.pk,
            level=level.key,
            **kwargs,
        )
        self.send_notifications(update.get_level())
        return update

    def send_notifications(self, level):
        # If SMS alerts are disbaled, do nothing.
        if not settings.SEND_SMS_ALERTS:
            return

        icon = '⚠️' if level != AQLevel.scale.GOOD else '✅'

        message = '\n'.join([
            _('{icon} Air Quality Alert for {name} in {county} County').format(
                icon=icon,
                name=self.monitor.name,
                county=self.monitor.county,
            ),
            f'{self.entry_model.label}: {level.label}',
            f'{level.guidance}\n' or '',
            f'🔗 https://sjvair.com{self.monitor.get_absolute_url()}',
        ])

        queryset = (Subscription.objects
            .filter(monitor_id=self.monitor.pk)
            .select_related('user')
        )

        for sub in queryset:
            sub_level = AQLevel.scale[sub.level.upper()]
            if level >= sub_level:
                sub.user.send_sms(message)


class AlertUpdate(TimeStampedModel):
    alert = models.ForeignKey('alerts.Alert', related_name='updates', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(default=timezone.now)
    level = models.CharField(max_length=25)

    class Meta:
        get_latest_by = 'timestamp'
        ordering = ['timestamp']

    def __str__(self):
        return f'AlertUpdate for {self.alert_id} @ {self.timestamp} => {self.level}'

    def get_level(self):
        return self.alert.entry_model.Levels[self.level]

    def clean(self):
        if not self.alert.entry_model or not self.alert.entry_model.Levels:
            raise ValidationError('This alert entry type does not support alert levels.')

        if self.alert.entry_model.Levels.lookup(self.level) is None:
            raise ValidationError(f'{self.level} is not a valid alert level for {self.alert.entry_type.label}.')
