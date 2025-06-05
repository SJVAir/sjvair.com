import requests, zipfile, io, os
import geopandas as gpd
from django.contrib.gis.geos import GEOSGeometry
from datetime import datetime
from ..models import Smoke
from .helpers import *
from shapely.wkt import loads as load_wkt
from django.conf import settings
from .....utils.counties import County


def get_smoke_file():
    """
    Retrieves smoke file from https://www.ospo.noaa.gov/products/land/hms.html#data
    and converts it into a GeoJSON format
    
    Returns:
        GeoJSON with hms smoke data
    Raises:
        requests.HTTPError: If the HTTP request for the ZIP file fails.
        FileNotFoundError: If the expected shapefile is not found after extraction.
    
    """
    #Clear directory before populating
    try:
        outputPath = os.path.join(
            settings.BASE_DIR,'camp',
            'apps','monitors','hms_smoke', 
            'services','smoke_data'
            )
        os.makedirs(outputPath, exist_ok=True)
        rm_dir(outputPath)                       #clear directory
        date = datetime.now(timezone.utc) 
        #Construct download url for NOAA Smoke shapefile 
        baseUrl = "https://satepsanone.nesdis.noaa.gov\
                  /pub/FIRE/web/HMS/Smoke_Polygons/Shapefile/"
        finalUrl = baseUrl + f"{date.year}/{date.strftime('%m')}\
                                /hms_smoke{date.strftime('%Y%m%d')}.zip"  
        print("Downloading from URL:", finalUrl)
        response = requests.get(finalUrl)
        if response.status_code != 200:
            print("Download failed with status:", response.status_code)
            response.raise_for_status()
        zipfile.ZipFile(io.BytesIO(response.content)).extractall(outputPath)
        #read_file reads shape file from zip file and uses the other files also
        geo = gpd.read_file(f"{outputPath}/hms_smoke{date.strftime('%Y%m%d')}.shp")
        for i in range(len(geo)):
            to_db(geo.iloc[i])
    except Exception:
        print(Exception.with_traceback())
        print("Error with data retrieval.")



def rm_dir(path):
    """
    Takes in a path and clears the directory of files. 
    Used to clear files to prevent cluttering

    Args:
        path (str): path of directory that needs to be cleared
    """
    dir_path = os.path.join(os.path.dirname(path), "smoke_data")
    for file in os.listdir(dir_path):
        #create file path for every file
        file_path = os.path.join(dir_path, file) 
        if os.path.isfile(file_path):
            #Remove file
            os.remove(file_path)
            
            
            
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
        geoCheck(curr["geometry"])
        geometry=GEOSGeometry(curr['geometry'].wkt, srid=4326)
        #If the county is not within the SJV return it does not need to be added
        if not County.in_SJV(curr.geometry):
            print("Not in SJV: ", curr.name)
            return
        print("In SJV: ", curr.name)
        density = densityCheck(curr["Density"])
        satellite = strCheck(curr["Satellite"])
        name = strCheck(str(curr.name))
        #convert date,time string to datetime object
        start = dateCheck(curr["Start"]) 
        end = dateCheck(curr["End"])
        observation_time = datetime.now(timezone.utc)
        newobj = Smoke.objects.create(density=density, start=start, end=end, satellite=satellite, geometry=geometry , FID=name, observation_time=observation_time)
        newobj.save()
    except Exception as e:
        print("Exception: ", e)
        raise
    
    
