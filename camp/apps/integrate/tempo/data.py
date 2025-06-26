import pyrsig
import tempfile
import zipfile
import io
from datetime import timedelta
from django.utils import timezone
from shapely  import Polygon
import geopandas as gpd
from django.contrib.gis.geos import GEOSGeometry
from camp.apps.integrate.tempo.models import PollutantPoint
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


def tempo_data(key):
    token = 'anonymous' #PUT API ENV TOKEN HERE
    token_dict = {"api_key":token}
    #bbox = (-74.8, 40.32, -71.43, 41.4)
    SJV_bbox = (-121.585078, 34.788655, -117.616517, 38.300252) #San Joaquin Valley Boundary Box
    keys = {
        'no2':['tempo.l2.no2.vertical_column_troposphere', 'no2_vertical_column_troposphere'], 
        'o3tot':['tempo.l3.o3tot.column_amount_o3','o3_column_amount_o3'],
        'hcho':['tempo.l3.hcho.vertical_column','vertical_colum'],
        }
    
    #Initial data between 12 - 2pm and ends 1-2am
    bdate = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    edate = timezone.now()
    coordkeys = [
        'Longitude_SW', 'Latitude_SW',
        'Longitude_SE', 'Latitude_SE',
        'Longitude_NE', 'Latitude_NE',
        'Longitude_NW', 'Latitude_NW',
        'Longitude_SW', 'Latitude_SW',
        ]
    
    with tempfile.TemporaryDirectory() as temp_dir:
        api = pyrsig.RsigApi(workdir=temp_dir, tempo_kw=token_dict, bdate=bdate, gridfit=True, bbox=SJV_bbox, edate=edate) 
        tempokey = keys[key][0]
        tempodf = api.to_dataframe(
            tempokey, unit_keys=False, parse_dates=True, backend='xdr'
        )
        for i in range(len(tempodf)):
            geom = Polygon(tempodf[coordkeys].iloc[i].values.reshape(5, 2))
            geometry = GEOSGeometry(geom.wkt, srid=4326)
            curr = tempodf.iloc[i]
            point = PollutantPoint(  
                timestamp=curr.time,
                geometry=geometry,
                amount=curr[keys[key][1]],
                pollutant=key,
            
            )
            point.full_clean()
            point.save()