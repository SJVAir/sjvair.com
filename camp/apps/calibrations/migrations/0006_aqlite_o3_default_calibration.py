from django.db import migrations


def create(apps, schema_editor):
    DefaultCalibration = apps.get_model('calibrations', 'DefaultCalibration')
    DefaultCalibration.objects.get_or_create(
        monitor_type='aqlite',
        entry_type='o3',
        defaults={'calibration': 'AQLiteHourlyAggregator'},
    )


def delete(apps, schema_editor):
    DefaultCalibration = apps.get_model('calibrations', 'DefaultCalibration')
    DefaultCalibration.objects.filter(monitor_type='aqlite', entry_type='o3').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('calibrations', '0005_defaultcalibration_calibrationpair_calibration'),
    ]

    operations = [
        migrations.RunPython(create, delete),
    ]
