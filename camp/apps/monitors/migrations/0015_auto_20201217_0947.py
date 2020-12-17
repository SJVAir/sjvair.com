# Generated by Django 3.1.1 on 2020-12-17 09:47

from django.db import migrations, models
import django.utils.timezone
import django_smalluuid.models
import model_utils.fields


class Migration(migrations.Migration):

    dependencies = [
        ('monitors', '0014_remove_entry_pm100_aqi'),
    ]

    operations = [
        migrations.CreateModel(
            name='Calibration',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('id', django_smalluuid.models.SmallUUIDField(db_index=True, default=django_smalluuid.models.UUIDDefault(), editable=False, primary_key=True, serialize=False, unique=True, verbose_name='ID')),
                ('monitor_type', models.CharField(choices=[('airnow', 'airnow'), ('bam1022', 'bam1022'), ('purpleair', 'purpleair')], max_length=20)),
                ('county', models.CharField(choices=[('Fresno', 'Fresno'), ('Kern', 'Kern'), ('Kings', 'Kings'), ('Madera', 'Madera'), ('Merced', 'Merced'), ('San Joaquin', 'San Joaquin'), ('Stanislaus', 'Stanislaus'), ('Tulare', 'Tulare')], max_length=20)),
                ('pm25_formula', models.CharField(blank=True, default='', max_length=255)),
            ],
        ),
        migrations.AlterField(
            model_name='monitor',
            name='county',
            field=models.CharField(blank=True, choices=[('Fresno', 'Fresno'), ('Kern', 'Kern'), ('Kings', 'Kings'), ('Madera', 'Madera'), ('Merced', 'Merced'), ('San Joaquin', 'San Joaquin'), ('Stanislaus', 'Stanislaus'), ('Tulare', 'Tulare')], max_length=20),
        ),
        migrations.AddIndex(
            model_name='calibration',
            index=models.Index(fields=['monitor_type', 'county'], name='monitors_ca_monitor_d72e8c_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='calibration',
            unique_together={('monitor_type', 'county')},
        ),
    ]
