# Generated by Django 3.2.16 on 2022-11-19 13:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purpleair', '0003_auto_20200724_1141'),
    ]

    operations = [
        migrations.AddField(
            model_name='purpleair',
            name='purple_id',
            field=models.IntegerField(db_index=True, null=True),
        ),
    ]
