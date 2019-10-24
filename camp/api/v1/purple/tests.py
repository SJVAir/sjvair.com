import json
import random

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from resticus.encoders import JSONEncoder

from . import endpoints
from camp.apps.purple.models import PurpleAir, Entry
from camp.utils.test import get_response_data

purple_list = endpoints.PurpleAirList.as_view()
purple_detail = endpoints.PurpleAirDetail.as_view()
entry_list = endpoints.EntryList.as_view()


class PurpleAPITests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.device = PurpleAir.objects.get(label='Root Access Hackerspace')

    def test_get_device_list(self):
        url = reverse('api:v1:purple-air:device-list')
        request = self.factory.get(url)
        response = purple_list(request)
        assert response.status_code == 200

        content = get_response_data(response)
        assert str(self.device.pk) in [device['id'] for device in content['data']]

    def test_get_device_detail(self):
        url = reverse('api:v1:purple-air:device-detail', kwargs={
            'purple_air_id': self.device.pk
        })
        request = self.factory.get(url)
        response = purple_detail(request, purple_air_id=self.device.pk)
        assert response.status_code == 200

        content = get_response_data(response)
        assert content['data']['id'] == str(self.device.pk)

    def test_get_entry_list(self):
        url = reverse('api:v1:purple-air:entry-list', kwargs={
            'purple_air_id': self.device.pk
        })
        request = self.factory.get(url)
        response = entry_list(request, purple_air_id=self.device.pk)
        assert response.status_code == 200

        content = get_response_data(response)
        assert len(content['data'])
