from decimal import Decimal

from django.apps import apps
from django.contrib.gis.db import models
from django.contrib.postgres.indexes import BrinIndex
from django.utils import timezone

from django_smalluuid.models import SmallUUIDField, uuid_default

from camp.apps.monitors.models import Monitor


class BaseEntry(models.Model):
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
    # calibration_type = models.CharField(max_length=50, blank=True, null=True, default='', db_index=True)
    # calibration_data = models.JSONField(default=dict)

    class Meta:
        abstract = True
        constraints = (
            models.UniqueConstraint(fields=['monitor', 'timestamp', 'sensor'], name='unique_entry_%(class)s'),
        )
        indexes = (
            BrinIndex(fields=['timestamp', 'sensor'], autosummarize=True),
        )
        ordering = ('-timestamp', 'sensor',)

    def declared_fields(self):
        base_field_names = {
            f.name for f in BaseEntry._meta.get_fields()
            if not f.auto_created
        }

        return [
            f for f in self.__class__._meta.get_fields()
            if (f.name not in base_field_names and not f.auto_created)
        ]

    def declared_data(self):
        data = {
            f.name: getattr(self, f.name)
            for f in self.declared_fields()
        }

        if len(data) == 1 and "value" in data:
            key = self.__class__._meta.model_name
            data[key] = data.pop('value')

        return data
    
    def pollutant_context(self) -> dict:
        """
        Gathers data from all other BaseEntry subclasses that share
        (monitor, timestamp, sensor) with this entry.
        Merges all declared_data() into one dictionary.
        """
        # Start with the current entry's data
        context = self.declared_data()

        # Find all non-abstract models that inherit from BaseEntry
        EntryModels = [
            m for m in apps.get_models()
            if issubclass(m, BaseEntry) and not m._meta.abstract
        ]

        for EntryModel in EntryModels:
            # Skip if it's the same model class as self
            if EntryModel is self.__class__:
                continue

            # Build lookup dict for (monitor, timestamp, sensor)
            lookup = {
                'monitor': self.monitor,
                'timestamp': self.timestamp
            }
            if hasattr(EntryModel, 'sensor') and self.sensor:
                lookup['sensor'] = self.sensor

            # Attempt to get a single matching entry
            try:
                entry = EntryModel.objects.get(**lookup)
                # Merge the declared data from that entry
                context.update(entry.declared_data())
            except EntryModel.DoesNotExist:
                # No matching entry, skip
                pass
            except EntryModel.MultipleObjectsReturned:
                # If multiple found, decide how to handle 
                # or just skip
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
    
    def process_data(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
    
    def related(self):
        return self.__class__.objects.filter(
            monitor=self.monitor,
            sensor=self.sensor,
            timestamp=self.timestamp,
        ).exclude(pk=self.pk)
    
    def validation_check(self):
        return not self.__class__.objects.filter(
            monitor=self.monitor,
            sensor=self.sensor,
            timestamp=self.timestamp,
            # TODO: calibration type
        ).exists()


# Particulate Matter

class PM25(BaseEntry):
    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="PM2.5 (µg/m³)",
    )
        
    # def calibrate_epa(self, value):
    #     pass


class Particulates(BaseEntry):
    particles_03um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_05um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_10um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_25um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_50um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_100um = models.DecimalField(max_digits=8, decimal_places=2)


class PM10(BaseEntry):
    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="PM1.0 (µg/m³)"
    )


class PM100(BaseEntry):
    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="PM10.0 (µg/m³)"
    )


# Meteorological

class Temperature(BaseEntry):
    value = models.DecimalField(
        max_digits=4, decimal_places=1,
        help_text="Temperature (°F)"
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
    

class Humidity(BaseEntry):
    value = models.DecimalField(
        max_digits=4, decimal_places=1,
        help_text="Relative humidity (%)"
    )


class Pressure(BaseEntry):
    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="Atmospheric pressure (mmHg)",
    )


# Gases

class O3(BaseEntry):
    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="Ozone (ppb)"
    )


class NO2(BaseEntry):
    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="Nitrogen dioxide (ppb)",
    )


class CO(BaseEntry):
    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="Carbon monoxide (ppm)",
    )


class SO2(BaseEntry):
    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="Sulfer dioxide (ppb)",
    )