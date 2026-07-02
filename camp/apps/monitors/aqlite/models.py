from django.contrib.gis.geos import Point
from django.db import models
from django.utils.dateparse import parse_datetime
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel

from camp.apps.calibrations import processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor
from camp.utils.datetime import make_aware


class Organization(TimeStampedModel):
    sqid = SqidsField(alphabet=shuffle_alphabet('aqlite.Organization'))

    name = models.CharField(_('Name'), max_length=100)
    url = models.URLField(_('URL'), max_length=100, blank=True)
    key = models.CharField(_('API Key'), max_length=100)
    is_enabled = models.BooleanField(_('Enabled'), default=True)

    class Meta:
        verbose_name = _('Organization')
        verbose_name_plural = _('Organizations')
        ordering = ['name']

    def __str__(self):
        return self.name

    @cached_property
    def api(self):
        from camp.apps.monitors.aqlite.api import AQLiteAPI
        return AQLiteAPI(key=self.key)


class AQLite(Monitor):
    LAST_ACTIVE_LIMIT = int(60 * 60 * 1.5)

    DATA_PROVIDERS = [{
        'name': '2B Technologies',
        'url': 'https://2btech.io/',
    }]
    DATA_SOURCE = {
        'name': '2B Technologies AQLite',
        'url': 'https://2btech.io/',
    }
    DEVICE = 'AQLite'
    GRADE = Monitor.Grade.FEM
    EXPECTED_INTERVAL = '5 min'
    GPS_JITTER_THRESHOLD = 0.0005  # ~50m in degrees; filters noise on stationary devices

    ENTRY_CONFIG = {
        entry_models.O3: {
            'fields': {'value': 'OZONE'},
            'allowed_stages': [
                entry_models.O3.Stage.RAW,
                entry_models.O3.Stage.CLEANED,
                entry_models.O3.Stage.CALIBRATED,
            ],
            'default_stage': entry_models.O3.Stage.CALIBRATED,
            'processors': {
                entry_models.O3.Stage.RAW: [processors.AQLiteRawCleaner],
            },
            'alerts': {'stage': entry_models.O3.Stage.CALIBRATED},
        },
        entry_models.Temperature: {
            'fields': {'celsius': 'TEMP'},
            'allowed_stages': [entry_models.Temperature.Stage.RAW],
            'default_stage': entry_models.Temperature.Stage.RAW,
        },
        entry_models.Humidity: {
            'fields': {'value': 'RELHUM'},
            'allowed_stages': [entry_models.Humidity.Stage.RAW],
            'default_stage': entry_models.Humidity.Stage.RAW,
        },
        entry_models.Pressure: {
            'fields': {'hpa': 'PRESS'},
            'allowed_stages': [entry_models.Pressure.Stage.RAW],
            'default_stage': entry_models.Pressure.Stage.RAW,
        },
        entry_models.CO2: {
            'fields': {'value': 'CO2'},
            'allowed_stages': [entry_models.CO2.Stage.RAW],
            'default_stage': entry_models.CO2.Stage.RAW,
        },
    }

    organization = models.ForeignKey(
        'aqlite.Organization',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='monitors',
        verbose_name=_('Organization'),
    )
    device_id = models.CharField(
        _('Device ID'),
        max_length=50,
        unique=True,
        help_text=_('Full device identifier, e.g. AQLite-1234'),
    )

    class Meta:
        verbose_name = 'AQLite'

    def _update_position(self, lat, lon):
        new_point = Point(lon, lat)
        if self.position is not None:
            dlat = lat - self.position.y
            dlon = lon - self.position.x
            if (dlat ** 2 + dlon ** 2) < self.GPS_JITTER_THRESHOLD ** 2:
                return
        self.position = new_point
        if not self.location:
            self.location = Monitor.LOCATION.outside

    def create_entries(self, payload):
        timestamp = make_aware(parse_datetime(payload['timestamp']))

        try:
            self._update_position(float(payload['LAT']), float(payload['LON']))
        except (KeyError, TypeError, ValueError):
            pass

        entries = []
        for EntryModel, config in self.ENTRY_CONFIG.items():
            data = {
                field: payload.get(source)
                for field, source in config['fields'].items()
            }
            if any(v is None for v in data.values()):
                continue
            if entry := self.create_entry(EntryModel, timestamp=timestamp, **data):
                entries.append(entry)
        return entries
