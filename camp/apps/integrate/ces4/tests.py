from io import StringIO

from django.db.models import Max, Min
from django.core.management import call_command
from django.test import TestCase

from camp.apps.integrate.ces4.management.commands.resolve_ces4_tracts import normalize
from camp.apps.integrate.ces4.models import Record
from camp.apps.regions.models import Boundary, Region



class Tests_CES4_App(TestCase):
    #Confirms the ces4 data retrieval pathway and that each tract for 2010 and 2020 had an equal amount of ces4 records.
    def test_request(self):
        out = StringIO()
        call_command('import_counties', stdout=out)
        call_command('import_census_tracts', stdout=out)
        call_command('resolve_ces4_tracts', stdout=out)

        ces_2020 = Record.objects.filter(boundary__version='2020')
        assert Record.objects.filter(boundary__version='2010').count() == Boundary.objects.filter(region__type=Region.Type.TRACT, version='2010').count()
        assert ces_2020.count() == Boundary.objects.filter(region__type=Region.Type.TRACT, version='2020').count()
        
        #Tests the weight averaging was correct
        assert ces_2020.aggregate(Max('pol_ozone'))['pol_ozone__max'] < .07
        assert ces_2020.aggregate(Max('pol_ozone_p'))['pol_ozone_p__max'] <= 100
        assert ces_2020.aggregate(Min('pol_ozone_p'))['pol_ozone_p__min'] >= 0
        assert Record.objects.count() == 1738
        
    def test_normalize(self):
        assert normalize('ozoneP') == normalize('pol_ozone_p')
        assert normalize('ACS2019Tot') == normalize('population')
        assert normalize('Other_Mult') == normalize('pop_other')
        assert normalize('Elderly__1') == normalize('pop_65_p')
        assert normalize('RSEIhaz') == normalize('pol_rsei_haz')
        assert normalize('tract') == normalize('tract')
        assert normalize('pmP') == normalize('pol_pm_p')
        assert normalize('PollutionS') == normalize('pollution_s')
        assert normalize('housingBP') == normalize('char_housingb_p')
        
        
        
    
        
        