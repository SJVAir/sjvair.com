# Generated by Django 3.0.6 on 2020-07-24 12:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitors', '0003_auto_20200604_0016'),
    ]

    operations = [
        migrations.AddField(
            model_name='entry',
            name='sensor',
            field=models.CharField(db_index=True, max_length=50, blank=True, default=''),
        ),
    ]
