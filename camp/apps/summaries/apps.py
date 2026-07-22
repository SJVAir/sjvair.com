import os

from django.apps import AppConfig


class SummariesConfig(AppConfig):
    name = 'camp.apps.summaries'

    def ready(self):
        # Temporary diagnostic for the huey_summaries memory investigation.
        # Gated behind an env var so it's a no-op unless explicitly enabled,
        # and cheap to disable again once we have an answer. Safe to leave
        # in the codebase; tracemalloc's own overhead is small and it's only
        # active when MEMORY_DEBUG is set.
        if os.environ.get('MEMORY_DEBUG'):
            import tracemalloc
            tracemalloc.start(10)
