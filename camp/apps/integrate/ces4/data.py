from .models import CalEnviro
import geopandas as gpd
import os
from django.conf import settings
from camp.utils.counties import County
import io
import requests
import tempfile
import zipfile

def ces4_to_db():
    try:
        data_path = os.path.join(settings.BASE_DIR,'camp', 'apps','integrate','ces4', 'ces4_shp', 'CalEnviroScreen_4.0_Results.shp')
        geo = gpd.read_file(data_path)
        processDF(geo)
        
    except Exception as e:
        print(e.with_traceback)
    

def ces4_request_db():
    try: 
        url = 'https://oehha.ca.gov/sites/default/files/media/downloads/calenviroscreen/document/calenviroscreen40shpf2021shp.zip'
        
        response = requests.get(url)
        if response.status_code != 200:
            print("CES4 - Download failed with status:", response.status_code)
            response.raise_for_status()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            zipfile.ZipFile(io.BytesIO(response.content)).extractall(temp_dir)
            geo = gpd.read_file(f"{temp_dir}/CalEnviroScreen_4.0_Results.shp")
            processDF(geo)
            
        print("CES4 - Data extraction successful.")
    
    except:
        raise Exception("CES4 - Error with data retrieval.")


def processDF(geo):
    
    for x in range(len(geo)):
        curr = geo.iloc[x]
        county = County.in_SJV(curr.geometry)

        if county:            
            items = ['OBJECTID', 'ACS2019Tot', 'CIscore', 'CIscoreP', 'ozone', 'ozoneP'
            , 'pm','pmP','diesel', 'dieselP', 'pest', 'pestP', 'RSEIhaz', 'RSEIhazP',
            'asthma', 'asthmaP','cvd', 'cvdP', 'Pollution', 'PollutionP']
            currDict= {}    
            for i in items:
                try:
                    currDict[i] = float(curr[i])
                except Exception:
                    currDict[i] = None       
            newobj = CalEnviro.objects.create(
                OBJECTID=int(currDict['OBJECTID']), tract=str(curr.tract), ACS2019Tot=currDict['ACS2019Tot'] ,
                CIscore=currDict['CIscore'], CIscoreP=currDict['CIscoreP'], 
                ozone=currDict['ozone'], ozoneP=currDict['ozoneP'],
                pm=currDict['pm'] ,pmP=currDict['pmP'],
                diesel=currDict['diesel'], dieselP=currDict['dieselP'], 
                pest=currDict['pest'], pestP=currDict['pestP'], 
                RSEIhaz=currDict['RSEIhaz'], RSEIhazP=currDict['RSEIhazP'], 
                asthma=currDict['asthma'], asthmaP=currDict['asthmaP'], 
                cvd=currDict['cvd'], cvdP=currDict['cvdP'],
                pollution=currDict['Pollution'], pollutionP=currDict['PollutionP'], 
                county=county.lower(), geometry=curr['geometry']
            )
            newobj.save()  
                
                