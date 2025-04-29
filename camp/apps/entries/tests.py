# camp/apps/entries/tests.py

from django.test import TestCase
from camp.apps.entries.fetchers import EntryDataFetcher
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.entries.models import PM25, Temperature


class EntryDataFetcherTest(TestCase):
    def setUp(self):
        self.monitor = PurpleAir.objects.create(
            name='Test Monitor',
            position='POINT(0 0)',
            county='Fresno',
            purple_id=11235,
        )

    def test_to_dataframe_returns_none_if_no_data(self):
        fetcher = EntryDataFetcher(monitor=self.monitor, entry_types=[PM25])
        df = fetcher.to_dataframe()

        assert df is None

    def test_to_dataframe_merges_dataframes_correctly(self):
        PM25.objects.create(monitor=self.monitor, timestamp='2025-01-01T00:00:00Z', value=10)
        PM25.objects.create(monitor=self.monitor, timestamp='2025-01-01T01:00:00Z', value=12)
        Temperature.objects.create(monitor=self.monitor, timestamp='2025-01-01T00:00:00Z', value=65)
        Temperature.objects.create(monitor=self.monitor, timestamp='2025-01-01T02:00:00Z', value=66)

        fetcher = EntryDataFetcher(monitor=self.monitor, entry_types=[PM25, Temperature])
        df = fetcher.to_dataframe()

        assert df is not None
        assert set(df.columns) == {'timestamp', 'pm25', 'temperature'}
        assert len(df) == 3

        row = df[df['timestamp'] == '2025-01-01T00:00:00Z'].iloc[0]
        assert row['pm25'] == 10
        assert row['temperature'] == 65

    def test_to_dataframe_uses_custom_entry_types(self):
        PM25.objects.create(monitor=self.monitor, timestamp='2025-01-01T00:00:00Z', value=10)
        Temperature.objects.create(monitor=self.monitor, timestamp='2025-01-01T00:00:00Z', value=65)

        fetcher = EntryDataFetcher(monitor=self.monitor, entry_types=[PM25])
        df = fetcher.to_dataframe()

        assert 'pm25' in df.columns
        assert 'temperature' not in df.columns

    def test_to_dataframe_infers_entry_types_if_none(self):
        PM25.objects.create(monitor=self.monitor, timestamp='2025-01-01T00:00:00Z', value=10)

        fetcher = EntryDataFetcher(monitor=self.monitor)  # entry_types=None
        df = fetcher.to_dataframe()

        assert 'pm25' in df.columns
