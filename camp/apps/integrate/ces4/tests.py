from django.test import TestCase

#from camp.api.v1.ces4.endpoints import CalEnviro
import geopandas as gpd

# Create your tests here.


class modelTest(TestCase):
    def test1(self):
        geo = gpd.read_file('/vagrant/camp/apps/integrate/ces4/ces4_shp/CalEnviroScreen_4.0_Results.shp')
        for i in range(len(geo)):
            for col, val in geo.iloc[i].items():
                print(f"{col}: {val}") 
            break