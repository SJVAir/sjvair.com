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
from camp.apps.integrate.tempo.models import O3totPoints, No2Points, HchoPoints

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
keys = {
        'no2':['tempo.l2.no2.vertical_column_troposphere', 'no2_vertical_column_troposphere', No2Points], 
        'o3tot':['tempo.l3.o3tot.column_amount_o3','o3_column_amount_o3', O3totPoints],
        'hcho':['tempo.l3.hcho.vertical_column','vertical_column', HchoPoints],
        }

def tempo_data(key, bdate):
    global keys
    print("START TIME OF THIS ITERATION: ", timezone.now())
    token = 'anonymous' #PUT API ENV TOKEN HERE
    token_dict = {"api_key":token}
    SJV_bbox = (-121.585078, 34.788655, -117.616517, 38.300252) #San Joaquin Valley Boundary Box
    edate = timezone.now() 
    coordkeys = [
        'Longitude_SW', 'Latitude_SW',
        'Longitude_SE', 'Latitude_SE',
        'Longitude_NE', 'Latitude_NE',
        'Longitude_NW', 'Latitude_NW',
        'Longitude_SW', 'Latitude_SW',
        ]
    
    #QUERY FOR TEMPO DATA FROM PYRSIG
    with tempfile.TemporaryDirectory() as temp_dir:
        api = pyrsig.RsigApi(workdir=temp_dir, tempo_kw=token_dict, bdate=bdate, gridfit=True, bbox=SJV_bbox, edate=edate) 
        tempokey = keys[key][0]
        tempodf = api.to_dataframe(
            tempokey, unit_keys=False, parse_dates=True, 
        )
            
        if len(tempodf) ==0:
            return 
        tempodf['row_index'] = tempodf.index
        print(tempodf.groupby('time')['row_index'].agg(['min', 'max']))
        for timestamp, group in tempodf.groupby('time'):
            if keys[key][2].objects.filter(timestamp=timestamp).exists():
                print("Timestamp: ", timestamp, ' EXISTS')
                continue
            else:
                print("Timestamp: ", timestamp, 'ADDED')
            geometries = []
            values = []   
            for x in range(len(group)):
                geom = Polygon(group[coordkeys].iloc[x].values.reshape(5, 2))
                geometries.append(geom)
                values.append(group.iloc[x][keys[key][1]])
                if x%10000 == 0:
                    print(x, ' ', group.iloc[x].time)
            gdf = gpd.GeoDataFrame({keys[key][1]: values}, geometry=geometries, crs="EPSG:4326")
            stamp = timestamp.to_pydatetime()
            filename = key.upper() + stamp.strftime("%Y%m%d:%H:%M:%S")
            shp_path = os.path.join(temp_dir, f"{filename}.shp")
            gdf.to_file(shp_path, driver="ESRI Shapefile")
            zip_path = os.path.join(temp_dir, f"{filename}.shp")
            print(zip_path)
            
            #CONVERT SHP FILES INTO A ZIP 
            with zipfile.ZipFile(zip_path, 'w') as zf:
                for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
                    filepath = os.path.join(temp_dir, f"{filename}{ext}")
                    if os.path.exists(filepath):
                        print(filepath)
                        zf.write(filepath, arcname=f"{filename}{ext}")
                        
            #STORE THE ZIP FILES AS A FILEFIELD IN THE PARTICULAR OBJECT TYPE
            with open(zip_path, 'rb') as f:
                obj = keys[key][2]()
                print("HERE")
                obj.file.save(f"{filename}.zip", File(f))
                obj.timestamp = stamp
                obj.save()
            
            