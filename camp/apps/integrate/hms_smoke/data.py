from datetime import datetime
import geopandas as gpd
import io
import requests
import tempfile
import zipfile

from django.contrib.gis.geos import GEOSGeometry
from django.forms import ValidationError
from django.utils import timezone
from django.utils.timezone import make_aware

from .models import Smoke
from camp.utils.counties import County


def parse_timestamp(string):
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
    #Construct download url for NOAA Smoke shapefile 
    base_url = "https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/Shapefile/"
    final_url = (
        f"{base_url}{date.year}/"
        f"{date.strftime('%m')}/"
        f"hms_smoke{date.strftime('%Y%m%d')}.zip"
        )
    response = requests.get(final_url)
    if response.status_code != 200:
        response.raise_for_status()
        
    with tempfile.TemporaryDirectory() as temp_dir:     #create temp_dir for zipfiles, add necessary data, then remove dir
        zipfile.ZipFile(io.BytesIO(response.content)).extractall(temp_dir)
        geo = gpd.read_file(f"{temp_dir}/hms_smoke{date.strftime('%Y%m%d')}.shp")
        if date.date() != timezone.now().date():        #If this smoke file is historical data, set the time to 0
            date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        for i in range(len(geo)):
            to_db(geo.iloc[i], date)
            
            
#Save GeoDataFrame as an object
def to_db(curr, date):
    """
    Used to add hms smoke data into the database.
    Converts start and end times into datetime objects so they are easily comparable
    
    Args:
        curr (geoDF): this is one row of the geoPandasDF recovered using .iloc[]
    """
    #If the county is not within the SJV return it does not need to be added
    if not County.in_SJV(curr.geometry):
        return
    if date.date() != timezone.now().date(): 
        if Smoke.objects.filter(timestamp__date=date.date()).exists():
            return
    geometry = GEOSGeometry(curr.geometry.wkt, srid=4326)
    start = parse_timestamp(curr.Start)
    end = parse_timestamp(curr.End)
    smoke = Smoke(
        timestamp=date,
        density=curr.Density.lower().strip(),
        start=start,
        end=end,
        satellite=curr.Satellite,
        geometry=geometry,
        )
    try:
        smoke.full_clean()
        smoke.save()
    except ValidationError:
        return 
