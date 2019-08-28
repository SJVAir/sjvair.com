PM2_SCHEMA = {
    'type': 'object',
    'properties': {
        'pm10_standard': {'type': 'number'},
        'pm25_standard': {'type': 'number'},
        'pm100_standard': {'type': 'number'},
        'pm10_env': {'type': 'number'},
        'pm25_env': {'type': 'number'},
        'pm100_env': {'type': 'number'},
        'particles_03um': {'type': 'number'},
        'particles_05um': {'type': 'number'},
        'particles_10um': {'type': 'number'},
        'particles_25um': {'type': 'number'},
        'particles_50um': {'type': 'number'},
        'particles_100um': {'type': 'number'},
    },
    'required': [
        'pm10_standard',
        'pm25_standard',
        'pm100_standard',
        'pm10_env',
        'pm25_env',
        'pm100_env',
        'particles_03um',
        'particles_05um',
        'particles_10um',
        'particles_25um',
        'particles_50um',
        'particles_100um',
    ]
}

PAYLOAD_SCHEMA = {
    'type': 'object',
    'properties': {
        'celcius': {'type': 'number'},
        'humidity': {'type': 'number'},
        'pressure': {'type': 'number'},
        'voc': {'type': 'number'},
        'pm2_a': PM2_SCHEMA,
        'pm2_b': PM2_SCHEMA,
        },
    },
    'required': [
        'celcius',
        'humidity',
        'pressure',
        'voc',
        'pm2'
    ]
}
