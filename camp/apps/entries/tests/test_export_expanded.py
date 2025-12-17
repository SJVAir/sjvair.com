import pandas as pd

from django.test import TestCase
from django.utils.timezone import make_aware
from datetime import datetime, timedelta

from camp.apps.entries.timelines import ExpandedEntryTimeline
from camp.apps.entries.models import PM25, Humidity, Temperature
from camp.apps.monitors.purpleair.models import PurpleAir


class ExpandedEntryTimelineTests(TestCase):
    fixtures = ['purple-air.yaml']

    def _create_entry(self, entry_model, timestamp, value, **kwargs):
        kwargs.setdefault('stage', self.monitor.get_default_stage(entry_model))
        return entry_model.objects.create(
            monitor=self.monitor,
            timestamp=timestamp,
            value=value,
            **kwargs
        )

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.timestamp = make_aware(datetime(2025, 1, 1, 12, 0))

        # PM2.5 - a
        self._create_entry(PM25, timestamp=self.timestamp, value=10, sensor='a', stage=PM25.Stage.RAW)
        self._create_entry(PM25, timestamp=self.timestamp, value=9.5, sensor='a', stage=PM25.Stage.CLEANED)
        self._create_entry(PM25, timestamp=self.timestamp, value=8.7, sensor='a', stage=PM25.Stage.CALIBRATED, processor='linear')

        # PM2.5 - b
        self._create_entry(PM25, timestamp=self.timestamp, value=12, sensor='b', stage=PM25.Stage.RAW)
        self._create_entry(PM25, timestamp=self.timestamp, value=11.5, sensor='b', stage=PM25.Stage.CLEANED)
        self._create_entry(PM25, timestamp=self.timestamp, value=10.7, sensor='b', stage=PM25.Stage.CALIBRATED, processor='linear')

        # Humidity
        self._create_entry(Humidity, timestamp=self.timestamp, value=54.3, stage=Humidity.Stage.RAW)
        self._create_entry(Humidity, timestamp=self.timestamp, value=52.6, stage=Humidity.Stage.CALIBRATED, processor='AirGradientHumidity')

        # Temperature
        self._create_entry(Temperature, timestamp=self.timestamp, value=87, stage=Temperature.Stage.RAW)
        self._create_entry(Temperature, timestamp=self.timestamp, value=86, stage=Temperature.Stage.CALIBRATED, processor='AirGradientTemperature')

    def test_to_dataframe(self):
        start_time = datetime.combine(self.timestamp.date(), datetime.min.time())
        end_time = datetime.combine(self.timestamp.date() + timedelta(days=1), datetime.min.time())
        df = ExpandedEntryTimeline(
            monitor=self.monitor,
            start_time=start_time,
            end_time=end_time,
            entry_types=[PM25, Humidity, Temperature],
        ).to_dataframe()

        assert len(df) == 1
        assert 'timestamp' == df.index.name
        assert 'timestamp_local' in df.columns
        assert 'pm25_raw_a' in df.columns
        assert 'pm25_cleaned_a' in df.columns
        assert 'pm25_linear_a' in df.columns
        assert 'humidity_raw' in df.columns

        row = df.iloc[0]
        assert row['pm25_raw_a'] == 10.0
        assert row['pm25_cleaned_a'] == 9.5
        assert row['pm25_linear_a'] == 8.7
        assert row['humidity_raw'] == 54.3

    def test_includes_b_sensor_columns(self):
        df = ExpandedEntryTimeline(
            monitor=self.monitor,
            start_time=self.timestamp - timedelta(hours=1),
            end_time=self.timestamp + timedelta(hours=1),
            entry_types=[PM25],
        ).to_dataframe()

        assert 'pm25_raw_b' in df.columns
        assert 'pm25_cleaned_b' in df.columns
        assert 'pm25_linear_b' in df.columns

        row = df.iloc[0]
        assert row['pm25_raw_b'] == 12.0
        assert row['pm25_cleaned_b'] == 11.5
        assert row['pm25_linear_b'] == 10.7

    def test_column_key_uses_processor_only_for_calibrated(self):
        df = ExpandedEntryTimeline(
            monitor=self.monitor,
            start_time=self.timestamp - timedelta(hours=1),
            end_time=self.timestamp + timedelta(hours=1),
            entry_types=[Humidity],
        ).to_dataframe()

        assert 'humidity_raw' in df.columns
        assert 'humidity_AirGradientHumidity' in df.columns

    def test_time_filtering_start_inclusive_end_exclusive(self):
        t0 = self.timestamp
        t1 = self.timestamp + timedelta(hours=1)

        self._create_entry(PM25, timestamp=t1, value=99, sensor='a', stage=PM25.Stage.RAW)

        df = ExpandedEntryTimeline(
            monitor=self.monitor,
            start_time=t0,
            end_time=t1,
            entry_types=[PM25],
        ).to_dataframe()

        assert len(df) == 1
        assert df.index[0] == pd.Timestamp(t0)
        assert 'pm25_raw_a' in df.columns
        assert df.iloc[0]['pm25_raw_a'] == 10.0

    def test_entry_types_filtering(self):
        df = ExpandedEntryTimeline(
            monitor=self.monitor,
            start_time=self.timestamp - timedelta(hours=1),
            end_time=self.timestamp + timedelta(hours=1),
            entry_types=[Humidity],
        ).to_dataframe()

        assert 'humidity_raw' in df.columns
        assert not any(col.startswith('pm25_') for col in df.columns)

    def test_empty_dataset_returns_empty_df_with_datetime_index(self):
        df = ExpandedEntryTimeline(
            monitor=self.monitor,
            start_time=self.timestamp + timedelta(days=10),
            end_time=self.timestamp + timedelta(days=11),
            entry_types=[PM25],
        ).to_dataframe()

        assert isinstance(df, pd.DataFrame)
        assert df.empty


