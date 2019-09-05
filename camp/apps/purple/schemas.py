PM2_SCHEMA = {
    'type': 'object',
    'properties': {
        'pm25_standard': {'type': 'number'},
        'pm10_env': {'type': 'number'},
        'pm25_env': {'type': 'number'},
        'pm100_env': {'type': 'number'},
    },
    'required': [
        'pm25_standard',
        'pm10_env',
        'pm25_env',
        'pm100_env',
    ]
}
