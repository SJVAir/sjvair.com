import itertools

from datetime import timedelta
from pprint import pprint

from django.db import models
from django.db.models import F
from django.utils import timezone

from django_smalluuid.models import SmallUUIDField, uuid_default
from geopy.distance import distance as geopy_distance
from model_utils.models import TimeStampedModel

# data modeling
import pandas as pd
from sklearn.linear_model import LinearRegression

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
                ['particles_03-10', 'particles_10-25'],
                lambda reg: ' + '.join([
                    f"((particles_03um - particles_10um) * {reg.coef_[0]})",
                    f"((particles_10um - particles_25um) * {reg.coef_[1]})",
                    f"{reg.intercept_}",
                ])
            ), (
                ['particles_03-10', 'particles_25-05'],
                lambda reg: ' + '.join([
                    f"((particles_03um - particles_10um) * {reg.coef_[0]})",
                    f"((particles_25um - particles_05um) * {reg.coef_[1]})",
                    f"{reg.intercept_}",
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
            in itertools.product(formulas, [7, 14])
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

        # Load the reference entries into a DataFrame, sampled hourly.
        ref_qs = (self.reference.entries
            .filter(timestamp__date__range=(start_date, end_date))
            .annotate(ref_pm25=F('pm25_env'))
            .values('timestamp', 'ref_pm25')
        )

        if not ref_qs.exists():
            return

        ref_df = pd.DataFrame(ref_qs).set_index('timestamp')
        ref_df = pd.to_numeric(ref_df.ref_pm25)
        # ref_df = ref_df.ref_pm25.astype('float')
        ref_df = ref_df.resample('H').mean()

        # Load the colocated entries into a DataFrame
        col_qs = (self.colocated.entries
            .filter(
                timestamp__date__range=(start_date, end_date),
                sensor='a', # Assumes PurpleAir
            )
            .annotate(col_pm25=F('pm25_env'))
            .values('timestamp', 'col_pm25', 'particles_03um',
                'particles_05um', 'particles_10um', 'particles_25um')
        )

        if not col_qs.exists():
            return

        col_df = pd.DataFrame(col_qs).set_index('timestamp')

        # Convert columns to floats
        # cols = df.columns[df.dtypes.eq('object')]
        col_df[col_df.columns] = col_df[col_df.columns].apply(pd.to_numeric, errors='coerce')

        # particle count calculations and hourly sample
        col_df['particles_03-10'] = col_df['particles_03um'] - col_df['particles_10um']
        col_df['particles_10-25'] = col_df['particles_10um'] - col_df['particles_25um']
        col_df['particles_25-05'] = col_df['particles_25um'] - col_df['particles_05um']
        col_df = col_df.resample('H').mean()

        # Merge the dataframes
        merged = pd.concat([ref_df, col_df], axis=1, join="inner")
        merged = merged.dropna()

        if not len(merged):
            return

        # Linear Regression time!
        endog = merged['ref_pm25']
        exog = merged[coefs]

        try:
            reg = LinearRegression()
            reg.fit(exog, endog)
        except ValueError as err:
            import code
            code.interact(local=locals())

        return {
            'start_date': start_date,
            'end_date': end_date,
            'r2': reg.score(exog, endog),
            'formula': formula(reg),
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
