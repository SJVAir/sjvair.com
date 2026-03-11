import csv

from datetime import datetime, timedelta
from itertools import islice
from unittest.mock import Mock

import pandas as pd

from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.http import StreamingHttpResponse
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from camp.apps.accounts.models import User
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.entries.models import PM25, Humidity, Temperature
from camp.api.v2.monitors import endpoints
from camp.api.v2.monitors.forms import EntryExportForm
from camp.utils.datetime import make_aware
from camp.utils.test import debug, get_response_data


entry_export = endpoints.EntryExport.as_view()
entry_export_json = endpoints.EntryExportJSON.as_view()
entry_export_csv = endpoints.EntryExportCSV.as_view()


def get_streaming_prefix(response, chunks=2):
    assert hasattr(response, 'streaming_content')
    prefix = b''.join(
        c if isinstance(c, bytes) else c.encode('utf-8')
        for c in islice(response.streaming_content, chunks)
    )
    return prefix.decode('utf-8')


class ExportTestsMixin:
    fixtures = ['purple-air', 'users']

    def setUp(self):
        self.factory = RequestFactory()
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
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


class EntryExportTests(ExportTestsMixin, TestCase):
    def test_entry_export_accepted(self):
        url = reverse('api:v2:monitors:entry-export', kwargs={'monitor_id': self.monitor.pk})
        data = {
            'start_date': self.start.strftime('%Y-%m-%d'),
            'end_date': self.end.strftime('%Y-%m-%d'),
        }
        request = self.factory.post(url, data)
        request.monitor = self.monitor
        request.user = self.user

        response = entry_export(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 202
        assert 'task_id' in content

    def test_entry_export_missing_dates(self):
        url = reverse('api:v2:monitors:entry-export', kwargs={'monitor_id': self.monitor.pk})
        request = self.factory.post(url, {})
        request.monitor = self.monitor
        request.user = self.user

        response = entry_export(request, monitor_id=self.monitor.pk)
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

        response = entry_export(request, monitor_id=self.monitor.pk)
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

        response = entry_export(request, monitor_id=self.monitor.pk)
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

        response = entry_export(request, monitor_id=self.monitor.pk)

        assert response.status_code == 401
        assert len(mail.outbox) == 0


class JSONExportTests(ExportTestsMixin, TestCase):
    def test_entry_json_export(self):
        url = reverse('api:v2:monitors:entry-export-json', kwargs={'monitor_id': self.monitor.pk})
        start_date, end_date = self.start, (self.end - timedelta(days=2))
        params = {
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
        }

        request = self.factory.get(url, params)
        request.monitor = self.monitor

        response = entry_export_json(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200

        expected_timestamp = make_aware(datetime.combine(self.end - timedelta(days=2), datetime.min.time()))
        assert content['data'][-1]['timestamp'] == expected_timestamp.isoformat()
        assert 'pm25' in content['data'][0]
        assert 'humidity' in content['data'][0]

    def test_entry_json_export_default_scope(self):
        url = reverse('api:v2:monitors:entry-export-json', kwargs={'monitor_id': self.monitor.pk})
        start_date, end_date = self.start, (self.end - timedelta(days=2))
        params = {
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
        }

        request = self.factory.get(url, params)
        request.monitor = self.monitor
        request.user = self.user

        response = entry_export_json(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data']
        assert 'timestamp' in content['data'][0]
        assert 'pm25' in content['data'][0]
        assert 'humidity' in content['data'][0]

        expected_last_ts = make_aware(datetime.combine(end_date, datetime.min.time()))
        assert content['data'][-1]['timestamp'] == expected_last_ts.isoformat()

    def test_entry_json_export_empty_dataset(self):
        url = reverse('api:v2:monitors:entry-export-json', kwargs={'monitor_id': self.monitor.pk})
        params = {
            'start_date': '1999-01-01',
            'end_date': '1999-01-02',
        }

        request = self.factory.get(url, params)
        request.monitor = self.monitor
        request.user = self.user

        response = entry_export_json(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content == {'data': []}

    def test_scope_routes_to_full_dataframe_method(self):
        # This test should not depend on real dataframe building.
        df = pd.DataFrame({'pm25': [1.0]}, index=[make_aware(datetime(2025, 1, 1))])

        self.monitor.get_resolved_entries = Mock(return_value=df)
        self.monitor.get_expanded_entries = Mock(return_value=df)

        url = reverse('api:v2:monitors:entry-export-json', kwargs={'monitor_id': self.monitor.pk})
        params = {
            'start_date': self.start.strftime('%Y-%m-%d'),
            'end_date': (self.start + timedelta(days=1)).strftime('%Y-%m-%d'),
            'scope': EntryExportForm.Scope.EXPANDED,
        }

        request = self.factory.get(url, params)
        request.monitor = self.monitor
        request.user = self.user

        response = entry_export_json(request, monitor_id=self.monitor.pk)
        assert response.status_code == 200

        assert self.monitor.get_resolved_entries.call_count == 0
        assert self.monitor.get_expanded_entries.call_count == 1

        _, kwargs = self.monitor.get_expanded_entries.call_args
        assert kwargs['entry_types'] is None
        assert kwargs['start_time'] < kwargs['end_time']

    def test_time_range_start_inclusive_end_exclusive(self):
        # Your get_time_range uses end_date + 1 day at midnight (exclusive).
        start_date = self.start
        end_date = self.start

        start_ts = make_aware(datetime.combine(start_date, datetime.min.time()))
        end_exclusive_ts = make_aware(datetime.combine(end_date + timedelta(days=1), datetime.min.time()))

        url = reverse('api:v2:monitors:entry-export-json', kwargs={'monitor_id': self.monitor.pk})
        params = {
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
        }

        request = self.factory.get(url, params)
        request.monitor = self.monitor
        request.user = self.user

        response = entry_export_json(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)

        timestamps = [row['timestamp'] for row in content['data']]
        assert start_ts.isoformat() in timestamps
        assert end_exclusive_ts.isoformat() not in timestamps


class CSVExportTests(ExportTestsMixin, TestCase):
    fixtures = ['purple-air', 'users']

    def test_entry_csv_export_headers_and_content_disposition(self):
        url = reverse('api:v2:monitors:entry-export-csv', kwargs={'monitor_id': self.monitor.pk})
        params = {
            'start_date': self.start.strftime('%Y-%m-%d'),
            'end_date': (self.start + timedelta(days=1)).strftime('%Y-%m-%d'),
        }

        request = self.factory.get(url, params)
        request.monitor = self.monitor
        request.user = self.user

        response = entry_export_csv(request, monitor_id=self.monitor.pk)

        assert response.status_code == 200
        assert isinstance(response, StreamingHttpResponse)
        assert response['Content-Type'].startswith('text/csv')

        disposition = response.headers.get('Content-Disposition', '')
        assert 'attachment;' in disposition
        assert f'entries_{self.monitor.slug}_{self.monitor.pk}_' in disposition
        assert 'default' not in disposition

        # Consume the full content for this tiny test, then parse first rows.
        body = get_response_data(response)
        reader = csv.reader(body.splitlines())
        rows = list(islice(reader, 3))

        assert rows
        header = rows[0]
        assert header[0] == 'timestamp'
        assert 'pm25' in header
        assert 'humidity' in header

    def test_entry_csv_export_empty_dataset_is_valid_csv(self):
        url = reverse('api:v2:monitors:entry-export-csv', kwargs={'monitor_id': self.monitor.pk})
        params = {
            'start_date': '1999-01-01',
            'end_date': '1999-01-02',
        }

        request = self.factory.get(url, params)
        request.monitor = self.monitor
        request.user = self.user

        response = entry_export_csv(request, monitor_id=self.monitor.pk)
        body = get_response_data(response)

        assert response.status_code == 200
        assert isinstance(body, str)
        # Your current implementation yields a single empty string for empty df
        assert body == '' or body.strip() == ''

    def test_entry_csv_export_includes_scope_in_filename_when_full(self):
        url = reverse('api:v2:monitors:entry-export-csv', kwargs={'monitor_id': self.monitor.pk})
        params = {
            'start_date': self.start.strftime('%Y-%m-%d'),
            'end_date': (self.start + timedelta(days=1)).strftime('%Y-%m-%d'),
            'scope': EntryExportForm.Scope.EXPANDED,
        }

        request = self.factory.get(url, params)
        request.monitor = self.monitor
        request.user = self.user

        response = entry_export_csv(request, monitor_id=self.monitor.pk)

        assert response.status_code == 200
        disposition = response.headers.get('Content-Disposition', '')
        assert EntryExportForm.Scope.EXPANDED in disposition

    def test_csv_is_actually_streaming(self):
        # This test does NOT join the full response.
        url = reverse('api:v2:monitors:entry-export-csv', kwargs={'monitor_id': self.monitor.pk})
        params = {
            'start_date': self.start.strftime('%Y-%m-%d'),
            'end_date': (self.start + timedelta(days=1)).strftime('%Y-%m-%d'),
        }

        request = self.factory.get(url, params)
        request.monitor = self.monitor
        request.user = self.user

        response = entry_export_csv(request, monitor_id=self.monitor.pk)

        assert response.status_code == 200
        assert hasattr(response, 'streaming_content')

        prefix = get_streaming_prefix(response, chunks=2)
        # For non-empty df, the first chunk should usually contain the header row.
        assert 'timestamp' in prefix
