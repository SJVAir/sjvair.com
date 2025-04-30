import copy
import uuid

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.contrib.gis.db import models
from django.contrib.postgres.indexes import BrinIndex
from django.db.models import Avg, Q
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.text import slugify

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices
from py_expression_eval import Parser as ExpressionParser

from camp.apps.calibrations.utils import get_default_calibration
from camp.apps.entries import stages
from camp.apps.entries.fields import EntryTypeField
from camp.apps.monitors.managers import MonitorManager
from camp.utils import classproperty
from camp.utils.counties import County
from camp.utils.datetime import make_aware


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


class DefaultSensor(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    monitor = models.ForeignKey('monitors.Monitor', on_delete=models.CASCADE, related_name='default_sensors')
    entry_type = EntryTypeField()
    sensor = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        unique_together = ('monitor', 'entry_type')

    def __str__(self):
        return f'{self.monitor.name} → {self.entry_type} = {self.sensor or "default"}'

    @cached_property
    def entry_model(self):
        return EntryTypeField.get_model_map().get(self.entry_type)


class LatestEntry(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    monitor = models.ForeignKey('monitors.Monitor', on_delete=models.CASCADE, related_name='latest_entries')

    entry_type = EntryTypeField()
    entry_id = SmallUUIDField()

    stage = models.CharField(max_length=16, choices=stages.Stage.choices, default=stages.Stage.RAW)
    processor = models.CharField(max_length=50, blank=True, default='')
    timestamp = models.DateTimeField(db_index=True)

    class Meta:
        unique_together = ('monitor', 'entry_type', 'processor')

    def __str__(self):
        return f"{self.monitor.name} latest {self.entry_type}"

    @cached_property
    def entry_model(self):
        return EntryTypeField.get_model_map().get(self.entry_type)

    @property
    def entry(self):
        if not hasattr(self, '_entry'):
            self._entry = self.entry_model.objects.get(pk=self.entry_id)
        return self._entry

    @entry.setter
    def entry(self, value):
        """
        When setting entry, also update related fields to keep in sync.
        """
        self.entry_type = value.entry_type
        self.entry_id = value.pk
        self.stage = value.stage
        self.processor = value.processor
        self.timestamp = value.timestamp

        # Update the cache
        self._entry = value


class Monitor(models.Model):
    COUNTIES = Choices(*County.names)
    LOCATION = Choices('inside', 'outside')

    CALIBRATE = False # Legacy
    LAST_ACTIVE_LIMIT = 60 * 60

    SENSORS = [''] # Legacy

    DATA_PROVIDERS = []
    DATA_SOURCE = {}
    DEVICE = None

    EXPECTED_INTERVAL = '1h'
    ENTRY_CONFIG = {}
    ENTRY_UPLOAD_ENABLED = False

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

    # Entries - Legacy
    latest = models.ForeignKey('monitors.Entry', blank=True, null=True, related_name='latest_for', on_delete=models.SET_NULL)

    # TODO: default_pm25_sensor (default_ENTRY_sensor, etc)
    default_sensor = models.CharField(max_length=50, default='', blank=True)

    current_health = models.ForeignKey('qaqc.SensorAnalysis',
        blank=True,
        null=True,
        related_name="current_for",
        on_delete=models.SET_NULL
    )

    objects = MonitorManager()

    class Meta:
        base_manager_name = 'objects'
        ordering = ('name',)

    def __str__(self):
        return self.name

    @classproperty
    def monitor_type(cls):
        return cls._meta.model_name

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

    def set_default_sensor(self, EntryModel, sensor):
        config = self.ENTRY_CONFIG.get(EntryModel)
        if config is None:
            raise ValidationError(f'{EntryModel.__name__} is not configured for this monitor.')

        valid_sensors = config.get('sensors', [])
        if sensor not in valid_sensors:
            raise ValidationError(
                f'"{sensor}" is not a valid sensor for {EntryModel.__name__}. '
                f'Valid options: {valid_sensors}'
            )

        entry_type = EntryModel.entry_type
        DefaultSensor.objects.update_or_create(
            monitor=self,
            entry_type=entry_type,
            defaults={'sensor': sensor}
        )

    def get_default_sensor(self, EntryModel):
        '''
        Returns the default sensor for this monitor and EntryModel.

        Logic:
        - If the EntryModel does not support multiple sensors, return ''
        - If a DefaultSensor exists in the DB or cache, return it
        - Otherwise, return the first defined sensor in ENTRY_CONFIG
        '''
        config = self.ENTRY_CONFIG.get(EntryModel, {})
        sensors = config.get('sensors')

        if sensors is None:
            return ''

        entry_type = EntryModel.entry_type

        # Use prefetched default_sensors if available
        for ds in getattr(self, '_prefetched_objects_cache', {}).get('default_sensors', []):
            if ds.entry_type == entry_type:
                return ds.sensor

        # Fallback to DB query
        sensor = (self.default_sensors
            .filter(entry_type=entry_type)
            .values_list('sensor', flat=True)
            .first()
        )
        if sensor is not None:
            return sensor

        # Final fallback to first sensor in config
        return sensors[0]

    def get_default_stage(self, EntryModel):
        return self.ENTRY_CONFIG.get(EntryModel, {}).get('default_stage', EntryModel.Stage.RAW)

    def get_initial_stage(self, EntryModel):
        '''
        Returns the first allowed stage for this entry type on this monitor.
        Used when creating new raw entries.

        Falls back to 'raw' if not explicitly configured.
        '''
        for stage in self.ENTRY_CONFIG.get(EntryModel, {}).get('allowed_stages'):
            return stage
        return EntryModel.Stage.RAW

    def get_default_calibration(self, EntryModel):
        return get_default_calibration(self.__class__, EntryModel)

    def get_absolute_url(self):
        return f'/monitor/{self.pk}'

    def initialize_entry(self, EntryModel, **kwargs):
        defaults = {
            'monitor': self,
            'position': self.position,
            'location': self.location,
            'stage': self.get_initial_stage(EntryModel)
        }
        defaults.update(**kwargs)
        return EntryModel(**defaults)

    def create_entry(self, EntryModel, **data):
        entry = self.initialize_entry(EntryModel)

        for key, value in data.items():
            setattr(entry, key, value)

        if entry.validation_check():
            entry.save()
            entry.refresh_from_db()
            self.update_latest_entry(entry)
            return entry

    def process_entries_ng(self, entries):
        processed_entries = []
        for entry in entries:
            if results := self.process_entry_ng(entry):
                processed_entries.extend(results)
        return processed_entries

    def process_entry_ng(self, entry):
        config = self.ENTRY_CONFIG.get(entry.__class__, {})
        processors = config.get('processors', {}).get(entry.stage, [])

        processed_entries = []
        for processor in processors:
            if (result := processor(entry).run()):
                self.update_latest_entry(result)
                processed_entries.append(result)

        return processed_entries

    def process_entry_pipeline(self, entry):
        '''
        Recursively processes an entry through its pipeline stages, as defined in ENTRY_CONFIG.

        Returns:
            List of all new entries created during processing (can include cleaned and calibrated stages).
        '''
        processed = []

        for result in self.process_entry_ng(entry):
            processed.append(result)
            processed.extend(self.process_entry_pipeline(result))  # Recursive step

        return processed

    def update_latest_entry(self, entry):
        # Skip if not the default sensor
        if entry.sensor != self.get_default_sensor(entry.__class__):
            return

        allowed_stages = (
            self.get_default_stage(entry.__class__),
            entry.Stage.CALIBRATED
        )
        if entry.stage not in allowed_stages:
            return

        # Skip if not the default calibration
        if entry.stage == entry.Stage.CALIBRATED:
            if entry.calibration != self.get_default_calibration(entry.__class__):
                return

        lookup = {
            'monitor_id': self.pk,
            'entry_type': entry.entry_type,
            'processor': entry.processor,
        }

        try:
            latest = LatestEntry.objects.get(**lookup)
        except LatestEntry.DoesNotExist:
            LatestEntry.objects.create(
                entry_id=entry.pk,
                timestamp=entry.timestamp,
                **lookup
            )
            return

        # Manual compare to avoid hitting the DB unless necessary
        try:
            if latest.entry.timestamp >= entry.timestamp:
                return
        except ObjectDoesNotExist:
            # referenced entry was deleted
            pass

        latest.entry_id = entry.pk
        latest.timestamp = entry.timestamp
        latest.save()


    def get_latest_data(self):
        '''
        Returns a dictionary of the most recent entries for each supported
        entry type on this monitor. Assumes latest_entries are already filtered
        by calibration (via .with_latest_entries()).
        '''
        data = {}

        for latest in self.latest_entries.all():
            payload = latest.entry.declared_data()
            payload.update({
                'sensor': latest.entry.sensor,
                'timestamp': latest.entry.timestamp,
                'calibration': latest.entry.calibration
            })
            data[latest.entry_type] = payload

        return data

    def save(self, *args, **kwargs):
        if self.position:
            # TODO: Can we do this only when self.position is updated?
            self.county = County.lookup(self.position)
        super().save(*args, **kwargs)

    # Legacy

    def create_entry_legacy(self, payload, sensor=None):
        entry = Entry(
            monitor=self,
            sensor=sensor or '',
            position=self.position,
            location=self.location,
        )

        entry = self.process_entry(entry, payload)
        if entry is not None:
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

    def check_latest(self, entry):
        if self.latest_id:
            is_latest = make_aware(entry.timestamp) > self.latest.timestamp
        else:
            is_latest = True

        if entry.sensor == self.default_sensor and is_latest:
            self.latest = entry


# Deprecated (Old and Busted)

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
                monitor_id=self.monitor_id,
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

        # CONSIDER: If the calibrator is too far, do we
        # skip and go with county? How far is too far?
        calibrator = (Calibrator.objects
            .filter(
                is_enabled=True,
                calibrations__end_date__lte=self.timestamp,
            )
            .exclude(calibration__isnull=True)
            .select_related('calibration')
            .closest(self.position)
        )

        if calibrator is not None:
            calibration = calibrator.calibrations.filter(end_date__lte=self.timestamp).first()
            if calibration is not None:
                return calibration.formula

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
