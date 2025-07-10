from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from django_smalluuid.models import SmallUUIDField, uuid_default
from geopy.distance import distance as geopy_distance
from model_utils.models import TimeStampedModel

from camp.apps.calibrations import trainers
from camp.apps.calibrations.linreg import LinearRegressions
from camp.apps.calibrations.querysets import CalibratorQuerySet, CalibrationPairQuerySet, CalibrationQuerySet
from camp.apps.calibrations.utils import calibration_model_upload_to
from camp.apps.entries.fields import EntryTypeField
from camp.apps.entries.models import BaseEntry
from camp.apps.entries.utils import get_entry_model_by_name
from camp.apps.monitors.fields import MonitorTypeField
from camp.apps.monitors.validators import validate_formula


class DefaultCalibration(models.Model):
    """
    Stores the default calibration processor to use for a given monitor type and entry type.

    - `monitor_type` is a string identifier corresponding to a monitor model class (e.g., 'purpleair').
    - `entry_type` is a string identifier corresponding to an entry model class (e.g., 'pm25').
    - `calibration` is the name of the calibration processor class to apply for calibrated entries, or blank for raw.

    Used to determine which calibration processor should be the displayed default for real-time entries on the map.
    """

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    monitor_type = MonitorTypeField()
    entry_type = EntryTypeField()
    calibration = models.CharField(max_length=50, blank=True, default='')

    class Meta:
        unique_together = ('monitor_type', 'entry_type')

    def __str__(self):
        return f'{self.monitor_type} → {self.entry_type} = {self.calibration}'

    @property
    def entry_model(self):
        return EntryTypeField.get_model_map().get(self.entry_type)

    @property
    def monitor_model(self):
        return MonitorTypeField.get_model_map().get(self.monitor_type)

    @property
    def allowed_processors(self):
        target_stages = set([
            self.monitor_model.get_default_stage(self.entry_model),
            BaseEntry.Stage.CALIBRATED,
        ])

        processors = set()
        config = self.monitor_model.ENTRY_CONFIG.get(self.entry_model, {})
        for stage_processors in config.get('processors', {}).values():
            for processor in stage_processors:
                if processor.next_stage in target_stages:
                    processors.add(processor)
        return sorted(processors, key=lambda p: p.name)


class CalibrationPair(TimeStampedModel):
    """
    Defines a colocated reference + colocated monitor pair for generating calibrations.
    """

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    reference = models.ForeignKey(
        'monitors.Monitor',
        on_delete=models.CASCADE,
        related_name='reference_pairs'
    )
    colocated = models.ForeignKey(
        'monitors.Monitor',
        on_delete=models.CASCADE,
        related_name='colocated_pairs'
    )

    entry_type = EntryTypeField()

    is_enabled = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default='')

    objects = CalibrationPairQuerySet.as_manager()

    def __str__(self):
        return f'{self.colocated} → {self.reference} ({self.entry_type})'

    @property
    def entry_model(self):
        return get_entry_model_by_name(self.entry_type)

    @property
    def reference_stage(self):
        return self.reference.get_default_stage(self.entry_model)

    @property
    def colocated_stage(self):
        return self.colocated.get_default_stage(self.entry_model)

    def get_distance(self):
        return geopy_distance(
            (self.reference.position.y, self.reference.position.x),
            (self.colocated.position.y, self.colocated.position.x),
        )

    def get_current_calibration(self, trainer_name):
        return (self.calibrations
            .filter(trainer=trainer_name)
            .order_by('-end_time')
            .first()
        )

    def get_trainers(self):
        return trainers.get_for_entry_type(self.entry_type)

    def train(self, trainer, end_time=None):
        if isinstance(trainer, str):
            trainer = trainers[trainer]

        if trainer not in self.get_trainers():
            raise ValueError(f'Trainer {trainer} is not valid for this CalibrationPair ({self})')

        return trainer(self, end_time=end_time).run()



class Calibration(TimeStampedModel):
    """
    A saved calibration model derived from a CalibrationPair.
    """

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    pair = models.ForeignKey(
        CalibrationPair,
        on_delete=models.CASCADE,
        related_name='calibrations'
    )

    entry_type = EntryTypeField()

    trainer = models.CharField(
        max_length=255,
        help_text="The trainer class used to generate this calibration."
    )

    # Model coefficients or formulas
    formula = models.TextField(blank=True, null=True, help_text="Formula string, if model can be expressed this way (e.g., for linear regression).")
    intercept = models.FloatField(blank=True, null=True)

    # File for serialized ML model (e.g., .bin, .pt)
    model_file = models.FileField(
        upload_to=calibration_model_upload_to,
        blank=True,
        null=True,
        help_text='Trained model file (.bin, .pt, etc.) if not using a simple formula.'
    )


    # Training data window
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)

    # Metrics
    r2 = models.FloatField(blank=True, null=True)
    rmse = models.FloatField(blank=True, null=True)
    mae = models.FloatField(blank=True, null=True)

    # Which features were used
    features = ArrayField(models.CharField(max_length=50), default=list)

    metadata = models.JSONField(default=dict, blank=True)

    objects = CalibrationQuerySet.as_manager()

    def __str__(self):
        return f'{self.entry_type} {self.trainer} ({self.created.date()})'



## ========== LEGACY ========== ##

class Calibrator(TimeStampedModel):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    # TODO: What if this has gone inactive?
    reference = models.ForeignKey('monitors.Monitor',
        related_name='reference_calibrator',
        on_delete=models.CASCADE
    )

    # TODO: What if this has gone inactive?
    colocated = models.ForeignKey('monitors.Monitor',
        related_name='colocated_calibrator',
        on_delete=models.CASCADE
    )

    is_enabled = models.BooleanField(default=False)

    calibration = models.OneToOneField('calibrations.AutoCalibration',
        blank=True, null=True, related_name='calibrator_current',
        on_delete=models.SET_NULL)

    objects = CalibratorQuerySet.as_manager()

    def get_distance(self):
        return geopy_distance(
            (self.reference.position.y, self.reference.position.x),
            (self.colocated.position.y, self.colocated.position.x),
        )

    def calibrate(self, end_date=None):
        if end_date is None:
            end_date = timezone.now()

        linreg = LinearRegressions(calibrator=self, end_date=end_date)
        linreg.process_regressions()

        print('----------')
        print(self.reference.name, '/', self.colocated.name)
        for reg in linreg.regressions:
            print(', '.join(map(str, [reg.r2, reg.coefs, reg.intercept, (reg.end_date - reg.start_date).days])))

        results = linreg.best_fit()

        if results is not None:
            self.calibration = self.calibrations.create(
                start_date=results.start_date,
                end_date=results.end_date,
                formula=results.formula,
                r2=results.r2,
            )
            self.save()
            return True
        return False


class AutoCalibration(TimeStampedModel):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    calibrator = models.ForeignKey('calibrations.Calibrator',
        related_name='calibrations',
        on_delete=models.CASCADE
    )

    formula = models.CharField(max_length=255, blank=True,
        default='', validators=[validate_formula])

    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    r2 = models.FloatField()

    class Meta:
        ordering = ['-end_date', '-r2']

    def __str__(self):
        return self.formula

    @property
    def days(self):
        return (self.end_date - self.start_date).days
