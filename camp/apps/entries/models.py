from decimal import Decimal

from django.apps import apps
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.gis.db import models
from django.contrib.postgres.indexes import BrinIndex
from django.utils import timezone

from django_smalluuid.models import SmallUUIDField, uuid_default

from camp.apps.monitors.models import Monitor
from camp.utils import clamp, classproperty


class BaseEntry(models.Model):
    epa_aqs_code = None
    is_calibratable = False

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

    class Meta:
        abstract = True
        get_latest_by = 'timestamp'
        constraints = (
            models.UniqueConstraint(fields=['monitor', 'timestamp', 'sensor'], name='unique_entry_%(class)s'),
        )
        indexes = (
            BrinIndex(fields=['timestamp', 'sensor'], autosummarize=True),
        )
        ordering = ('-timestamp', 'sensor',)

    @classproperty
    def label(cls):
        return cls.__name__

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

    def declared_data(self):
        data = {}

        for f in self.declared_fields:
            if f.name == 'value':
                data['value'] = self.value
            else:
                data[f.name] = getattr(self, f.name)

        # Rename 'value' to model_name if it's the only field
        if len(data) == 1 and 'value' in data:
            key = self.__class__._meta.model_name
            data[key] = data.pop('value')

        return data
    
    def entry_context(self) -> dict:
        '''
        Gathers data from all other BaseEntry subclasses that share
        (monitor, timestamp, sensor) with this entry.
        Merges all declared_data() into one dictionary.
        '''
        context = {}

        for EntryModel, config in self.monitor.ENTRY_CONFIG.items():
            lookup = {
                'monitor': self.monitor,
                'timestamp': self.timestamp,
            }

            # Only filter by sensor if the entry type supports this sensor
            if self.sensor in config.get('sensors', []):
                lookup['sensor'] = self.sensor

            # Only include uncalibrated entries for calibratable models
            if EntryModel.is_calibratable:
                lookup['calibration'] = ''

            try:
                entry = EntryModel.objects.get(**lookup)
                context.update(entry.declared_data())
            except EntryModel.DoesNotExist:
                pass
            except EntryModel.MultipleObjectsReturned:
                # Optional: pick .first(), raise, or log
                pass

        return context

    def clone(self):
        return self.__class__(
            monitor=self.monitor,
            timestamp=self.timestamp,
            position=self.position,
            location=self.location,
            sensor=self.sensor,
        )
    
    def validation_check(self):
        return not self.__class__.objects.filter(
            monitor=self.monitor,
            sensor=self.sensor,
            timestamp=self.timestamp,
            # TODO: calibration type
        ).exists()


class BaseCalibratedEntry(BaseEntry):
    is_calibratable = True
    min_valid_value = Decimal('0.0')
    max_valid_value = Decimal('500.0')
    max_acceptable_value = Decimal('900.0')

    calibration = models.CharField(max_length=50, blank=True, default='', db_index=True)
    calibration_data = models.JSONField(default=dict)

    calibration_content_type = models.ForeignKey(ContentType,
        null=True, db_index=True, editable=False,
        on_delete=models.SET_NULL,
    )
    calibration_object_id = SmallUUIDField(null=True, db_index=True, editable=False)
    calibration_object = GenericForeignKey('calibration_content_type', 'calibration_object_id')

    class Meta(BaseEntry.Meta):
        abstract = True
        constraints = [
            models.UniqueConstraint(
                fields=['monitor', 'timestamp', 'sensor', 'calibration'],
                name='unique_calibrated_entry_%(class)s',
            ),
        ]
    
    def get_calibrated_entries(self):
        '''
        Returns all calibrated entries derived from this entry.
        Uses (monitor, timestamp, sensor) match and requires calibration to be set.
        '''
        return self.__class__.objects.filter(
            monitor=self.monitor,
            timestamp=self.timestamp,
            sensor=self.sensor,
        ).exclude(calibration__isnull=True)
    
    def get_raw_entry(self):
        '''
        Returns the uncalibrated (raw) version of this entry,
        based on monitor, timestamp, and sensor match.
        '''
        return self.__class__.objects.filter(
            monitor=self.monitor,
            timestamp=self.timestamp,
            sensor=self.sensor,
            calibration__isnull=True,
        ).first()
    
    def get_readings(self):
        '''
        Returns a dictionary of all values recorded for this entry,
        including the raw value and any calibrated versions.

        Keys are:
            - 'raw' for the original value
            - calibration name for calibrated values
        '''
        data = {}

        if raw := self.get_raw_entry():
            data['raw'] = raw.declared_data()

        for entry in self.get_calibrated_entries():
            data[entry.calibration] = entry.declared_data

        return data


# Particulate Matter

class PM25(BaseCalibratedEntry):
    label = 'PM2.5'
    epa_aqs_code = 88101
    
    min_valid_value = Decimal('0.0')
    max_valid_value = Decimal('500.0')
    
    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='PM2.5 (µg/m³)',
    )


class Particulates(BaseEntry):
    particles_03um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_05um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_10um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_25um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_50um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_100um = models.DecimalField(max_digits=8, decimal_places=2)


class PM10(BaseEntry):
    label = 'PM1.0'

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='PM1.0 (µg/m³)'
    )


class PM100(BaseEntry):
    label = 'PM10.0'
    epa_aqs_code = 81102

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='PM10.0 (µg/m³)'
    )


# Meteorological

class Temperature(BaseCalibratedEntry):
    epa_aqs_code = 62101

    value = models.DecimalField(
        max_digits=4, decimal_places=1,
        help_text='Temperature (°F)'
    )

    @property
    def fahrenheit(self):
        return self.value
    
    @fahrenheit.setter
    def fahrenheit(self, value):
        self.value = value

    @property
    def celsius(self):
        return (Decimal(self.fahrenheit) - 32) * (Decimal(5) / Decimal(9))
    
    @celsius.setter
    def celsius(self, value):
        self.fahrenheit = (Decimal(value) * (Decimal(9) / Decimal(5))) + 32
    

    def declared_data(self):
        return {
            'temperature_f': self.fahrenheit,
            'temperature_c': self.celsius,
        }


class Humidity(BaseCalibratedEntry):
    epa_aqs_code = 62201

    value = models.DecimalField(
        max_digits=4, decimal_places=1,
        help_text='Relative humidity (%)'
    )


class Pressure(BaseEntry):
    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Atmospheric pressure (mmHg)',
    )


# Gases

class O3(BaseEntry):
    label = 'Ozone'
    epa_aqs_code = 44201

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Ozone (ppb)'
    )


class NO2(BaseEntry):
    label = 'Nitrogen Dioxide'
    epa_aqs_code = 42602

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Nitrogen dioxide (ppb)',
    )


class CO(BaseEntry):
    label = 'Carbon Monoxide'
    epa_aqs_code = 42101

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Carbon monoxide (ppm)',
    )


class SO2(BaseEntry):
    label = 'Sulfer Dioxide'
    epa_aqs_code = 42401

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Sulfer dioxide (ppb)',
    )