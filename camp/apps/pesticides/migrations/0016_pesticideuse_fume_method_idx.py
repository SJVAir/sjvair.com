from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY can't run in a transaction. It's its own
    # migration so 0015's ADD COLUMN lock isn't held through the scan of the
    # ~16M-row table.
    atomic = False

    dependencies = [
        ('pesticides', '0015_fumigation_method'),
    ]

    operations = [
        AddIndexConcurrently(
            model_name='pesticideuse',
            index=models.Index(condition=models.Q(('fume_method__isnull', False)), fields=['fume_method'], name='pesticide_use_fume_idx'),
        ),
    ]
