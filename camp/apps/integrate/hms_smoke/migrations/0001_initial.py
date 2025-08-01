# Generated by Django 4.2.20 on 2025-07-10 16:38

import django.contrib.gis.db.models.fields
from django.db import migrations, models
import django_smalluuid.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Smoke',
            fields=[
                ('id', django_smalluuid.models.SmallUUIDField(db_index=True, default=django_smalluuid.models.UUIDDefault(), editable=False, primary_key=True, serialize=False, unique=True, verbose_name='ID')),
                ('date', models.DateField(null=True)),
                ('satellite', models.CharField(max_length=20)),
                ('start', models.DateTimeField(null=True)),
                ('end', models.DateTimeField(null=True)),
                ('density', models.CharField(choices=[('light', 'Light'), ('medium', 'Medium'), ('heavy', 'Heavy')], default='light', max_length=10)),
                ('geometry', django.contrib.gis.db.models.fields.MultiPolygonField(srid=4326)),
                ('is_final', models.BooleanField(default=False)),
            ],
        ),
    ]
