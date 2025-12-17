from typing import List, Optional, Type

from django.conf import settings

import pandas as pd

from camp.apps.entries.models import BaseEntry


class EntryTimeline:
    """
    Fetches and assembles multiple entry types into a wide-format DataFrame,
    aligned by timestamp, using each entry's default stage and sensor.

    If entry_types is None, all known Entry types will be fetched.
    """

    def __init__(
        self,
        monitor,
        start_time=None,
        end_time=None,
        entry_types: Optional[List[Type[BaseEntry]]] = None,
    ):
        self.monitor = monitor
        self.entry_types = entry_types or monitor.entry_types
        self.start_time = start_time
        self.end_time = end_time

    def get_queryset(self, entry_model):
        queryset = entry_model.objects.filter(
            monitor_id=self.monitor.pk,
        )

        if self.start_time:
            queryset = queryset.filter(timestamp__gte=self.start_time)

        if self.end_time:
            queryset = queryset.filter(timestamp__lt=self.end_time)

        return queryset.order_by('timestamp')

    def finalize(self, df: Optional[pd.DataFrame]) -> pd.DataFrame:
        if df is None or df.empty:
            # Return an empty dataframe with a timestamp index
            empty = pd.DataFrame()
            empty.index = pd.DatetimeIndex([], tz='UTC', name='timestamp')
            return empty

        df = df.copy()

        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True, errors='raise')
            df = df.set_index('timestamp', drop=True)

        df.index = pd.to_datetime(df.index, utc=True, errors='raise')
        df.index.name = 'timestamp'
        df = df.sort_index()

        # Guarantee timestamp_local exists
        df.insert(0, 'timestamp_local', df.index.tz_convert(settings.DEFAULT_TIMEZONE))

        return df

    def to_dataframe(self) -> Optional[pd.DataFrame]:
        raise NotImplementedError


class ResolvedEntryTimeline(EntryTimeline):
    def get_queryset(self, entry_model):
        queryset = super().get_queryset(entry_model)
        queryset = queryset.filter(
            stage=self.monitor.get_default_stage(entry_model),
        )
        return queryset

    def get_field_map(self, entry_model):
        fields = entry_model.declared_field_names
        field_map = {}

        for field in fields:
            field_map[field] = (entry_model.entry_type
                if len(fields) == 1
                else f'{entry_model.entry_type}_{field}'
            )

        return field_map

    def to_dataframe(self) -> Optional[pd.DataFrame]:
        frames: list[pd.DataFrame] = []

        for entry_model in self.entry_types:
            data = (self
                .get_queryset(entry_model)
                .projections(fields=['timestamp'] + entry_model.declared_field_names)
            )

            df = pd.DataFrame.from_records(data)
            field_map = self.get_field_map(entry_model)

            if df.empty:
                # Create an empty DataFrame with the expected columns
                df = pd.DataFrame(columns=dict(timestamp='timestamp', **field_map).values())
            else:
                df = df.rename(columns=field_map)

            frames.append(df)

        if not frames:
            return pd.DataFrame()

        # Outer join all DataFrames on timestamp
        merged = frames[0]
        for frame in frames[1:]:
            merged = pd.merge(merged, frame, on='timestamp', how='outer')

        return self.finalize(merged)


class ExpandedEntryTimeline(EntryTimeline):
    def to_dataframe(self) -> Optional[pd.DataFrame]:
        frames: list[pd.DataFrame] = []

        for entry_model in self.entry_types:
            queryset = self.get_queryset(entry_model)
            df = queryset.to_dataframe()

            if df is None or df.empty:
                continue

            df = df.reset_index()

            def label_row(row) -> str:
                bits = [entry_model.entry_type]
                bits.append(row['processor'] if row['stage'] == entry_model.Stage.CALIBRATED else row['stage'])
                if row['sensor']:
                    bits.append(row['sensor'])
                return '_'.join(bits)

            df['column_key'] = df.apply(label_row, axis=1)
            frames.append(df[['timestamp', 'sensor', 'column_key', *entry_model.declared_field_names]])

        if not frames:
            return pd.DataFrame()

        pivoted = (pd
            .concat(frames, axis=0)
            .pivot_table(
                index='timestamp',
                columns='column_key',
                values='value',
                aggfunc='first',
            )
            .reset_index()
        )
        pivoted.columns.name = None

        return self.finalize(pivoted)
