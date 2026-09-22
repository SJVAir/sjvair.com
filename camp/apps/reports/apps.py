from django.apps import AppConfig


class ReportsConfig(AppConfig):
    name = 'camp.apps.reports'
    verbose_name = 'Reports'

    def ready(self):
        from camp.apps.reports import panels  # noqa: F401 -- registers the Region admin panels
