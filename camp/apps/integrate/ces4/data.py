import io
import geopandas as gpd
import requests
import tempfile
import zipfile

from django.contrib.gis.geos import GEOSGeometry

from camp.apps.integrate.ces4.models import Ces4


class Ces4Data:
    def county_map(geo):
        ca_fips = {
            "019": "fresno",
            "029": "kern",
            "031": "kings",
            "039": "madera",
            "047": "merced",
            "077": "san joaquin",
            "099": "stanislaus",
            "107": "tulare",
                }
        geo['TractTXT'] = '0' + geo['TractTXT']
        geo['county_fips'] = geo['TractTXT'].str[2:5]
        geo['county'] = geo['county_fips'].map(ca_fips)
        geo = geo[geo['county'].notna()]
        return geo
              
    def ces4_request():
        url = 'https://gis.data.ca.gov/api/download/v1/items/b6e0a01c423b489f8d98af641445da28/shapefile?layers=0'
        response = requests.get(url)
        if response.status_code != 200:
            response.raise_for_status()
        with tempfile.TemporaryDirectory() as temp_dir:
            zipfile.ZipFile(io.BytesIO(response.content)).extractall(temp_dir)
            geo = gpd.read_file(f"{temp_dir}/CalEnviroScreen_4.0_Results.shp")
            geo = geo.to_crs(epsg=4326)
            object_params = {f.name.lower(): f.name for f in Ces4._meta.get_fields()}
            geo = Ces4Data.county_map(geo)
            Ces4Data.process_df(geo, object_params)

    def process_df(geo, object_params):
        for x in range(len(geo)):
            curr = geo.iloc[x]       
            params =  {
                object_params[col.lower()]:curr[col] 
                for col in geo.columns 
                if col.lower() in object_params
                }
            params['geometry'] = GEOSGeometry(params['geometry'].wkt, srid=4326) 
            Ces4.objects.create(**params) 
                          