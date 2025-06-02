from django.test import TestCase

# Create your tests here.
#TODO Rewrite Testcases from APITestCase to TestCase (Test local then add to git)

from django.test import TestCase
from django.urls import reverse
from ....apps.monitors.hms_smoke.models import Smoke
from datetime import datetime, timedelta
from django.contrib.gis.geos import GEOSGeometry
from datetime import timezone
from shapely.wkt import loads as load_wkt

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
        start = datetime.now(timezone.utc) - timedelta(hours=2)
    else:
        start = datetime.now(timezone.utc) + timedelta(hours=1)
    if end ==-1:
        end = datetime.now(timezone.utc) - timedelta(hours=1)
    else:
        end = datetime.now(timezone.utc) + timedelta(hours=2)
    
    FID = "0"
    satellite = "TestSatellite"
    observation_time = datetime.now(timezone.utc)
    
    return Smoke.objects.create(density=density,end=end,start=start,FID=FID,satellite=satellite, geometry=geometry, observation_time = observation_time)


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
        
        url = reverse("api:v1:hms_smoke:ongoing_smoke")
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()["data"])==1
        assert response.json()['data'][0]['density'].lower() == 'light'
        assert response.json()['data'][0]["id"] == str(self.smoke1.id)
    def test2_OngoingSmokeView(self):
        ongoing_end = datetime.now(timezone.utc) + timedelta(hours=1)
        self.smoke2.end = ongoing_end
        self.smoke2.save
        
        url = reverse("api:v1:hms_smoke:ongoing_smoke")
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()["data"])==1
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
        self.smoke1 = CreateSmokeObjects("light", -1, 1)
        self.smoke2 = CreateSmokeObjects("medium", -1, -1)
        self.smoke3 = CreateSmokeObjects("heavy", 1, 1)
        self.smoke4 = CreateSmokeObjects("medium", -1, 1)
        self.smoke5 = CreateSmokeObjects("heavy", -1, 1)
    #Query for smoke 1 and 4 (light and medium)
    def test1_OngoingSmokeDensityView(self):
        url = reverse("api:v1:hms_smoke:ongoing_smoke_density")
        url_with_params = f"{url}?density=light&density=medium"
        #Test to make sure it returns by end time
        newdate = datetime.now(timezone.utc) + timedelta(hours=3)
        self.smoke4.end = newdate
        self.smoke4.save()
        response = self.client.get(url_with_params)
    
        
        assert response.status_code == 200
        assert len(response.json()["data"])==2
        for feature in response.json()['data']:
            if feature['density'].lower() =='light':
                assert feature["id"] == str(self.smoke1.id)
            elif feature['density'].lower() =='medium':
                assert feature["id"] == str(self.smoke4.id)
            else:
                assert 1==2 # A HEAVY DENSITY WAS QUERIED
        
    
    #Query for heavy densities      
    def test2_OngoingSmokeDensityView(self):
        url = reverse("api:v1:hms_smoke:ongoing_smoke_density")
        url_with_params = f"{url}?density=heavy"
        response = self.client.get(url_with_params)
        
        
        assert response.status_code == 200
        assert len(response.json()["data"])==1
        assert response.json()['data'][0]['density'].lower() == 'heavy'
    
    #No density should return no smokes      
    def test3_OngoingSmokeDensityView(self):
        url = reverse("api:v1:hms_smoke:ongoing_smoke_density")
        response = self.client.get(url)
        
        
        assert response.status_code == 200
        assert len(response.json()['data'])==0
        

class Tests_LatestObeservableSmokeView(TestCase):
    """
    setUp - create objects for testing
            smoke1,4,5- ongoing
            smoke1 - light
            smoke2,4 = medium
            smoke3,5 =heavy
            smoke1,5 = before latest obs
    test1 - query for latest observation smokes
    
    """
    def setUp(self):
        self.smoke1 = CreateSmokeObjects("light", -1, 1)
        self.smoke2 = CreateSmokeObjects("medium", -1, -1)
        self.smoke3 = CreateSmokeObjects("light", 1, 1)
        self.smoke4 = CreateSmokeObjects("medium", -1, 1)
        self.smoke5 = CreateSmokeObjects("heavy", -1, 1)
        
        pre_obs = datetime.now(timezone.utc) - timedelta(hours=2)
        
        self.smoke1.observation_time=pre_obs
        self.smoke1.save()
        self.smoke4.observation_time=pre_obs
        self.smoke4.save()
        
    def test1_LatestObeservableSmokeView(self):
        url = reverse("api:v1:hms_smoke:last_observable_smoke")
        response = self.client.get(url)
        
        assert response.status_code == 200
        assert len(response.json()['data']) == 3
        for feature in response.json()['data']:
            if feature['density'].lower() =='light':
                assert feature["id"] == str(self.smoke3.id)
            if feature['density'].lower() =='medium':
                assert feature["id"] == str(self.smoke2.id)
            if feature['density'].lower() =='heavy':
                assert feature["id"] == str(self.smoke5.id)

class Tests_LatestObeservableSmokeDensityView(TestCase):
    """
    setUp - create objects for testing
            smoke1,4,5- ongoing
            smoke1 - light
            smoke2,4 = medium
            smoke3,5 =heavy
            smoke2,5 = before latest obs
    test1 - query for light and medium, that are latest observation
            returns only smoke 4, and 1
    test2 - query for heavy, latest
            returns only smoke 4
    test3 - empty query 
            returns empty features
    
    """
    def setUp(self):
        self.smoke1 = CreateSmokeObjects("light", -1, 1)
        self.smoke2 = CreateSmokeObjects("medium", -1, -1)
        self.smoke3 = CreateSmokeObjects("heavy", 1, 1)
        self.smoke4 = CreateSmokeObjects("medium", -1, 1)
        self.smoke5 = CreateSmokeObjects("heavy", -1, 1)
        
        pre_obs = datetime.now(timezone.utc) - timedelta(hours=2)
        
        self.smoke2.observation_time=pre_obs
        self.smoke2.save()
        self.smoke5.observation_time=pre_obs
        self.smoke5.save()
        
    def test1_LatestObeservableSmokeDensityView(self):
        url = reverse("api:v1:hms_smoke:last_observable_smoke_density")
        url_with_params = f"{url}?density=light&density=medium"
        response = self.client.get(url_with_params)
    
        assert response.status_code == 200
        assert len(response.json()["data"])==2
        for feature in response.json()['data']:
            assert feature['density'].lower() != 'heavy'
            if feature['density'].lower() =='light':
                assert feature["id"]== str(self.smoke1.id)
            if feature['density'].lower() =='medium':
                assert feature["id"]== str(self.smoke4.id)
    #Query for heavy densities      
    def test2_LatestObeservableSmokeDensityView(self):
        url = reverse("api:v1:hms_smoke:last_observable_smoke_density")
        url_with_params = f"{url}?density=heavy"
        response = self.client.get(url_with_params)
        
      
        assert response.status_code == 200
        assert len(response.json()["data"])>0
        for item in response.json()["data"]:
            assert item['density'].lower() == 'heavy'
        assert response.json()["data"][0]["id"] == str(self.smoke3.id)
    
    #No density should return no smokes      
    def test3_LatestObeservableSmokeDensityView(self):
        url = reverse("api:v1:hms_smoke:last_observable_smoke_density")
        response = self.client.get(url)
        
        assert response.status_code == 200
        assert len(response.json()["data"])==0   
        
        
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
        url = reverse("api:v1:hms_smoke:smoke_by_id", kwargs={'pk':self.smoke1.id})
        response = self.client.get(url)
        
        assert response.status_code == 200
        assert response.json()["data"]["id"] == str(self.smoke1.id)
    def test2_SelectSmokeView(self):
        url = reverse("api:v1:hms_smoke:smoke_by_id", kwargs={'pk':"aaaaaa"})
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
        #geometry = GEOSGeometry(polygon_wkt, srid=4326)
        geometry = load_wkt(polygon_wkt)
        print(type(geometry))
        #If the county is not within the SJV return it does not need to be added
        if not County.within_SJV(geometry):
            assert 1==1
        else:
            assert 1==2
        print(type(self.smoke1.geometry))
        
        #Smoke1 format is <class 'django.contrib.gis.geos.polygon.Polygon'>
        #SRID=4326;POLYGON ((-119.860839 36.660399, -119.860839 36.905755, -119.650879 36.905755, -119.650879 36.660399, -119.860839 36.660399))
        
        #Need to convert to shapely to use shapely intersects(), so strip everything before polygon to get a proper str to load_wkt()
        geoStr = str(self.smoke1.geometry)[10:]
        if County.within_SJV(load_wkt(geoStr)):
            assert 1==1
        else: 
            assert 1==2    
        
    def test_all_by_timestamp(self):
        
        timestampChange = datetime.now(timezone.utc) + timedelta(hours=1)
        self.smoke3.observation_time = timestampChange
        self.smoke3.save()
        
        url = reverse("api:v1:hms_smoke:all_by_timestamp")
        response = self.client.get(url)
        
        assert response.status_code == 200
        assert len(response.json()["data"])==5
        assert response.json()["data"][0]['id'] ==str(self.smoke3.id)
    
    

#THESE TESTS ARE TIME SENSITIVE, IF TOO CLOSE TO 00:00 UTC TESTS WILL FAIL
class Test_TimeFilterQuery(TestCase):
    
    def setUp(self):
        self.smoke1 = CreateSmokeObjects("Light", -1, 1)
        self.smoke2 = CreateSmokeObjects("MEDIUM", -1, -1)
        self.smoke3 = CreateSmokeObjects("Heavy", 1, 1)
        self.smoke4 = CreateSmokeObjects("MEDIUM", -1, 1)
        self.smoke5 = CreateSmokeObjects("Heavy", -1, 1)
    
    #returns everything but smoke 3, it queries any smokes active in the range of -2 hr to -1 hr from current. 
    #So any smoke with -1 as its start value, because this is -2hrs before current, 1 would be -1 hr from current
    def test1_TimeFilterQuery(self):
        
        url = reverse("api:v1:hms_smoke:start_end_filter")
        startTime = datetime.now(timezone.utc) - timedelta(hours=2)
        endTime = datetime.now(timezone.utc) - timedelta(hours=1)
        startTime = startTime.strftime("%H%M")
        endTime = endTime.strftime("%H%M")
        url+= f"?start={startTime}&end={endTime}"
        
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()["data"]) == 4
        for feature in response.json()["data"]:
            if feature["id"] == str(self.smoke3.id):
                assert 1==2
        
    #Returns Everything but smoke 2, it queries any smokes active in the range of +1 hr to +2 hr from current. 
    #so, any value with end value as 1 will return 
    def test2_TimeFilterQuery(self):
        url = reverse("api:v1:hms_smoke:start_end_filter")
        startTime = datetime.now(timezone.utc) + timedelta(hours=1)
        endTime = datetime.now(timezone.utc) + timedelta(hours=2)
        startTime = startTime.strftime("%H%M")
        endTime = endTime.strftime("%H%M")
        url+= f"?start={startTime}&end={endTime}"
        
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()["data"]) == 4
        for feature in response.json()["data"]:
            if feature["id"] == str(self.smoke2.id):
                assert 1==2

    #Returns only smoke1 because it is changes to extend the duration so it occurs longer for a later time query.
    def test3_TimeFilterQuery(self):
        url = reverse("api:v1:hms_smoke:start_end_filter")
        startTime = datetime.now(timezone.utc) + timedelta(hours=2, minutes =1)
        endTime = datetime.now(timezone.utc) + timedelta(hours=2, minutes=3)
        startTime = startTime.strftime("%H%M")
        endTime = endTime.strftime("%H%M")
        url+= f"?start={startTime}&end={endTime}"
        
        self.smoke1.end = datetime.now(timezone.utc) + timedelta(hours=3)
        self.smoke1.save()
        print(url)
        
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]['id'] == str(self.smoke1.id)   
        
        
    #will return 0 smoke objects, added 1 minute to start + 2 hrs because if end is gte start then it will trigger, and end is +2hrs from current
    def test4_TimeFilterQuery(self):
        url = reverse("api:v1:hms_smoke:start_end_filter")
        startTime = datetime.now(timezone.utc) + timedelta(hours=2, minutes =1)
        endTime = datetime.now(timezone.utc) + timedelta(hours=2, minutes=3)
        startTime = startTime.strftime("%H%M")
        endTime = endTime.strftime("%H%M")
        url+= f"?start={startTime}&end={endTime}"
            
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.json()["data"]) == 0



class FetchFilesTaskTest(TestCase):
    def test_fetch_files_triggers_file_download(self):
        from ....apps.monitors.hms_smoke.tasks import fetch_files
        fetch_files()
       
        

        
        
        