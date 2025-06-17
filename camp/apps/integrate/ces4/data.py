import io
import geopandas as gpd
import os
import requests
import tempfile
import zipfile

from django.contrib.gis.geos import GEOSGeometry
from django.conf import settings

from .models import Ces4

class Ces4Processing:
    def county_mapping(geo):
        ca_fips = {
            "019":"fresno",
            "029":"kern",
            "031": "Kings",
            "039": "Madera",
            "047": "Merced",
            "077": "San Joaquin",
            "099": "Stanislaus",
            "107": "Tulare",
                }
        geo['county_fips'] = geo['TractTXT'].str[1:4]
        geo['county_name'] = geo['county_fips'].map(ca_fips)
        geo = geo[geo['county_name'].notna()]
        return geo


    def ces4_to_db():
        data_path = os.path.join(settings.BASE_DIR,'camp', 'apps','integrate','ces4', 'ces4_shp', 'CalEnviroScreen_4.0_Results.shp')
        geo = gpd.read_file(data_path)
        geo = geo.to_crs(epsg=4326)
        mapped_geo = Ces4Processing.county_mapping(geo)            
        Ces4Processing.process_df(mapped_geo)
        
        
    def ces4_request_db():
        try: 
            url = 'https://gis.data.ca.gov/api/download/v1/items/b6e0a01c423b489f8d98af641445da28/shapefile?layers=0'
            response = requests.get(url)
            if response.status_code != 200:
                print("CES4 - Download failed with status:", response.status_code)
                response.raise_for_status()

            with tempfile.TemporaryDirectory() as temp_dir:
                zipfile.ZipFile(io.BytesIO(response.content)).extractall(temp_dir)
                geo = gpd.read_file(f"{temp_dir}/CalEnviroScreen_4.0_Results.shp")
                geo = geo.to_crs(epsg=4326)
                mapped_geo = Ces4Processing.county_mapping(geo)
                Ces4Processing.process_df(mapped_geo)
            print("CES4 - Data extraction successful.")
        
        except Exception as e:
            print(e)
            raise Exception("CES4 - Error with data retrieval.")


    def process_df(geo):
        for x in range(len(geo)):
            curr = geo.iloc[x]      
            items = [
                'ACS2019Tot', 'CIscore', 'CIscoreP', 'ozone', 'ozoneP',
                'pm','pmP','diesel', 'dieselP', 'pest', 'pestP', 'RSEIhaz', 'RSEIhazP',
                'asthma', 'asthmaP','cvd', 'cvdP', 'Pollution', 'PollutionP'
                ]
            curr_dict= {}    
            for i in items:
                    curr_dict[i] = float(curr[i]) 
            geometry = GEOSGeometry(curr.geometry.wkt, srid=4326)     
            Ces4.objects.create(
                OBJECTID=int(curr.OBJECTID), tract=str(curr.tract), ACS2019Tot=curr_dict['ACS2019Tot'] ,
                CIscore=curr_dict['CIscore'], CIscoreP=curr_dict['CIscoreP'], 
                ozone=curr_dict['ozone'], ozoneP=curr_dict['ozoneP'],
                pm=curr_dict['pm'] ,pmP=curr_dict['pmP'],
                diesel=curr_dict['diesel'], dieselP=curr_dict['dieselP'], 
                pest=curr_dict['pest'], pestP=curr_dict['pestP'], 
                RSEIhaz=curr_dict['RSEIhaz'], RSEIhazP=curr_dict['RSEIhazP'], 
                asthma=curr_dict['asthma'], asthmaP=curr_dict['asthmaP'], 
                cvd=curr_dict['cvd'], cvdP=curr_dict['cvdP'],
                pollution=curr_dict['Pollution'], pollutionP=curr_dict['PollutionP'], 
                county=curr.county_name.lower(), geometry=geometry
            ) 
                    
                