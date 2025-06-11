from django.test import TestCase
from django.urls import reverse
from ....apps.integrate.hms_smoke.models import Smoke
from datetime import timedelta
from django.contrib.gis.geos import GEOSGeometry
from shapely.wkt import loads as load_wkt
import geopandas as gpd
from django.utils import timezone


#create test objects here
def CreateSmokeObjects(density, start, end):
    """
    create smoke objects for testing, use artificial geometry and a before/after 
    current time for start and end times.
    Satellite/fid are not important for testing

    Args:
        density (str): density of smoke can be light, medium, heavy
        start (int): describes whether the time is before or after current
        end (int): describes whether the time is before or after current

    Returns:
        Smoke Object(
    """
    #Geometry object
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
    if start ==-1:
        start = timezone.now() - timedelta(hours=2)
    else:
        start = timezone.now() + timedelta(hours=1)
    if end ==-1:
        end = timezone.now() - timedelta(hours=1)
    else:
        end = timezone.now() + timedelta(hours=2)
    
    satellite = "TestSatellite"
    
    
    return Smoke.objects.create(density=density,end=end,start=start,satellite=satellite, geometry=geometry)




class Tests_O(TestCase):
    def setUp(self):
        #ONLY SMOKE1 SHOULD RETURN 
        """
    setUp - create objects for testing
            smoke1- ongoing
            smoke1 - light
            smoke2 = medium
            smoke3 =heavy
    test1 - query for ongoing, which is only smoke 1
   
    
    """
        self.smoke1 = CreateSmokeObjects("Light", -1, 1)
        self.smoke2 = CreateSmokeObjects("MEDIUM", -1, -1)
        self.smoke3 = CreateSmokeObjects("Heavy", 1, 1)
        
    def test1_SmokeView(self):
        print("ID: ",self.smoke1.id, type(self.smoke1.id))
        self.smoke1.satellite = "TestSatellite1"
        self.smoke1.save()
        url = reverse("api:v1:hms_smoke:smoke-list")
        url_with_params = f"{url}?satellite=TestSatellite1"
        
        response = self.client.get(url_with_params)
        #print("RESPONSE:", response.status_code, response.content)
        
        assert response.status_code == 200
        assert len(response.json()["data"])==1
        assert response.json()["data"][0]['id'] == str(self.smoke1.id)

    def test2_SmokeView(self):
        print("ID: ",self.smoke1.id, type(self.smoke1.id))
        url = reverse("api:v1:hms_smoke:smoke-list")
        time = timezone.now().strftime('%Y-%m-%dT%H:%M:%S')
        url_with_params = f"{url}?start__gte={time}"
        
        response = self.client.get(url_with_params)
        #print("RESPONSE:", response.status_code, response.content)
        
        assert response.status_code == 200
        assert len(response.json()["data"])==1
        assert response.json()["data"][0]['id'] == str(self.smoke3.id)
    def test3_SmokeView(self):
        print("ID: ",self.smoke1.id, type(self.smoke1.id))
        url = reverse("api:v1:hms_smoke:smoke-list")
        url_with_params = f"{url}?density__iexact=light"
        
        response = self.client.get(url_with_params)
        #print("RESPONSE:", response.status_code, response.content)
        
        assert response.status_code == 200
        assert len(response.json()["data"])==1
        assert response.json()["data"][0]['id'] == str(self.smoke1.id)

    def test4_SmokeView(self):
        print("ID: ",self.smoke1.id, type(self.smoke1.id))
        url = reverse("api:v1:hms_smoke:smoke-list")
        #time = timezone.now() + timedelta(hours=2)
        time = self.smoke2.end.strftime('%Y-%m-%dT%H:%M:%S:%f')
        url_with_params = f"{url}?end={time}"
        
        response = self.client.get(url_with_params)
        print("RESPONSE:", response.status_code, response.content)
        
        assert response.status_code == 200
        assert len(response.json()["data"])==1
        assert response.json()["data"][0]['id'] == str(self.smoke2.id)
    








#TESTS OngoingSmokeView
class Tests_OngoingSmokeView(TestCase):
    def setUp(self):
        #ONLY SMOKE1 SHOULD RETURN 
        """
    setUp - create objects for testing
            smoke1- ongoing
            smoke1 - light
            smoke2 = medium
            smoke3 =heavy
    test1 - query for ongoing, which is only smoke 1
   
    
    """
        self.smoke1 = CreateSmokeObjects("Light", -1, 1)
        self.smoke2 = CreateSmokeObjects("MEDIUM", -1, -1)
        self.smoke3 = CreateSmokeObjects("Heavy", 1, 1)
        
    def test_OngoingSmokeView(self):
        print("ID: ",self.smoke1.id, type(self.smoke1.id))
        url = reverse("api:v1:hms_smoke:smoke-ongoing")
        response = self.client.get(url)
        
        assert response.status_code == 200
        assert len(response.json()["data"])==1
        assert response.json()['data'][0]['density'].lower() == 'light'
        assert response.json()['data'][0]["id"] == str(self.smoke1.id)
        
    def test2_OngoingSmokeView(self):
        ongoing_end = timezone.now() + timedelta(hours=1)
        self.smoke2.end = ongoing_end
        self.smoke2.save()
        
        url = reverse("api:v1:hms_smoke:smoke-ongoing")
        response = self.client.get(url)
        
        
        assert response.status_code == 200
        assert len(response.json()["data"])==2
        for feature in response.json()["data"]:
            if feature['density'].lower() == 'light':
                assert feature["id"] == str(self.smoke1.id)
            if feature['density'].lower() == 'medium':
                assert feature["id"] == str(self.smoke2.id)
                
                
#TESTS OngoingSmokeDensityView
class Tests_OngoingSmokeDensityView(TestCase):
    """
    setUp - create objects for testing
            smoke1,4,5- ongoing
            smoke1 - light
            smoke2,4 = medium
            smoke3,5 =heavy
    test1 - query for light and medium, that are ongoing
            returns only smoke 1 and 4
    test2 - query for heavy, ongoing
            returns only smoke 5
    test3 - empty query 
            returns empty features
    """
    def setUp(self):
        self.smoke1 = CreateSmokeObjects("LIGHT", -1, 1)
        self.smoke2 = CreateSmokeObjects("medium", -1, -1)
        self.smoke3 = CreateSmokeObjects("heavy", 1, 1)
        self.smoke4 = CreateSmokeObjects("medium", -1, 1)
        self.smoke5 = CreateSmokeObjects("heavy", -1, 1)
    #Query for smoke 1 and 4 (light and medium)
    def test1_OngoingSmokeDensityView(self):
        url = reverse("api:v1:hms_smoke:smoke-ongoing")
        url_with_params = f"{url}?density__iexact=lighT"
        #Test to make sure it returns by end time
        self.smoke4.end = timezone.now() + timedelta(hours=3)
        self.smoke4.save()
        response = self.client.get(url_with_params)
        print("RESPONSE:", response.status_code, response.content)
        
        assert response.status_code == 200
        assert len(response.json()["data"])==1
        for feature in response.json()['data']:
            if feature['density'].lower() =='light':
                assert feature["id"] == str(self.smoke1.id)
            else:
                assert 1==2 # A HEAVY/MEDIUM DENSITY WAS QUERIED
        
    
    #Query for heavy densities      
    def test2_OngoingSmokeDensityView(self):
        url = reverse("api:v1:hms_smoke:smoke-ongoing")
        url_with_params = f"{url}?density__iexact=heavy"
        response = self.client.get(url_with_params)
        
        
        assert response.status_code == 200
        assert len(response.json()["data"])==1
        assert response.json()['data'][0]['density'].lower() == 'heavy'
    
    
    #No density should return no smokes      
    def test3_OngoingSmokeDensityView(self):
        url = reverse("api:v1:hms_smoke:smoke-ongoing")
        url_with_params = f"{url}?density__iexact=MEDIUM"
        
        response = self.client.get(url_with_params)
        
        assert response.status_code == 200
        assert len(response.json()["data"])==1
        for feature in response.json()['data']:
            if feature['density'] =='medium':
                assert feature["id"] == str(self.smoke4.id)
            else:
                assert 1==2 # A HEAVY/LIGHT DENSITY WAS QUERIED
        
        
class Tests_SelectSmokeView(TestCase):
    """
    setUp - create objects for testing
            smoke1,4,5- ongoing
            smoke1 - light
            smoke2,4 = medium
            smoke3,5 =heavy
            smoke2,5 = before latest obs
    test1 - query for smoke by small_uuid, specifically smoke 1
            only returned one object so not a list
    
    """
    def setUp(self):
        self.smoke1 = CreateSmokeObjects("Light", -1, 1)
        self.smoke2 = CreateSmokeObjects("MEDIUM", -1, -1)
        self.smoke3 = CreateSmokeObjects("Heavy", 1, 1)
        self.smoke4 = CreateSmokeObjects("MEDIUM", -1, 1)
        self.smoke5 = CreateSmokeObjects("Heavy", -1, 1)
        
    #returns 
    def test1_SelectSmokeView(self):
        url = reverse("api:v1:hms_smoke:smoke-detail", kwargs={'smoke_id':self.smoke1.id})
        response = self.client.get(url)
        
        assert response.status_code == 200
        assert response.json()["data"]["id"] == str(self.smoke1.id)
    def test2_SelectSmokeView(self):
        url = reverse("api:v1:hms_smoke:smoke-detail", kwargs={'smoke_id':"gQ7rC18FRKuu15z9m2CsFm"})
        response = self.client.get(url)
        
        assert response.status_code == 404
           
        
class Tests_Miscellaneous(TestCase):
    
    def setUp(self):
        self.smoke1 = CreateSmokeObjects("Light", -1, 1)
        self.smoke2 = CreateSmokeObjects("MEDIUM", -1, -1)
        self.smoke3 = CreateSmokeObjects("Heavy", 1, 1)
        self.smoke4 = CreateSmokeObjects("MEDIUM", -1, 1)
        self.smoke5 = CreateSmokeObjects("Heavy", -1, 1)
      
    def test_OnlySJVShapes(self):
        from ....utils.counties import County
        
        polygon_wkt = "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"
        geometry = load_wkt(polygon_wkt)
        #If the county is not within the SJV return it does not need to be added
        if not County.in_SJV(geometry):
            assert 1==1
        else:
            assert 1==2
        
        #Smoke1 format is <class 'django.contrib.gis.geos.polygon.Polygon'>
        #SRID=4326;POLYGON ((-119.860839 36.660399, -119.860839 36.905755, -119.650879 36.905755, -119.650879 36.660399, -119.860839 36.660399))
        
        #Need to convert to shapely to use shapely intersects(), so strip everything before polygon to get a proper str to load_wkt()
        geoStr = str(self.smoke1.geometry)[10:]
        if County.in_SJV(load_wkt(geoStr)):
            assert 1==1
        else: 
            assert 1==2    
        

class FetchFilesTaskTest(TestCase):
    def test_fetch_files_triggers_file_download(self):
        from camp.apps.integrate.hms_smoke.tasks import fetch_files
        fetch_files(timezone.now())
        
    def test_get_smoke_file(self):
        from camp.apps.integrate.hms_smoke.data import get_smoke_file
        get_smoke_file(timezone.now()-timedelta(days=1))
        
        
    def test_to_db1(self):
        from camp.apps.integrate.hms_smoke.data import to_db
        polygon_wkt = (
                        "POLYGON(("
                        "-119.860839 36.660399, "
                        "-119.860839 36.905755, "
                        "-119.650879 36.905755, "
                        "-119.650879 36.660399, "
                        "-119.860839 36.660399"
                        "))"
                    )

        geometry = load_wkt(polygon_wkt) 
        input = [{
                "geometry": geometry,
                "Density": "Light",
                "End":"202515 1440",
                "Start": "202515 1540",
                "Satellite": "GOES-WEST",
                }]
        input = gpd.GeoDataFrame(input)
        to_db(input.iloc[0])
    def test_to_db_notSJV(self):
         from camp.apps.integrate.hms_smoke.data import to_db
         polygon_wkt = ("POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))")

         geometry = load_wkt(polygon_wkt) 
         input = [{
                "geometry": geometry,
                "Density": "Light",
                "End":"202515 1440",
                "Start": "202515 1540",
                "Satellite": "GOES-WEST",
                }]
         input = gpd.GeoDataFrame(input)
         to_db(input.iloc[0])
        

        
        
        