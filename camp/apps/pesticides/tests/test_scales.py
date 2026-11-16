from django.test import TestCase

from camp.apps.pesticides.places import SPRAYDAYS_URL
from camp.apps.pesticides.scales import get_spray_notice_scale


class SprayNoticeScaleTests(TestCase):
    def test_one_level_category(self):
        scale = get_spray_notice_scale().to_json()
        assert scale['id'] == 'spray-notice'
        assert scale['label'] == 'Spray Notices'
        assert scale['units'] == ''
        assert scale['kind'] == 'category'
        assert scale['averaging_hours'] is None
        assert scale['daily_statistic'] is None
        assert scale['source'] == {'name': 'California Department of Pesticide Regulation, SprayDays', 'url': SPRAYDAYS_URL}
        assert scale['levels'] == [{
            'key': 'notice', 'label': 'Spray notice', 'color': '#e64980', 'tier': None,
            'description': '', 'guidance': '', 'min': None, 'max': None,
            'value': 'notice', 'opacity': None,
        }]
