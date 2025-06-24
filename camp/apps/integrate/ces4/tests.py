from django.contrib.gis.geos import GEOSGeometry
from django.test import TestCase
from django.urls import reverse
from shapely.wkt import loads as load_wkt

from camp.utils.counties import County
from camp.apps.integrate.ces4.data import Ces4Processing
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
        pollution=0, pollutionP=0,
        county=county, geometry=geometry,
        )
    
class Tests_CES4List(TestCase):
    """
    test1 - get all data points, returns all 3 objects
    test2 - query all objects with pm gt 1.111, returns object 1
    test3 - query all objects with pmP equal to .3, returns object 2
    test4 - query all objects with ozone gt 0, returns empty list
    """
    def setUp(self):
        self.ces4_1 = create_test_ces4_obj(1, 2.1, .65)
        self.ces4_2 = create_test_ces4_obj(2, .89, .3)
        self.ces4_3 = create_test_ces4_obj(3, .1, .05)
    
    def test1_list(self):
        url = reverse("api:v1:ces4:ces4-list")
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()['data']) == 3
    
    def test2_list(self):
        url = reverse("api:v1:ces4:ces4-list")
        url += "?pm__gt=1.111"
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()['data']) == 1
        assert response.json()['data'][0]['OBJECTID'] == self.ces4_1.OBJECTID
        assert response.json()['data'][0]['pm'] == self.ces4_1.pm
        
    def test3_list(self):
        url = reverse("api:v1:ces4:ces4-list")
        url += "?pmP=.3"
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()['data']) == 1
        assert response.json()['data'][0]['OBJECTID'] == self.ces4_2.OBJECTID
        assert response.json()['data'][0]['pmP'] == self.ces4_2.pmP
        
    def test4_list(self):
        url = reverse("api:v1:ces4:ces4-list")
        url += "?ozone__gt=0"
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()['data']) == 0
        
        
class Tests_CES4Detail(TestCase):
    """
    test1 - query for objectID = 1, returns object 1
    test2 - query for ObjectID = 5, 404 error because not founde
    """
    def setUp(self):
        self.ces4_1 = create_test_ces4_obj(1, 2.1, .65)
        self.ces4_2 = create_test_ces4_obj(2, .89, .3)
        self.ces4_3 = create_test_ces4_obj(3, .1, .05)
        
    def test1_detail(self):
        url = reverse("api:v1:ces4:ces4-detail", kwargs={'pk':self.ces4_1.OBJECTID})
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.json()['data']['OBJECTID'] == self.ces4_1.OBJECTID
        assert response.json()['data']['pm'] == self.ces4_1.pm
        
    def test2_detail(self):
        url = reverse("api:v1:ces4:ces4-detail", kwargs={'pk':5})
        response = self.client.get(url)
        assert response.status_code == 404


class Tests_CES4_Miscellaneous(TestCase):
    """
    inSJV - tests if fresno + tulare polygons are returned with the respective names + not false 
    """
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
    
    def test_static_to_db(self):
        Ces4Processing.ces4_to_db()
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
        
        
    def test_request_to_db(self):
        Ces4Processing.ces4_request_db()
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
        