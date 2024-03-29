# Generated by Django 4.2.4 on 2023-08-14 18:22

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import django_smalluuid.models
import model_utils.fields


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('monitors', '0026_entry_ozone'),
    ]

    operations = [
        migrations.CreateModel(
            name='SensorAnalysis',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('id', django_smalluuid.models.SmallUUIDField(db_index=True, default=django_smalluuid.models.UUIDDefault(), editable=False, primary_key=True, serialize=False, unique=True, verbose_name='ID')),
                ('r2', models.FloatField()),
                ('intercept', models.FloatField()),
                ('coef', models.FloatField()),
                ('start_date', models.DateTimeField()),
                ('end_date', models.DateTimeField()),
                ('monitor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sensor_analysis', to='monitors.monitor')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
