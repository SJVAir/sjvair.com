from datetime import timedelta

from django.utils.functional import cached_property
from django.utils import timezone

import pandas as pd

class SensorAnalysisData:
    data_field = 'pm25_reported'

    def __init__(self, monitor, start_date=None, end_date=None, **kwargs):
        self.monitor = monitor
        self.end_date = end_date or timezone.now()
        self.start_date = start_date or self.end_date - timedelta(**kwargs)

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
