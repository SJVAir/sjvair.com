"""
The 0008 data migration, run for real: migrate back to 0007 (the ten
columns exist again, empty), write records the old way, migrate forward,
and check the copy. A TransactionTestCase because the executor commits.
"""
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [('emissions', '0007_toxics_long_format')]
AFTER = [('emissions', '0009_drop_named_toxics')]


class NamedToxicsMigrationTests(TransactionTestCase):
    # Restricting flush to the apps this test actually touches also makes
    # Django pass allow_cascade=True to the post-test flush; without it,
    # flush's plain TRUNCATE trips over an unrelated app's shared M2M
    # through table (helpdesk.Term/Article) that isn't in this test's way.
    available_apps = ['camp.apps.emissions', 'camp.apps.regions', 'django.contrib.contenttypes']

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self.migrate(AFTER)

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

        apps = self.migrate(AFTER)
        ToxicEmission = apps.get_model('emissions', 'ToxicEmission')
        ToxicPollutant = apps.get_model('emissions', 'ToxicPollutant')
        EmissionsRecord = apps.get_model('emissions', 'EmissionsRecord')

        rows = {(row.year, row.pollutant.carb_id): row.lbs for row in ToxicEmission.objects.select_related('pollutant')}
        assert rows == {(2024, '71432'): Decimal('2.0'), (2024, '18540299'): Decimal('0.001')}
        assert ToxicPollutant.objects.count() == 10
        chromium = ToxicPollutant.objects.get(carb_id='18540299')
        assert (chromium.name, chromium.slug, chromium.cas_number, chromium.kind) == ('Hexavalent chromium', 'hexavalent-chromium', '18540-29-9', 'toxic')
        assert chromium.cancer_weight == 0 and chromium.iur is None
        # Nothing else on the records moved.
        assert EmissionsRecord.objects.count() == 2
        assert EmissionsRecord.objects.get(year=2024).total_score == Decimal('12.5')
        assert not hasattr(EmissionsRecord.objects.get(year=2024), 'benzene')
