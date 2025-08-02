from datetime import datetime, timedelta

from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from camp.apps.accounts.models import User
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.entries.models import PM25, Humidity, Temperature
from camp.api.v2.monitors.endpoints import EntryExport
from camp.utils.datetime import make_aware
from camp.utils.test import debug, get_response_data


class EntryExportEndpointTests(TestCase):
    fixtures = ['purple-air', 'users']

    def setUp(self):
        self.factory = RequestFactory()
        self.monitor = PurpleAir.objects.get(purple_id=8892)
        self.start = timezone.now().date() - timedelta(days=7)
        self.end = timezone.now().date()
        self.user = User.objects.get(email='user@sjvair.com')

        # Create PM2.5 and humidity entries over multiple days
        for i in range(7):
            timestamp = make_aware(datetime.combine(self.start + timedelta(days=i), datetime.min.time()))
            PM25.objects.create(
                monitor=self.monitor, timestamp=timestamp,
                sensor='a', stage=PM25.Stage.RAW, value=10.0 + i
            )
            Humidity.objects.create(
                monitor=self.monitor, timestamp=timestamp,
                stage=Humidity.Stage.RAW, value=40.0 + i
            )
            Temperature.objects.create(
                monitor=self.monitor, timestamp=timestamp,
                stage=Humidity.Stage.RAW, value=80.0 + i
            )

    def test_entry_export_accepted(self):
        url = reverse('api:v2:monitors:entry-export', kwargs={'monitor_id': self.monitor.pk})
        data = {
            'start_date': self.start.strftime('%Y-%m-%d'),
            'end_date': self.end.strftime('%Y-%m-%d'),
        }
        request = self.factory.post(url, data)
        request.monitor = self.monitor
        request.user = self.user

        response = EntryExport.as_view()(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 202
        assert 'task_id' in content

    def test_entry_export_missing_dates(self):
        url = reverse('api:v2:monitors:entry-export', kwargs={'monitor_id': self.monitor.pk})
        request = self.factory.post(url, {})
        request.monitor = self.monitor
        request.user = self.user

        response = EntryExport.as_view()(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 400
        assert 'start_date' in content['errors']
        assert 'end_date' in content['errors']

    def test_entry_export_date_too_long(self):
        url = reverse('api:v2:monitors:entry-export', kwargs={'monitor_id': self.monitor.pk})
        data = {
            'start_date': (self.start - timedelta(days=365)).strftime('%Y-%m-%d'),
            'end_date': self.end.strftime('%Y-%m-%d'),
        }
        request = self.factory.post(url, data)
        request.monitor = self.monitor
        request.user = self.user

        response = EntryExport.as_view()(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 400
        assert 'errors' in content
        assert any('Maximum export range' in err['message'] for err in content['errors']['__all__'])

    def test_email_sent_to_authenticated_user(self):
        url = reverse('api:v2:monitors:entry-export', kwargs={'monitor_id': self.monitor.pk})
        data = {
            'start_date': self.start.strftime('%Y-%m-%d'),
            'end_date': self.end.strftime('%Y-%m-%d')
        }

        request = self.factory.post(url, data)
        request.monitor = self.monitor
        request.user = self.user

        response = EntryExport.as_view()(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 202
        assert 'task_id' in content

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [self.user.email]
        assert 'Your SJVAir data export' in mail.outbox[0].subject

    def test_no_email_sent_for_anonymous_user(self):
        url = reverse('api:v2:monitors:entry-export', kwargs={'monitor_id': self.monitor.pk})
        data = {
            'start_date': self.start.strftime('%Y-%m-%d'),
            'end_date': self.end.strftime('%Y-%m-%d')
        }

        request = self.factory.post(url, data)
        request.user = AnonymousUser()
        request.monitor = self.monitor

        response = EntryExport.as_view()(request, monitor_id=self.monitor.pk)

        assert response.status_code == 401
        assert len(mail.outbox) == 0
