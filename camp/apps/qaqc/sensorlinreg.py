import dataclasses
import itertools
import types

from datetime import datetime, timedelta

import pandas as pd

from django.db.models import F
from django.utils import timezone
from django.utils.functional import cached_property

from sklearn.linear_model import LinearRegression
from sklearn.metrics import explained_variance_score

from .models import SensorAnalysis


class SensorLinearRegression:
    days = 7
    data_field = 'pm25_reported'

    def __init__(self, monitor, end_date=None):
        self.monitor = monitor
        self.end_date = end_date or timezone.now()
        self.start_date = self.end_date - timedelta(days=self.days)

    @cached_property
    def queryset(self):
        queryset = (self.monitor.entries
            .filter(timestamp__range=(self.start_date, self.end_date))
            .values('timestamp', 'sensor', self.data_field)
        )

        return queryset

    @cached_property
    def df(self):
        df = pd.DataFrame(self.queryset)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df[self.data_field] = pd.to_numeric(df[self.data_field])

        return df

    @cached_property
    def endog(self):
        return self.__get_sensor_group(self.monitor.SENSORS[1])

    @cached_property
    def exog(self):
        return self.__get_sensor_group(self.monitor.SENSORS[0])

    def generate_regression(self):
        if self.endog is None or self.exog is None:
            return None

        r2_weight = 1
        v_weight = 1

        try:
            linreg = LinearRegression()
            linreg.fit(self.exog, self.endog)
            r2=linreg.score(self.exog, self.endog)

            variance = explained_variance_score(
                self.exog['pm25_reported'].values,
                self.endog['pm25_reported'].values
            )
        except ValueError as err:
            print('QAQC Linear Regression Error:', err)
            return None

        return SensorAnalysis(
            monitor=self.monitor,
            r2=r2,
            variance=variance,
            grade=((r2 * r2_weight) + (variance * v_weight)) / (r2_weight + v_weight),
            intercept=linreg.intercept_,
            coef=linreg.coef_[0][0],
            start_date=self.start_date,
            end_date=self.end_date,
        )
    
    def __get_sensor_group(self, sensor):
        groups = self.df.groupby('sensor')

        try:
            grp = groups.get_group(sensor).loc[:, ['timestamp', self.data_field]]
        except KeyError:
            return None

        if not len(grp):
            return None

        grp = grp.set_index('timestamp')
        grp = grp.resample('H').mean()
        grp = grp.dropna()

        return grp

