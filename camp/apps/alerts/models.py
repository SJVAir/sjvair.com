from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext as _

from django_smalluuid.models import SmallUUIDField, uuid_default
from django_sqids import SqidsField, shuffle_alphabet
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

    # Notification state (see notifications.get_alert_level). A blank
    # last_notified_level means the subscription is re-armed.
    last_notified_level = models.CharField(_('Last notified level'), max_length=25, blank=True)
    last_notified_at = models.DateTimeField(_('Last notified at'), null=True, blank=True)
    below_threshold_since = models.DateTimeField(_('Below threshold since'), null=True, blank=True)

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

    def get_threshold(self):
        # No alert record exists below Moderate, so a 'good' subscription
        # behaves as 'moderate'.
        return max(AQLevel.scale[self.level.upper()], AQLevel.scale.MODERATE, key=lambda level: level.rank)

    def get_last_notified_level(self):
        if self.last_notified_level:
            return AQLevel.scale[self.last_notified_level.upper()]


class Alert(TimeStampedModel):
    sqid = SqidsField(alphabet=shuffle_alphabet('alerts.Alert'))

    monitor = models.ForeignKey('monitors.Monitor', related_name='alerts', on_delete=models.CASCADE)
    entry_type = EntryTypeField()

    start_time = models.DateTimeField()
    end_time = models.DateTimeField(blank=True, null=True)

    latest = models.OneToOneField(
        'alerts.AlertUpdate',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+'
    )

    class Meta:
        ordering = ['-start_time']
        constraints = [
            models.UniqueConstraint(
                fields=['monitor', 'entry_type'],
                condition=models.Q(end_time__isnull=True),
                name='one_open_alert_per_monitor_entry_type',
            ),
        ]

    def __str__(self):
        return f'Alert for {self.monitor_id} ({self.entry_type}) @ {self.start_time}'

    @cached_property
    def entry_model(self):
        return EntryTypeField.get_model_map().get(self.entry_type)

    def create_update(self, level, timestamp=None):
        return AlertUpdate.objects.create(
            alert_id=self.pk,
            level=level.key,
            timestamp=timestamp or timezone.now(),
        )


class AlertUpdate(TimeStampedModel):
    sqid = SqidsField(alphabet=shuffle_alphabet('alerts.AlertUpdate'))

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

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.alert.latest or self.alert.latest.timestamp < self.timestamp:
            self.alert.latest_id = self.pk
            self.alert.save(update_fields=['latest_id'])


class Notification(TimeStampedModel):
    class Status(models.TextChoices):
        QUEUED = 'queued', _('Queued')
        SENT = 'sent', _('Sent')
        DELIVERED = 'delivered', _('Delivered')
        UNDELIVERED = 'undelivered', _('Undelivered')
        FAILED = 'failed', _('Failed')

    class Kind(models.TextChoices):
        ALERT = 'alert', _('Alert')
        REMINDER = 'reminder', _('Reminder')

    sqid = SqidsField(alphabet=shuffle_alphabet('alerts.Notification'))

    alert_update = models.ForeignKey('alerts.AlertUpdate', related_name='notifications', on_delete=models.CASCADE)
    subscription = models.ForeignKey('alerts.Subscription', null=True, blank=True, related_name='notifications', on_delete=models.SET_NULL)
    user = models.ForeignKey('accounts.User', related_name='notifications', on_delete=models.CASCADE)

    kind = models.CharField(_('Kind'), max_length=10, choices=Kind.choices, default=Kind.ALERT)
    level = models.CharField(_('Level'), max_length=25, blank=True)

    status = models.CharField(max_length=11, choices=Status.choices, default=Status.QUEUED)
    message = models.TextField()
    provider_id = models.CharField(max_length=64, blank=True)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return f'Notification for {self.user_id} @ {self.status}'
