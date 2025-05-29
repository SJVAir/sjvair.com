from django.apps import AppConfig


class HmsSmokeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'camp.apps.monitors.hms_smoke'
    
    def ready(self):
        from . import tasks
