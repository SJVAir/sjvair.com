import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from smalluuid import SmallUUID

from . import endpoints

from camp.apps.accounts.models import User
from camp.apps.alerts import current
from camp.apps.alerts.evaluator import AlertEvaluator
from camp.apps.alerts.models import Subscription
from camp.apps.entries.models import PM25
from camp.apps.monitors.models import LatestEntry
from camp.apps.monitors.vozbox.models import VOZBox
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.test import CsrfExemptRequestFactory, debug, get_response_data

subscription_list = endpoints.SubscriptionList.as_view()
subscribe = endpoints.Subscribe.as_view()
unsubscribe = endpoints.Unsubscribe.as_view()
current_alerts = endpoints.CurrentAlertValues.as_view()


class EndpointTests(TestCase):
    fixtures = ['users.yaml', 'purple-air.yaml']

    def setUp(self):
        self.factory = CsrfExemptRequestFactory()
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.user = User.objects.get(email='user@sjvair.com')

    def test_subscription_list_authenticated(self):
        '''
            Test that we can GET the monitor detail endpoint.
        '''
        Subscription.objects.create(
            user=self.user,
            monitor=self.monitor,
            level='unhealthy'
        )

        url = reverse('api:v2:subscription-list')
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

        url = reverse('api:v2:subscription-list')
        request = self.factory.get(url)
        request.monitor = self.monitor
        request.user = AnonymousUser()

        response = subscription_list(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 401

    def test_create_subscription(self):
        '''
            Test that we can GET the monitor detail endpoint.
        '''
        payload = {'level': PM25.Levels.UNHEALTHY.key}

        url = reverse('api:v2:monitors:alerts:subscribe', kwargs={
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
            level=payload['level'],
        ).exists()


    def test_update_subscription(self):
        '''
            Test that we can GET the monitor detail endpoint.
        '''
        Subscription.objects.create(
            user=self.user,
            monitor=self.monitor,
            level=PM25.Levels.UNHEALTHY.key
        )

        payload = {'level': PM25.Levels.HAZARDOUS.key}

        url = reverse('api:v2:monitors:alerts:subscribe', kwargs={
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
            level=PM25.Levels.HAZARDOUS.key,
        ).exists()

    def test_resubscribe_keeps_notification_state(self):
        subscription = Subscription.objects.create(
            user=self.user,
            monitor=self.monitor,
            level=PM25.Levels.UNHEALTHY.key,
            last_notified_level=PM25.Levels.UNHEALTHY.key,
        )

        url = reverse('api:v2:monitors:alerts:subscribe', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.post(url, {'level': PM25.Levels.HAZARDOUS.key})
        request.monitor = self.monitor
        request.user = self.user

        # A tick texts the subscriber after the endpoint loaded its copy.
        original_get_object = endpoints.Subscribe.get_object

        def stale_get_object(view):
            obj = original_get_object(view)
            Subscription.objects.filter(pk=subscription.pk).update(last_notified_level='hazardous')
            return obj

        with patch.object(endpoints.Subscribe, 'get_object', stale_get_object):
            response = subscribe(request, monitor_id=self.monitor.pk)

        assert response.status_code == 200
        subscription.refresh_from_db()
        assert subscription.level == PM25.Levels.HAZARDOUS.key
        assert subscription.last_notified_level == 'hazardous'

    def test_unsubscribe(self):
        '''
            Test that we can GET the monitor detail endpoint.
        '''
        Subscription.objects.create(
            user=self.user,
            monitor=self.monitor,
            level=PM25.Levels.UNHEALTHY.key
        )

        url = reverse('api:v2:monitors:alerts:subscribe', kwargs={
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


class CurrentAlertValuesTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        cache.clear()
        self.factory = CsrfExemptRequestFactory()
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.lookup = AlertEvaluator.split_config(self.monitor.alertable_entry_types[PM25])[0]

    def tearDown(self):
        cache.clear()

    def get(self, monitor):
        url = reverse('api:v2:monitors:alerts:current', kwargs={'monitor_id': monitor.pk})
        request = self.factory.get(url)
        request.monitor = monitor
        response = current_alerts(request, monitor_id=monitor.pk)
        return response, get_response_data(response)

    def mark_active(self, monitor):
        entry = PM25.objects.create(monitor=monitor, value=5, timestamp=timezone.now(), **self.lookup)
        LatestEntry.objects.create(
            monitor=monitor,
            entry_type=PM25.entry_type,
            stage=entry.stage,
            processor='',
            entry_id=entry.pk,
            timestamp=entry.timestamp,
        )

    def store_results(self, monitor):
        now = timezone.now()
        for i in range(30):
            PM25.objects.create(
                monitor=monitor,
                value=40,
                timestamp=now - timedelta(minutes=i * 2),
                **self.lookup
            )
        current.store(monitor, AlertEvaluator(monitor).get_results(), now)

    def test_serves_stored_result(self):
        self.store_results(self.monitor)
        response, content = self.get(self.monitor)

        assert response.status_code == 200
        assert content['data']['pm25']['status'] == 'ok'
        assert set(content['data']['pm25']) == {'status', *current.RESULT_FIELDS}
        assert content['data']['pm25']['level'] == 'unhealthy_sensitive'
        assert re.search(r'[+-]\d\d:\d\d$', content['data']['pm25']['window']['end'])
        assert response['Cache-Control'] == 'public, max-age=60'
        assert isinstance(content['data']['pm25']['value'], float)
        # The 30 readings span the last hour only, so the hour before is empty.
        assert content['data']['pm25']['previous'] == {
            'status': 'no_data', 'value': None, 'level': None, 'latest_timestamp': None,
        }

    def test_previous_value_is_a_number(self):
        now = timezone.now()
        for i in range(60):
            PM25.objects.create(
                monitor=self.monitor, value=40,
                timestamp=now - timedelta(minutes=i * 2), **self.lookup
            )
        current.store(monitor=self.monitor, results=AlertEvaluator(self.monitor).get_results(now=now), evaluated_at=now)
        data = self.client.get(f'/api/2.0/monitors/{self.monitor.pk}/alerts/current/').json()['data']['pm25']
        assert isinstance(data['value'], float)
        assert data['previous']['status'] == 'ok'
        assert isinstance(data['previous']['value'], float)
        # Pacific offset, like the current value's, and an older reading.
        assert re.search(r'[+-]\d\d:\d\d$', data['previous']['latest_timestamp'])
        assert data['previous']['latest_timestamp'] < data['latest_timestamp']

    def test_miss_active_is_pending(self):
        self.mark_active(self.monitor)
        response, content = self.get(self.monitor)

        assert response.status_code == 200
        assert list(content['data']) == ['pm25']
        pending = content['data']['pm25']
        assert pending['status'] == 'pending'
        assert all(value is None for key, value in pending.items() if key != 'status')

    def test_miss_inactive_is_no_data(self):
        # The middleware's cached monitor can carry a stale is_active.
        self.monitor.__dict__['is_active'] = True
        response, content = self.get(self.monitor)

        assert response.status_code == 200
        assert content['data']['pm25']['status'] == 'no_data'

    def test_type_without_alerts_is_empty(self):
        monitor = VOZBox.objects.create(sensor_id='e00fce68f12da1a0c5de6248', name='Test', location='outside')
        response, content = self.get(monitor)

        assert response.status_code == 200
        assert content['data'] == {}

    def test_hidden_monitor_is_served(self):
        self.store_results(self.monitor)
        self.monitor.is_hidden = True
        self.monitor.save()
        response = self.client.get(f'/api/2.0/monitors/{self.monitor.pk}/alerts/current/')

        assert response.status_code == 200
        assert response.json()['data']['pm25']['status'] == 'ok'

    def test_unknown_id_404s(self):
        response = self.client.get('/api/2.0/monitors/doesnotexist/alerts/current/')
        assert response.status_code == 404
        assert response['Cache-Control'] == 'no-cache'

    def test_well_formed_unknown_id_404s(self):
        unknown = SmallUUID()
        response = self.client.get(f'/api/2.0/monitors/{unknown}/alerts/current/')
        assert response.status_code == 404
        assert response['Cache-Control'] == 'no-cache'

    def test_client_get_existing_monitor(self):
        self.store_results(self.monitor)
        response = self.client.get(f'/api/2.0/monitors/{self.monitor.pk}/alerts/current/')

        assert response.status_code == 200
        assert response['Cache-Control'] == 'public, max-age=60'
        assert response.json()['data']['pm25']['status'] == 'ok'
