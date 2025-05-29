from django.apps import AppConfig


class HmsSmokeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hms_smoke'
    
    def ready(self):
        import hms_smoke.tasks
