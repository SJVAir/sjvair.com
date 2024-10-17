from decimal import Decimal

from django.contrib.gis.db import models
from django.contrib.postgres.indexes import BrinIndex
from django.utils import timezone

from django_smalluuid.models import SmallUUIDField, uuid_default
from py_expression_eval import Parser as ExpressionParser


class BaseEntry(models.Model):
    monitor_attr = None

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
    sensor = models.CharField(max_length=50, blank=True, default='', db_index=True)

    class Meta:
        abstract = True
        constraints = (
            models.UniqueConstraint(fields=['monitor', 'timestamp', 'sensor'], name='unique_entry_%(class)s'),
        )
        indexes = (
            BrinIndex(fields=['timestamp', 'sensor'], autosummarize=True),
        )
        ordering = ('-timestamp', 'sensor',)

    def process(self):
        pass

    def validation_check(self):
        return not self.__class__.objects.filter(
            monitor=self.monitor,
            sensor=self.sensor,
            timestamp=self.timestamp,
        ).exists()

        # base_fields = [f.attname for f in BaseEntry._meta.fields]
        # this_fields = [f.attname for f in self._meta.fields if f.attname not in base_fields]


class PM25(BaseEntry):
    monitor_attr = 'pm25'
    pm25_reported = models.DecimalField(max_digits=6, decimal_places=2)
    pm25_calibrated = models.DecimalField(max_digits=6, decimal_places=2, null=True)
    pm25_calibration_formula = models.TextField(blank=True, default='')

    @property
    def pm25(self):
        return self.pm25_calibrated or self.pm25_reported

    def get_calibration_formula(self):
        from camp.apps.calibrations.models import Calibrator

        calibrator = (Calibrator.objects
            .filter(is_enabled=True)
            .exclude(calibration__isnull=True)
            .select_related('calibration')
            .closest(self.monitor.position)
        )

        if calibrator is not None:
            calibration = calibrator.calibrations.filter(end_date__lte=self.timestamp).first()
            if calibration is not None:
                return calibration.formula

    def calibrate(self):
        formula = self.get_calibration_formula()

        if formula:
            parser = ExpressionParser()
            expression = parser.parse(formula)
            context = self.get_calibration_context()

            self.pm25_calibrated = expression.evaluate(context)
            self.pm25_calibration_formula = formula

    def process(self):
        if self.monitor.CALIBRATE:
            self.calibrate()
        return super().process()


class PM10(BaseEntry):
    monitor_attr = 'pm10'
    pm10 = models.DecimalField(max_digits=6, decimal_places=2)


class PM100(BaseEntry):
    monitor_attr = 'pm100'
    pm100 = models.DecimalField(max_digits=6, decimal_places=2)


class Particulates(BaseEntry):
    monitor_attr = 'particulates'
    particles_03um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_05um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_10um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_25um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_50um = models.DecimalField(max_digits=8, decimal_places=2)
    particles_100um = models.DecimalField(max_digits=8, decimal_places=2)


class Temperature(BaseEntry):
    monitor_attr = 'temperature'
    celsius = models.DecimalField(max_digits=5, decimal_places=1)
    fahrenheit = models.DecimalField(max_digits=5, decimal_places=1)

    def save(self, *args, **kwargs):
        if self.fahrenheit is None and self.celsius is not None:
            self.fahrenheit = (Decimal(self.celsius) * (Decimal(9) / Decimal(5))) + 32
        if self.celsius is None and self.fahrenheit is not None:
            self.celsius = (Decimal(self.fahrenheit) - 32) * (Decimal(5) / Decimal(9))
        return super().save(*args, **kwargs)


class Humidity(BaseEntry):
    monitor_attr = 'humidity'
    humidity = models.DecimalField(max_digits=4, decimal_places=1)


class Pressure(BaseEntry):
    monitor_attr = 'pressure'
    pressure = models.DecimalField(max_digits=6, decimal_places=2)


class Ozone(BaseEntry):
    monitor_attr = 'ozone'
    ozone = models.DecimalField(max_digits=8, decimal_places=2)
