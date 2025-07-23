from django.apps import AppConfig


class CalibrationsConfig(AppConfig):
    name = 'camp.apps.calibrations'

    def ready(self):
        # Load the registries of training and processing classes.
        from . import trainers, processors
        trainers._load_all()
        processors._load_all()
