from django.db import migrations, models


def _field(model_name):
    return migrations.AddField(
        model_name=model_name,
        name='is_partial',
        field=models.BooleanField(db_default=False, default=False, verbose_name='is partial'),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('summaries', '0008_period_daily_statistic'),
    ]

    # Atomic (the Postgres default), so SET LOCAL holds for the ALTER TABLEs below.
    # Each needs a brief ACCESS EXCLUSIVE lock; without a timeout it would wait behind
    # an open summaries transaction and stall every read and write queued behind it.
    # A timeout fails the release instead, and the deploy can be retried.
    operations = [
        migrations.RunSQL("SET LOCAL lock_timeout = '10s'", migrations.RunSQL.noop),
        _field('monitorsummary'),
        _field('regionsummary'),
    ]
