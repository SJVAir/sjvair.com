from django.apps import AppConfig


class QueuesConfig(AppConfig):
    name = 'camp.apps.queues'

    def ready(self):
        from .stats import configure_queue_stats
        configure_queue_stats('primary')
