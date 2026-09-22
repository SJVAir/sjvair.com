from django.apps import AppConfig


class ForecastsConfig(AppConfig):
    name = 'camp.apps.forecasts'

    def ready(self):
        from camp.apps.forecasts import panels  # noqa: F401 -- registers the Region admin forecast panel
