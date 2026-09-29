from django.db import migrations, models


def stamp_legacy(apps, schema_editor):
    """Every point that exists today has unknown provenance."""
    Facility = apps.get_model('emissions', 'Facility')
    Facility.objects.filter(point__isnull=False).update(point_source='legacy')


class Migration(migrations.Migration):
    dependencies = [
        ('emissions', '0009_drop_named_toxics'),
    ]

    operations = [
        migrations.AddField(
            model_name='facility',
            name='point_source',
            field=models.CharField(
                blank=True,
                choices=[('census', 'Census street match'), ('carb', 'CARB coordinates'), ('maptiler', 'MapTiler'), ('legacy', 'Legacy (unknown)')],
                default='',
                max_length=16,
                verbose_name='Point source',
            ),
        ),
        migrations.RunPython(stamp_legacy, migrations.RunPython.noop),
    ]
