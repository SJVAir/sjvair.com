import pyrsig
import tempfile
import zipfile
import io
import os
from datetime import timedelta
from django.utils import timezone
from shapely  import Polygon, MultiPolygon
import geopandas as gpd
from django.contrib.gis.geos import GEOSGeometry
from django.core.files import File
from camp.apps.integrate.tempo.models import TempoGrid

#bounding boxes 
'''
San joaquin  = -121.585078	37.481783	-120.917007	38.300252
Fresno = -120.918731	35.906914	-118.360586	37.585837
Kern = -120.194369	34.788655	-117.616517	35.798392
Tulare = -119.573194	35.788935	-117.980761	36.744816
Stanislaus = -121.486775	37.134774	-120.387329	38.077421
Kings = -120.315068	35.78858	-119.474354	36.488962
Madera = -120.545536	36.763047	-119.022363	37.777986
Merced = -121.248647	36.740381	-120.052055	37.633364

Final bounding box = (-121.585078, 34.788655, -117.616517, 38.300252)

'''
#THIS IS USED TO MAKE THE RETRIEVING DATA FUNCTION MODULAR FOR ALL POLLUTANT TYPES

def tempo_data(key, bdate, edate):
    keys = {
        'no2':['tempo.l2.no2.vertical_column_troposphere', 'no2_vertical_column_troposphere', 'no2_col'], 
        'o3tot':['tempo.l3.o3tot.column_amount_o3','o3_column_amount_o3', 'o3_col'],
        'hcho':['tempo.l3.hcho.vertical_column','vertical_column', 'hcho_col'],
        }
    obj_list = []
    token_dict = {"api_key":'anonymous'}
    SJV_bbox = (-121.585078, 34.788655, -117.616517, 38.300252) #San Joaquin Valley Boundary Box
    tempokey, column, shp_col = keys[key]

    #QUERY FOR TEMPO DATA FROM PYRSIG
    with tempfile.TemporaryDirectory() as temp_dir:
        api = pyrsig.RsigApi(workdir=temp_dir, tempo_kw=token_dict, bdate=bdate, gridfit=True, bbox=SJV_bbox, edate=edate) 
        tempodf = api.to_dataframe(
            tempokey, unit_keys=False, parse_dates=True, 
        )  
        if len(tempodf) ==0:
            return obj_list
        
        #ORGANIZE DATA BY TIMESTAMP
        tempodf['row_index'] = tempodf.index
        print(tempodf.groupby('time')['row_index'].agg(['min', 'max']))
        for timestamp, group in tempodf.groupby('time'):
            if TempoGrid.objects.filter(timestamp=timestamp, pollutant=key, ).exists():
                continue
            geometries, values = [], []
            coordkeys = [
                'Longitude_SW', 'Latitude_SW',
                'Longitude_SE', 'Latitude_SE',
                'Longitude_NE', 'Latitude_NE',
                'Longitude_NW', 'Latitude_NW',
                'Longitude_SW', 'Latitude_SW',
            ]   
            for x in range(len(group)):
                geom = Polygon(group[coordkeys].iloc[x].values.reshape(5, 2))
                geometries.append(geom)
                values.append(group.iloc[x][column])
                
            #CONSTRUCT SHAPE FILES
            gdf = gpd.GeoDataFrame({shp_col: values}, geometry=geometries, crs="EPSG:4326")
            stamp = timestamp.to_pydatetime()
            filename = f"{key}{stamp.strftime('%Y%m%d%H%M%S')}"
            shp_path = os.path.join(temp_dir, f"{filename}")
            gdf.to_file(shp_path, driver="ESRI Shapefile")
            
            #STORE THE ZIP FILES AS A FILEFIELD IN THE PARTICULAR OBJECT TYPE
            obj = TempoGrid(timestamp=stamp, pollutant=key,)
            for ext in ["shp", "shx", "dbf", "prj", "cpg"]:
                path = os.path.join(shp_path, f"{filename}.{ext}")
                with open(path, "rb") as f:
                    getattr(obj, ext).save(f"{filename}.{ext}", File(f), save=False) 
            obj.save()
            obj_list.append(obj)
    return obj_list

