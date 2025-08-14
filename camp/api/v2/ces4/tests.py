from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import TestCase
from django.urls import reverse

from camp.apps.integrate.ces4.models import Record
from camp.apps.regions.models import Boundary, Region


def create_test_boundary(version):
    region = Region.objects.create(
        name="Test Region",
        slug="test-region",
        type=Region.Type.TRACT
    )
    poly = Polygon((
        (0, 0),
        (0, 1),
        (1, 1),
        (1, 0),
        (0, 0)
    ))
    mpoly = MultiPolygon(poly)
    boundary = Boundary.objects.create(
        region=region,
        version=version,
        geometry=mpoly,
        metadata={}
    )
    region.boundary = boundary
    region.save()
    return boundary


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
    params = {f.name: 0 for f in Record._meta.get_fields()}
    params['objectid'] = id
    params['pol_pm'] = pm
    params['pol_pm_p'] = pm_p
    params['boundary'] = create_test_boundary("2020")
    return Record.objects.create(**params)


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
        assert int(response.json()['data'][0]['objectid']) == self.ces4_1.pk
        assert response.json()['data'][0]['pol_pm'] == self.ces4_1.pol_pm
        
    def test3_list(self):
        url = reverse("api:v2:ces4:ces4-list")
        url += "?pol_pm_p=.3"
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()['data']) == 1
        assert int(response.json()['data'][0]['objectid']) == self.ces4_2.pk
        assert response.json()['data'][0]['pol_pm_p'] == self.ces4_2.pol_pm_p
        
    def test4_list(self):
        url = reverse("api:v2:ces4:ces4-list")
        url += "?pol_ozone__gt=0"
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()['data']) == 0
        
    def test5_list(self):
        url = reverse("api:v2:ces4:ces4-list")
        url += "?boundary__version=2020"
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()['data']) == 3
        
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
        assert int(response.json()['data']['objectid']) == self.ces4_1.pk
        assert response.json()['data']['pol_pm'] == self.ces4_1.pol_pm
        
    def test2_detail(self):
        url = reverse("api:v2:ces4:ces4-detail", kwargs={'pk':5})
        response = self.client.get(url)
        assert response.status_code == 404
