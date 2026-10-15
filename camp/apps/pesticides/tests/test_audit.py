from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

import pytest

from camp.apps.pesticides import audit
from camp.apps.pesticides.models import Chemical, PesticideNotice, PesticideUse
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


class AuditTests(RollupTestMixin, TestCase):
    """audit_pesticides_imports: which imports look done, from the data they leave."""
    fixtures = ['pesticides-explorer']

    def steps(self):
        return {step.command: step for step in audit.audit()}

    def test_every_deploy_step_is_listed_in_order(self):
        commands = [step.command for step in audit.audit()]
        assert commands[0] == 'import_counties'
        newest = max(audit.PUR_YEARS)
        # The newest year loads CDPR's lookups; the rest skip them.
        assert f'import_pur --year {newest}' in commands
        assert f'import_pur --year {newest - 1} --skip-lookup' in commands
        assert commands.index('import_schools') < commands.index(f'import_pur --year {newest}') < commands.index('import_comptox --phase search')
        assert commands.index('import_comptox --phase hazard') < commands.index('import_prop65 --path p65chemicalslist.csv') < commands.index('rebuild_pesticide_rollup --all')
        assert commands[-1] == 'fetch_spraydays'

    def test_a_year_with_some_counties_is_partial(self):
        counties = Region.objects.counties().count()
        # The fixture's 2023 records sit in Fresno and Kern; drop Kern's.
        PesticideUse.objects.filter(year=2023, county__slug='kern').delete()
        step = self.steps()['import_pur --year 2023']
        assert step.status == audit.PARTIAL and f'1/{counties} counties' in step.found
        assert 'kern' in step.notes[0] and step.fix == 'python manage.py import_pur --year 2023'
        assert self.steps()['import_pur --year 2018 --skip-lookup'].status == audit.MISSING

    def test_the_chemical_lists_are_told_apart(self):
        steps = self.steps()
        assert steps['import_prop65 --path p65chemicalslist.csv'].status == audit.MISSING
        chemical = Chemical.objects.first()
        # A carcinogen alone could be CARB's; only Prop 65 marks a reproductive toxin.
        chemical.categories = [Chemical.Category.CARCINOGEN]
        chemical.save()
        assert self.steps()['import_prop65 --path p65chemicalslist.csv'].status == audit.MISSING
        chemical.categories = [Chemical.Category.REPRODUCTIVE_TOXIN]
        chemical.save()
        assert self.steps()['import_prop65 --path p65chemicalslist.csv'].status == audit.OK

    def test_the_rollup_follows_the_imports_before_it(self):
        # Years are missing above it, so it reruns after them.
        step = self.steps()['rebuild_pesticide_rollup --all']
        assert step.status == audit.NEEDED and step.notes == ['after the imports above']
        assert audit.rollup({2022, 2023}).status == audit.OK
        assert audit.rollup({2021, 2022, 2023}).status == audit.NEEDED

    def test_notices_go_stale(self):
        PesticideNotice.objects.update(created=timezone.now())
        assert self.steps()['fetch_spraydays'].status == audit.OK
        PesticideNotice.objects.update(created=timezone.now() - timedelta(days=10))
        step = self.steps()['fetch_spraydays']
        assert step.status == audit.STALE and step.fix == 'python manage.py fetch_spraydays'
        PesticideNotice.objects.all().delete()
        assert self.steps()['fetch_spraydays'].status == audit.MISSING

    def test_the_command_lists_what_to_run(self):
        out = StringIO()
        call_command('audit_pesticides_imports', stdout=out)
        text = out.getvalue()
        assert 'MISSING  import_pur --year 2018 --skip-lookup' in text and 'steps look done.' in text
        fixes = text[text.index('To finish, in this order:'):]
        # In the deploy's order, each once, the rollup after the imports and the cache clear last.
        assert fixes.index('import_pur --year 2018') < fixes.index('import_prop65') < fixes.index('rebuild_pesticide_rollup --all') < fixes.index('cache.clear()')
        assert fixes.count('rebuild_pesticide_rollup') == 1
        with pytest.raises(CommandError):
            call_command('audit_pesticides_imports', strict=True, stdout=StringIO())
