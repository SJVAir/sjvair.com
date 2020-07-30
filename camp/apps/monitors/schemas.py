DATA_SCHEMA = {
    'type': 'object',
    'properties': {
        'celcius': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'fahrenheit': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'humidity': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'pressure': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'altitude': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'dew_point': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},

        'pm10_standard': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'pm25_standard': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'pm100_standard': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},

        'pm10_env': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'pm25_env': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'pm100_env': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},

        'particles_03um': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'particles_05um': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'particles_10um': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'particles_25um': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'particles_50um': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'particles_100um': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},

        'pm2_aqi': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
        'pm100_aqi': {'oneOf': [{'type': 'number'}, {'type': 'null'}]},
    },
    'required': [
        'celcius',
        'fahrenheit',
        'humidity',
        'pressure',
        'pm10_standard',
        'pm25_standard',
        'pm100_standard',
        'pm10_env',
        'pm25_env',
        'pm100_env',
        'pm2_aqi',
        'pm100_aqi',
    ]
}
