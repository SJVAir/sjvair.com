from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
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
    
    @property
    def timestamp_pst(self):
        return timezone.localtime(self.timestamp, settings.DEFAULT_TIMEZONE)

    def declared_data(self):
        return {f.name: getattr(self, f.name) for f in self.declared_fields}
    
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
                data = entry.declared_data()
                if len(data) == 1 and 'value' in data:
                    data[EntryModel._meta.model_name] = data.pop('value')
                context.update(data)
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
        lookup = {
            'monitor': self.monitor,
            'sensor': self.sensor,
            'timestamp': self.timestamp,
        }

        if self.is_calibratable:
            lookup['calibration'] = self.calibration

        return not (self.__class__.objects
            .filter(**lookup)
            .exclude(pk=self.pk)
            .exists()
        )


class BaseCalibratedEntry(BaseEntry):
    is_calibratable = True
    min_valid_value = Decimal('0.0')
    max_valid_value = Decimal('1000.0')

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
        ordering = ('-timestamp', 'sensor', 'calibration')

    def is_valid_value(self):
        return self.value is not None and self.value <= self.max_valid_value
    
    def get_calibrated_entries(self):
        '''
        Returns all calibrated entries derived from this entry.
        Uses (monitor, timestamp, sensor) match and requires calibration to be set.
        '''
        return self.__class__.objects.filter(
            monitor=self.monitor,
            timestamp=self.timestamp,
            sensor=self.sensor,
        ).exclude(calibration='')
    
    def get_raw_entry(self):
        '''
        Returns the uncalibrated (raw) version of this entry,
        based on monitor, timestamp, and sensor match.
        '''
        return self.__class__.objects.filter(
            monitor=self.monitor,
            timestamp=self.timestamp,
            sensor=self.sensor,
            calibration='',
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
            data[entry.calibration] = entry.declared_data()

        return data


# Particulate Matter

class PM25(BaseCalibratedEntry):
    label = 'PM2.5'
    epa_aqs_code = 88101
    
    max_valid_value = Decimal('1000.0')
    
    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='PM2.5 (µg/m³)',
    )


class Particulates(BaseEntry):
    max_valid_value = Decimal('500000.0')

    particles_03um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_05um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_10um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_25um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_50um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_100um = models.DecimalField(max_digits=8, decimal_places=2)


class PM10(BaseEntry):
    label = 'PM1.0'

    max_valid_value = Decimal('2000.0')

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='PM1.0 (µg/m³)'
    )


class PM100(BaseEntry):
    label = 'PM10.0'
    epa_aqs_code = 81102

    max_valid_value = Decimal('5000.0')

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='PM10.0 (µg/m³)'
    )


# Meteorological

class Temperature(BaseCalibratedEntry):
    epa_aqs_code = 62101

    max_valid_value = Decimal('140.0')

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
        value = (Decimal(self.fahrenheit) - 32) * (Decimal(5) / Decimal(9))
        return value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    
    @celsius.setter
    def celsius(self, value):
        value = (Decimal(value) * (Decimal(9) / Decimal(5))) + 32
        self.fahrenheit = value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    

    def declared_data(self):
        return {
            'temperature_f': self.fahrenheit,
            'temperature_c': self.celsius,
        }


class Humidity(BaseCalibratedEntry):
    epa_aqs_code = 62201

    max_valid_value = Decimal('100.0')

    value = models.DecimalField(
        max_digits=4, decimal_places=1,
        help_text='Relative humidity (%)'
    )


class Pressure(BaseEntry):
    max_valid_value = Decimal('850.0')

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Atmospheric pressure (mmHg)',
    )

    @property
    def mmhg(self):
        return self.value

    @mmhg.setter
    def mmhg(self, value):
        self.value = Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def hpa(self):
        return (self.mmhg * Decimal('1.33322')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

    @hpa.setter
    def hpa(self, value):
        self.mmhg = Decimal(value) / Decimal('1.33322')

    def declared_data(self):
        return {
            'pressure_mmhg': self.mmhg,
            'pressure_hpa': self.hpa,
        }

# Gases

class O3(BaseEntry):
    label = 'Ozone'
    epa_aqs_code = 44201

    max_valid_value = Decimal('400.0')

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Ozone (ppb)'
    )


class NO2(BaseEntry):
    label = 'Nitrogen Dioxide'
    epa_aqs_code = 42602

    max_valid_value = Decimal('600.0')

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Nitrogen dioxide (ppb)',
    )


class CO(BaseEntry):
    label = 'Carbon Monoxide'
    epa_aqs_code = 42101

    max_valid_value = Decimal('75.0')

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Carbon monoxide (ppm)',
    )


class SO2(BaseEntry):
    label = 'Sulfer Dioxide'
    epa_aqs_code = 42401

    max_valid_value = Decimal('600.0')

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Sulfer dioxide (ppb)',
    )