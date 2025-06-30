from django.contrib.gis.geos import GEOSGeometry
from django.test import TestCase
from shapely.wkt import loads as load_wkt

from camp.utils.counties import County
from camp.apps.integrate.ces4.data import Ces4Data
from camp.apps.integrate.ces4.models import Ces4
from camp.apps.integrate.ces4.tasks import ces4_load

def create_test_ces4_obj(id, pm, pmP):
    polygon_wkt = (
        "POLYGON(("
        "-119.860839 36.660399, "
        "-119.860839 36.905755, "
        "-119.650879 36.905755, "
        "-119.650879 36.660399, "
        "-119.860839 36.660399"
        "))"
    )
    geometry = GEOSGeometry(polygon_wkt, srid=4326)
    county = County.in_SJV(load_wkt(geometry.wkt))
     
    return Ces4.objects.create(
        OBJECTID=id, tract=0, ACS2019Tot=0,
        CIscore=0, CIscoreP=0,
        pollution=0, pollutionP=0, pollutionS=0,
        ozone=0, ozoneP=0, pm=pm, pmP=pmP,
        diesel=0, dieselP=0, pest=0, pestP=0,
        RSEIhaz=0, RSEIhazP=0, asthma=0, asthmaP=0,
        cvd=0, cvdP=0, traffic=0, trafficP=0,
        drink=0, drinkP=0, lead=0, leadP=0,
        cleanups=0, cleanupsP=0, gwthreats=0, gwthreatsP=0,
        iwb=0, iwbP=0, swis=0, swisP=0,
        popchar=0, popcharSco=0, popcharP=0,
        lbw=0, lbwP=0, edu=0, eduP=0,
        ling=0, lingP=0, pov=0, povP=0,
        unemp=0, unempP=0, housingB=0, housingBP=0,
        county=county, geometry=geometry,
        )
    


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
        Ces4Data.ces4_request()
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
            assert count == Ces4.objects.filter(county=county).count()
        assert 760 == Ces4.objects.count()
        
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
        
    def test_task(self):
        ces4_load.call_local()
        assert 760 == Ces4.objects.count()
        