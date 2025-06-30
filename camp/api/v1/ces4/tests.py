from django.contrib.gis.geos import GEOSGeometry
from django.test import TestCase
from django.urls import reverse
from shapely.wkt import loads as load_wkt

from camp.utils.counties import County
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
