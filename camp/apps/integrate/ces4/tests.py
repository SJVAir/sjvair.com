from io import StringIO
from django.core.management import call_command
from django.test import TestCase

from camp.apps.integrate.ces4.models import Record
from camp.apps.regions.models import Boundary, Region


class Tests_CES4_App(TestCase):
    #Confirms the ces4 data retrieval pathway and that each tract for 2010 and 2020 had an equal amount of ces4 records.
    def test_request(self):
        out = StringIO()
        call_command('import_counties', stdout=out)
        call_command('import_census_tracts_2010', stdout=out)
        call_command('import_census_tracts_2020', stdout=out)
        call_command('resolve_ces4_tracts', stdout=out)

        assert Record.objects.filter(boundary__version='2010').count() == Boundary.objects.filter(region__type=Region.Type.TRACT, version='2010').count()
        assert Record.objects.filter(boundary__version='2020').count() == Boundary.objects.filter(region__type=Region.Type.TRACT, version='2020').count()
        assert Record.objects.count() == 1738
        