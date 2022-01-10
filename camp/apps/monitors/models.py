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
from django.utils.dateparse import parse_datetime
from django.utils.functional import lazy

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices
from model_utils.fields import AutoCreatedField, AutoLastModifiedField
from model_utils.models import TimeStampedModel
from py_expression_eval import Parser as ExpressionParser
from resticus.encoders import JSONEncoder
from resticus.serializers import serialize

from camp.apps.monitors.validators import validate_formula
from camp.utils.counties import County
from camp.utils.datetime import make_aware
from camp.utils.managers import InheritanceManager
from camp.utils.validators import JSONSchemaValidator


class Monitor(models.Model):
    COUNTIES = Choices(*County.names)
    LOCATION = Choices('inside', 'outside')

    LAST_ACTIVE_LIMIT = 60 * 10
    PAYLOAD_SCHEMA = None
    SENSORS = ['']

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

    # Where is this sensor setup?
    position = models.PointField(null=True, db_index=True)
    county = models.CharField(max_length=20, blank=True, choices=COUNTIES)
    location = models.CharField(max_length=10, choices=LOCATION)

    notes = models.TextField(blank=True, help_text="Notes for internal use.")

    latest = JSONField(encoder=JSONEncoder, default=dict)
    default_sensor = models.CharField(max_length=50, default='', blank=True)

    pm25_calibration_formula = models.CharField(max_length=255, blank=True,
        default='', validators=[validate_formula])

    objects = InheritanceManager()

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name

    @classmethod
    def subclasses(cls):
        return cls.objects.get_queryset()._get_subclasses_recurse(cls)

    @property
    def device(self):
        return self.__class__.__name__

    @property
    def is_active(self):
        if not self.latest:
            return False
        now = timezone.now()
        cutoff = timedelta(seconds=self.LAST_ACTIVE_LIMIT)
        return (now - parse_datetime(self.latest['timestamp'])) < cutoff

    def get_absolute_url(self):
        return f'/#/monitor/{self.pk}'

    def get_current_pm25_average(self, minutes):
        end_time = timezone.now()
        start_time = end_time - timedelta(minutes=minutes)
        queryset = self.entries.filter(
            timestamp__range=(start_time, end_time),
            sensor=self.default_sensor,
            pm25_env__isnull=False,
        )

        aggregate = queryset.aggregate(average=Avg('pm25_env'))
        return aggregate['average']

    def get_pm25_calibration_formula(self):
        # Check for a formula set on this specific monitor.
        if self.pm25_calibration_formula:
            return self.pm25_calibration_formula

        # Fallback to the formula for this kind of monitor in this county.
        try:
            return Calibration.objects.values_list('pm25_formula', flat=True).get(
                county=self.county,
                monitor_type=self._meta.model_name
            )
        except Calibration.DoesNotExist:
            # Default to an empty string
            return ''

    def create_entry(self, payload, sensor=None):
        return Entry(
            monitor=self,
            payload=payload,
            sensor=sensor or '',
            position=self.position,
            location=self.location,
            is_processed=False,
        )

    def process_entry(self, entry):
        entry.position = self.position
        entry.location = self.location
        entry.calibrate_pm25(self.get_pm25_calibration_formula())
        entry.calculate_aqi()
        entry.calculate_averages()
        entry.is_processed = True
        return entry

    def check_latest(self, entry):
        from camp.api.v1.monitors.serializers import EntrySerializer

        timestamp = self.latest.get('timestamp')
        if timestamp is None:
            is_latest = True
        else:
            timestamp = parse_datetime(timestamp)
            is_latest = make_aware(entry.timestamp) > timestamp

        if entry.sensor == self.default_sensor and is_latest:
            fields = ['id'] + EntrySerializer.fields + EntrySerializer.value_fields
            self.latest = json.loads(json.dumps(serialize(entry, fields=fields), cls=JSONEncoder))

        self.save()

    def save(self, *args, **kwargs):
        if self.position:
            # TODO: Can we do this only when self.position is updated?
            self.county = County.lookup(self.position)
        super().save(*args, **kwargs)


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
        'celcius', 'fahrenheit', 'humidity', 'pressure',
        'pm10_env', 'pm25_env', 'pm100_env',
        'pm10_standard', 'pm25_standard', 'pm100_standard',
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
    timestamp = models.DateTimeField(default=timezone.now)
    monitor = models.ForeignKey('monitors.Monitor', related_name='entries', on_delete=models.CASCADE)
    sensor = models.CharField(max_length=50, blank=True, default='', db_index=True)

    # Where was the monitor when this entry was logged?
    position = models.PointField(null=True, db_index=True)
    location = models.CharField(max_length=10, choices=Monitor.LOCATION)

    # Has the raw data been calibrated and processed?
    is_processed = models.BooleanField(default=False, db_index=True)

    # Original payload from the device / api
    payload = JSONField(encoder=JSONEncoder, default=dict)

    pm25_calibration_formula = models.CharField(max_length=255, blank=True, default='')

    # Post-processed, calibrated data
    celcius = models.DecimalField(max_digits=8, decimal_places=1, null=True)
    fahrenheit = models.DecimalField(max_digits=8, decimal_places=1, null=True)
    humidity = models.DecimalField(max_digits=8, decimal_places=1, null=True)
    pressure = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    pm10_env = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    pm25_env = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    pm100_env = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    pm10_standard = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    pm25_standard = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    pm100_standard = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    pm25_avg_15 = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    pm25_avg_60 = models.DecimalField(max_digits=8, decimal_places=2, null=True)

    pm25_aqi = models.IntegerField(null=True)

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
        ordering = ('sensor', '-timestamp',)

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

    def calibrate_pm25(self, formula):
        if formula:
            parser = ExpressionParser()
            expression = parser.parse(formula)
            context = self.get_calibration_context()

            self.pm25_env = expression.evaluate(context)
            self.pm25_calibration_formula = formula

    def calculate_aqi(self):
        algo = aqi.get_algo(aqi.ALGO_EPA)
        try:
            self.pm25_aqi = algo.iaqi(aqi.POLLUTANT_PM25, min(
                self.get_average('pm25_env', 60 * 12),
                algo.piecewise['bp'][aqi.POLLUTANT_PM25][-1][1])
            )
        except Exception:
            # python-aqi often errors on high numbers because it
            # doesn't account for calculations above 500. Since AQI
            # only goes to 500, just set it to the max. (Yikes!)
            self.pm25_aqi = 500

    def calculate_averages(self):
        self.pm25_avg_15 = self.get_average('pm25_env', 15)
        self.pm25_avg_60 = self.get_average('pm25_env', 60)

    def save(self, *args, **kwargs):
        # Temperature adjustments
        if self.fahrenheit is None and self.celcius is not None:
            self.fahrenheit = (Decimal(self.celcius) * (Decimal(9) / Decimal(5))) + 32
        if self.celcius is None and self.fahrenheit is not None:
            self.celcius = (Decimal(self.fahrenheit) - 32) * (Decimal(5) / Decimal(9))

        return super().save(*args, **kwargs)
