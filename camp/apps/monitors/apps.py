from django.apps import AppConfig

from health_check.plugins import plugin_dir


class MonitorsConfig(AppConfig):
    name = 'camp.apps.monitors'

    def ready(self):
        from . import health_checks
        plugin_dir.register(health_checks.AirGradientHealthCheck)
        plugin_dir.register(health_checks.AirNowHealthCheck)
        plugin_dir.register(health_checks.AQviewHealthCheck)
        plugin_dir.register(health_checks.CCACBAMHealthCheck)
        plugin_dir.register(health_checks.PurpleAirHealthCheck)
