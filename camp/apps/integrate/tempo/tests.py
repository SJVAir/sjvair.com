from django.test import TestCase
from .data import tempo_data
from camp.apps.integrate.tempo.models import PollutantPoint

# Create your tests here.

class Test(TestCase):
    def test1(self):
        tempo_data('o3tot')
        print("COUNT: ", PollutantPoint.objects.all().count())