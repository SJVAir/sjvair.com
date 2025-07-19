from django.test import TestCase
from datetime import datetime

from camp.apps.entries.utils import to_multi_entry_wide_dataframe
from camp.apps.entries.models import PM25, Humidity, Temperature
from camp.apps.monitors.purpleair.models import PurpleAir


class ToMultiEntryWideDataFrameTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(purple_id=8892)
        self.timestamp = datetime(2025, 1, 1, 12, 0)

        # PM2.5 - a
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.timestamp,
            sensor='a', stage=PM25.Stage.RAW, value=10.0
        )
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.timestamp,
            sensor='a', stage=PM25.Stage.CLEANED, value=9.5
        )
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.timestamp,
            sensor='a', stage=PM25.Stage.CALIBRATED, processor='linear', value=8.7
        )

        # PM2.5 - b
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.timestamp,
            sensor='b', stage=PM25.Stage.RAW, value=12.0
        )
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.timestamp,
            sensor='b', stage=PM25.Stage.CLEANED, value=11.5
        )
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.timestamp,
            sensor='b', stage=PM25.Stage.CALIBRATED, processor='linear', value=10.7
        )

        # Humidity
        Humidity.objects.create(
            monitor=self.monitor, timestamp=self.timestamp,
            stage=Humidity.Stage.RAW, value=54.3
        )
        Humidity.objects.create(
            monitor=self.monitor, timestamp=self.timestamp,
            stage=Humidity.Stage.CALIBRATED, processor='AirGradientHumidity', value=52.6
        )

        # Temperature
        Temperature.objects.create(
            monitor=self.monitor, timestamp=self.timestamp,
            stage=Humidity.Stage.RAW, value=87,
        )
        Temperature.objects.create(
            monitor=self.monitor, timestamp=self.timestamp,
            stage=Humidity.Stage.CALIBRATED, processor='AirGradientHumidity', value=86,
        )

    def test_to_multi_entry_wide_dataframe_returns_expected_columns(self):
        df = self.monitor.get_entry_data_table([PM25, Humidity, Temperature])

        assert len(df) == 1
        assert 'timestamp' in df.columns
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
