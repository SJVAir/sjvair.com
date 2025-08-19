import geopandas as gpd
from datetime import datetime

from django.test import TestCase
from django.utils import timezone
from shapely.wkt import loads as load_wkt
from django.core.exceptions import ValidationError
from django.utils.timezone import make_aware

from camp.api.v2.hms_smoke.tests import create_smoke_objects
from camp.apps.integrate.hms_smoke.data import get_smoke_file, to_db
from camp.apps.integrate.hms_smoke.models import Smoke
from camp.apps.integrate.hms_smoke.tasks import fetch_files, final_file
from camp.utils.counties import County


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
    def test_clearing_old_data(self):
        get_smoke_file(make_aware(datetime(2025, 7, 2)).date())
        Smoke.objects.all().update(is_final=False)
        count = Smoke.objects.all().count()
        assert count > 0
        get_smoke_file(make_aware(datetime(2025, 7, 2)).date())
        assert Smoke.objects.filter(is_final=True).count() == count
        assert Smoke.objects.all().count() == count 
    
    def test_get_smoke_file(self):
        assert Smoke.objects.all().count() == 0
        get_smoke_file(make_aware(datetime(2025, 7, 2)).date())
        count = Smoke.objects.all().count()
        assert count > 0
        assert Smoke.objects.first().is_final == True
        assert Smoke.objects.first().date == datetime(2025, 7, 2).date()
        assert Smoke.objects.first().density == 'light'
        
        smokes = get_smoke_file(make_aware(datetime(2025, 7, 2)).date())
        assert Smoke.objects.all().count() == count #entry not added to db
        assert len(smokes) == count
        
    def test_to_db_SJV(self):
        count = Smoke.objects.all().count()
        polygon_wkt = (
                        "MULTIPOLYGON((("
                        "-119.860839 36.660399, "
                        "-119.860839 36.905755, "
                        "-119.650879 36.905755, "
                        "-119.650879 36.660399, "
                        "-119.860839 36.660399"
                        ")))"
                    )
        geometry = load_wkt(polygon_wkt) 
        input = [{
                "geometry": geometry,
                "Density": "Light",
                "End":"202515 1440",
                "Start": "202515 1540",
                "Satellite": "Satellite1",
                }]
        input = gpd.GeoDataFrame(input)
        to_db(input.iloc[0], timezone.now(), True)
        assert Smoke.objects.all().count() == count + 1 #entry added to db
        
    def test_to_db_notSJV(self):
        count = Smoke.objects.all().count()
        polygon_wkt = ("POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))")
        geometry = load_wkt(polygon_wkt) 
        input = [{
                "geometry": geometry,
                "Density": "Light",
                "End":"202515 1440",
                "Start": "202515 1540",
                "Satellite": "Satellite1",
                }]
        input = gpd.GeoDataFrame(input)
        to_db(input.iloc[0], timezone.now(), True)
        assert Smoke.objects.all().count() == count #entry not added to db
    