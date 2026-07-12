from django.contrib.gis.db import models

from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor


class CIMIS(Monitor):
    LAST_ACTIVE_LIMIT = int(60 * 60 * 3)

    DATA_PROVIDERS = [{
        'name': 'California Department of Water Resources',
        'url': 'https://water.ca.gov',
    }]
    DATA_SOURCE = {
        'name': 'CIMIS',
        'url': 'https://cimis.water.ca.gov/',
    }
    DEVICE = 'CIMIS Weather Station'

    EXPECTED_INTERVAL = '1h'
    ENTRY_CONFIG = {
        entry_models.Temperature: {
            'fields': {'value': 'HlyAirTmp'},
            'allowed_stages': [entry_models.Temperature.Stage.RAW],
            'default_stage': entry_models.Temperature.Stage.RAW,
        },
        entry_models.Humidity: {
            'fields': {'value': 'HlyRelHum'},
            'allowed_stages': [entry_models.Humidity.Stage.RAW],
            'default_stage': entry_models.Humidity.Stage.RAW,
        },
        entry_models.DewPoint: {
            'fields': {'value': 'HlyDewPnt'},
            'allowed_stages': [entry_models.DewPoint.Stage.RAW],
            'default_stage': entry_models.DewPoint.Stage.RAW,
        },
        entry_models.SoilTemperature: {
            'fields': {'value': 'HlySoilTmp'},
            'allowed_stages': [entry_models.SoilTemperature.Stage.RAW],
            'default_stage': entry_models.SoilTemperature.Stage.RAW,
        },
        entry_models.WindSpeed: {
            'fields': {'value': 'HlyWindSpd'},
            'allowed_stages': [entry_models.WindSpeed.Stage.RAW],
            'default_stage': entry_models.WindSpeed.Stage.RAW,
        },
        entry_models.WindDirection: {
            'fields': {'value': 'HlyWindDir'},
            'allowed_stages': [entry_models.WindDirection.Stage.RAW],
            'default_stage': entry_models.WindDirection.Stage.RAW,
        },
        entry_models.Precipitation: {
            'fields': {'value': 'HlyPrecip'},
            'allowed_stages': [entry_models.Precipitation.Stage.RAW],
            'default_stage': entry_models.Precipitation.Stage.RAW,
        },
        entry_models.SolarRadiation: {
            'fields': {'value': 'HlySolRad'},
            'allowed_stages': [entry_models.SolarRadiation.Stage.RAW],
            'default_stage': entry_models.SolarRadiation.Stage.RAW,
        },
        entry_models.NetRadiation: {
            'fields': {'value': 'HlyNetRad'},
            'allowed_stages': [entry_models.NetRadiation.Stage.RAW],
            'default_stage': entry_models.NetRadiation.Stage.RAW,
        },
        entry_models.VaporPressure: {
            'fields': {'value': 'HlyVapPres'},
            'allowed_stages': [entry_models.VaporPressure.Stage.RAW],
            'default_stage': entry_models.VaporPressure.Stage.RAW,
        },
        entry_models.ETo: {
            'fields': {'value': 'HlyAsceEto'},
            'allowed_stages': [entry_models.ETo.Stage.RAW],
            'default_stage': entry_models.ETo.Stage.RAW,
        },
        entry_models.ETr: {
            'fields': {'value': 'HlyAsceEtr'},
            'allowed_stages': [entry_models.ETr.Stage.RAW],
            'default_stage': entry_models.ETr.Stage.RAW,
        },
    }

    GRADE = None

    station_number = models.CharField(max_length=20, unique=True)

    class Meta:
        verbose_name = 'CIMIS'

    ENTRY_MAP = {
        config['fields']['value']: EntryModel
        for EntryModel, config in ENTRY_CONFIG.items()
    }
