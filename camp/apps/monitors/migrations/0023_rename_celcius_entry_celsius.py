# Generated by Django 3.2.16 on 2022-11-21 02:09

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('monitors', '0022_auto_20221121_0132'),
    ]

    operations = [
        migrations.RenameField(
            model_name='entry',
            old_name='celcius',
            new_name='celsius',
        ),
    ]
