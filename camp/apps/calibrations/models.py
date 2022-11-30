import itertools

from datetime import timedelta
from pprint import pprint

from django.db import models
from django.db.models import F
from django.utils import timezone

from django_smalluuid.models import SmallUUIDField, uuid_default
from geopy.distance import distance as geopy_distance
from model_utils.models import TimeStampedModel

from camp.apps.monitors.linreg import linear_regression
from camp.apps.monitors.validators import validate_formula


class Calibrator(TimeStampedModel):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    reference = models.ForeignKey('monitors.Monitor',
        related_name='reference_calibrator',
        on_delete=models.CASCADE
    )

    # TODO: What if this has gone inactive?
    colocated = models.ForeignKey('monitors.Monitor',
        related_name='colocated_calibrator',
        on_delete=models.CASCADE
    )

    is_active = models.BooleanField(default=False)

    calibration = models.OneToOneField('calibrations.Calibration',
        blank=True, null=True, related_name='calibrator_current',
        on_delete=models.SET_NULL)

    # manual_calibration = models.OneToOneField('calibrations.Calibration',
    #     blank=True, null=True, related_name='calibrator_current',
    #     on_delete=models.SET_NULL)

    # auto_calibration = models.OneToOneField('calibrations.Calibration',
    #     blank=True, null=True, related_name='calibrator_current',
    #     on_delete=models.SET_NULL)

    def get_distance(self):
        return geopy_distance(
            (self.reference.position.y, self.reference.position.x),
            (self.colocated.position.y, self.colocated.position.x),
        )

    def calibrate(self, end_date=None):
        # assert self.reference.is_active
        # assert self.colocated.is_active

        if end_date is None:
            end_date = timezone.now().date()

        # Set of coefficients to test and the
        # formulas for their calibrations
        formulas = [
            (
                ['particles_03-10', 'particles_10-25', 'humidity'],
                lambda results: ' + '.join([
                    f"((particles_03um - particles_10um) * {results.coefs['particles_03-10']})",
                    f"((particles_10um - particles_25um) * {results.coefs['particles_10-25']})",
                    f"(humidity * {results.coefs['humidity']})"
                    f"{results.intercept}",
                ])
            ), (
                ['particles_10-25', 'particles_25-05', 'humidity'],
                lambda results: ' + '.join([
                    f"((particles_10um - particles_25um) * {results.coefs['particles_10-25']})",
                    f"((particles_25um - particles_05um) * {results.coefs['particles_25-05']})",
                    f"(humidity * {results.coefs['humidity']})",
                    f"{results.intercept}",
                ])
            )
        ]

        results = list(filter(bool, [
            self.generate_calibration(
                coefs=coefs,
                formula=formula,
                end_date=end_date,
                days=days,
            )
            for (coefs, formula), days
            in itertools.product(formulas, [7, 14, 21, 28])
        ]))

        print(f'{self.reference.name} / {self.colocated.name} ({self.get_distance().meters} m)')
        pprint(results)
        print('\n')

        if results:
            # Sort by R2 (highest last)...
            results.sort(key=lambda i: i['r2'])

            # ...and save the calibration
            self.calibrations.create(**results[-1])
            self.calibration = self.calibrations.order_by('end_date').first()

    def generate_calibration(self, coefs, formula, end_date, days):
        start_date = end_date - timedelta(days=days)
        ref_qs = self.reference.entries.filter(timestamp__date__range=(start_date, end_date))
        col_qs = (self.colocated.entries
            .filter(
                timestamp__date__range=(start_date, end_date),
                sensor=self.colocated.default_sensor,
            )
            .annotate(**{
                'particles_03-10': F('particles_03um') - F('particles_10um'),
                'particles_10-25': F('particles_10um') - F('particles_25um'),
                'particles_25-05': F('particles_25um') - F('particles_05um'),
            })
        )

        results = linear_regression(ref_qs, col_qs, coefs)
        if results is not None:
            return {
                'start_date': start_date,
                'end_date': end_date,
                'r2': results.r2,
                'formula': formula(results),
            }


class Calibration(TimeStampedModel):
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

    start_date = models.DateTimeField()
    end_date = models.DateTimeField(db_index=True)

    r2 = models.FloatField()
    formula = models.CharField(max_length=255, blank=True,
        default='', validators=[validate_formula])

    def __str__(self):
        return self.formula

    @property
    def days(self):
        return (self.end_date - self.start_date).days
