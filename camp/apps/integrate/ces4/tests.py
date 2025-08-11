from io import StringIO
from django.core.management import call_command
from django.test import TestCase
from shapely.wkt import loads as load_wkt

from camp.utils.counties import County
from camp.api.v2.ces4.tests import create_test_ces4_obj
from camp.apps.integrate.ces4.models import Record
from camp.apps.regions.management.commands.resolve_ces4_tracts import resolve

class Tests_CES4_App(TestCase):
    """
    inSJV - tests if fresno + tulare polygons are returned with the respective names + not false 
    request_to_db - tests the request function and processing from Ces4Data
    tract_map - tests the mapping + parsing from shp files in the tract-map function
    task - tests the db_task function to make sure it works only
    """ 
    def test_inSJV(self):
        self.ces4_1 = create_test_ces4_obj(1,.1,.1)
        #Test to make sure this function returns Fresno
        country = load_wkt(self.ces4_1.geometry.wkt)
        check = County.in_SJV(country)
        assert check is not False
        assert check == 'Fresno'
        
        #Test for Tulare also
        country2 = load_wkt(
            'POLYGON ((-119.353 36.206, -119.353 36.220, -119.330 36.220, -119.330 36.206, -119.353 36.206))'
            )
        check2 = County.in_SJV(country2)
        assert check2 is not False
        assert check2 == 'Tulare'    
        
    def test_request(self):
        out = StringIO()
        call_command('resolve_ces4_tracts', stdout=out)
        tract_count = {
            'fresno': 199,
            'tulare': 78,
            'kings': 27,
            'kern': 151,
            'san joaquin': 139,
            'stanislaus': 94,
            'merced': 49,
            'madera': 23,            
        }
        for county, count in tract_count.items():
            assert count == Record.objects.filter(county=county).count()
        assert Record.objects.count() == 760
        