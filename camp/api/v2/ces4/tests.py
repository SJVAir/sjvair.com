from django.contrib.gis.geos import GEOSGeometry
from django.test import TestCase
from django.urls import reverse
from shapely.wkt import loads as load_wkt

from camp.utils.counties import County
from camp.apps.integrate.ces4.models import Tract

def create_test_ces4_obj(id, pm, pm_p):
    polygon_wkt = (
        "MULTIPOLYGON((("
        "-119.860839 36.660399, "
        "-119.860839 36.905755, "
        "-119.650879 36.905755, "
        "-119.650879 36.660399, "
        "-119.860839 36.660399"
        ")))"
    )
    geometry = GEOSGeometry(polygon_wkt, srid=4326)
    county = County.in_SJV(load_wkt(geometry.wkt))
    params = {f.name: 0 for f in Tract._meta.get_fields()}
    params['objectid'] = id
    params['pol_pm'] = pm
    params['pol_pm_p'] = pm_p
    params['county'] = county
    params['geometry'] = geometry
    return Tract.objects.create(**params)


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
        url = reverse("api:v2:ces4:ces4-list")
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()['data']) == 3
    
    def test2_list(self):
        url = reverse("api:v2:ces4:ces4-list")
        url += "?pol_pm__gt=1.111"
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()['data']) == 1
        assert response.json()['data'][0]['objectid'] == self.ces4_1.pk
        assert response.json()['data'][0]['pol_pm'] == self.ces4_1.pol_pm
        
    def test3_list(self):
        url = reverse("api:v2:ces4:ces4-list")
        url += "?pol_pm_p=.3"
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()['data']) == 1
        assert response.json()['data'][0]['objectid'] == self.ces4_2.pk
        assert response.json()['data'][0]['pol_pm_p'] == self.ces4_2.pol_pm_p
        
    def test4_list(self):
        url = reverse("api:v2:ces4:ces4-list")
        url += "?pol_ozone__gt=0"
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
        url = reverse("api:v2:ces4:ces4-detail", kwargs={'pk':self.ces4_1.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.json()['data']['objectid'] == self.ces4_1.pk
        assert response.json()['data']['pol_pm'] == self.ces4_1.pol_pm
        
    def test2_detail(self):
        url = reverse("api:v2:ces4:ces4-detail", kwargs={'pk':5})
        response = self.client.get(url)
        assert response.status_code == 404
