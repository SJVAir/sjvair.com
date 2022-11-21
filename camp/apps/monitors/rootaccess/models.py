import time

from resticus.encoders import JSONEncoder

from camp.apps.monitors.models import Monitor, Entry


class RootAccess(Monitor):
    def process_entry(self, entry, payload):
        env_attrs = ['celcius', 'humidity', 'pressure']
        pm_attrs = [
            'particles_03um',
            'particles_05um',
            'particles_100um',
            'particles_10um',
            'particles_25um',
            'particles_50um',
            'pm100',
            'pm10',
            'pm25',
        ]

        for attr in env_attrs:
            setattr(entry, attr, payload.get(attr))

        for attr in pm_attrs:
            setattr(entry, attr, payload['pm2_a'].get(attr))

        return super().process_entry(entry, payload)
