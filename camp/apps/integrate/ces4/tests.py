from django.test import TestCase
from shapely.wkt import loads as load_wkt

from camp.utils.counties import County
from camp.api.v2.ces4.tests import create_test_ces4_obj
from camp.apps.integrate.ces4.data import Ces4Data
from camp.apps.integrate.ces4.models import Tract


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
        list_count = Ces4Data.ces4_request()
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
        #print(Ces4.objects.first().__dict__)
        for county, count in tract_count.items():
            assert count == Tract.objects.filter(county=county).count()
        assert Tract.objects.count() == 760
        assert len(list_count) == 760
        
    def test_tract_map(self):
        import pandas as pd
        ca_fips = {
            "019": "fresno",
            "029": "kern",
            "031": "kings",
            "039": "madera",
            "047": "merced",
            "077": "san joaquin",
            "099": "stanislaus",
            "107": "tulare",
                }
        df = pd.DataFrame(data={'TractTXT':['6019', '6019', '6107']})
        for fip in ca_fips:
            df.loc[len(df)] = '6' + fip
        df = Ces4Data.map_tracts(df)
        assert df.loc[df['county'] == 'fresno', 'county'].count().sum() == 3
        assert df.loc[df['county'] == 'tulare', 'county'].count().sum() == 2
        assert df.loc[df['county'] == 'kings', 'county'].count().sum() == 1

        