import geopandas as gpd
from datetime import timedelta

from django.contrib.gis.geos import GEOSGeometry
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from shapely.wkt import loads as load_wkt
from django.core.exceptions import ValidationError

from camp.apps.integrate.hms_smoke.data import get_smoke_file, to_db
from camp.apps.integrate.hms_smoke.models import Smoke
from camp.apps.integrate.hms_smoke.tasks import fetch_files
from camp.utils.counties import County


def create_smoke_objects(density, start, end):
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
    if start == -1:
        start = timezone.now() - timedelta(hours=2)
    else:
        start = timezone.now() + timedelta(hours=1)
    if end == -1:
        end = timezone.now() - timedelta(hours=1)
    else:
        end = timezone.now() + timedelta(hours=2)
    
    satellite = "TestSatellite"
    timestamp = timezone.now().replace(minute=0, second=0, microsecond=0)
    smoke = Smoke(density=density.lower().strip(),end=end,start=start,satellite=satellite, geometry=geometry, timestamp=timestamp)
    smoke.full_clean()
    smoke.save()
    return smoke
    


class Tests_SmokeFilter(TestCase):
    """
    setUp - create objects for testing
            smoke1 - ongoing
            smoke1 - light - default from not one of the choice values 
            smoke2 - medium
            smoke3 - 
    test1 - query for satellite__exact = TestSatellite1, returns smoke1
    test2 - query for a start time gte the current time, returns smoke3
    test3 - query for density iexact = LIGHT, returns smoke1
    test4 - query for exact time for smoke 2, returns smoke2, need seconds and microseconds to be equal
    test5 - query for heavy, but remove heavy from smoke 3 - returns empty
    """
    def setUp(self):
        self.smoke1 = create_smoke_objects("Light", -1, 1) #This will default to 'light'
        self.smoke2 = create_smoke_objects("MEDIUM", -1, -1)
        self.smoke3 = create_smoke_objects("Heavy", 1, 1)
        
    def test1_smoke_filter_view(self):
        self.smoke1.satellite = "TestSatellite1"
        self.smoke1.save()
        url = reverse("api:v1:hms_smoke:smoke-list")
        url_with_params = f"{url}?satellite=TestSatellite1"
        
        response = self.client.get(url_with_params)
        
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]['id'] == str(self.smoke1.id)
        assert response.json()["data"][0]['density'] == 'light'

    def test2_smoke_filter_view(self):
        url = reverse("api:v1:hms_smoke:smoke-list")
        time = timezone.now().strftime('%Y-%m-%dT%H:%M:%S')
        url_with_params = f"{url}?start__gte={time}"
        
        response = self.client.get(url_with_params)
        
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]['id'] == str(self.smoke3.id)
               
    def test3_smoke_filter_view(self):
        url = reverse("api:v1:hms_smoke:smoke-list")
        url_with_params = f"{url}?density__iexact=LIGHT"
        
        response = self.client.get(url_with_params)
       
        assert response.status_code == 200
        print(response.json())
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]['id'] == str(self.smoke1.id)

    def test4_smoke_filter_view(self):
        url = reverse("api:v1:hms_smoke:smoke-list")
        time = self.smoke2.end.strftime('%Y-%m-%dT%H:%M:%S:%f')
        url_with_params = f"{url}?end={time}"
        
        response = self.client.get(url_with_params)
        
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]['id'] == str(self.smoke2.id)
    
    def test3_smoke_filter_view(self):
        self.smoke3.density ='NotHeavy'
        self.smoke3.save()
        url = reverse("api:v1:hms_smoke:smoke-list")
        url_with_params = f"{url}?density__iexact=heavy"
        
        response = self.client.get(url_with_params)
       
        assert response.status_code == 200
        assert len(response.json()["data"]) == 0
        

class Tests_OngoingSmoke(TestCase):
    """
    setUp - create objects for testing
            smoke1 - light, ongoing
            smoke2 - medium
            smoke3 - heavy
            smoke4 - light, ongoing
    test1 - query for ongoing, which is only smoke 1, set smoke4 to previous query + ongoing so it won't return
    test2 - query for ongoing, add smoke2 to ongoing, returns smoke1 + 2
    test3 - query for ongoing, filtering for medium, returns smoke2
    test4 - query for ongoing, filtering for heavy, returns empty queryset
    """
    def setUp(self): 
        self.smoke1 = create_smoke_objects("Light", -1, 1)
        self.smoke2 = create_smoke_objects("MEDIUM", -1, -1)
        self.smoke3 = create_smoke_objects("Heavy", 1, 1)
        self.smoke4 = create_smoke_objects("light", -1, 1)
        
        self.smoke4.timestamp = timezone.now() - timedelta(hours=1)
        self.smoke4.save()
        
    def test1_ongoing_smoke(self):
        url = reverse("api:v1:hms_smoke:smoke-ongoing")
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
        assert response.json()['data'][0]['density'].lower() == 'light'
        assert response.json()['data'][0]["id"] == str(self.smoke1.id)
        
    def test2_ongoing_smoke(self):
        ongoing_end = timezone.now() + timedelta(hours=1)
        self.smoke2.end = ongoing_end
        self.smoke2.save()
        url = reverse("api:v1:hms_smoke:smoke-ongoing")
        response = self.client.get(url)
         
        assert response.status_code == 200
        assert len(response.json()["data"]) == 2
        for feature in response.json()["data"]:
            if feature['density'].lower() == 'light':
                assert feature["id"] == str(self.smoke1.id)
            if feature['density'].lower() == 'medium':
                assert feature["id"] == str(self.smoke2.id)
                
    def test3_ongoing_smoke(self):
        ongoing_end = timezone.now() + timedelta(hours=1)
        self.smoke2.end = ongoing_end
        self.smoke2.save()
        url = reverse("api:v1:hms_smoke:smoke-ongoing")
        final_url = f'{url}?density=medium'
        response = self.client.get(final_url)
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
        assert response.json()['data'][0]['density'] == 'medium'
        assert response.json()['data'][0]["id"] == str(self.smoke2.id)
        
    def test4_ongoing_smoke(self):
        url = reverse("api:v1:hms_smoke:smoke-ongoing")
        final_url = f'{url}?density=heavy'
        response = self.client.get(final_url)
        assert response.status_code == 200
        assert len(response.json()["data"]) == 0                
       
        
class Tests_DetailSmoke(TestCase):
    """
    setUp - create objects for testing
            smoke1,4,5 - ongoing
            smoke1 - light
            smoke2,4 - medium
            smoke3,5 - heavy
            smoke2,5 - before latest obs
    test1 - query for smoke by small_uuid, specifically smoke 1
            only returned one object so not a list
    test2 - query for a small_uuid that doesnt exist, returns 404
    
    """
    def setUp(self):
        self.smoke1 = create_smoke_objects("Light", -1, 1)
        self.smoke2 = create_smoke_objects("MEDIUM", -1, -1)
        self.smoke3 = create_smoke_objects("Heavy", 1, 1)
        self.smoke4 = create_smoke_objects("MEDIUM", -1, 1)
        self.smoke5 = create_smoke_objects("Heavy", -1, 1)
        
    #returns 
    def test1_detail_smoke(self):
        url = reverse("api:v1:hms_smoke:smoke-detail", kwargs={'smoke_id':self.smoke1.id})
        response = self.client.get(url)
        
        assert response.status_code == 200
        assert response.json()["data"]["id"] == str(self.smoke1.id)
        
    def test2_detail_smoke(self):
        url = reverse("api:v1:hms_smoke:smoke-detail", kwargs={'smoke_id':"gQ7rC18FRKuu15z9m2CsFm"})
        response = self.client.get(url)
        
        assert response.status_code == 404
           
        
class Tests_Miscellaneous(TestCase):
    """
    setUp - create objects for testing
        smoke1,4,5 - ongoing
        smoke1 - light
        smoke2,4 - medium
        smoke3,5 - heavy
        smoke2,5 - before latest obs
    
    test  - full_clean() from TextChoiceModel throws error from wrong input
    test1 - not in SJV so should return false
    test2 - in SJV so should return true
    
    """
        
    def setUp(self):  
        self.smoke1 = create_smoke_objects("Light", -1, 1)
        self.smoke2 = create_smoke_objects("MEDIUM", -1, -1)
        self.smoke3 = create_smoke_objects("Heavy", 1, 1)
        self.smoke4 = create_smoke_objects("MEDIUM", -1, 1)
        self.smoke5 = create_smoke_objects("Heavy", -1, 1)
      
    def test_full_clean_test(self):
        #confirms that a validation error from smoke.full_clean() occurs
        with self.assertRaises(ValidationError):
            create_smoke_objects('Light1',-1,-1)
            
    def test1_only_SJV_counties(self):
        polygon_wkt = "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"
        geometry = load_wkt(polygon_wkt)
        #If the county is not within the SJV return it does not need to be added
        if not County.in_SJV(geometry):
            assert 1 == 1
        else:
            assert 1 == 2
        
    def test2_only_SJV_counties(self):
        #Smoke1 format is <class 'django.contrib.gis.geos.polygon.Polygon'>
        #SRID=4326;POLYGON ((-119.860839 36.660399, -119.860839 36.905755, -119.650879 36.905755, -119.650879 36.660399, -119.860839 36.660399))
        #Need to convert to shapely to use shapely intersects(), so strip everything before polygon to get a proper str to load_wkt()
        geoStr = str(self.smoke1.geometry)[10:]
        if County.in_SJV(load_wkt(geoStr)):
            assert 1 == 1
        else: 
            assert 1 == 2    
        
        
class FetchFilesTaskTest(TestCase):
    """
    These Tests should be monitored through print statements
    test_fetch_files_triggers_file_download:
        Tests gathering data for todays date (use -s to check print statements)
    test_get_smoke_file:
        Tests getting the smoke file, which is the function in the fetch files (just in case logic is needed in fetch files)
    test_to_db_SJV:
        valid object, should add
    test_to_db_notSJV:
        bad data, polygon not in SJV should return 
    """
    def test_fetch_files_triggers_file_download(self):
        fetch_files(timezone.now())
        
    def test_get_smoke_file(self):
        get_smoke_file(timezone.now()-timedelta(days=1))
        
    def test_to_db_SJV(self):
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
        to_db(input.iloc[0], timezone.now())
        
    def test_to_db_notSJV(self):
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
         to_db(input.iloc[0], timezone.now())
        