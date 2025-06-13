from django.test import TestCase, RequestFactory
from django.urls import reverse

from . import endpoints
from camp.utils.test import get_response_data

current_time = endpoints.CurrentTime.as_view()


class EndpointTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_get_current_time(self):
        url = reverse('api:v1:current-time')
        request = self.factory.get(url)
        response = current_time(request)
        assert response.status_code == 200

        content = get_response_data(response)
        assert isinstance(content, int)
