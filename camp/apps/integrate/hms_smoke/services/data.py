import requests, zipfile, io, tempfile
import geopandas as gpd
from django.contrib.gis.geos import GEOSGeometry
from ..models import Smoke
#from .helpers import *
from camp.utils.counties import County
from .helpers import str_to_time
from ..models import Density

def get_smoke_file(date):
    """
    Retrieves smoke file from https://www.ospo.noaa.gov/products/land/hms.html#data
    and converts it into a GeoJSON format
    
    Returns:
        GeoJSON with hms smoke data
    Raises:
        requests.HTTPError: If the HTTP request for the ZIP file fails.
        FileNotFoundError: If the expected shapefile is not found after extraction.
    
    """
    try:
        #rm
        #date = currentTime() 
       
        #Construct download url for NOAA Smoke shapefile 
        baseUrl = "https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/Shapefile/"
        finalUrl = (
            f"{baseUrl}{date.year}/"
            f"{date.strftime('%m')}/"
            f"hms_smoke{date.strftime('%Y%m%d')}.zip"
            )
        
        print("HMS Smoke - Downloading from URL:", finalUrl)
        
        response = requests.get(finalUrl)
        if response.status_code != 200:
            print("HMS Smoke - Download failed with status:", response.status_code)
            response.raise_for_status()
            
        with tempfile.TemporaryDirectory() as temp_dir:     #create temp_dir for zipfiles, add necessary data, then remove dir
            zipfile.ZipFile(io.BytesIO(response.content)).extractall(temp_dir)
            geo = gpd.read_file(f"{temp_dir}/hms_smoke{date.strftime('%Y%m%d')}.shp")
            for i in range(len(geo)):
                to_db(geo.iloc[i])
        print("HMS Smoke - Data extraction successful")
    except Exception as e:
        print("HMS Smoke - Error with data retrieval.")
            
            
#Save GeoDataFrame as an object
def to_db(curr):
    """
    Used to add hms smoke data into the database.
    Converts start and end times into datetime objects so they are easily comparable
    
    Args:
        curr (geoDF): this is one row of the geoPandasDF recovered using .iloc[]
    """
    
    #Parameter Checks
    #converts wkt to django GeosGeometry object, using coordinate system 4326, which was 
    #recovered from the hms file using I believe geofile.crs (after reading it)
    
    ### ADD LOCATION CHECKER TO HELPER
    try:
        #rm
        # cleaned = totalHelper(
        #     Density = curr["Density"],
        #     Satellite = curr["Satellite"],
        #     FID = curr.name, 
        #     Start = curr["Start"], 
        #     End = curr["End"], 
        #     Geometry = curr['geometry'],
        # )  
    
        #If the county is not within the SJV return it does not need to be added
        if not County.in_SJV(curr.geometry):
            return
        #rm
        #observation_time = currentTime()
        
        geometry=GEOSGeometry(curr.geometry.wkt, srid=4326)
        start = str_to_time(curr.Start)
        end = str_to_time(curr.End)
        if curr.Density not in Density.values:
            curr.Density = Density.LIGHT
        print(start, end, curr.Density)
        Smoke.objects.create(
            density=curr.Density,
            start=start,
            end=end,
            satellite=curr.Satellite,
            geometry=geometry,
            #rm
            # FID=cleaned["FID"],
            # observation_time=observation_time,
            )
        
    except Exception as e:
        print("Exception: ", e)
        raise
    
    
