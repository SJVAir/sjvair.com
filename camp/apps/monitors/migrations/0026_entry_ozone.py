# Generated by Django 4.2.4 on 2023-08-09 21:19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitors', '0025_auto_20230731_2249'),
    ]

    operations = [
        migrations.AddField(
            model_name='entry',
            name='ozone',
            field=models.DecimalField(decimal_places=2, max_digits=8, null=True),
        ),
    ]
