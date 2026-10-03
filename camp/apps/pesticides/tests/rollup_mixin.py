from django.core.cache import cache

from camp.apps.pesticides import rollup


class RollupTestMixin:
    """Build rollup rows from the loaded fixture before the class's tests run."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        rollup.rebuild_all()

    def setUp(self):
        super().setUp()
        # The pages cache their stats, and the test cache lives as long as the
        # xdist worker: without this a page can serve numbers another class
        # cached from different data (an empty landing page, say).
        cache.clear()
