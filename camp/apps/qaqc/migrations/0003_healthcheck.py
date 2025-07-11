# Generated by Django 4.2.20 on 2025-07-04 22:19

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import django_smalluuid.models
import model_utils.fields


class Migration(migrations.Migration):

    dependencies = [
        ('monitors', '0034_delete_defaultsensor'),
        ('qaqc', '0002_sensoranalysis_grade_sensoranalysis_variance'),
    ]

    operations = [
        migrations.CreateModel(
            name='HealthCheck',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('id', django_smalluuid.models.SmallUUIDField(db_index=True, default=django_smalluuid.models.UUIDDefault(), editable=False, primary_key=True, serialize=False, unique=True, verbose_name='ID')),
                ('hour', models.DateTimeField()),
                ('score', models.PositiveSmallIntegerField()),
                ('variance', models.FloatField(blank=True, null=True)),
                ('correlation', models.FloatField(blank=True, null=True)),
                ('monitor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='health_checks', to='monitors.monitor')),
            ],
            options={
                'indexes': [models.Index(fields=['monitor', 'hour'], name='qaqc_health_monitor_f87c26_idx')],
                'unique_together': {('monitor', 'hour')},
            },
        ),
    ]
