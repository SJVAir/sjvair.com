from datetime import datetime
import geopandas as gpd
import io
import requests
import tempfile
import zipfile

from django.contrib.gis.geos import GEOSGeometry
from django.utils.timezone import make_aware

from .models import Density
from .models import Smoke
from camp.utils.counties import County


def str_to_time(string):
    time = datetime.strptime(string, '%Y%j %H%M')
    return make_aware(time)
    

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
        #Construct download url for NOAA Smoke shapefile 
        base_url = "https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/Shapefile/"
        final_url = (
            f"{base_url}{date.year}/"
            f"{date.strftime('%m')}/"
            f"hms_smoke{date.strftime('%Y%m%d')}.zip"
            )
        print("HMS Smoke - Downloading from URL:", final_url)
        
        response = requests.get(final_url)
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
        print("Exception: ", e)
            
            
#Save GeoDataFrame as an object
def to_db(curr):
    """
    Used to add hms smoke data into the database.
    Converts start and end times into datetime objects so they are easily comparable
    
    Args:
        curr (geoDF): this is one row of the geoPandasDF recovered using .iloc[]
    """
    #If the county is not within the SJV return it does not need to be added
    if not County.in_SJV(curr.geometry):
        return
    geometry=GEOSGeometry(curr.geometry.wkt, srid=4326)
    start = str_to_time(curr.Start)
    end = str_to_time(curr.End)
    if curr.Density.lower().strip() not in Density.values:
        curr.Density = Density.LIGHT
        
    Smoke.objects.create(
        density=curr.Density.lower(),
        start=start,
        end=end,
        satellite=curr.Satellite,
        geometry=geometry,
        )

    
