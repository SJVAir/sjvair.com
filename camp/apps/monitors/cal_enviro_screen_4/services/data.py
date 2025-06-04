from ..models import CalEnviro
import geopandas as gpd
import os
from django.conf import settings


def CalEnviroToDB():
    try:
        data_path = os.path.join(settings.BASE_DIR,'camp', 'apps','monitors','cal_enviro_screen_4', 'calEnvShapefiles', 'CalEnviroScreen_4.0_Results.shp')
        geo = gpd.read_file(data_path)
        
        
        
        
    except Exception as e:
        print(e.with_traceback)
    
    

def processRow(geo):
    items = ['OBJECTID', 'tract', 'ACS2019Tot', 'CIscore', 'CIscoreP', 'ozone', 'ozoneP'
            , 'pm','pmP','diesel', 'dieselP', 'pest', 'pestP', 'RSEIhaz', 'RSEIhazP',
            'asthma', 'asthmaP', 'geometry']
    
    for x in range(len(geo)):
        curr = geo.iloc[x]
        currDict= {}
        
        for i in items:
            currDict[i] = curr[i]
        ##Default if item not in set to null or something
        
        