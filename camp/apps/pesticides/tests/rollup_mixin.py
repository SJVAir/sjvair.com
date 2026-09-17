from camp.apps.pesticides import rollup


class RollupTestMixin:
    """Build rollup rows from the loaded fixture before the class's tests run."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        rollup.rebuild_all()
