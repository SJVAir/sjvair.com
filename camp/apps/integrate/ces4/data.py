import io
import geopandas as gpd
import re
import requests
import tempfile
import zipfile


from django.contrib.gis.geos import GEOSGeometry, MultiPolygon

from camp.apps.integrate.ces4.models import Tract

pol_fields = [f.name[4:] for f in Tract._meta.fields if f.name.startswith('pol_')]
char_fields = [f.name[4:] for f in Tract._meta.fields if f.name.startswith('char_')]
pop_fields = [f.name[4:] for f in Tract._meta.fields if f.name.startswith('pop_')]
class Ces4Data:
    #Normalizes input data columns and Tract class variables to be comparable for seemless db entry
    def normalize(name):
        sub = {
            'ACS2019Tot': 'population', # convert to a readable variable
            '_pct': '_p', # 'White_pct' -> _p
            'A_1': '_p', # 'Native_A_1' -> native_p
            '10_6_': '10_64_', #'Pop_10_6_1' -> pop_10_64
            'ly__1': 'ly_65_p', # 'Elderly__1' ->pop_65
            'Pop_': '_', # 'Pop_10_64_' -> pop_10_64 
            'pop_': '_', # rm pop as a model label, ex: pop_other
            '_10': '10', # to prevent _1 catching _10 int _p0
            '_1': '_p', # some percentiles in shp file are labaeled with _1
            'Sco': '_s', # PopCharSco -> popchar_s
            'Amer': '', #'Asian_Amer' -> asian
            'Ame': '', #'Native_Ame' -> native
            'Am': '', # rm Am from 'Asian_Am_1' and 'African_Am'
            'n_u': 'n', # rm _u specifically from 'Children_u', _u catches char_unemp
            'Children': '10', # replace Children with 10, matches with pop_10, for under 10
            'Elderly': '', # convert elderly to pop_65, aka no 'Elderly'
            'African': 'black', # short hand African_am to black
            '_Mult': '', # standardize Multiple ethnicities to other only
            '_Mu': '', # _Mu ==_Mult in this case also
            'pol_': '', # rm class label
            'popchar_':'popchar', #to prevent the next char_ from catching  popchar_s/p
            'char_': '', #rm class label
            '_': '', #strip all '_'
        }
        for key, value in sub.items():
            name = re.sub(key, value, name)
            
        return name.lower() # lower all bc some input columns have captialization.
    
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
            params = {Ces4Data.normalize(f.name): f.name for f in Tract._meta.get_fields()}
            geo = Ces4Data.map_tracts(geo)
            Ces4Data.to_db(geo, params)

#geo = geodf, params is a dict like {modelnames.lower():modelName,...} 
#This function creates a dictionary using params[modelname.lower()] -> modelName:value
#This is so we can use capitalized letters for Percentile = P + other small differences
    def to_db(geo, params):
        for x in range(len(geo)):
            curr = geo.iloc[x]       
            inputs = {
                params[Ces4Data.normalize(col)]:curr[col] 
                for col in geo.columns 
                if Ces4Data.normalize(col) in params
                }
            geometry = GEOSGeometry(inputs['geometry'].wkt, srid=4326)
            if geometry.geom_type == 'Polygon':
                geometry = MultiPolygon(geometry)
            inputs['geometry'] = geometry
            Tract.objects.create(**inputs) 
            