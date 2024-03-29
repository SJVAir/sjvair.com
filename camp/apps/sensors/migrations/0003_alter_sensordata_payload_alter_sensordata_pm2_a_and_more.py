# Generated by Django 4.2.4 on 2023-08-11 20:05

import camp.utils.validators
from django.db import migrations, models
import resticus.encoders


class Migration(migrations.Migration):

    dependencies = [
        ('sensors', '0002_auto_20190828_2149'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sensordata',
            name='payload',
            field=models.JSONField(default=dict, encoder=resticus.encoders.JSONEncoder, validators=[camp.utils.validators.JSONSchemaValidator({'properties': {'celcius': {'type': 'number'}, 'humidity': {'type': 'number'}, 'pm2_a': {'properties': {'particles_03um': {'type': 'number'}, 'particles_05um': {'type': 'number'}, 'particles_100um': {'type': 'number'}, 'particles_10um': {'type': 'number'}, 'particles_25um': {'type': 'number'}, 'particles_50um': {'type': 'number'}, 'pm100_env': {'type': 'number'}, 'pm100_standard': {'type': 'number'}, 'pm10_env': {'type': 'number'}, 'pm10_standard': {'type': 'number'}, 'pm25_env': {'type': 'number'}, 'pm25_standard': {'type': 'number'}}, 'required': ['pm10_standard', 'pm25_standard', 'pm100_standard', 'pm10_env', 'pm25_env', 'pm100_env', 'particles_03um', 'particles_05um', 'particles_10um', 'particles_25um', 'particles_50um', 'particles_100um'], 'type': 'object'}, 'pm2_b': {'properties': {'particles_03um': {'type': 'number'}, 'particles_05um': {'type': 'number'}, 'particles_100um': {'type': 'number'}, 'particles_10um': {'type': 'number'}, 'particles_25um': {'type': 'number'}, 'particles_50um': {'type': 'number'}, 'pm100_env': {'type': 'number'}, 'pm100_standard': {'type': 'number'}, 'pm10_env': {'type': 'number'}, 'pm10_standard': {'type': 'number'}, 'pm25_env': {'type': 'number'}, 'pm25_standard': {'type': 'number'}}, 'required': ['pm10_standard', 'pm25_standard', 'pm100_standard', 'pm10_env', 'pm25_env', 'pm100_env', 'particles_03um', 'particles_05um', 'particles_10um', 'particles_25um', 'particles_50um', 'particles_100um'], 'type': 'object'}, 'pressure': {'type': 'number'}, 'voc': {'type': 'number'}}, 'required': ['celcius', 'humidity', 'pressure', 'voc', 'pm2_a', 'pm2_b'], 'type': 'object'})]),
        ),
        migrations.AlterField(
            model_name='sensordata',
            name='pm2_a',
            field=models.JSONField(encoder=resticus.encoders.JSONEncoder, null=True, validators=[camp.utils.validators.JSONSchemaValidator({'properties': {'particles_03um': {'type': 'number'}, 'particles_05um': {'type': 'number'}, 'particles_100um': {'type': 'number'}, 'particles_10um': {'type': 'number'}, 'particles_25um': {'type': 'number'}, 'particles_50um': {'type': 'number'}, 'pm100_env': {'type': 'number'}, 'pm100_standard': {'type': 'number'}, 'pm10_env': {'type': 'number'}, 'pm10_standard': {'type': 'number'}, 'pm25_env': {'type': 'number'}, 'pm25_standard': {'type': 'number'}}, 'required': ['pm10_standard', 'pm25_standard', 'pm100_standard', 'pm10_env', 'pm25_env', 'pm100_env', 'particles_03um', 'particles_05um', 'particles_10um', 'particles_25um', 'particles_50um', 'particles_100um'], 'type': 'object'})]),
        ),
        migrations.AlterField(
            model_name='sensordata',
            name='pm2_b',
            field=models.JSONField(encoder=resticus.encoders.JSONEncoder, null=True, validators=[camp.utils.validators.JSONSchemaValidator({'properties': {'particles_03um': {'type': 'number'}, 'particles_05um': {'type': 'number'}, 'particles_100um': {'type': 'number'}, 'particles_10um': {'type': 'number'}, 'particles_25um': {'type': 'number'}, 'particles_50um': {'type': 'number'}, 'pm100_env': {'type': 'number'}, 'pm100_standard': {'type': 'number'}, 'pm10_env': {'type': 'number'}, 'pm10_standard': {'type': 'number'}, 'pm25_env': {'type': 'number'}, 'pm25_standard': {'type': 'number'}}, 'required': ['pm10_standard', 'pm25_standard', 'pm100_standard', 'pm10_env', 'pm25_env', 'pm100_env', 'particles_03um', 'particles_05um', 'particles_10um', 'particles_25um', 'particles_50um', 'particles_100um'], 'type': 'object'})]),
        ),
    ]
