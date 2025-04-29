from django.db import models

import pandas as pd


class EntryQuerySet(models.QuerySet):
    def projections(self, fields=None):
        """
        Returns the queryset projected to the model's projection_fields.

        Usage:
            Entry.objects.filter(...).projections()
        """
        fields = fields or self.model.projection_fields
        return self.values(*fields)

    def to_dataframe(self, fields=None):
        """
        Serialize the queryset into a DataFrame including core fields and declared pollutant fields.
        """

        if not self.exists():
            return None

        qs = self.projections(fields)
        df = pd.DataFrame.from_records(qs)

        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
            df = df.set_index('timestamp')

        return df
