from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

import pytest

from camp.apps.emissions import audit
from camp.apps.emissions.models import EmissionsRecord, Facility, SourceImport, Well
from camp.apps.emissions.tests.test_wells import make_well
from camp.apps.regions.models import Region


class AuditTests(TestCase):
    """audit_emissions_imports: which imports look done, from the data they leave."""
    fixtures = ['regions.yaml', 'emissions.yaml']

    def steps(self):
        return {step.command: step for step in audit.audit()}

    def test_every_deploy_step_is_listed_in_order(self):
        commands = [step.command for step in audit.audit()]
        assert commands[0] == 'import_health_values --url'
        assert commands.index('import_ceidars --year 2024') < commands.index('clean_facility_points') < commands.index('import_icis_air')
        assert commands.index('import_mrr --year 2024 --url') < commands.index('import_cepam --year 2018') < commands.index('import_cadd --url')
        assert commands[-1] == 'import_nei --year 2023'

    def test_a_year_with_some_counties_is_partial(self):
        # The fixture's facilities sit in Fresno and Kern only.
        counties = set(Facility.objects.values_list('county__slug', flat=True))
        year = max(audit.CEIDARS_YEARS)
        for facility in Facility.objects.all():
            EmissionsRecord.objects.get_or_create(facility=facility, year=year)
        step = self.steps()[f'import_ceidars --year {year}']
        assert step.status == audit.PARTIAL and f'{len(counties)}/8 counties' in step.found
        assert step.fix == f'python manage.py import_ceidars --year {year}' and 'no rows for:' in step.notes[0]

    def test_a_scheduled_import_goes_stale(self):
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        assert self.steps()['import_wells'].status == audit.MISSING
        make_well('0402900001', (-119.02, 35.37), kern)
        stamp = SourceImport.objects.create(source='wellstar')
        assert self.steps()['import_wells'].status == audit.OK
        SourceImport.objects.filter(pk=stamp.pk).update(imported_at=timezone.now() - timedelta(days=30))
        step = self.steps()['import_wells']
        assert step.status == audit.STALE and step.fix == 'python manage.py import_wells'

    def test_the_command_lists_what_to_run(self):
        out = StringIO()
        call_command('audit_emissions_imports', stdout=out)
        text = out.getvalue()
        assert 'MISSING  import_cadd --url' in text and 'steps look done.' in text
        fixes = text[text.index('To finish, in this order:'):]
        # In the deploy's order, each once, the cache clear last.
        assert fixes.index('import_icis_air') < fixes.index('import_cadd --url') < fixes.index('import_wells') < fixes.index('cache.clear()')
        assert fixes.count('import_cadd --url') == 1
        with pytest.raises(CommandError):
            call_command('audit_emissions_imports', '--strict', stdout=StringIO())
