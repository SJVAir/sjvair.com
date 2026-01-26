import copy
import math
import uuid

from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd

from django.core.exceptions import ObjectDoesNotExist
from django.contrib.gis.db import models
from django.contrib.postgres.indexes import BrinIndex
from django.db.models import Avg, Q
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices
from model_utils.models import TimeStampedModel
from phonenumber_field.modelfields import PhoneNumberField
from py_expression_eval import Parser as ExpressionParser

from camp.apps.calibrations.utils import get_default_calibration
from camp.apps.entries import stages
from camp.apps.entries.fields import EntryTypeField
from camp.apps.monitors.managers import MonitorManager
from camp.apps.qaqc.models import HealthCheck
from camp.utils import classproperty
from camp.utils.counties import County
from camp.utils.datetime import make_aware
from camp.utils.fields import MACAddressField


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

    class Grade(models.TextChoices):
        FEM = 'fem', _('Federal Equivalent Method')
        FRM = 'frm', _('Federal Reference Method')
        LCS = 'lcs', _('Low-Cost Sensor')

    grade = None

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

    # Who is hosting this monitor?
    host = models.ForeignKey(
        'monitors.Host',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='monitors',
        help_text=_('Who is currently hosting this device.'),
    )

    # Data provider info
    data_provider = models.CharField(max_length=100, blank=True)
    data_provider_url = models.URLField(max_length=100, blank=True)

    # Where is this sensor setup?
    position = models.PointField(null=True, db_index=True)
    county = models.CharField(max_length=20, blank=True, choices=COUNTIES)
    location = models.CharField(max_length=10, choices=LOCATION)

    notes = models.TextField(blank=True, help_text="Notes for internal use.")

    health = models.OneToOneField('qaqc.HealthCheck',
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    # Entries - Legacy
    latest = models.ForeignKey('monitors.Entry', blank=True, null=True, related_name='latest_for', on_delete=models.SET_NULL)
    default_sensor = models.CharField(max_length=50, default='', blank=True)

    objects = MonitorManager()

    class Meta:
        base_manager_name = 'objects'
        ordering = ('name',)

    def __str__(self):
        return self.name

    @classmethod
    def subclasses(cls):
        return cls.objects.get_queryset()._get_subclasses_recurse(cls)

    @classproperty
    def monitor_type(cls):
        return cls._meta.model_name

    @classproperty
    def entry_types(self):
        return list(self.ENTRY_CONFIG.keys())

    @classproperty
    def alertable_entry_types(cls):
        return {
            model: config['alerts']
            for model, config in cls.ENTRY_CONFIG.items()
            if 'alerts' in config
        }

    @classproperty
    def expected_hourly_entries(self, entry_model=None) -> int:
        interval = pd.to_timedelta(self.EXPECTED_INTERVAL)
        if not interval or interval.total_seconds() == 0:
            return 0
        return math.floor(3600 / interval.total_seconds())

    @classmethod
    def get_subclasses(cls):
        subclasses = set()

        def recurse(subcls):
            for sc in subcls.__subclasses__():
                # Skip abstract models
                if not getattr(getattr(sc, '_meta', None), 'abstract', False):
                    subclasses.add(sc)
                recurse(sc)

        recurse(cls)
        return list(sorted(subclasses, key=lambda c: c.__name__))

    @property
    def slug(self):
        return slugify(self.name)

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
    def regions(self):
        """
        Returns a queryset of all regions that contain this monitor's location.
        """
        from camp.apps.regions.models import Region
        if not self.position:
            return Region.objects.none()

        return Region.objects.intersects(self.position)

    @property
    def is_regulatory(self):
        return self.grade in {self.Grade.FEM, self.Grade.FRM}

    @cached_property
    def is_active(self):
        now = timezone.now()
        cutoff = now - timedelta(seconds=self.LAST_ACTIVE_LIMIT)

        # If annotation is missing or None, fall back to query
        timestamp = getattr(self, 'last_entry_timestamp', None)
        if timestamp is None:
            timestamp = (self.latest_entries
                .order_by('-timestamp')
                .values_list('timestamp', flat=True)
                .first()
            )

        return timestamp is not None and timestamp >= cutoff

    @cached_property
    def health_grade(self):
        if self.health_id:
            return self.health.grade

    @classmethod
    def get_default_stage(cls, EntryModel):
        return cls.ENTRY_CONFIG.get(EntryModel, {}).get('default_stage', EntryModel.Stage.RAW)

    @classmethod
    def get_initial_stage(cls, EntryModel):
        '''
        Returns the first allowed stage for this entry type on this monitor.
        Used when creating new raw entries.

        Falls back to 'raw' if not explicitly configured.
        '''
        for stage in cls.ENTRY_CONFIG.get(EntryModel, {}).get('allowed_stages'):
            return stage
        return EntryModel.Stage.RAW

    @classmethod
    def get_default_calibration(cls, EntryModel):
        return get_default_calibration(cls, EntryModel)

    def get_device(self):
        return self.device or self.DEVICE or self._meta.verbose_name

    def get_absolute_url(self):
        return f'/monitor/{self.pk}'

    def get_resolved_entries(self, start_time=None, end_time=None, entry_types=None):
        """
        Return the resolved entry data for this monitor.

        - One column per entry type
        - Uses monitor default stage/calibration
        - No sensor or processor branching
        - Intended for API responses, analytics, and training
        """
        from camp.apps.entries.timelines import ResolvedEntryTimeline
        df = ResolvedEntryTimeline(
            monitor=self,
            start_time=start_time,
            end_time=end_time,
            entry_types=entry_types,
        ).to_dataframe()
        return df

    def get_expanded_entries(self, start_time=None, end_time=None, entry_types=None):
        """
        Return the full entry dataset for this monitor.

        - Includes all stages, processors, and sensors
        - Column names encode metadata
        - Intended for export, QA, and debugging
        """
        from camp.apps.entries.timelines import ExpandedEntryTimeline
        df = ExpandedEntryTimeline(
            monitor=self,
            start_time=start_time,
            end_time=end_time,
            entry_types=entry_types,
        ).to_dataframe()
        return df

    def is_processable(self, obj_or_model) -> bool:
        """
        Check whether this monitor can process either:
          - a model class, or
          - a specific entry instance.
        """
        from camp.apps.entries.models import BaseEntry

        entry_model = obj_or_model
        if isinstance(obj_or_model, BaseEntry):
            entry_model = type(obj_or_model)

        processors = (
            self.ENTRY_CONFIG
            .get(entry_model, {})
            .get('processors', {})
        )

        if isinstance(obj_or_model, BaseEntry):
            return bool(processors.get(obj_or_model.stage))
        return bool(processors)

    def initialize_entry(self, EntryModel, **kwargs):
        defaults = {
            'monitor': self,
            'position': self.position,
            'location': self.location,
            'stage': self.get_initial_stage(EntryModel)
        }
        defaults.update(**kwargs)
        return EntryModel(**defaults)

    def create_entry(self, EntryModel, save: bool = True, **data):
        entry = self.initialize_entry(EntryModel)

        for key, value in data.items():
            setattr(entry, key, value)

        if entry.validation_check():
            if save:
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

    def process_entry_ng(self, entry, cutoff_stage=None):
        config = self.ENTRY_CONFIG.get(entry.__class__, {})
        processors = config.get('processors', {}).get(entry.stage, [])

        processed_entries = []
        for processor in processors:
            if cutoff_stage and processor.next_stage == cutoff_stage:
                continue

            if (result := processor(entry).run()):
                self.update_latest_entry(result)
                processed_entries.append(result)

        return processed_entries

    def process_entry_pipeline(self, entry, cutoff_stage=None):
        '''
        Recursively processes an entry through its pipeline stages, as defined in ENTRY_CONFIG.

        Args:
            entry: The BaseEntry instance to process.
            cutoff_stage: Optional. If provided, processing will stop before this stage.

        Returns:
            List of all new entries created during processing.
        '''
        processed = []

        for result in self.process_entry_ng(entry, cutoff_stage):
            processed.append(result)
            processed.extend(self.process_entry_pipeline(result, cutoff_stage))

        return processed

    def update_latest_entry(self, entry):
        allowed_stages = (
            self.get_default_stage(entry.__class__),
            entry.Stage.CALIBRATED
        )
        if entry.stage not in allowed_stages:
            return

        # Skip if not the default calibration
        if entry.stage == entry.Stage.CALIBRATED:
            if entry.processor != self.get_default_calibration(entry.__class__):
                return

        lookup = {
            'monitor_id': self.pk,
            'entry_type': entry.entry_type,
            'processor': entry.processor,
            'stage': entry.stage,
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
                'stage': latest.entry.stage,
                'processor': latest.entry.processor,
            })
            data[latest.entry_type] = payload

        return data

    @classmethod
    def supports_health_checks(cls):
        from camp.apps.entries.models import PM25
        config = cls.ENTRY_CONFIG.get(PM25)
        if not config:
            return False

        sensors = config.get('sensors', [])
        return len(sensors) >= 2


    def run_health_check(self, hour):
        """
        Convenience method to run a HealthCheck for this monitor at a given hour.

        Args:
            hour (datetime): The start of the hour to evaluate

        Returns:
            HealthCheck instance (created or updated)
        """
        return HealthCheck.objects.evaluate(monitor=self, hour=hour)

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

    def get_entry_migration_status(self, min_date=None) -> str:
        # Normalize min_date to aware datetime if provided
        if min_date:
            if isinstance(min_date, date) and not isinstance(min_date, datetime):
                min_date = datetime.combine(min_date, datetime.min.time())
            min_date = timezone.make_aware(min_date)

        legacy_qs = self.entries.all()

        # No legacy data at all
        if not legacy_qs.exists():
            return 'ok'

        # No legacy data in the requested window → nothing to migrate
        if min_date and not legacy_qs.filter(timestamp__gte=min_date).exists():
            return 'ok'

        # First legacy timestamp in the window
        legacy_ts = (
            legacy_qs.filter(timestamp__gte=min_date).earliest('timestamp').timestamp
            if min_date
            else legacy_qs.earliest('timestamp').timestamp
        )

        pm25_qs = self.pm25_entries.all()

        # No PM25 data at all
        if not pm25_qs.exists():
            return 'needs_full_migration'

        pm25_ts = pm25_qs.earliest('timestamp').timestamp

        # PM25 starts after legacy in the window
        if pm25_ts > legacy_ts:
            return 'needs_backfill'

        return 'ok'



class LCSMixin(Monitor):
    sensor_id = models.IntegerField(unique=True)
    hardware_id = MACAddressField(blank=True, null=True)

    grade = Monitor.Grade.LCS

    class Meta:
        abstract = True

    def get_related_monitors_by_hardware(self, include_self: bool = False):
        """
        Return all monitors of the same class with the same hardware ID.
        """
        if not self.hardware_id:
            return self.__class__.objects.none()

        queryset = self.__class__.objects.filter(hardware_id=self.hardware_id)
        if not include_self and self.pk:
            queryset = queryset.exclude(pk=self.pk)
        return queryset

    def get_related_monitors_by_name(self, include_self: bool = False):
        """
        Return all monitors of the same class with the same hardware ID.
        """
        queryset = self.__class__.objects.filter(name__iexact=self.name)
        if not include_self and self.pk:
            queryset = queryset.exclude(pk=self.pk)
        return queryset


class Host(TimeStampedModel):
    name = models.CharField(max_length=200, help_text=_('Contact or organization name.'))
    email = models.EmailField(blank=True)
    phone = PhoneNumberField(blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.name


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
