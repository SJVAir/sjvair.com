import csv

from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from pprint import pprint

import pytest

from django.conf import settings
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from camp.api.v2.monitors import endpoints
from camp.apps.entries import models as entry_models
from camp.apps.entries.utils import get_all_entry_models
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.datetime import make_aware
from camp.utils.test import debug, get_response_data

closest_monitor = endpoints.ClosestMonitor.as_view()
current_data = endpoints.CurrentData.as_view()
monitor_list = endpoints.MonitorList.as_view()
monitor_detail = endpoints.MonitorDetail.as_view()
monitor_meta = endpoints.MonitorMetaEndpoint.as_view()
create_entry = endpoints.CreateEntry.as_view()
entry_list = endpoints.EntryList.as_view()
entry_csv = endpoints.EntryCSV.as_view()

pytestmark = [
    pytest.mark.usefixtures('purpleair_monitor'),
    pytest.mark.django_db(transaction=True),
]


class EndpointTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def get_purple_air(self):
        return PurpleAir.objects.get(purple_id=8892)

    def get_bam1022(self):
        return BAM1022.objects.get(name='CCAC')

    def test_monitor_list(self):
        '''
            Test that we can GET the monitor list endpoint.
        '''
        url = reverse('api:v2:monitors:monitor-list')
        request = self.factory.get(url)
        response = monitor_list(request)
        content = get_response_data(response)
        assert response.status_code == 200

    def _fetch_monitor_meta(self):
        url = reverse('api:v2:monitors:monitor-meta')
        request = self.factory.get(url)
        response = monitor_meta(request)
        return response, get_response_data(response)

    @override_settings(DEFAULT_POLLUTANT='pm25')
    def test_monitor_meta_pm25(self):
        '''
            Test that we can GET the monitor meta endpoint.
        '''
        response, content = self._fetch_monitor_meta()
        assert response.status_code == 200
        assert content['data']['default_pollutant'] == 'pm25'

    @override_settings(DEFAULT_POLLUTANT='o3')
    def test_monitor_meta_o3(self):
        response, content = self._fetch_monitor_meta()
        assert response.status_code == 200
        assert content['data']['default_pollutant'] == 'o3'

    @override_settings(DEFAULT_POLLUTANT='lolnope')
    def test_monitor_meta_invalid(self):
        response, content = self._fetch_monitor_meta()
        assert response.status_code == 200
        assert content['data']['default_pollutant'] == 'pm25'

    def test_current_data(self):
        '''
            Test that we can GET the current data endpoint.
        '''
        kwargs = {'entry_type': 'pm25'}
        url = reverse('api:v2:monitors:current-data', kwargs=kwargs)
        request = self.factory.get(url)
        response = current_data(request, **kwargs)
        content = get_response_data(response)
        assert response.status_code == 200

    def test_closest_monitor(self):
        '''
            Test that we can GET the current data endpoint.
        '''
        monitor = self.get_purple_air()
        monitor.create_entry(
            entry_models.PM25,
            timestamp=timezone.now(),
            value=10.0,
            sensor='a',
            stage=entry_models.PM25.Stage.CLEANED
        )

        kwargs = {'entry_type': 'pm25'}
        url = reverse('api:v2:monitors:monitor-closest', kwargs=kwargs)
        params = {
            'latitude': monitor.position.y,
            'longitude': monitor.position.x,
        }
        request = self.factory.get(url, params)
        response = closest_monitor(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert isinstance(content['data'], list)
        assert 1 <= len(content['data']) <= 3

        for monitor in content['data']:
            assert 'latest' in monitor
            assert monitor['latest']['entry_type'] == kwargs['entry_type']

            assert 'distance' in monitor
            assert isinstance(monitor['distance'], (float, int))

    def test_monitor_detail(self):
        '''
            Test that we can GET the monitor detail endpoint.
        '''
        monitor = self.get_purple_air()
        url = reverse('api:v2:monitors:monitor-detail', kwargs={
            'monitor_id': monitor.pk
        })
        request = self.factory.get(url)
        request.monitor = monitor
        response = monitor_detail(request, monitor_id=monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data']['id'] == str(monitor.pk)

    def test_entry_list(self):
        '''
            Test that we can GET the entry list endpoint.
        '''
        monitor = self.get_purple_air()

        kwargs = {
            'monitor_id': monitor.pk,
            'entry_type': 'pm25'
        }

        url = reverse('api:v2:monitors:entry-list', kwargs=kwargs)
        request = self.factory.get(url)
        request.monitor = monitor
        response = entry_list(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert {e['stage'] for e in content['data']} == set([monitor.get_default_stage(entry_models.PM25).value])

    def test_entry_list_sensor(self):
        '''
            Test that we can GET the entry list endpoint.
        '''
        monitor = self.get_purple_air()

        kwargs = {
            'monitor_id': monitor.pk,
            'entry_type': 'pm25'
        }

        url = reverse('api:v2:monitors:entry-list', kwargs=kwargs)
        params = {'sensor': 'b', 'stage': 'raw'}
        request = self.factory.get(url, params)
        request.monitor = monitor
        response = entry_list(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert {e['sensor'] for e in content['data']} == set([params['sensor']])
        assert {e['processor'] for e in content['data']} == set([''])

    def test_entry_list_processor(self):
        '''
            Test that we can GET the entry list endpoint.
        '''
        monitor = self.get_purple_air()

        monitor.create_entry(
            entry_models.PM25,
            timestamp=timezone.now(),
            value=10.0,
            sensor='a',
            stage=entry_models.PM25.Stage.CALIBRATED,
            processor='EPA_PM25_Oct2021'
        )

        kwargs = {
            'monitor_id': monitor.pk,
            'entry_type': 'pm25'
        }

        url = reverse('api:v2:monitors:entry-list', kwargs=kwargs)
        params = {'processor': 'EPA_PM25_Oct2021'}
        request = self.factory.get(url, params)
        request.monitor = monitor
        response = entry_list(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert {e['stage'] for e in content['data']} == set([entry_models.PM25.Stage.CALIBRATED.value])
        assert {e['processor'] for e in content['data']} == set([params['processor']])

    def test_entry_list_timestamp(self):
        '''
            Test that we can GET the entry list endpoint.
        '''
        monitor = self.get_purple_air()

        pacific_midnight = make_aware(datetime(2024, 7, 24, 0, 0), tz=settings.DEFAULT_TIMEZONE)

        # Create entries just before and after midnight in UTC
        entry_1 = monitor.create_entry(
            entry_models.PM25,
            timestamp=pacific_midnight - timedelta(minutes=1),  # 11:59pm on July 23 PST
            value=10.0,
            sensor='a',
            stage=monitor.get_default_stage(entry_models.PM25),
        )

        entry_2 = monitor.create_entry(
            entry_models.PM25,
            timestamp=pacific_midnight + timedelta(hours=1),  # 1:00am on July 24 PST
            value=20.0,
            sensor='a',
            stage=monitor.get_default_stage(entry_models.PM25),
        )

        kwargs = {
            'monitor_id': monitor.pk,
            'entry_type': 'pm25'
        }
        url = reverse('api:v2:monitors:entry-list', kwargs=kwargs)
        params = {'timestamp__date': '2024-07-24'}
        request = self.factory.get(url, params)
        request.monitor = monitor
        response = entry_list(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert len(content['data']) == 1
        assert content['data'][0]['timestamp'] == '2024-07-24T01:00:00-07:00'  # PST

    def test_entry_csv(self):
        '''
            Test that we can GET the entry list endpoint.
        '''
        monitor = self.get_purple_air()

        kwargs = {
            'monitor_id': monitor.pk,
            'entry_type': 'pm25'
        }

        url = reverse('api:v2:monitors:entry-csv', kwargs=kwargs)
        request = self.factory.get(url)
        request.monitor = monitor
        response = entry_csv(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert response['Content-Type'] == 'text/csv'

        csv_file = StringIO(content)
        reader = csv.DictReader(csv_file)
        rows = list(reader)

        assert {e['stage'] for e in rows} == set([monitor.get_default_stage(entry_models.PM25).value])

    def test_entry_csv_sensor(self):
        '''
            Test that we can GET the entry list endpoint.
        '''
        monitor = self.get_purple_air()

        kwargs = {
            'monitor_id': monitor.pk,
            'entry_type': 'pm25'
        }

        url = reverse('api:v2:monitors:entry-csv', kwargs=kwargs)
        params = {'sensor': 'b', 'stage': 'raw'}
        request = self.factory.get(url, params)
        request.monitor = monitor
        response = entry_csv(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert response['Content-Type'] == 'text/csv'

        csv_file = StringIO(content)
        reader = csv.DictReader(csv_file)
        rows = list(reader)

        assert {e['sensor'] for e in rows} == set([params['sensor']])
        assert {e['processor'] for e in rows} == set([''])

    def test_entry_csv_processor(self):
        '''
            Test that we can GET the entry list endpoint.
        '''
        monitor = self.get_purple_air()

        monitor.create_entry(
            entry_models.PM25,
            timestamp=timezone.now(),
            value=10.0,
            sensor='',
            stage=entry_models.PM25.Stage.CALIBRATED,
            processor='EPA_PM25_Oct2021'
        )

        kwargs = {
            'monitor_id': monitor.pk,
            'entry_type': 'pm25'
        }

        url = reverse('api:v2:monitors:entry-csv', kwargs=kwargs)
        params = {'processor': 'EPA_PM25_Oct2021'}
        request = self.factory.get(url, params)
        request.monitor = monitor
        response = entry_csv(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert response['Content-Type'] == 'text/csv'

        csv_file = StringIO(content)
        reader = csv.DictReader(csv_file)
        rows = list(reader)

        assert {e['sensor'] for e in rows} == set([''])
        assert {e['processor'] for e in rows} == set([params['processor']])
        assert {e['stage'] for e in rows} == set([entry_models.PM25.Stage.CALIBRATED.value])

    def test_create_entry(self):
        '''
            Test that we can create an entry.
        '''
        monitor = self.get_bam1022()
        payload = {
            'Time': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'AT(C)': Decimal('30.6'),
            'RH(%)': Decimal('25.0'),
            'BP(mmHg)': Decimal('764.5'),
            'ConcHR(ug/m3)': Decimal('14'),
        }
        url = reverse('api:v2:monitors:entry-create', kwargs={'monitor_id': monitor.pk})
        request = self.factory.post(url, payload, HTTP_ACCESS_KEY=str(monitor.access_key))
        request.monitor = monitor
        response = create_entry(request, monitor_id=monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 200
        assert isinstance(content.get('data'), list)
        assert len(content['data']) == 5

        entries = {}
        for entry in content['data']:
            entries.setdefault(entry['entry_type'], [])
            entries[entry['entry_type']].append(entry)

        # Check that the returned entries match the values submitted
        # PM2.5: two stages expected
        pm25_raw, pm25_cleaned = entries['pm25']
        assert Decimal(pm25_raw['value']) == payload['ConcHR(ug/m3)']
        assert pm25_raw['stage'] == entry_models.PM25.Stage.RAW
        assert Decimal(pm25_cleaned['value']) == payload['ConcHR(ug/m3)']
        assert pm25_cleaned['stage'] == entry_models.PM25.Stage.CLEANED

        # Other entries
        temp = entries['temperature'][0]
        humidity = entries['humidity'][0]
        pressure = entries['pressure'][0]

        assert Decimal(temp['temperature_c']) == payload['AT(C)']
        assert Decimal(humidity['value']) == payload['RH(%)']
        assert Decimal(pressure['pressure_mmhg']) == payload['BP(mmHg)']

        # Check that the entries actually exist in the database
        model_map = {Model.label: Model for Model in get_all_entry_models()}
        for entry in content['data']:
            EntryModel = model_map[entry['label']]
            lookup = {
                'monitor_id': monitor.pk,
                'timestamp': entry['timestamp'],
                'stage': entry['stage'],
            }
            if 'sensor' in entry:
                lookup['sensor'] = entry['sensor']
            if 'value' in entry:
                lookup['value'] = Decimal(entry['value'])
            if 'temperature_f' in entry:
                lookup['value'] = Decimal(entry['temperature_f'])
            if 'pressure_mmhg' in entry:
                lookup['value'] = Decimal(entry['pressure_mmhg'])

            assert EntryModel.objects.get(**lookup) is not None

    def test_create_entry_rejected(self):
        monitor = self.get_purple_air()
        assert monitor.ENTRY_UPLOAD_ENABLED is False

        payload = {
            'timestamp': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'pm25': '12.0',
        }

        url = reverse('api:v2:monitors:entry-create', kwargs={'monitor_id': monitor.pk})
        request = self.factory.post(url, payload, HTTP_ACCESS_KEY=str(monitor.access_key))
        request.monitor = monitor
        response = create_entry(request, monitor_id=monitor.pk)
        content = get_response_data(response)

        assert response.status_code == 403
        assert 'errors' in content
        assert content['errors']['detail'][0]['message'] == endpoints.CreateEntry.upload_not_allowed

