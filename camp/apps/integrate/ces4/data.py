from .models import CalEnviro
import geopandas as gpd
import os
from django.conf import settings
from datetime import datetime, timezone

def CalEnviroToDB():
    try:
        data_path = os.path.join(settings.BASE_DIR,'camp', 'apps','monitors','cal_enviro_screen_4', 'calEnvShapefiles', 'CalEnviroScreen_4.0_Results.shp')
        geo = gpd.read_file(data_path)
        processDF(geo)
        
    except Exception as e:
        print(e.with_traceback)
    
    

def processDF(geo):
    items = ['OBJECTID', 'tract', 'ACS2019Tot', 'CIscore', 'CIscoreP', 'ozone', 'ozoneP'
            , 'pm','pmP','diesel', 'dieselP', 'pest', 'pestP', 'RSEIhaz', 'RSEIhazP',
            'asthma', 'asthmaP']

    
    for x in range(len(geo)):
        
        #TODO IMPORT INSJV COUNTIES
        #IF GEOIN SJV COUNTIES 
        #DO BELOW LOGIC ELSE CONTINUE THROUGH RANGE
    
    
        curr = geo.iloc[x]
        currDict= {}    
        for i in items:
            try:
                currDict[i] = float(curr[i])
            except Exception:
                currDict[i] = None
        timestamp = datetime.now(timezone.utc)        
        
        newobj = CalEnviro.objects.create(
            OBJECTID=int(currDict['OBJECTID']), timestamp = timestamp,tract=currDict['tract'],ACS2019Tot = currDict['ACS2019Tot'] ,
            CIscore = currDict['CIscore'], CIscoreP= currDict['CIscoreP'], ozone= currDict['ozone'], ozoneP= currDict['ozoneP'],
            pm = currDict['pm'] ,pmP = currDict['pmP'],diesel = currDict['diesel'], dieselP= currDict['dieselP'], pest= currDict['pest'],
            pestP= currDict['pestP'], RSEIhaz= currDict['RSEIhaz'], RSEIhazP= currDict['RSEIhazP'], asthma= currDict['asthma'], asthmaP= currDict['asthmaP'], geometry=curr['geometry']
        )
    
        newobj.save()  
                
                
                
        
        