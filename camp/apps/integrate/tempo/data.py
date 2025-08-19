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
from camp.apps.regions.models import Region
# from camp.apps.regions.querysets import combined_geometry

def tempo_data(key, bdate, edate):
    keys = {
        'no2':['tempo.l2.no2.vertical_column_troposphere', 'no2_vertical_column_troposphere', 'no2_col'], 
        'o3tot':['tempo.l3.o3tot.column_amount_o3','o3_column_amount_o3', 'o3_col'],
        'hcho':['tempo.l3.hcho.vertical_column','vertical_column', 'hcho_col'],
        }
    obj_list = []
    token_dict = {"api_key":'anonymous'}
    
    # SJV_bbox = (-121.585078, 34.788655, -117.616517, 38.300252) #San Joaquin Valley Boundary Box
    bbox = Region.objects.filter(type=Region.Type.COUNTY).combined_geometry()
    tempokey, column, shp_col = keys[key]
    print(type(bbox))
    #QUERY FOR TEMPO DATA FROM PYRSIG
    with tempfile.TemporaryDirectory() as temp_dir:
        api = pyrsig.RsigApi(workdir=temp_dir, tempo_kw=token_dict, bdate=bdate, gridfit=True, bbox=bbox.extent, edate=edate) 
        tempodf = api.to_dataframe(
            tempokey, unit_keys=False, parse_dates=True, 
        )  
        if len(tempodf) ==0:
            return obj_list
        if key == 'no2' or key =='hcho':
            tempodf[column] = tempodf[column]/1000000000
        tempodf = tempodf.sort_values(by='time', ascending=True)
        tempodf['row_index'] = tempodf.index
        print(tempodf.groupby('time')['row_index'].agg(['min', 'max']))
        
        coordkeys = [
                    'Longitude_SW', 'Latitude_SW',
                    'Longitude_SE', 'Latitude_SE',
                    'Longitude_NE', 'Latitude_NE',
                    'Longitude_NW', 'Latitude_NW',
                    'Longitude_SW', 'Latitude_SW',
                ]  
        
        if key == 'no2': #PROCESS NO2 FILES HERE
            obj_list.append(no2_data(tempodf, column, shp_col, key, temp_dir, coordkeys))
        #ORGANIZE DATA BY TIMESTAMP
        
        else: #PROCESS HCHO AND O3TOT
            for timestamp, group in tempodf.groupby('time'):
                if TempoGrid.objects.filter(timestamp=timestamp, pollutant=key, ).exists():
                    continue
                geometries, values = [], [] 
                for x in range(len(group)):
                    geom = Polygon(group[coordkeys].iloc[x].values.reshape(5, 2))
                    geometries.append(geom)
                    values.append(group.iloc[x][column])
                    
                obj_list.append(df_to_shp(geometries, values, [timestamp], key, shp_col, temp_dir, True))
        return obj_list


#COMBINES THE 2 NO2 SCANS INTO ONE SHAPEFILE/OBJECT
def no2_data(tempodf, column, shp_col, key, temp_dir, coordkeys):
    obj_list = []
    geometries, values, timestamps= [], [], []
    all_timestamps = tempodf['time'].unique()
    all_timestamps.to_pydatetime().sort()
    final_stamp = all_timestamps[-1]
    for timestamp, group in tempodf.groupby('time'):
        timestamp = timestamp.to_pydatetime()
        if TempoGrid.objects.filter(timestamp=timestamp, pollutant='no2', final=True).exists() or TempoGrid.objects.filter(timestamp_2=timestamp, pollutant='no2', final=True).exists():
            continue
        elif len(timestamps) == 1 and not (abs(timestamps[0] - timestamp) <= timedelta(minutes=15)):
            obj_list.append(df_to_shp(geometries, values, timestamps, key, shp_col, temp_dir, False))
            geometries, values, timestamps = [], [], []
        timestamps.append(timestamp)
      
        for x in range(len(group)):
            geom = Polygon(group[coordkeys].iloc[x].values.reshape(5, 2))
            geometries.append(geom)
            values.append(group.iloc[x][column])  
                  
        if len(timestamps) == 2:  
            obj_list.append(df_to_shp(geometries, values, timestamps, key, shp_col, temp_dir, True))
            geometries, values, timestamps = [], [], []
        elif timestamp == final_stamp:
            obj_list.append(df_to_shp(geometries, values, timestamps, key, shp_col, temp_dir, False))
    return obj_list
    
    
#CREATES SHAPEFILE AND ADDS TO DB
def df_to_shp(geometries, values, stamp, key, shp_col, temp_dir, final):
    #CONSTRUCT SHAPE FILES
    gdf = gpd.GeoDataFrame({shp_col: values}, geometry=geometries, crs="EPSG:4326")
    filename = f"{key}{stamp[0].strftime('%Y%m%d%H%M%S')}"
    shp_path = os.path.join(temp_dir, f"{filename}.shp")
    gdf.to_file(shp_path, driver="ESRI Shapefile")
    zip_path = os.path.join(temp_dir, f"{filename}.zip")
    
    with zipfile.ZipFile(zip_path, 'w') as zf:
        for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
            filepath = os.path.join(temp_dir, f"{filename}{ext}")
            if os.path.exists(filepath):
                zf.write(filepath, arcname=f"{filename}{ext}")
    
    #STORE THE ZIP FILES AS A FILEFIELD IN THE PARTICULAR OBJECT TYPE
    with open(zip_path, "rb") as f:
        obj = TempoGrid(timestamp=stamp[0], pollutant=key, final=final)
        if len(stamp) == 2: 
            obj.timestamp_2 = stamp[1]
        obj.file.save(f"{filename}.zip", File(f)) 
        obj.save()
    return obj
