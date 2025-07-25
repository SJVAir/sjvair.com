from django.test import TestCase
from .data import tempo_data
from camp.apps.integrate.tempo.models import TempoGrid
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
        tempo_data('o3tot', self.bdate, timezone.now())
        print("COUNT: ", TempoGrid.objects.all().count())
        
  
    # def test2(self):
    #     tempo_data('hcho', self.bdate)
    #     print("COUNT: ", HchoFile.objects.all().count())
 