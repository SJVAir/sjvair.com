from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.utils.functional import cached_property

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils.models import TimeStampedModel

from camp.apps.calibrations import processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor
from camp.apps.monitors.airgradient.api import AirGradientAPI
from camp.utils.datetime import parse_timestamp
from camp.utils.fields import MACAddressField


class Place(TimeStampedModel):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    name = models.CharField(max_length=100, blank=True)
    url = models.URLField(max_length=100, blank=True)
    token = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    @cached_property
    def api(self):
        return AirGradientAPI(token=self.token)


class AirGradient(Monitor):
    DATA_PROVIDERS = [{
        'name': 'AirGradient',
        'url': 'https://www.airgradient.com/'
    }]

    DATA_SOURCE = {
        'name': 'AirGradient',
        'url': 'https://www.airgradient.com/'
    }

    EXPECTED_INTERVAL = '2min'
    ENTRY_CONFIG = {
        entry_models.PM10: {
            'sensors': ['1', '2'],
            'fields': {'value': 'pm1.0_atm'},
            'allowed_stages': [entry_models.PM10.Stage.RAW],
            'default_stage': entry_models.PM10.Stage.RAW,
        },
        entry_models.PM25: {
            'sensors': ['1', '2'],
            'fields': {'value': 'pm2.5_atm'},
            'allowed_stages': [
                entry_models.PM25.Stage.RAW,
                entry_models.PM25.Stage.CORRECTED,
                entry_models.PM25.Stage.CLEANED,
                entry_models.PM25.Stage.CALIBRATED,
            ],
            'default_stage': entry_models.PM25.Stage.CLEANED,
            'processors': {
                entry_models.PM25.Stage.RAW: [processors.PM25_LCS_Correction],
                entry_models.PM25.Stage.CORRECTED: [processors.PM25_LCS_Cleaning],
                entry_models.PM25.Stage.CLEANED: [
                    processors.PM25_UnivariateLinearRegression,
                    processors.PM25_MultivariateLinearRegression,
                    processors.PM25_EPA_Oct2021,
                ],
            }
        },
        entry_models.PM100: {
            'sensors': ['1', '2'],
            'fields': {'value': 'pm10.0_atm'},
            'allowed_stages': [entry_models.PM25.Stage.RAW],
            'default_stage': entry_models.PM25.Stage.RAW,
        },
        entry_models.Particulates: {
            'sensors': ['1', '2'],
            'fields': {
                'particles_03um': '0.3_um_count',
                'particles_05um': '0.5_um_count',
                'particles_10um': '1.0_um_count',
                'particles_25um': '2.5_um_count',
                'particles_50um': '5.0_um_count',
                'particles_100um': '10.0_um_count',
            },
            'allowed_stages': [entry_models.Particulates.Stage.RAW],
            'default_stage': entry_models.Particulates.Stage.RAW,
        },
        entry_models.Temperature: {
            'fields': {'fahrenheit': 'temperature'},
            'allowed_stages': [
                entry_models.Temperature.Stage.RAW,
                entry_models.Temperature.Stage.CALIBRATED
            ],
            'processors': {
                entry_models.Temperature.Stage.RAW: [processors.AirGradientTemperature],
            },
            'default_stage': entry_models.Temperature.Stage.RAW,
        },
        entry_models.Humidity: {
            'fields': {'value': 'humidity'},
            'allowed_stages': [
                entry_models.Humidity.Stage.RAW,
                entry_models.Humidity.Stage.CALIBRATED
            ],
            'processors': {
                entry_models.Humidity.Stage.RAW: [processors.AirGradientHumidity],
            },
            'default_stage': entry_models.Humidity.Stage.RAW,
        },
        entry_models.Pressure: {
            'fields': {'hpa': 'pressure'},
            'allowed_stages': [entry_models.Pressure.Stage.RAW],
            'default_stage': entry_models.Pressure.Stage.RAW,
        },
    }

    place = models.ForeignKey('AirGradient.Place', related_name='monitors', on_delete=models.SET_NULL, blank=True)
    location_id = models.IntegerField(unique=True)
    serial = MACAddressField()

    @property
    def data_providers(self):
        providers = super().data_providers
        if self.place:
            providers.append({
                'name': self.place.name,
                'url': self.place.url
            })
        return providers
