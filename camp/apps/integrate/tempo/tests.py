from io import StringIO
from django.core.management import call_command
from django.test import TestCase
from .data import tempo_data
from camp.apps.integrate.tempo.models import TempoGrid
from django.utils import timezone
from datetime import datetime

class Test(TestCase):
    def setUp(self):
        out = StringIO()
        call_command('import_counties', stdout=out)
        self.bdate = datetime(2025, 7, 12, 0, 0, 0, 0)
        self.edate = datetime(2025, 7, 12, 13, 0, 0, 0)
    
    def test1(self):
        tempo_data('o3tot', self.bdate, self.edate)
        qs = TempoGrid.objects.all()
        assert qs.count() == 3
        assert qs.first().pollutant == 'o3tot'
        assert qs.first().final == True
    
    def test2(self):
        self.edate = datetime(2025, 7, 12, 0, 0, 0, 0)
        tempo_data('no2', self.bdate, self.edate)
        qs = TempoGrid.objects.all()
        assert qs.count() == 2
        assert qs.filter(timestamp_2=None)[0].final == False
        assert qs.filter(timestamp_2=None)[0].timestamp == datetime(2025, 7, 12, 0, 59, 0, 0, tzinfo=timezone.utc)
        assert qs.filter(timestamp_2__isnull=False)[0].final == True
        

 