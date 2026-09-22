from django.apps import AppConfig


class SummariesConfig(AppConfig):
    name = 'camp.apps.summaries'

    def ready(self):
        from camp.apps.summaries import panels  # noqa: F401 -- registers the Region admin trend panel
