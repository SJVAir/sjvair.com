import dataclasses
import itertools
import types

from datetime import datetime, timedelta

import pandas as pd

from django.db.models import F
from django.utils import timezone
from django.utils.functional import cached_property

from sklearn.linear_model import LinearRegression as skLinearRegression

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

        try:
            linreg = skLinearRegression()
            linreg.fit(self.exog, self.endog)
        except ValueError as err:
            print('QAQC Linear Regression Error:', err)
            return None

        results = SensorAnalysis(
            monitor=self.monitor,
            r2=linreg.score(self.exog, self.endog),
            intercept=linreg.intercept_,
            coef=linreg.coef_[0][0],
            start_date=self.start_date,
            end_date=self.end_date,
        )

        if results.r2 < 0.9:
            print(f'{self.monitor.name} is possibly bad: {results.r2}')

        return results
    
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

