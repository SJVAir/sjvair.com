from django.test import TestCase

import pandas as pd

from camp.apps.entries.timelines import ResolvedEntryTimeline
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.entries.models import PM25, Temperature


class ResolvedEntryTimelineTests(TestCase):
    def setUp(self):
        self.monitor = PurpleAir.objects.create(
            name='Test Monitor',
            position='POINT(0 0)',
            county='Fresno',
            sensor_id=11235,
        )

    def _create_entry(self, entry_model, timestamp, value, **kwargs):
        kwargs.setdefault('stage', self.monitor.get_default_stage(entry_model))
        return entry_model.objects.create(
            monitor=self.monitor,
            timestamp=timestamp,
            value=value,
            **kwargs
        )

    def test_to_dataframe_returns_empty_df(self):
        df = ResolvedEntryTimeline(monitor=self.monitor, entry_types=[PM25]).to_dataframe()

        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_to_dataframe_merges_dataframes_correctly(self):
        self._create_entry(PM25, timestamp='2025-01-01T00:00:00Z', value=10)
        self._create_entry(PM25, timestamp='2025-01-01T01:00:00Z', value=12)
        self._create_entry(Temperature, timestamp='2025-01-01T00:00:00Z', value=65)
        self._create_entry(Temperature, timestamp='2025-01-01T02:00:00Z', value=66)

        df = ResolvedEntryTimeline(monitor=self.monitor, entry_types=[PM25, Temperature]).to_dataframe()

        assert df is not None
        assert set(df.columns) == {'pm25', 'temperature', 'timestamp_local'}
        assert df.index.name == 'timestamp'
        assert len(df) == 3

        row = df.loc[pd.Timestamp('2025-01-01T00:00:00Z', tz='UTC')]
        assert row['pm25'] == 10
        assert row['temperature'] == 65

    def test_to_dataframe_uses_custom_entry_types(self):
        self._create_entry(PM25, timestamp='2025-01-01T00:00:00Z', value=10)
        self._create_entry(Temperature, timestamp='2025-01-01T00:00:00Z', value=65)

        df = ResolvedEntryTimeline(monitor=self.monitor, entry_types=[PM25]).to_dataframe()

        assert 'pm25' in df.columns
        assert 'temperature' not in df.columns

    def test_to_dataframe_infers_entry_types_if_none(self):
        self._create_entry(PM25, timestamp='2025-01-01T00:00:00Z', value=10)

        df = ResolvedEntryTimeline(monitor=self.monitor).to_dataframe()

        assert 'pm25' in df.columns

    def test_to_dataframe_respects_start_inclusive_end_exclusive(self):
        self._create_entry(PM25, timestamp='2025-01-01T00:00:00Z', value=1)
        self._create_entry(PM25, timestamp='2025-01-01T01:00:00Z', value=2)
        self._create_entry(PM25, timestamp='2025-01-01T02:00:00Z', value=3)

        df = ResolvedEntryTimeline(
            monitor=self.monitor,
            entry_types=[PM25],
            start_time='2025-01-01T01:00:00Z',
            end_time='2025-01-01T02:00:00Z',
        ).to_dataframe()

        assert list(df.index) == [pd.Timestamp('2025-01-01T01:00:00Z')]
        assert df.iloc[0]['pm25'] == 2

    def test_to_dataframe_filters_to_default_stage(self):
        default_stage = self.monitor.get_default_stage(PM25)
        other_stage = PM25.Stage.RAW if default_stage != PM25.Stage.RAW else PM25.Stage.CLEANED
        self._create_entry(PM25, timestamp='2025-01-01T00:00:00Z', value=10, stage=default_stage)
        self._create_entry(PM25, timestamp='2025-01-01T01:00:00Z', value=999, stage=other_stage)

        df = ResolvedEntryTimeline(monitor=self.monitor, entry_types=[PM25]).to_dataframe()

        # Only the default stage row should be present
        assert len(df) == 1
        assert df.iloc[0]['pm25'] == 10

    def test_to_dataframe_contract(self):
        self._create_entry(PM25, timestamp='2025-01-01T01:00:00Z', value=12)
        self._create_entry(PM25, timestamp='2025-01-01T00:00:00Z', value=10)

        df = ResolvedEntryTimeline(monitor=self.monitor, entry_types=[PM25]).to_dataframe()

        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.name == 'timestamp'
        assert str(df.index.tz) in ('UTC', 'UTC+00:00')  # depends on pandas
        assert list(df.index) == sorted(df.index)

        # timestamp_local should be derived from index and have same length
        assert 'timestamp_local' in df.columns
        assert len(df['timestamp_local']) == len(df.index)
