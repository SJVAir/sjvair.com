import io
import geopandas as gpd
import requests
import tempfile
import zipfile

from django.contrib.gis.geos import GEOSGeometry

from camp.apps.integrate.ces4.models import Ces4


class Ces4Data:
    def map_tracts(geo):
        fips = {
            "019": "fresno",
            "029": "kern",
            "031": "kings",
            "039": "madera",
            "047": "merced",
            "077": "san joaquin",
            "099": "stanislaus",
            "107": "tulare",
                }
        geo['tract'] = '0' + geo['TractTXT']
        geo['county'] = geo['tract'].str[2:5].map(fips)
        geo = geo[geo['county'].notna()]
        return geo
              
    def ces4_request():
        url = 'https://gis.data.ca.gov/api/download/v1/items/b6e0a01c423b489f8d98af641445da28/shapefile?layers=0'
        response = requests.get(url)
        if response.status_code != 200:
            response.raise_for_status()
        with tempfile.TemporaryDirectory() as temp_dir:
            zipfile.ZipFile(io.BytesIO(response.content)).extractall(temp_dir)
            geo = gpd.read_file(f"{temp_dir}/CalEnviroScreen_4.0_Results.shp").to_crs(epsg=4326)
            params = {f.name.lower(): f.name for f in Ces4._meta.get_fields()}
            geo = Ces4Data.map_tracts(geo)
            Ces4Data.to_db(geo, params)

    def to_db(geo, params):
        for x in range(len(geo)):
            curr = geo.iloc[x]       
            inputs = {
                params[col.lower()]:curr[col] 
                for col in geo.columns 
                if col.lower() in params
                }
            inputs['geometry'] = GEOSGeometry(inputs['geometry'].wkt, srid=4326) 
            Ces4.objects.create(**inputs) 
                          