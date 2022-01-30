import time

from resticus.encoders import JSONEncoder

from camp.apps.monitors.models import Monitor, Entry


class RootAccess(Monitor):
    def process_entry(self, entry):
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
            setattr(entry, attr, entry.payload.get(attr))

        for attr in pm_attrs:
            setattr(entry, attr, entry.payload['pm2_a'].get(attr))

        self.is_processed = True
        return entry
