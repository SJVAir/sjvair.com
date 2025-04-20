from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property

from django_smalluuid.models import SmallUUIDField, uuid_default
from geopy.distance import distance as geopy_distance
from model_utils.models import TimeStampedModel

from camp.apps.entries.fields import EntryTypeField
from camp.apps.monitors.fields import MonitorTypeField
from camp.apps.monitors.validators import validate_formula
from camp.apps.calibrations.linreg import LinearRegressions
from camp.apps.calibrations.querysets import CalibratorQuerySet


class DefaultCalibration(models.Model):
    '''
    Stores the default calibration to use for a given monitor type and entry type.

    - `monitor_type` is a string identifier corresponding to a monitor model class (e.g. 'purpleair').
    - `entry_type` is a string identifier corresponding to an entry model class (e.g. 'pm25').
    - `calibration` is the name of the calibration method (e.g. 'linear', 'epa-adjusted') or blank for raw.

    Used in calibration logic to determine which calibration should be applied
    to real-time entries based on monitor type and pollutant.
    '''

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
    
    def clean(self):
        '''
        Validates that the selected calibration is allowed for the given monitor type and entry type.

        Raises:
            ValidationError: If the selected calibration is not listed in the monitor model's
            ENTRY_CONFIG for the given entry model.
        '''
        super().clean()

        if not self.monitor_model or not self.entry_model:
            raise ValidationError('Invalid monitor or entry type.')

        config = self.monitor_model.ENTRY_CONFIG.get(self.entry_model)
        if not config:
            raise ValidationError(
                f'{self.monitor_type} does not support entry type {self.entry_type}.'
            )

        calibrations = [c.name for c in config.get('calibrations', [])]
        if self.calibration and self.calibration not in calibrations:
            raise ValidationError(
                f'"{self.calibration}" is not a valid calibration for {self.monitor_type} - {self.entry_type}. '
                f'Valid options: {calibrations or ["(none)"]}'
            )
    
    


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
