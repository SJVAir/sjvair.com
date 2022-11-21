from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, RequestFactory
from django.urls import reverse

from . import endpoints

from camp.apps.accounts.models import User
from camp.apps.alerts.models import Subscription
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.test import debug, get_response_data

subscription_list = endpoints.SubscriptionList.as_view()
subscribe = endpoints.Subscribe.as_view()
unsubscribe = endpoints.Unsubscribe.as_view()


class EndpointTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.monitor = PurpleAir.objects.get(purple_id=8892)
        self.user = User.objects.get(email='user@sjvair.com')

    def test_subscription_list_authenticated(self):
        '''
            Test that we can GET the monitor detail endpoint.
        '''
        Subscription.objects.create(
            user=self.user,
            monitor=self.monitor,
            level=Subscription.LEVELS.unhealthy
        )

        url = reverse('api:v1:subscription-list')
        request = self.factory.get(url)
        request.monitor = self.monitor
        request.user = self.user

        response = subscription_list(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data'][0]['monitor'] == str(self.monitor.pk)

    def test_subscription_list_anonymous(self):
        '''
            Test that we can GET the monitor detail endpoint.
        '''

        url = reverse('api:v1:subscription-list')
        request = self.factory.get(url)
        request.monitor = self.monitor
        request.user = AnonymousUser()

        response = subscription_list(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 403

    def test_create_subscription(self):
        '''
            Test that we can GET the monitor detail endpoint.
        '''
        payload = {'level': Subscription.LEVELS.unhealthy}

        url = reverse('api:v1:monitors:alerts:subscribe', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.post(url, payload)
        request.monitor = self.monitor
        request.user = self.user

        response = subscribe(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data']['monitor'] == str(self.monitor.pk)
        assert self.user.subscriptions.filter(
            monitor_id=self.monitor.pk,
            level=Subscription.LEVELS.unhealthy,
        ).exists()


    def test_update_subscription(self):
        '''
            Test that we can GET the monitor detail endpoint.
        '''
        Subscription.objects.create(
            user=self.user,
            monitor=self.monitor,
            level=Subscription.LEVELS.unhealthy
        )

        payload = {'level': Subscription.LEVELS.hazardous}

        url = reverse('api:v1:monitors:alerts:subscribe', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.post(url, payload)
        request.monitor = self.monitor
        request.user = self.user

        response = subscribe(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data']['monitor'] == str(self.monitor.pk)
        assert self.user.subscriptions.filter(
            monitor_id=self.monitor.pk,
            level=Subscription.LEVELS.hazardous,
        ).exists()

    def test_unsubscribe(self):
        '''
            Test that we can GET the monitor detail endpoint.
        '''
        Subscription.objects.create(
            user=self.user,
            monitor=self.monitor,
            level=Subscription.LEVELS.unhealthy
        )

        url = reverse('api:v1:monitors:alerts:subscribe', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.post(url)
        request.monitor = self.monitor
        request.user = self.user

        response = unsubscribe(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['success'] == True
        assert self.user.subscriptions.filter(
            monitor_id=self.monitor.pk,
        ).exists() is False
