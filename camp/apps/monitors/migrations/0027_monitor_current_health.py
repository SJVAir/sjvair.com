# Generated by Django 4.2.4 on 2023-08-14 18:27

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('qaqc', '0001_initial'),
        ('monitors', '0026_entry_ozone'),
    ]

    operations = [
        migrations.AddField(
            model_name='monitor',
            name='current_health',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='current_for', to='qaqc.sensoranalysis'),
        ),
    ]