# Generated by Django 3.2.16 on 2022-12-10 06:29

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('calibrations', '0002_auto_20221207_0229'),
    ]

    operations = [
        migrations.DeleteModel(
            name='CountyCalibration',
        ),
    ]