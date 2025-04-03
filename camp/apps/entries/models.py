from decimal import Decimal

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
    # calibration_data = models.TextArea(blank=True, null=True, default='')

    class Meta:
        abstract = True
        constraints = (
            models.UniqueConstraint(fields=['monitor', 'timestamp', 'sensor'], name='unique_entry_%(class)s'),
        )
        indexes = (
            BrinIndex(fields=['timestamp', 'sensor'], autosummarize=True),
        )
        ordering = ('-timestamp', 'sensor',)

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


    # def get_calibration_formula(self):
    #     from py_expression_eval import Parser as ExpressionParser
    #     from camp.apps.calibrations.models import Calibrator

    #     calibrator = (Calibrator.objects
    #         .filter(is_enabled=True)
    #         .exclude(calibration__isnull=True)
    #         .select_related('calibration')
    #         .closest(self.monitor.position)
    #     )

    #     if calibrator is not None:
    #         calibration = calibrator.calibrations.filter(end_date__lte=self.timestamp).first()
    #         if calibration is not None:
    #             return calibration.formula

    # def calibrate_local(self, value):
    #     formula = self.get_local_calibration_formula()

    #     if formula:
    #         parser = ExpressionParser()
    #         expression = parser.parse(formula)
    #         context = self.get_calibration_context()
    #         return expression.evaluate(context)
        
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