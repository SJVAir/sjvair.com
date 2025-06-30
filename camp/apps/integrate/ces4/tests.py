from django.contrib.gis.geos import GEOSGeometry
from django.test import TestCase
from shapely.wkt import loads as load_wkt

from camp.utils.counties import County
from camp.apps.integrate.ces4.data import Ces4Data
from camp.apps.integrate.ces4.models import Ces4


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
        ozone=0, ozoneP=0,
        pm=pm, pmP=pmP,
        diesel=0, dieselP=0,
        pest=0, pestP=0,
        RSEIhaz=0, RSEIhazP=0,
        asthma=0, asthmaP=0,
        cvd=0, cvdP=0,
        pollution=0, pollutionP=0,pollutionS=0,
        traffic=0, trafficP=0,
        drink=0, drinkP=0,
        lead=0, leadP=0,
        cleanups=0,cleanupsP=0,
        gwthreats=0, gwthreatsP=0,
        iwb=0, iwbP=0,
        swis=0, swisP=0,
        popchar=0, popcharSco=0, popcharP=0,
        lbw=0, lbwP=0, 
        edu=0, eduP=0,
        ling=0, lingP=0,
        pov=0, povP=0,
        unemp=0, unempP=0,
        housingB=0, housingBP=0,
        county=county, geometry=geometry,
        )
    


class Tests_CES4_Miscellaneous(TestCase):
    """
    inSJV - tests if fresno + tulare polygons are returned with the respective names + not false 
    """
    def test_datacheck(self):
        Ces4Data.ces4_request()
        assert Ces4.objects.all().count() == 760
        
    def test_inSJV(self):
        self.ces4_1 = create_test_ces4_obj(1,.1,.1)
        #Test to make sure this function returns Fresno
        shapely_country = load_wkt(self.ces4_1.geometry.wkt)
        county_check = County.in_SJV(shapely_country)
        assert county_check is not False
        assert county_check == 'Fresno'
        
        #Test for Tulare also
        shapely_country2 = load_wkt(
            'POLYGON ((-119.353 36.206, -119.353 36.220, -119.330 36.220, -119.330 36.206, -119.353 36.206))'
            )
        county_check2 = County.in_SJV(shapely_country2)
        assert county_check2 is not False
        assert county_check2 == 'Tulare'    
        
    def test_request_to_db(self):
        Ces4Data.ces4_request()
        count_check = {
            'fresno': 199,
            'tulare': 78,
            'kings': 27,
            'kern': 151,
            'san joaquin': 139,
            'stanislaus': 94,
            'merced': 49,
            'madera': 23,            
        }
        for county, count in count_check.items():
            assert count == Ces4.objects.filter(county=county).count()
        total = Ces4.objects.count()
        assert 760 == total
        