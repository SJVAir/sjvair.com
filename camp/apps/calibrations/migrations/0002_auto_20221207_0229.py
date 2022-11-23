# Generated by Django 3.2.16 on 2022-12-07 02:29

import camp.apps.monitors.validators
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import django_smalluuid.models
import model_utils.fields


class Migration(migrations.Migration):

    dependencies = [
        ('calibrations', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='AutoCalibration',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('id', django_smalluuid.models.SmallUUIDField(db_index=True, default=django_smalluuid.models.UUIDDefault(), editable=False, primary_key=True, serialize=False, unique=True, verbose_name='ID')),
                ('formula', models.CharField(blank=True, default='', max_length=255, validators=[camp.apps.monitors.validators.validate_formula])),
                ('start_date', models.DateTimeField()),
                ('end_date', models.DateTimeField()),
                ('r2', models.FloatField()),
            ],
            options={
                'ordering': ['-end_date', '-r2'],
            },
        ),
        migrations.CreateModel(
            name='CountyCalibration',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('id', django_smalluuid.models.SmallUUIDField(db_index=True, default=django_smalluuid.models.UUIDDefault(), editable=False, primary_key=True, serialize=False, unique=True, verbose_name='ID')),
                ('monitor_type', models.CharField(choices=[('airnow', 'airnow'), ('bam1022', 'bam1022'), ('methane', 'methane'), ('purpleair', 'purpleair')], max_length=20)),
                ('county', models.CharField(choices=[('Fresno', 'Fresno'), ('Kern', 'Kern'), ('Kings', 'Kings'), ('Madera', 'Madera'), ('Merced', 'Merced'), ('San Joaquin', 'San Joaquin'), ('Stanislaus', 'Stanislaus'), ('Tulare', 'Tulare')], max_length=20)),
                ('pm25_formula', models.CharField(blank=True, default='', max_length=255, validators=[camp.apps.monitors.validators.validate_formula])),
            ],
        ),
        migrations.RemoveField(
            model_name='calibration',
            name='calibrator',
        ),
        migrations.AddIndex(
            model_name='countycalibration',
            index=models.Index(fields=['monitor_type', 'county'], name='calibration_monitor_7a3e4c_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='countycalibration',
            unique_together={('monitor_type', 'county')},
        ),
        migrations.AddField(
            model_name='autocalibration',
            name='calibrator',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='calibrations', to='calibrations.calibrator'),
        ),
        migrations.AlterField(
            model_name='calibrator',
            name='calibration',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='calibrator_current', to='calibrations.autocalibration'),
        ),
        migrations.DeleteModel(
            name='Calibration',
        ),
    ]