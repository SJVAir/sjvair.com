from django.db import migrations, models


def _fields(model_name):
    return [
        migrations.AddField(
            model_name=model_name,
            name='daily_statistic_mean',
            field=models.FloatField(blank=True, null=True, verbose_name='average of daily figures'),
        ),
        migrations.AddField(
            model_name=model_name,
            name='daily_statistic_days',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='days with a daily figure'),
        ),
        migrations.AddField(
            model_name=model_name,
            name='daily_statistic_expected_days',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='expected days'),
        ),
    ]


class Migration(migrations.Migration):

    dependencies = [
        ('summaries', '0007_summary_peaks'),
    ]

    # Atomic (the Postgres default), so SET LOCAL holds for the ALTER TABLEs below.
    # Each needs a brief ACCESS EXCLUSIVE lock; without a timeout it would wait behind
    # an open summaries transaction and stall every read and write queued behind it.
    # A timeout fails the release instead, and the deploy can be retried.
    operations = [
        migrations.RunSQL("SET LOCAL lock_timeout = '10s'", migrations.RunSQL.noop),
        *_fields('monitorsummary'),
        *_fields('regionsummary'),
    ]
