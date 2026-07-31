from django.db import models
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel

from camp.apps.entries import levels


class Forecast(TimeStampedModel):
    class Pollutant(models.TextChoices):
        OZONE = 'O3', _('Ozone')
        PM25 = 'PM2.5', _('PM2.5')

    sqid = SqidsField(alphabet=shuffle_alphabet('forecasts.Forecast'))

    region = models.ForeignKey(
        'regions.Region',
        on_delete=models.CASCADE,
        related_name='forecasts',
    )
    zone_name = models.CharField(_('zone name'), max_length=64)

    forecast_date = models.DateField(_('forecast date'))
    issued_date = models.DateField(_('issued date'))
    published_at = models.DateTimeField(_('published at'))

    aqi_value = models.PositiveSmallIntegerField(_('AQI value'))
    aqi_category = models.CharField(_('AQI category'), max_length=32)
    pollutant = models.CharField(_('pollutant'), max_length=16, choices=Pollutant.choices)

    burn_status = models.CharField(_('burn status'), max_length=32, blank=True)
    burn_status_text = models.CharField(_('burn status text'), max_length=255, blank=True)

    air_alert = models.BooleanField(_('air alert'), default=False)
    air_alert_start = models.DateField(_('air alert start'), null=True, blank=True)
    air_alert_end = models.DateField(_('air alert end'), null=True, blank=True)

    class Meta:
        ordering = ('-issued_date', 'region__name')
        indexes = [
            models.Index(fields=['region', 'forecast_date']),
            models.Index(fields=['issued_date']),
        ]

    def __str__(self):
        return f'{self.zone_name} forecast for {self.forecast_date} (issued {self.issued_date})'

    @property
    def color(self):
        return levels.AQI.get_color(self.aqi_value)
