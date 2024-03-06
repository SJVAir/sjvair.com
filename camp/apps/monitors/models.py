import copy
import json
import uuid

from datetime import timedelta
from decimal import Decimal

import aqi

from django.contrib.gis.db import models
from django.contrib.postgres.indexes import BrinIndex
from django.db.models import Avg, Q
from django.db.models.functions import Least
from django.contrib.postgres.fields import JSONField
from django.utils import timezone
from django.utils.functional import cached_property, lazy
from django.utils.text import slugify

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices
from model_utils.fields import AutoCreatedField, AutoLastModifiedField
from model_utils.models import TimeStampedModel
from py_expression_eval import Parser as ExpressionParser
from resticus.encoders import JSONEncoder
from resticus.serializers import serialize

from camp.apps.monitors.managers import MonitorManager
from camp.apps.monitors.validators import validate_formula
from camp.utils.counties import County
from camp.utils.datetime import make_aware
from camp.utils.validators import JSONSchemaValidator


class Monitor(models.Model):
    COUNTIES = Choices(*County.names)
    LOCATION = Choices('inside', 'outside')

    CALIBRATE = False
    LAST_ACTIVE_LIMIT = 60 * 60
    PAYLOAD_SCHEMA = None
    SENSORS = ['']

    DATA_PROVIDERS = []
    DATA_SOURCE = {}
    DEVICE = None

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    name = models.CharField(max_length=250)
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    access_key = models.UUIDField(default=uuid.uuid4)

    is_hidden = models.BooleanField(default=False, help_text="Hides the monitor on the map.")
    is_sjvair = models.BooleanField(default=False, help_text="Is this monitor part of the SJVAir network?")
    device = models.CharField(max_length=50, blank=True)

    # Data provider info
    data_provider = models.CharField(max_length=100, blank=True)
    data_provider_url = models.URLField(max_length=100, blank=True)

    # Where is this sensor setup?
    position = models.PointField(null=True, db_index=True)
    county = models.CharField(max_length=20, blank=True, choices=COUNTIES)
    location = models.CharField(max_length=10, choices=LOCATION)

    notes = models.TextField(blank=True, help_text="Notes for internal use.")

    current_health = models.ForeignKey('qaqc.SensorAnalysis',
        blank=True,
        null=True,
        related_name="current_for",
        on_delete=models.SET_NULL
    )
    latest = models.ForeignKey('monitors.Entry', blank=True, null=True, related_name='latest_for', on_delete=models.SET_NULL)
    default_sensor = models.CharField(max_length=50, default='', blank=True)

    pm25_calibration_formula = models.CharField(max_length=255, blank=True,
        default='', validators=[validate_formula])

    objects = MonitorManager()

    class Meta:
        base_manager_name = 'objects'
        ordering = ('name',)

    def __str__(self):
        return self.name

    @classmethod
    def subclasses(cls):
        return cls.objects.get_queryset()._get_subclasses_recurse(cls)

    @property
    def slug(self):
        return slugify(self.name)

    def get_device(self):
        return self.device or self.DEVICE or self._meta.verbose_name

    @property
    def data_providers(self):
        providers = copy.deepcopy(self.DATA_PROVIDERS)
        if self.data_provider:
            providers.append({'name': self.data_provider})
            if self.data_provider_url:
                providers[-1]['url'] = self.data_provider_url
        return providers

    @property
    def data_source(self):
        return self.DATA_SOURCE

    @property
    def is_active(self):
        if not self.latest_id:
            return False
        now = timezone.now()
        cutoff = timedelta(seconds=self.LAST_ACTIVE_LIMIT)
        return (now - self.latest.timestamp) < cutoff

    @cached_property
    def health_grade(self):
        if self.current_health_id:
            return self.current_health.grade

    def get_absolute_url(self):
        return f'/monitor/{self.pk}'

    def get_current_pm25_average(self, minutes):
        end_time = timezone.now()
        start_time = end_time - timedelta(minutes=minutes)
        queryset = self.entries.filter(
            timestamp__range=(start_time, end_time),
            sensor=self.default_sensor,
            pm25__isnull=False,
        )

        aggregate = queryset.aggregate(average=Avg('pm25'))
        return aggregate['average']

    def create_entry(self, payload, sensor=None):
        entry = Entry(
            monitor=self,
            sensor=sensor or '',
            position=self.position,
            location=self.location,
        )

        entry = self.process_entry(entry, payload)
        entry.save()
        return entry

    def process_entry(self, entry, payload):
        '''
            Process the data on an entry, copying data from the monitor and
            payload, and run the calibrations.

            When overridden by a subclass, the super() method should
            be called last.
        '''

        # Calculate the latest averages.
        entry.pm25_avg_15 = entry.get_average('pm25', 15)
        entry.pm25_avg_60 = entry.get_average('pm25', 60)

        # Calibrate the PM25
        if self.CALIBRATE:
            entry.calibrate_pm25()

        return entry

    def check_latest(self, entry):
        if self.latest_id:
            is_latest = make_aware(entry.timestamp) > self.latest.timestamp
        else:
            is_latest = True

        if entry.sensor == self.default_sensor and is_latest:
            self.latest = entry

    def save(self, *args, **kwargs):
        if self.position:
            # TODO: Can we do this only when self.position is updated?
            self.county = County.lookup(self.position)
        super().save(*args, **kwargs)


class Group(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    name = models.CharField(max_length=100)
    monitors = models.ManyToManyField('monitors.Monitor', related_name='groups', blank=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class Calibration(TimeStampedModel):
    COUNTIES = Choices(*County.names)
    MONITOR_TYPES = lazy(lambda: Choices(*Monitor.subclasses()), list)()

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    monitor_type = models.CharField(max_length=20, choices=MONITOR_TYPES)
    county = models.CharField(max_length=20, choices=COUNTIES)
    pm25_formula = models.CharField(max_length=255, blank=True,
        default='', validators=[validate_formula])

    class Meta:
        indexes = [
            models.Index(fields=['monitor_type', 'county'])
        ]

        unique_together = [
            ('monitor_type', 'county')
        ]

    def __str__(self):
        return f'{self.monitor_type} – {self.county}'


class Entry(models.Model):
    ENVIRONMENT = [
        'celsius', 'fahrenheit', 'humidity', 'pressure',
        'pm10', 'pm25', 'pm25_reported', 'pm100',
        'particles_03um', 'particles_05um', 'particles_10um',
        'particles_25um', 'particles_50um', 'particles_100um',
    ]

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
    monitor = models.ForeignKey('monitors.Monitor', related_name='entries', on_delete=models.CASCADE)
    sensor = models.CharField(max_length=50, blank=True, default='', db_index=True)

    # Where was the monitor when this entry was logged?
    position = models.PointField(null=True, db_index=True) # Can we drop this index?
    location = models.CharField(max_length=10, choices=Monitor.LOCATION)

    # TODO: TextField
    pm25_calibration_formula = models.CharField(max_length=255, blank=True, default='')

    celsius = models.DecimalField(max_digits=8, decimal_places=1, null=True)
    fahrenheit = models.DecimalField(max_digits=8, decimal_places=1, null=True)
    humidity = models.DecimalField(max_digits=8, decimal_places=1, null=True)
    pressure = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    ozone = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    # PM 1.0
    pm10 = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    # PM 10.0
    pm100 = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    pm25 = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    pm25_reported = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    pm25_avg_15 = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    pm25_avg_60 = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    particles_03um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_05um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_10um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_25um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_50um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_100um = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=['monitor', 'timestamp', 'sensor'], name='unique_entry'),
        )
        indexes = (
            BrinIndex(fields=['timestamp', 'sensor'], autosummarize=True),
        )
        ordering = ('-timestamp', 'sensor',)

    def get_calibration_context(self):
        return {
            field: float(getattr(self, field, None) or 0)
            for field in self.ENVIRONMENT
        }

    def get_average(self, field, minutes):
        values = list(Entry.objects
            .filter(
                monitor=self.monitor,
                sensor=self.sensor,
                timestamp__range=(
                    self.timestamp - timedelta(minutes=minutes),
                    self.timestamp,
                ))
            .exclude(
                Q(pk=self.pk)
                | Q(**{f'{field}__isnull': True})
            )
            .values_list(field, flat=True)
        )

        if getattr(self, field) is not None:
            values.append(Decimal(getattr(self, field)))

        if values:
            return sum(values) / len(values)

        return 0

    def get_pm25_calibration_formula(self):
        from camp.apps.calibrations.models import Calibrator

        # Check for a formula set on this specific monitor.
        if self.monitor.pm25_calibration_formula:
            return self.monitor.pm25_calibration_formula

        # Distance-based calibrations
        # CONSIDER: If the calibrator is too far, do we
        # skip and go with county? How far is too far?
        calibrator = (Calibrator.objects
            .filter(is_enabled=True)
            .exclude(calibration__isnull=True)
            .select_related('calibration')
            .closest(self.position)
        )

        if calibrator is not None:
            calibration = calibrator.calibrations.filter(end_date__lte=self.timestamp).first()
            if calibration is not None:
                return calibration.formula

        # Fallback to county-based calibrations.
        try:
            return Calibration.objects.values_list('pm25_formula', flat=True).get(
                county=self.monitor.county,
                monitor_type=self.monitor._meta.model_name
            )
        except Calibration.DoesNotExist:
            # Default to an empty string, which is a noop formula.
            return ''

    def calibrate_pm25(self):
        formula = self.get_pm25_calibration_formula()

        if formula:
            parser = ExpressionParser()
            expression = parser.parse(formula)
            context = self.get_calibration_context()

            self.pm25 = expression.evaluate(context)
            self.pm25_calibration_formula = formula

    def save(self, *args, **kwargs):
        # Temperature adjustments
        if self.fahrenheit is None and self.celsius is not None:
            self.fahrenheit = (Decimal(self.celsius) * (Decimal(9) / Decimal(5))) + 32
        if self.celsius is None and self.fahrenheit is not None:
            self.celsius = (Decimal(self.fahrenheit) - 32) * (Decimal(5) / Decimal(9))

        return super().save(*args, **kwargs)
