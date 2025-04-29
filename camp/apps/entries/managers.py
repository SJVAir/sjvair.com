from django.db import models

import pandas as pd


class EntryQuerySet(models.QuerySet):
    def to_dataframe(self, fields=None):
        """
        Serialize the queryset into a DataFrame including core fields and declared pollutant fields.
        """
        if fields is None:
            core_fields = ['timestamp', 'sensor', 'stage', 'processor']
            declared_fields = [field.name for field in self.model.declared_fields]
            fields = core_fields + declared_fields

        qs = self.values(*fields)
        if not qs.exists():
            return None

        df = pd.DataFrame.from_records(qs)

        if 'timestamp' in fields:
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
            df = df.set_index('timestamp')

        return df
