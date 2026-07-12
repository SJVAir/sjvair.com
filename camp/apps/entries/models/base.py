from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.indexes import BrinIndex
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from django_smalluuid.models import SmallUUIDField, uuid_default

from camp.apps.monitors.models import Monitor
from camp.utils import classproperty

from ..levels import LevelSet, AQLevel
from ..managers import EntryQuerySet
from .. import stages


class BaseEntry(models.Model):
    epa_aqs_code = None
    units = None
    summarize = False
    Stage = stages.Stage
    Levels = None

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    monitor = models.ForeignKey('monitors.Monitor', related_name='%(class)s_entries', on_delete=models.CASCADE)
    position = models.PointField(null=True, blank=True)
    location = models.CharField(max_length=10, choices=Monitor.LOCATION)

    sensor = models.CharField(max_length=50, blank=True, default='', db_index=True)

    stage = models.CharField(max_length=16, choices=Stage.choices, default=Stage.RAW, help_text=_('The processing stage for this entry.'))
    origin = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='derived_entries')

    processor = models.CharField(
        max_length=100,
        blank=True,
        default='',
        db_index=True,
        help_text=_('The processor class used to generate this entry.')
    )

    calibration = models.ForeignKey(
        'calibrations.Calibration',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='%(class)s_entries',
        help_text=_('The calibration record applied to this entry (if applicable).')
    )

    objects = EntryQuerySet.as_manager()

    class Meta:
        abstract = True
        get_latest_by = 'timestamp'
        constraints = (
            models.UniqueConstraint(
                fields=['monitor', 'timestamp', 'sensor', 'stage', 'processor'],
                name='unique_entry_%(class)s'
            ),
        )
        indexes = (
            BrinIndex(fields=['timestamp', 'sensor'], autosummarize=True),
        )
        ordering = ('-timestamp', 'sensor', 'processor')

    @classproperty
    def label(cls):
        return cls.__name__

    @classproperty
    def entry_type(cls):
        return cls._meta.model_name

    @classproperty
    def declared_fields(cls):
        if hasattr(cls, '_declared_fields'):
            return cls._declared_fields

        # Collect all inherited (non-auto) field names
        base_field_names = set()
        for base in cls.__bases__:
            if hasattr(base, '_meta'):
                base_field_names.update(
                    f.name for f in base._meta.get_fields() if not f.auto_created
                )

        cls._declared_fields = [
            f for f in cls._meta.get_fields()
            if f.name not in base_field_names and not f.auto_created
        ]

        return cls._declared_fields

    @classproperty
    def declared_field_names(cls):
        return [f.name for f in cls.declared_fields]

    @classproperty
    def projection_fields(cls):
        core_fields = ['timestamp', 'sensor', 'stage', 'processor']
        return core_fields + cls.declared_field_names

    @classmethod
    def get_subclasses(cls):
        subclasses = set()

        def recurse(subcls):
            for sc in subcls.__subclasses__():
                subclasses.add(sc)
                recurse(sc)

        recurse(cls)
        return list(subclasses)

    @cached_property
    def level(self):
        if self.Levels and getattr(self, 'value', None) is not None:
            return self.Levels.get_level(self.value)

    @property
    def timestamp_local(self):
        return timezone.localtime(self.timestamp, settings.DEFAULT_TIMEZONE)

    def declared_data(self):
        return {f.name: getattr(self, f.name) for f in self.declared_fields}

    def serialized_data(self):
        return self.declared_data()

    def entry_context(self) -> dict:
        '''
        Gathers data from all other BaseEntry subclasses that share
        (monitor, timestamp, sensor, stage) with this entry.
        Merges all declared_data() into one dictionary.
        '''
        context = {}

        for EntryModel, config in self.monitor.ENTRY_CONFIG.items():
            lookup = {
                'monitor': self.monitor,
                'timestamp': self.timestamp,
                'stage': config.get('default_stage', BaseEntry.Stage.RAW),
            }

            entry = EntryModel.objects.filter(**lookup).first()
            if entry is not None:
                data = entry.declared_data()
                if len(data) == 1 and 'value' in data:
                    data[EntryModel._meta.model_name] = data.pop('value')
                context.update(data)

        return context

    def clone(self, **kwargs):
        values = {
            'monitor': self.monitor,
            'timestamp': self.timestamp,
            'position': self.position,
            'location': self.location,
            'sensor': self.sensor,
            'origin_id': self.pk,
        }
        entry = self.__class__(**values)
        for key, value in kwargs.items():
            setattr(entry, key, value)
        return entry

    def validation_check(self):
        return not (self.__class__.objects
            .filter(
                monitor_id=self.monitor.pk,
                timestamp=self.timestamp,
                sensor=self.sensor,
                stage=self.stage,
                processor=self.processor,
            )
            .exclude(pk=self.pk)
            .exists()
        )

    def get_next_entries(self):
        return self.__class__.objects.filter(
            monitor=self.monitor,
            sensor=self.sensor,
            timestamp__gt=self.timestamp,
            stage=self.stage,
            processor=self.processor,
        ).order_by('timestamp')

    def get_next_entry(self):
        return self.get_next_entries().first()

    def get_previous_entries(self):
        return self.__class__.objects.filter(
            monitor=self.monitor,
            sensor=self.sensor,
            timestamp__lt=self.timestamp,
            stage=self.stage,
            processor=self.processor,
        ).order_by('-timestamp')

    def get_previous_entry(self):
        return self.get_previous_entries().first()

    def get_sibling_entries(self):
        '''
        Returns a queryset of entries recorded at the same timestamp and stage,
        with the same monitor and entry type, but from a different sensor.
        Only applicable to entry types that support multiple sensors.
        '''
        if not self.sensor:
            return self.__class__.objects.none()

        config = self.monitor.ENTRY_CONFIG.get(self.__class__, {})
        sensors = config.get('sensors')
        if not sensors or len(sensors) < 2:
            return self.__class__.objects.none()

        return (self.__class__.objects
            .filter(
                monitor=self.monitor,
                timestamp=self.timestamp,
                stage=self.stage,
                sensor__in=sensors,
                processor=self.processor,
            )
            .exclude(sensor=self.sensor)
            .order_by('sensor')
        )

    def get_sibling_entry(self):
        return self.get_sibling_entries().first()

    def get_calibrated_entries(self):
        '''
        Returns all calibrated entries derived from this entry.
        Uses (monitor, timestamp, sensor) match and requires calibration to be set.
        '''
        return self.__class__.objects.filter(
            monitor=self.monitor,
            timestamp=self.timestamp,
            sensor=self.sensor,
            stage=self.Stage.CALIBRATED
        )

    def get_raw_entry(self):
        '''
        Returns the uncalibrated (raw) version of this entry,
        based on monitor, timestamp, and sensor match.
        '''
        return self.__class__.objects.filter(
            monitor=self.monitor,
            timestamp=self.timestamp,
            sensor=self.sensor,
            stage=self.Stage.RAW
        ).first()

    def get_related_entries(self):
        '''
        Returns a queryset of entries from the same monitor, timestamp, and sensor.
        This will include the raw, cleaned, and calibrated versions.
        '''
        return self.__class__.objects.filter(
            monitor=self.monitor,
            timestamp=self.timestamp,
        )

    def get_readings(self):
        '''
        Returns a dictionary of all values recorded for this entry.

        Keys:
            - 'raw' for the original unmodified value
            - 'cleaned' for the cleaned version (if any)
            - calibration name for each calibrated version
        '''
        readings = {}

        for entry in self.get_related_entries():
            bits = []
            if entry.sensor:
                bits.append(entry.sensor)
            bits.append(entry.processor if entry.stage == entry.Stage.CALIBRATED else entry.stage)
            key = '_'.join(bits)
            readings[key] = entry.declared_data()

        return readings
