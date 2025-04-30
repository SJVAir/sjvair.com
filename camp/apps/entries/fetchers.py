import pandas as pd
from typing import List, Optional, Type
from camp.apps.entries.models import BaseEntry


class EntryDataFetcher:
    """
    Fetches and assembles multiple entry types into a wide-format DataFrame,
    aligned by timestamp, using each entry's default stage and sensor.

    If entry_types is None, all known Entry types will be fetched.
    """

    def __init__(
        self,
        monitor,
        entry_types: Optional[List[Type[BaseEntry]]] = None,
        start_time=None,
        end_time=None,
    ):
        self.monitor = monitor
        self.entry_types = entry_types or BaseEntry.__subclasses__()
        self.start_time = start_time
        self.end_time = end_time

    def get_queryset(self, entry_model):
        queryset = entry_model.objects.filter(monitor_id=self.monitor.pk)

        if self.start_time:
            queryset = queryset.filter(timestamp__gte=self.start_time)

        if self.end_time:
            queryset = queryset.filter(timestamp__lte=self.end_time)

        if hasattr(entry_model, 'default_stage'):
            queryset = queryset.filter(stage=entry_model.default_stage)

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
        frames = []

        for entry_model in self.entry_types:
            data = (
                self.get_queryset(entry_model)
                .projections(fields=['timestamp'] + entry_model.declared_field_names)
            )

            df = pd.DataFrame.from_records(data)
            field_map = self.get_field_map(entry_model)

            if df.empty:
                # Create an empty DataFrame with the expected renamed columns
                renamed_columns = {'timestamp': 'timestamp'}
                renamed_columns.update(field_map)
                df = pd.DataFrame(columns=renamed_columns.values())
            else:
                df = df.rename(columns=field_map)

            frames.append(df)

        if not frames:
            return None

        # Outer join all DataFrames on timestamp
        merged = frames[0]
        for frame in frames[1:]:
            merged = pd.merge(merged, frame, on='timestamp', how='outer')

        if 'timestamp' in merged.columns:
            merged['timestamp'] = pd.to_datetime(merged['timestamp'], utc=True)
            merged = merged.set_index('timestamp')

        return merged.sort_index()
