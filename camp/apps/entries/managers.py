from django.db import models

import pandas as pd


class EntryQuerySet(models.QuerySet):
    def to_dataframe(self, fields=None):
        """
        Serialize the queryset into a DataFrame including core fields and declared pollutant fields.
        """
        # Core fields always included
        core_fields = ['timestamp', 'sensor', 'stage', 'processor']

        # Pull the declared fields from the entry model
        model_declared_fields = [field.name for field in self.model.declared_fields]

        # Final field list
        fields = fields or (core_fields + model_declared_fields)

        # Only query the needed fields
        qs = self.values(*fields)

        # Create the dataframe
        df = pd.DataFrame.from_records(qs)

        if not df.empty and 'timestamp' in df.columns:
            df = df.set_index('timestamp')

        return df
