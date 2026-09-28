"""
The 0008 data migration, run for real: migrate back to 0007 (the ten
columns exist again, empty), write records the old way, migrate forward,
and check the copy. A plain TestCase: Postgres DDL is transactional, and the
migration executor's steps nest as savepoints inside the test's outer
transaction, so the whole thing -- migrate down, write rows, migrate up,
assert, migrate back to head in tearDown -- rolls back like any other test.
Nothing is ever committed or flushed, so this can't disturb another test's
fixtures or the placeholder rows other migrations create; it also means no
`available_apps` / cascading TRUNCATE workaround is needed (a TransactionTestCase
here previously tripped an unrelated helpdesk M2M flush ordering bug).

`SET CONSTRAINTS ALL IMMEDIATE` runs before each migrate: forward migration
0009 drops columns on a table this test just wrote rows to inside the same
transaction, and without it a deferred FK/constraint trigger from that write
can still be pending when the DDL runs.
"""
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase

BEFORE = [('emissions', '0007_toxics_long_format')]


class NamedToxicsMigrationTests(TestCase):
    def _executor(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        return executor

    def _emissions_leaf_nodes(self, executor):
        # Not a hard-coded '0009_drop_named_toxics': once a later phase adds
        # another emissions migration, that's the real head, and pinning to
        # 0009 would silently leave the schema behind it for every test that
        # runs after this one.
        return [node for node in executor.loader.graph.leaf_nodes() if node[0] == 'emissions']

    def migrate(self, targets):
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        executor = self._executor()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self.migrate(self._emissions_leaf_nodes(self._executor()))

    def test_named_columns_become_toxic_emission_rows(self):
        apps = self.migrate(BEFORE)
        Region = apps.get_model('regions', 'Region')
        Facility = apps.get_model('emissions', 'Facility')
        EmissionsRecord = apps.get_model('emissions', 'EmissionsRecord')
        district = Region.objects.create(name='SJVAPCD', slug='sjvapcd-mig', type='air_district', external_id='SJU')
        plant = Facility.objects.create(county_code=10, air_district=district, facid=1, name='PLANT', address={})
        EmissionsRecord.objects.create(facility=plant, year=2024, nox=Decimal('1.5'), benzene=Decimal('2.0'),
                                       chromium_hexavalent=Decimal('0.001'), total_score=Decimal('12.5'))
        EmissionsRecord.objects.create(facility=plant, year=2023, nox=Decimal('1.0'))

        apps = self.migrate(self._emissions_leaf_nodes(self._executor()))
        ToxicEmission = apps.get_model('emissions', 'ToxicEmission')
        ToxicPollutant = apps.get_model('emissions', 'ToxicPollutant')
        EmissionsRecord = apps.get_model('emissions', 'EmissionsRecord')

        rows = {(row.year, row.pollutant.carb_id): row.lbs for row in ToxicEmission.objects.select_related('pollutant')}
        assert rows == {(2024, '71432'): Decimal('2.0'), (2024, '18540299'): Decimal('0.001')}
        # Only the two columns with data got a placeholder -- the other eight
        # named toxics never appear in this dataset.
        assert ToxicPollutant.objects.count() == 2
        chromium = ToxicPollutant.objects.get(carb_id='18540299')
        assert (chromium.name, chromium.slug, chromium.cas_number, chromium.kind) == ('Hexavalent chromium', 'hexavalent-chromium', '18540-29-9', 'toxic')
        assert chromium.cancer_weight == 0 and chromium.iur is None
        # Nothing else on the records moved.
        assert EmissionsRecord.objects.count() == 2
        assert EmissionsRecord.objects.get(year=2024).total_score == Decimal('12.5')
        assert not hasattr(EmissionsRecord.objects.get(year=2024), 'benzene')
