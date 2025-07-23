from django.test import TestCase
from .data import tempo_data
from camp.apps.integrate.tempo.models import O3TOT_Points, NO2_Points, HCHO_Points
from django.utils import timezone
from datetime import timedelta
from datetime import datetime

# Create your tests here.

class Test(TestCase):
    def setUp(self):
        bdate = timezone.now() 
        bdate = bdate.replace(hour=1, minute=0, second=0, microsecond=0)
        bdate = bdate - timedelta(hours=1)
        self.bdate = bdate
    
    def test1(self):
        tempo_data('no2', self.bdate)
        print("COUNT: ", O3TOT_Points.objects.all().count())
        
  
    def test2(self):
        tempo_data('hcho', self.bdate)
        print("COUNT: ", HCHO_Points.objects.all().count())
 