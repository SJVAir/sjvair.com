from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from camp.apps.purple import api
from camp.apps.purple.models import PurpleAir
from camp.apps.purple.tasks import periodic_purple_import

device_list = {
    '548 Walker': 18659,
    '908 Villa 3': 18647,
    'CART Four': 28513,
    'CCA CCAC PARKLAND (Indoor)': 8906,
    'CCA Del Rey': 8910,
    'Edison CCA': 6222,
    'FMBCC_First Armenian Presbyterian Church': 22491,
    'FMBCC_Precision': 22339,
    'FMBCC_Westside Church of God': 22527,
    'HFA_FresnoHS': 17279,
    'HFA_McLane': 17059,
    'Malaga': 3610,
    'Root Access Hackerspace': 8892
}


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        for sensor_id in device_list.values():
            PurpleAir.objects.get_or_create(sensor_id=sensor_id)
        periodic_purple_import()
