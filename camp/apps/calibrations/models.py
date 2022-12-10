import itertools

from datetime import timedelta

from django.db import models
from django.db.models import F
from django.utils import timezone
from django.utils.functional import lazy

from django_smalluuid.models import SmallUUIDField, uuid_default
from geopy.distance import distance as geopy_distance
from model_utils.models import TimeStampedModel

from camp.apps.monitors.models import Monitor
from camp.apps.monitors.validators import validate_formula
from camp.apps.calibrations.linreg import linear_regression, RegressionResults
from camp.apps.calibrations.querysets import CalibratorQuerySet


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
        # assert self.reference.is_enabled
        # assert self.colocated.is_enabled

        if end_date is None:
            end_date = timezone.now()

        # Set of coefficients to test and the
        # formulas for their calibrations
        formulas = [
            (
                ['particles_05-10', 'particles_10-25', 'humidity'],
                lambda results: ' + '.join([
                    f"((particles_05um - particles_10um) * ({results.coefs['particles_05-10']}))",
                    f"((particles_10um - particles_25um) * ({results.coefs['particles_10-25']}))",
                    f"(humidity * ({results.coefs['humidity']}))",
                    f"({results.intercept})",
                ])
            ), (
                ['particles_10-25', 'particles_25-05', 'humidity'],
                lambda results: ' + '.join([
                    f"((particles_10um - particles_25um) * ({results.coefs['particles_10-25']}))",
                    f"((particles_25um - particles_05um) * ({results.coefs['particles_25-05']}))",
                    f"(humidity * ({results.coefs['humidity']}))",
                    f"({results.intercept})",
                ])
            )
        ]

        # Generate the full set of calibrations...
        results = [
                self.generate_calibration(
                    coefs=coefs,
                    formula=formula,
                    end_date=end_date,
                    days=days,
                )
                for (coefs, formula), days
                in itertools.product(formulas, [7, 14, 21, 28])
            ]

        # ...and filter out any bad results
        results = [res for res in results if
            # 1. Must have completed successfully.
            res is not None
            # 2. Must be sufficiently confident (R2>0.8).
            and res.r2 > 0.8
            # 3. Must be no negative coefficients.
            and not any([coef < 0 for coef in res.coefs.values()])
        ]

        # Sort by R2 (highest last).
        results.sort(key=lambda res: res.r2)

        try:
            self.calibration = self.calibrations.create(
                start_date=results[-1].start_date,
                end_date=results[-1].end_date,
                formula=results[-1].formula,
                r2=results[-1].r2,
            )
            self.save()
            return True
        except IndexError:
            return False

    def generate_calibration(self, coefs, formula, end_date, days):
        start_date = end_date - timedelta(days=days)
        ref_qs = self.reference.entries.filter(
            sensor=self.reference.default_sensor,
            timestamp__date__range=(start_date, end_date),
        )

        col_qs = (self.colocated.entries
            .filter(
                sensor=self.colocated.default_sensor,
                timestamp__date__range=(start_date, end_date),
            )
            .annotate(**{
                'particles_05-10': F('particles_05um') - F('particles_10um'),
                'particles_10-25': F('particles_10um') - F('particles_25um'),
                'particles_25-05': F('particles_25um') - F('particles_05um'),
            })
        )

        results = linear_regression(ref_qs, col_qs, coefs)
        if results is not None:

            print('-' * 25)
            print(self.reference.name)
            print('coefs', results.coefs)
            print('days', days)
            print('ref_qs', ref_qs.count())
            print('col_qs', col_qs.count())
            print('R2', results.r2)
            print('-' * 25)

            # Tack on some other data we may need later
            results.start_date = start_date
            results.end_date = end_date
            results.formula = formula(results)
            return results


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
