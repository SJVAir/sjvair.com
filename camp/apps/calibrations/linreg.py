import dataclasses
import itertools
import types

from datetime import datetime, timedelta

import pandas as pd

from django.db.models import F
from django.utils import timezone
from django.utils.functional import cached_property

from sklearn.linear_model import LinearRegression as skLinearRegression


@dataclasses.dataclass
class RegressionResults:
    reg: skLinearRegression
    df: pd.DataFrame
    r2: float
    intercept: float
    coefs: dict

    start_date: datetime
    end_date: datetime
    formula: str = None


class LinearRegressions:
    # Coefficients
    coefs_base = ['pm25']
    coefs_computed = {
    }

    # What time periods to test?
    days = [1, 7, 14, 21, 28]

    formulas = [
        (
            ['pm25'],
            lambda coefs, intercept: (
                f"((pm25) * ({coefs['pm25']})) + ({intercept})"
            )
        ),
    ]

    def __init__(self, calibrator, end_date=None):
        self.calibrator = calibrator
        self.end_date = end_date or timezone.now()

    @property
    def coefs(self):
        return [*self.coefs_base, *self.coefs_computed.keys()]

    @cached_property
    def endog_qs(self):
        start_date = self.end_date - timedelta(days=max(self.days))
        queryset = (self.calibrator.reference.entries
            .filter(
                sensor=self.calibrator.reference.default_sensor,
                timestamp__range=(start_date, self.end_date),
            )
            .annotate(endog_pm25=F('pm25'))
            .values('timestamp', 'endog_pm25')
        )
        return queryset

    @cached_property
    def exog_qs(self):
        start_date = self.end_date - timedelta(days=max(self.days))
        queryset = (self.calibrator.colocated.entries
            .filter(
                sensor=self.calibrator.colocated.default_sensor,
                timestamp__range=(start_date, self.end_date),
            )
            .annotate(**self.coefs_computed)
            .values('timestamp', *self.coefs)
        )
        return queryset

    @cached_property
    def endog_df(self):
        df = pd.DataFrame(self.endog_qs)
        if not len(df):
            return None

        df = df.set_index('timestamp')
        df = pd.to_numeric(df.endog_pm25)
        df = df.resample('H').mean()
        return df

    @cached_property
    def exog_df(self):
        df = pd.DataFrame(self.exog_qs)
        if not len(df):
            return None

        df = df.set_index('timestamp')
        df[df.columns] = df[df.columns].apply(pd.to_numeric, errors='coerce')
        df = df.resample('H').mean()
        return df

    @cached_property
    def df(self):
        if self.endog_df is None or self.exog_df is None:
            return None

        df = pd.concat([self.endog_df, self.exog_df], axis=1, join="inner")
        df = df.dropna()

        if not len(df):
            return None

        return df

    def process_regressions(self):
        self.regressions = []

        if self.df is None:
            return

        self.regressions.extend(list(filter(bool, [
            self.generate_regression(coefs, formula, days)
            for (coefs, formula), days
            in itertools.product(self.formulas, self.days)
        ])))

    def generate_regression(self, coefs, formula, days):
        # Filter the dataframe to the number of days requested.
        start_date = self.end_date - timedelta(days=days)
        df = self.df[self.df.index.searchsorted(start_date):-1]

        if not len(df):
            print('No data in the dataframe.')
            return

        endog = df['endog_pm25']
        exog = df[coefs]

        try:
            linreg = skLinearRegression()
            linreg.fit(exog, endog)
        except ValueError as err:
            # import code
            # code.interact(local=locals())
            print('Linear Regression Error:', err)
            return

        results = RegressionResults(
            reg=linreg,
            df=df,
            r2=linreg.score(exog, endog),
            intercept=linreg.intercept_,
            coefs=dict(zip(coefs, linreg.coef_)),
            start_date=start_date,
            end_date=self.end_date,
        )
        results.formula = formula(coefs=results.coefs, intercept=results.intercept)
        return results

    def best_fit(self):
        if not hasattr(self, 'regressions'):
            self.process_regressions()

        candidates = [reg for reg in self.regressions if self.is_valid(reg)]
        candidates.sort(reverse=True, key=lambda reg: reg.r2)
        return next(iter(candidates), None)

    def is_valid(self, reg):
        if self.calibrator.calibration is not None:
            timesince = (timezone.now() - self.calibrator.calibration.end_date)

            # Less than 1 week, it's gotta beat the current R2.
            if timesince < timedelta(days=7):
                return reg.r2 > self.calibrator.calibration.r2

            # Less than 1 month, 0.75 is the magic number
            elif timesince < timedelta(days=30):
                return reg.r2 > 0.75

        # No previous calibration or last calibration longer
        # than a month ago? Set a low bar of 0.5.
        return reg.r2 > 0.5

