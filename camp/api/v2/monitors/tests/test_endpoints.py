import csv

from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from pprint import pprint

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from camp.api.v2.monitors import endpoints
from camp.apps.entries import models as entry_models
from camp.apps.entries.utils import get_all_entry_models
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.datetime import make_aware
from camp.utils.test import debug, get_response_data
from camp.utils.test.helpers import create_hourly_data_for_monitor

closest_monitor = endpoints.ClosestMonitor.as_view()
current_data = endpoints.CurrentData.as_view()
monitors_at = endpoints.MonitorsAt.as_view()
monitor_list = endpoints.MonitorList.as_view()
monitor_detail = endpoints.MonitorDetail.as_view()
monitor_meta = endpoints.MonitorMetaEndpoint.as_view()
create_entry = endpoints.CreateEntry.as_view()
entry_list = endpoints.EntryList.as_view()
entry_csv = endpoints.EntryCSV.as_view()

# A few minutes of per-minute data through the processing pipeline is
# enough for every stage/sensor to exist; a full hour costs seconds.
ENTRY_MINUTES = 5


class EndpointTests(TestCase):
    fixtures = ['purple-air.yaml', 'bam1022.yaml', 'default-calibrations.yaml']

    @classmethod
    def setUpTestData(cls):
        create_hourly_data_for_monitor(PurpleAir.objects.get(sensor_id=8892), minutes=ENTRY_MINUTES)

    def setUp(self):
        self.factory = RequestFactory()

    def get_purple_air(self):
        return PurpleAir.objects.get(sensor_id=8892)

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

    @override_settings(MONITOR_ENABLED_TYPES=['purpleair'])
    def test_monitor_list_filters_by_enabled_types(self):
        '''
            Monitors of a type not listed in MONITOR_ENABLED_TYPES are excluded.
        '''
        url = reverse('api:v2:monitors:monitor-list')
        request = self.factory.get(url, {'_cc': '1'})
        response = monitor_list(request)
        content = get_response_data(response)
        types = {monitor['type'] for monitor in content['data']}
        assert types == {'purpleair'}

    @override_settings(MONITOR_ENABLED_TYPES=['purpleair'])
    def test_monitor_meta_filters_by_enabled_types(self):
        '''
            /meta/ only advertises monitor types listed in MONITOR_ENABLED_TYPES.
        '''
        response, content = self._fetch_monitor_meta()
        assert set(content['data']['monitors'].keys()) == {'purpleair'}

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

    @override_settings(MONITOR_HEALTHY_THRESHOLD=0)
    def test_monitors_at_returns_entry_current_at_timestamp(self):
        # threshold=0 so the monitor is considered healthy despite the
        # test data not creating any HealthCheck rows.
        monitor = self.get_purple_air()
        as_of = make_aware(datetime(2026, 7, 4, 21, 0))
        stage = monitor.get_default_stage(entry_models.PM25)

        entry = entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of - timedelta(minutes=5),
            sensor='a', stage=stage, value=Decimal('12.0'),
        )
        entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of + timedelta(minutes=5),
            sensor='a', stage=stage, value=Decimal('999.0'),
        )

        kwargs = {'entry_type': 'pm25'}
        url = reverse('api:v2:monitors:monitor-at', kwargs=kwargs)
        request = self.factory.get(url, {'timestamp': as_of.isoformat()})
        response = monitors_at(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        ids = [m['id'] for m in content['data']]
        assert str(monitor.pk) in ids
        result = next(m for m in content['data'] if m['id'] == str(monitor.pk))
        assert Decimal(str(result['latest']['value'])) == entry.value

    def test_monitors_at_missing_timestamp_returns_empty(self):
        kwargs = {'entry_type': 'pm25'}
        url = reverse('api:v2:monitors:monitor-at', kwargs=kwargs)
        request = self.factory.get(url)  # no timestamp
        response = monitors_at(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data'] == []

    @override_settings(MONITOR_HEALTHY_THRESHOLD=0)
    def test_monitors_at_filters_by_bbox(self):
        # threshold=0 so the monitor is considered healthy despite the
        # test data not creating any HealthCheck rows.
        monitor = self.get_purple_air()
        as_of = make_aware(datetime(2026, 7, 4, 21, 0))
        stage = monitor.get_default_stage(entry_models.PM25)
        entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of - timedelta(minutes=5),
            sensor='a', stage=stage, value=Decimal('12.0'),
        )

        lon, lat = monitor.position.x, monitor.position.y
        kwargs = {'entry_type': 'pm25'}
        url = reverse('api:v2:monitors:monitor-at', kwargs=kwargs)

        # bbox far away -> excluded
        request = self.factory.get(url, {
            'timestamp': as_of.isoformat(),
            'bbox': f'{lon + 10},{lat + 10},{lon + 11},{lat + 11}',
        })
        response = monitors_at(request, **kwargs)
        assert get_response_data(response)['data'] == []

        # bbox around the monitor -> included
        request = self.factory.get(url, {
            'timestamp': as_of.isoformat(),
            'bbox': f'{lon - 0.01},{lat - 0.01},{lon + 0.01},{lat + 0.01}',
        })
        response = monitors_at(request, **kwargs)
        ids = [m['id'] for m in get_response_data(response)['data']]
        assert str(monitor.pk) in ids

    def test_monitors_at_bad_region_id_404s(self):
        # resticus.views.Endpoint.dispatch() catches Http404 raised anywhere
        # during dispatch (including get_queryset()) and converts it into a
        # 404 JSON response rather than letting it propagate to the caller,
        # matching the pattern used by every other Http404-raising endpoint
        # test in this codebase (e.g. camp/api/v2/summaries/tests.py).
        kwargs = {'entry_type': 'pm25'}
        url = reverse('api:v2:monitors:monitor-at', kwargs=kwargs)
        request = self.factory.get(url, {
            'timestamp': timezone.now().isoformat(),
            'region': 'not-a-real-sqid',
        })
        response = monitors_at(request, **kwargs)
        assert response.status_code == 404

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

    def test_closest_monitor_missing_params(self):
        kwargs = {'entry_type': 'pm25'}
        url = reverse('api:v2:monitors:monitor-closest', kwargs=kwargs)
        request = self.factory.get(url)  # no lat/lon
        response = closest_monitor(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data'] == []

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
        published = monitor.get_published_lookup(entry_models.PM25)
        assert content['data']
        assert {(e['stage'], e['processor']) for e in content['data']} == {(published['stage'].value, published['processor'])}

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
        params = {'timestamp__date': '2024-07-24', 'stage': monitor.get_default_stage(entry_models.PM25).value}
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

        published = monitor.get_published_lookup(entry_models.PM25)
        assert rows
        assert {(e['stage'], e['processor']) for e in rows} == {(published['stage'].value, published['processor'])}

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


class MonitorFilterDeviceTests(TestCase):
    '''
        MonitorFilter.filter_device() hardcodes a device-name -> lookup-field
        map. The purple-air.yaml fixture guarantees a non-CIMIS,
        non-AirGradient monitor exists, so these tests fail if filtering
        doesn't actually narrow the queryset.
    '''

    fixtures = ['purple-air.yaml', 'bam1022.yaml', 'default-calibrations.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        # The map endpoints only surface (monitor type, entry type) pairs
        # with a DefaultCalibration row; these tests exercise the device
        # filter via temperature, so opt the types in.
        from camp.apps.calibrations.models import DefaultCalibration
        for monitor_type in ('cimis', 'purpleair'):
            DefaultCalibration.objects.get_or_create(monitor_type=monitor_type, entry_type='temperature')

    @override_settings(MONITOR_ENABLED_TYPES=[])
    def test_filters_by_cimis_device(self):
        from django.contrib.gis.geos import Point

        CIMIS.objects.create(
            name='CIMIS Station',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )

        url = reverse('api:v2:monitors:monitor-list')
        request = self.factory.get(url, {'device': 'CIMIS'})
        response = monitor_list(request)
        content = get_response_data(response)

        assert response.status_code == 200
        assert len(content['data']) >= 1
        assert all(monitor['type'] == 'cimis' for monitor in content['data'])

    def test_filters_by_airgradient_device(self):
        from camp.apps.monitors.airgradient.models import AirGradient

        AirGradient.objects.create(name='AG Station', device='O-1PP', sensor_id=99999)

        url = reverse('api:v2:monitors:monitor-list')
        request = self.factory.get(url, {'device': 'AirGradient'})
        response = monitor_list(request)
        content = get_response_data(response)

        assert response.status_code == 200
        assert len(content['data']) >= 1
        assert all(monitor['type'] == 'airgradient' for monitor in content['data'])

    @override_settings(MONITOR_HEALTHY_THRESHOLD=0, MONITOR_ENABLED_TYPES=[])
    def test_current_data_filters_by_device(self):
        '''
            CurrentData didn't have filter_class wired in - ?device= was
            silently ignored. threshold=0 so the purpleair fixture (no
            HealthCheck rows) is eligible too, so exclusion here can only
            be the device filter, not the health-check requirement.
        '''
        from django.contrib.gis.geos import Point
        from camp.apps.monitors.purpleair.models import PurpleAir

        purpleair = PurpleAir.objects.get(sensor_id=8892)
        purpleair.create_entry(entry_models.Temperature, timestamp=timezone.now(), value=Decimal('70.0'))

        cimis = CIMIS.objects.create(
            name='CIMIS Station',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        cimis.create_entry(entry_models.Temperature, timestamp=timezone.now(), value=Decimal('75.0'))

        kwargs = {'entry_type': 'temperature'}
        url = reverse('api:v2:monitors:current-data', kwargs=kwargs)
        request = self.factory.get(url, {'device': 'CIMIS'})
        response = current_data(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        ids = [monitor['id'] for monitor in content['data']]
        assert str(cimis.pk) in ids
        assert str(purpleair.pk) not in ids

    @override_settings(MONITOR_ENABLED_TYPES=[])
    def test_closest_monitor_filters_by_device(self):
        '''ClosestMonitor didn't have filter_class wired in - ?device= was silently ignored.'''
        from django.contrib.gis.geos import Point
        from camp.apps.monitors.purpleair.models import PurpleAir

        purpleair = PurpleAir.objects.get(sensor_id=8892)
        purpleair.create_entry(entry_models.Temperature, timestamp=timezone.now(), value=Decimal('70.0'))

        cimis = CIMIS.objects.create(
            name='CIMIS Station',
            station_number='2',
            position=purpleair.position,
            location=CIMIS.LOCATION.outside,
        )
        cimis.create_entry(entry_models.Temperature, timestamp=timezone.now(), value=Decimal('75.0'))

        kwargs = {'entry_type': 'temperature'}
        url = reverse('api:v2:monitors:monitor-closest', kwargs=kwargs)
        params = {
            'latitude': purpleair.position.y,
            'longitude': purpleair.position.x,
            'device': 'CIMIS',
        }
        request = self.factory.get(url, params)
        response = closest_monitor(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        ids = [monitor['id'] for monitor in content['data']]
        assert str(cimis.pk) in ids
        assert str(purpleair.pk) not in ids

    @override_settings(MONITOR_ENABLED_TYPES=[])
    def test_closest_monitor_filters_before_limiting_to_three(self):
        '''
            The device filter must apply before the "3 nearest" slice, not
            after - otherwise a matching monitor just outside the raw top 3
            would be wrongly excluded. Three PurpleAir monitors are closer
            to the search point than the one CIMIS station.
        '''
        from django.contrib.gis.geos import Point
        from camp.apps.monitors.purpleair.models import PurpleAir

        origin = Point(-119.7871, 36.7378, srid=4326)
        for i, sensor_id in enumerate((90001, 90002, 90003), start=1):
            monitor = PurpleAir.objects.create(
                name=f'Nearby PurpleAir {i}',
                sensor_id=sensor_id,
                position=Point(-119.7871 + (0.001 * i), 36.7378, srid=4326),
                location=PurpleAir.LOCATION.outside,
            )
            monitor.create_entry(entry_models.Temperature, timestamp=timezone.now(), value=Decimal('70.0'))

        cimis = CIMIS.objects.create(
            name='CIMIS Station',
            station_number='2',
            position=Point(-119.7871 + 0.01, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        cimis.create_entry(entry_models.Temperature, timestamp=timezone.now(), value=Decimal('75.0'))

        kwargs = {'entry_type': 'temperature'}
        url = reverse('api:v2:monitors:monitor-closest', kwargs=kwargs)
        params = {'latitude': origin.y, 'longitude': origin.x, 'device': 'CIMIS'}
        request = self.factory.get(url, params)
        response = closest_monitor(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        ids = [monitor['id'] for monitor in content['data']]
        assert ids == [str(cimis.pk)]

    @override_settings(MONITOR_HEALTHY_THRESHOLD=0, MONITOR_ENABLED_TYPES=[])
    def test_monitors_at_filters_by_device(self):
        '''MonitorsAt didn't have filter_class wired in - ?device= was silently ignored.'''
        from django.contrib.gis.geos import Point
        from camp.apps.monitors.purpleair.models import PurpleAir

        as_of = timezone.now()

        purpleair = PurpleAir.objects.get(sensor_id=8892)
        purpleair.create_entry(entry_models.Temperature, timestamp=as_of, value=Decimal('70.0'))

        cimis = CIMIS.objects.create(
            name='CIMIS Station',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        cimis.create_entry(entry_models.Temperature, timestamp=as_of, value=Decimal('75.0'))

        kwargs = {'entry_type': 'temperature'}
        url = reverse('api:v2:monitors:monitor-at', kwargs=kwargs)
        request = self.factory.get(url, {'timestamp': as_of.isoformat(), 'device': 'CIMIS'})
        response = monitors_at(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        ids = [monitor['id'] for monitor in content['data']]
        assert str(cimis.pk) in ids
        assert str(purpleair.pk) not in ids



class PublishedEntryTypeTests(TestCase):
    """
    A DefaultCalibration row is the publish switch for the map endpoints
    (current/, at/, closest/): no row for (monitor type, entry type) means
    the type is ingested but not displayed for that pollutant.
    """

    fixtures = ['purple-air.yaml', 'bam1022.yaml', 'default-calibrations.yaml']

    def setUp(self):
        from django.contrib.gis.geos import Point
        from camp.apps.calibrations import processors
        from camp.apps.monitors.vozbox.models import VOZBox

        self.factory = RequestFactory()
        self.now = timezone.now()
        self.vozbox = VOZBox.objects.create(
            sensor_id='e00fce68published',
            name='VOZbox',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=VOZBox.LOCATION.outside,
        )
        self.vozbox.create_entry(entry_models.PM25, sensor='a', timestamp=self.now, value=Decimal('10.0'))
        self.vozbox.create_entry(entry_models.PM25, sensor='b', timestamp=self.now, value=Decimal('4.0'))
        self.vozbox.create_entry(
            entry_models.O3,
            sensor='1',
            timestamp=self.now,
            stage=entry_models.O3.Stage.CALIBRATED,
            processor=processors.VOZBox_QuinnCal.name,
            value=Decimal('35.0'),
        )

    def _current_ids(self, entry_type):
        # CurrentData caches per URL (locmem persists across tests in-process).
        from django.core.cache import cache
        cache.clear()
        kwargs = {'entry_type': entry_type}
        url = reverse('api:v2:monitors:current-data', kwargs=kwargs)
        response = current_data(self.factory.get(url), **kwargs)
        assert response.status_code == 200
        return [m['id'] for m in get_response_data(response)['data']]

    def _at_ids(self, entry_type):
        kwargs = {'entry_type': entry_type}
        url = reverse('api:v2:monitors:monitor-at', kwargs=kwargs)
        request = self.factory.get(url, {'timestamp': self.now.isoformat()})
        response = monitors_at(request, **kwargs)
        assert response.status_code == 200
        return [m['id'] for m in get_response_data(response)['data']]

    def _closest_ids(self, entry_type):
        kwargs = {'entry_type': entry_type}
        url = reverse('api:v2:monitors:monitor-closest', kwargs=kwargs)
        params = {'latitude': self.vozbox.position.y, 'longitude': self.vozbox.position.x}
        response = closest_monitor(self.factory.get(url, params), **kwargs)
        assert response.status_code == 200
        return [m['id'] for m in get_response_data(response)['data']]

    @override_settings(MONITOR_HEALTHY_THRESHOLD=0.9)
    def test_vozbox_o3_is_current_without_pm25_health_checks(self):
        # Health checks score dual-channel PM2.5 only; they must not gate O3.
        assert str(self.vozbox.pk) in self._current_ids('o3')

    @override_settings(MONITOR_HEALTHY_THRESHOLD=0.9)
    def test_vozbox_o3_is_at_without_pm25_health_checks(self):
        assert str(self.vozbox.pk) in self._at_ids('o3')

    def test_vozbox_o3_is_closest(self):
        assert str(self.vozbox.pk) in self._closest_ids('o3')

    @override_settings(MONITOR_HEALTHY_THRESHOLD=0)
    def test_vozbox_pm25_is_not_published(self):
        # Raw PM2.5 is stored (both sensors) but has no DefaultCalibration
        # row, so it stays off every map endpoint even with health disabled.
        assert entry_models.PM25.objects.filter(monitor=self.vozbox).count() == 2
        assert str(self.vozbox.pk) not in self._current_ids('pm25')
        assert str(self.vozbox.pk) not in self._at_ids('pm25')
        assert str(self.vozbox.pk) not in self._closest_ids('pm25')

    @override_settings(MONITOR_HEALTHY_THRESHOLD=0)
    def test_adding_a_row_publishes_the_type(self):
        from camp.apps.calibrations.models import DefaultCalibration
        DefaultCalibration.objects.create(monitor_type='vozbox', entry_type='pm25')
        assert str(self.vozbox.pk) in self._current_ids('pm25')

    def test_pm25_current_still_health_gated(self):
        # Sanity: the PM2.5 gate is untouched -- the purpleair monitor has
        # entries but no HealthCheck rows, so it's excluded at threshold 0.9
        # and included at 0.
        purpleair = PurpleAir.objects.get(sensor_id=8892)
        create_hourly_data_for_monitor(purpleair, minutes=ENTRY_MINUTES)
        with override_settings(MONITOR_HEALTHY_THRESHOLD=0.9):
            assert str(purpleair.pk) not in self._current_ids('pm25')
        with override_settings(MONITOR_HEALTHY_THRESHOLD=0):
            assert str(purpleair.pk) in self._current_ids('pm25')

    def test_meta_reports_published_flag(self):
        url = reverse('api:v2:monitors:monitor-meta')
        response = endpoints.MonitorMetaEndpoint.as_view()(self.factory.get(url))
        content = get_response_data(response)
        entries = content['data']['monitors']['vozbox']['entries']
        assert entries['o3']['published'] is True
        assert entries['pm25']['published'] is False


class PublishedFixtureTests(TestCase):
    fixtures = ['default-calibrations.yaml']

    def test_fixture_is_idempotent_and_matches_existing_rows(self):
        from django.core.management import call_command
        from camp.apps.calibrations.models import DefaultCalibration

        # Already loaded once as a class fixture; the vozbox/o3 row also
        # comes from migration 0007 with its own pk.
        # Loading again must update in place, not collide on unique_together.
        before = DefaultCalibration.objects.count()
        call_command('loaddata', 'default-calibrations.yaml', verbosity=0)
        assert DefaultCalibration.objects.count() == before

        rows = {(d.monitor_type, d.entry_type): d.calibration for d in DefaultCalibration.objects.all()}
        assert rows[('purpleair', 'pm25')] == 'PM25_EPA_Oct2021'
        assert rows[('airnow', 'o3')] == ''
        assert rows[('vozbox', 'o3')] == 'VOZBox_QuinnCal'
        assert ('vozbox', 'pm25') not in rows


@override_settings(MONITOR_HEALTHY_THRESHOLD=0)
class PublishedLatestEntryTests(TestCase):
    '''
    A PurpleAir keeps a LatestEntry for its cleaned PM2.5 and another for
    the calibrated one. current/, closest/, at/ and monitor detail all show
    the one its DefaultCalibration row publishes (PM25_EPA_Oct2021), so the
    map and the detail page agree.
    '''
    fixtures = ['purple-air.yaml', 'default-calibrations.yaml']

    def setUp(self):
        from django.core.cache import cache
        from camp.apps.monitors.models import LatestEntry

        cache.clear()
        self.factory = RequestFactory()
        self.now = timezone.now().replace(microsecond=0)
        self.monitor = PurpleAir.objects.get(pk='jLI5fer7S0uyR7eMYNSPpg')

        # Cleaned is created last, so an unordered pick tends to land on it.
        self.calibrated = self._latest(
            entry_models.PM25.Stage.CALIBRATED, 'PM25_EPA_Oct2021', Decimal('1771.47'))
        self.cleaned = self._latest(
            entry_models.PM25.Stage.CLEANED, 'PM25_LCS_Cleaning', Decimal('1077.00'))

    def _latest(self, stage, processor, value):
        from camp.apps.monitors.models import LatestEntry

        entry = entry_models.PM25.objects.create(
            monitor=self.monitor, timestamp=self.now, sensor='', stage=stage, processor=processor,
            location=self.monitor.location, position=self.monitor.position, value=value,
        )
        LatestEntry.objects.create(
            monitor=self.monitor, entry_type='pm25', entry_id=entry.pk,
            stage=stage, processor=processor, timestamp=self.now,
        )
        return entry

    def _detail(self):
        kwargs = {'monitor_id': self.monitor.pk}
        request = self.factory.get(reverse('api:v2:monitors:monitor-detail', kwargs=kwargs))
        request.monitor = self.monitor
        response = monitor_detail(request, **kwargs)
        assert response.status_code == 200
        return get_response_data(response)['data']['latest']['pm25']

    def _from_list(self, view, name, params=None):
        from django.core.cache import cache
        cache.clear()
        kwargs = {'entry_type': 'pm25'}
        response = view(self.factory.get(reverse(name, kwargs=kwargs), params or {}), **kwargs)
        assert response.status_code == 200
        [monitor] = [m for m in get_response_data(response)['data'] if m['id'] == str(self.monitor.pk)]
        return monitor['latest']

    def _current(self):
        return self._from_list(current_data, 'api:v2:monitors:current-data')

    def _closest(self):
        position = self.monitor.position
        return self._from_list(closest_monitor, 'api:v2:monitors:monitor-closest',
            {'latitude': position.y, 'longitude': position.x})

    def _at(self):
        return self._from_list(monitors_at, 'api:v2:monitors:monitor-at',
            {'timestamp': self.now.isoformat()})

    def _all(self):
        return {
            'detail': self._detail(),
            'current': self._current(),
            'closest': self._closest(),
            'at': self._at(),
        }

    def test_every_endpoint_shows_the_published_calibration(self):
        for name, latest in self._all().items():
            assert latest['processor'] == 'PM25_EPA_Oct2021', name
            assert Decimal(str(latest['value'])) == Decimal('1771.47'), name

    def test_blank_default_calibration_publishes_the_default_stage(self):
        from camp.apps.calibrations.models import DefaultCalibration
        DefaultCalibration.objects.filter(monitor_type='purpleair', entry_type='pm25').update(calibration='')

        for name, latest in self._all().items():
            assert latest['processor'] == 'PM25_LCS_Cleaning', name
            assert Decimal(str(latest['value'])) == Decimal('1077.00'), name

    def _entries(self, view=None, name='api:v2:monitors:entry-list', params=None):
        kwargs = {'monitor_id': self.monitor.pk, 'entry_type': 'pm25'}
        request = self.factory.get(reverse(name, kwargs=kwargs), params or {})
        request.monitor = self.monitor
        response = (view or entry_list)(request, **kwargs)
        assert response.status_code == 200
        return response

    def _entry_processors(self, params=None):
        return {e['processor'] for e in get_response_data(self._entries(params=params))['data']}

    def test_entries_default_to_the_published_calibration(self):
        # The detail chart asks for no stage or processor; it must plot the
        # same series as the reading above it.
        assert self._entry_processors() == {'PM25_EPA_Oct2021'}

    def test_entries_csv_defaults_to_the_published_calibration(self):
        response = self._entries(entry_csv, 'api:v2:monitors:entry-csv')
        rows = list(csv.DictReader(StringIO(get_response_data(response))))
        assert {r['processor'] for r in rows} == {'PM25_EPA_Oct2021'}

    def test_entries_honor_an_explicit_stage(self):
        assert self._entry_processors({'stage': 'cleaned'}) == {'PM25_LCS_Cleaning'}

    def test_entries_honor_an_explicit_processor(self):
        assert self._entry_processors({'processor': 'PM25_LCS_Cleaning'}) == {'PM25_LCS_Cleaning'}

    def test_entries_default_to_the_default_stage_when_calibration_is_blank(self):
        from camp.apps.calibrations.models import DefaultCalibration
        DefaultCalibration.objects.filter(monitor_type='purpleair', entry_type='pm25').update(calibration='')
        assert self._entry_processors() == {'PM25_LCS_Cleaning'}

    def _age_calibrated(self, age):
        from camp.apps.monitors.models import LatestEntry
        timestamp = self.now - age
        entry_models.PM25.objects.filter(pk=self.calibrated.pk).update(timestamp=timestamp)
        LatestEntry.objects.filter(processor='PM25_EPA_Oct2021').update(timestamp=timestamp)

    def test_published_calibration_a_little_behind_is_still_shown(self):
        # The pipeline saves cleaned a moment before EPA; within 3 PurpleAir
        # intervals (6 min) that's the race, not a stale calibration.
        self._age_calibrated(timedelta(minutes=4))
        for name, latest in self._all().items():
            assert latest['processor'] == 'PM25_EPA_Oct2021', name

    def test_stale_published_calibration_gives_way_to_the_default_stage(self):
        # EPA stopped (e.g. a dead humidity sensor) while cleaning carried on.
        self._age_calibrated(timedelta(minutes=10))
        for name, latest in self._all().items():
            assert latest['processor'] == 'PM25_LCS_Cleaning', name
            assert Decimal(str(latest['value'])) == Decimal('1077.00'), name

    def test_at_skips_the_default_stage_query_when_published_is_fresh(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            [monitor] = PurpleAir.objects.filter(pk=self.monitor.pk).with_entry_as_of(
                entry_models.PM25, self.now, seconds=3600)
        assert monitor.latest_entry.pk == self.calibrated.pk
        pm25_queries = [q for q in ctx.captured_queries if 'entries_pm25' in q['sql']]
        assert len(pm25_queries) == 1

    def test_falls_back_to_the_default_stage_without_a_calibrated_entry(self):
        from camp.apps.monitors.models import LatestEntry
        LatestEntry.objects.filter(processor='PM25_EPA_Oct2021').delete()
        self.calibrated.delete()

        for name, latest in self._all().items():
            assert latest['processor'] == 'PM25_LCS_Cleaning', name


@override_settings(MONITOR_ENABLED_TYPES=[])
class MonitorListQueryCountTests(TestCase):
    '''
        Each AirGradient's data_providers reads its place; without
        select_related that was one query per AirGradient on every list
        cache miss (266 locally).
    '''
    fixtures = ['default-calibrations.yaml']

    def setUp(self):
        from camp.apps.monitors.airgradient.models import Place
        self.factory = RequestFactory()
        self.place = Place.objects.create(name='Test Place', url='https://example.com', token='test-token')
        self.sensor_ids = iter(range(93000, 94000))
        cache.clear()

    def tearDown(self):
        cache.clear()

    def add_airgradients(self, count):
        from django.contrib.gis.geos import Point
        from camp.apps.monitors.airgradient.models import AirGradient
        for _ in range(count):
            sensor_id = next(self.sensor_ids)
            AirGradient.objects.create(
                name=f'AirGradient {sensor_id}', sensor_id=sensor_id, place=self.place,
                position=Point(-119.78, 36.73, srid=4326), location=AirGradient.LOCATION.outside,
            )

    def count_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        url = reverse('api:v2:monitors:monitor-list')
        with CaptureQueriesContext(connection) as ctx:
            response = monitor_list(self.factory.get(url, {'_cc': '1'}))
            get_response_data(response)
        assert response.status_code == 200
        return len(ctx)

    def test_query_count_does_not_grow_with_airgradients(self):
        self.add_airgradients(1)
        few = self.count_queries()
        self.add_airgradients(5)
        assert self.count_queries() == few


@override_settings(MONITOR_ENABLED_TYPES=[], MONITOR_HEALTHY_THRESHOLD=0)
class CurrentDataActiveTests(TestCase):
    '''
        current/ lists each public monitor with a position and a latest entry
        of the type, active within MONITOR_ACTIVE_WINDOW_DAYS. "Active" used
        to be get_active()'s join to LatestEntry + DISTINCT, which repeated
        each monitor once per LatestEntry row and pushed the plan over
        Postgres' JIT threshold; it is an EXISTS now.
    '''
    fixtures = ['default-calibrations.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.sensor_ids = iter(range(95000, 96000))
        cache.clear()

    def tearDown(self):
        cache.clear()

    def make(self, age=timedelta(minutes=1), extra_types=(), name='PurpleAir'):
        from django.contrib.gis.geos import Point
        monitor = PurpleAir.objects.create(
            name=name, sensor_id=next(self.sensor_ids),
            position=Point(-119.78, 36.73, srid=4326), location=PurpleAir.LOCATION.outside,
        )
        timestamp = timezone.now() - age
        monitor.create_entry(entry_models.PM25, timestamp=timestamp, value=10.0, sensor='a',
            stage=entry_models.PM25.Stage.CLEANED)
        for EntryModel in extra_types:
            monitor.create_entry(EntryModel, timestamp=timestamp, value=Decimal('50.0'))
        return monitor

    def get_ids(self):
        kwargs = {'entry_type': 'pm25'}
        url = reverse('api:v2:monitors:current-data', kwargs=kwargs)
        response = current_data(self.factory.get(url, {'_cc': '1'}), **kwargs)
        assert response.status_code == 200
        return [m['id'] for m in get_response_data(response)['data']]

    def test_active_window(self):
        window = timedelta(days=settings.MONITOR_ACTIVE_WINDOW_DAYS)
        recent = self.make(age=timedelta(days=10))
        edge = self.make(age=window - timedelta(hours=1))
        self.make(age=window + timedelta(days=1))
        assert sorted(self.get_ids()) == sorted([str(recent.pk), str(edge.pk)])

    def test_ordered_by_name_then_id(self):
        # Same-named monitors are common (the DISTINCT's sort used to break
        # those ties by id; without it they came back in any order).
        monitors = [self.make() for _ in range(5)]
        named = self.make(name='Aardvark')
        expected = [str(named.pk)] + [str(m.pk) for m in sorted(monitors, key=lambda m: m.pk.int)]
        assert self.get_ids() == expected

    def test_each_monitor_once_with_several_latest_entries(self):
        monitor = self.make(extra_types=(entry_models.Temperature, entry_models.Humidity))
        assert monitor.latest_entries.count() >= 3
        assert self.get_ids() == [str(monitor.pk)]

    def test_query_count_and_no_distinct(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        kwargs = {'entry_type': 'pm25'}
        url = reverse('api:v2:monitors:current-data', kwargs=kwargs)

        def run():
            with CaptureQueriesContext(connection) as ctx:
                response = current_data(self.factory.get(url, {'_cc': '1'}), **kwargs)
                get_response_data(response)
            return ctx.captured_queries

        self.make(extra_types=(entry_models.Temperature,))
        few = run()
        for _ in range(5):
            self.make(extra_types=(entry_models.Temperature,))
        many = run()

        # DefaultCalibration lookups (published types, published
        # calibrations), monitors, their LatestEntry rows, latest entries.
        assert len(few) == len(many) == 5
        main = max(many, key=lambda q: len(q['sql']))['sql']
        assert 'DISTINCT' not in main


@override_settings(MONITOR_ENABLED_TYPES=[], MONITOR_HEALTHY_THRESHOLD=0)
class EntryTypeIsActiveTests(TestCase):
    '''
    is_active on current/ and closest/ is for the requested entry type. The
    Ash Mountain case: AirNow stopped sending the site's PM2.5 but kept
    sending O3, so the PM2.5 map showed a months-old reading as active.
    Monitor list/detail keep is_active across every entry type.
    '''
    fixtures = ['default-calibrations.yaml']

    def setUp(self):
        from django.contrib.gis.geos import Point
        cache.clear()
        self.factory = RequestFactory()
        now = timezone.now()
        self.monitor = PurpleAir.objects.create(
            name='Stopped PM2.5', sensor_id=97001,
            position=Point(-119.78, 36.73, srid=4326), location=PurpleAir.LOCATION.outside,
        )
        self.monitor.create_entry(entry_models.PM25, timestamp=now - timedelta(days=2),
            value=10.0, sensor='a', stage=entry_models.PM25.Stage.CLEANED)
        self.monitor.create_entry(entry_models.Temperature, timestamp=now - timedelta(minutes=1),
            value=Decimal('50.0'))

    def tearDown(self):
        cache.clear()

    def _row(self, view, name, params=None, entry_type='pm25'):
        kwargs = {'entry_type': entry_type}
        url = reverse(f'api:v2:monitors:{name}', kwargs=kwargs)
        response = view(self.factory.get(url, params or {'_cc': '1'}), **kwargs)
        assert response.status_code == 200
        rows = [m for m in get_response_data(response)['data'] if m['id'] == str(self.monitor.pk)]
        assert len(rows) == 1
        return rows[0]

    def test_current_data_inactive_when_the_entry_type_stopped(self):
        assert self._row(current_data, 'current-data')['is_active'] is False

    def test_current_data_active_when_the_entry_type_is_recent(self):
        self.monitor.create_entry(entry_models.PM25, timestamp=timezone.now(),
            value=10.0, sensor='a', stage=entry_models.PM25.Stage.CLEANED)
        assert self._row(current_data, 'current-data')['is_active'] is True

    def test_closest_inactive_when_the_entry_type_stopped(self):
        params = {'latitude': self.monitor.position.y, 'longitude': self.monitor.position.x}
        assert self._row(closest_monitor, 'monitor-closest', params)['is_active'] is False

    def test_monitor_detail_still_counts_every_entry_type(self):
        url = reverse('api:v2:monitors:monitor-detail', kwargs={'monitor_id': self.monitor.pk})
        request = self.factory.get(url)
        request.monitor = self.monitor
        response = monitor_detail(request, monitor_id=self.monitor.pk)
        assert get_response_data(response)['data']['is_active'] is True

    def test_latest_entry_has_the_loaded_monitor(self):
        # entry.is_recent reads entry.monitor: the loaded subclass, so no
        # query per entry and the subclass's LAST_ACTIVE_LIMIT.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from camp.apps.monitors.models import Monitor

        monitor, = Monitor.objects.filter(pk=self.monitor.pk).with_latest_entry(entry_models.PM25)
        with CaptureQueriesContext(connection) as ctx:
            assert monitor.latest_entry.monitor is monitor
            assert monitor.latest_entry.is_recent is False
        assert len(ctx.captured_queries) == 0

    def test_is_active_keeps_its_place_in_the_response(self):
        keys = list(self._row(current_data, 'current-data'))
        assert keys.index('is_active') == keys.index('grade') + 1


@override_settings(MONITOR_ENABLED_TYPES=[])
class PublishedOutsidePipelineTests(TestCase):
    '''
    VOZbox and AQLite publish O3 from a processor listed under
    ENTRY_CONFIG['calibrations'] (written outside the per-entry pipeline),
    not under 'processors'. The published lookup has to find it there, or
    at/ falls back to whichever calibrated O3 is newest (e.g. O3_VOZBox).
    '''
    fixtures = ['default-calibrations.yaml']

    def setUp(self):
        from django.contrib.gis.geos import Point
        from camp.apps.monitors.vozbox.models import VOZBox

        cache.clear()
        self.factory = RequestFactory()
        self.now = timezone.now().replace(microsecond=0)
        self.vozbox = VOZBox.objects.create(
            sensor_id='published-outside-pipeline', name='VOZbox',
            position=Point(-119.7871, 36.7378, srid=4326), location=VOZBox.LOCATION.outside,
        )
        # The published QuinnCal reading is older than the regression one.
        self.quinn = self._calibrated('VOZBox_QuinnCal', Decimal('35.0'), self.now - timedelta(minutes=10))
        self._calibrated('O3_VOZBox', Decimal('80.0'), self.now - timedelta(minutes=1))

    def _calibrated(self, processor, value, timestamp):
        return entry_models.O3.objects.create(
            monitor=self.vozbox, timestamp=timestamp, sensor='1', processor=processor,
            stage=entry_models.O3.Stage.CALIBRATED, value=value,
            location=self.vozbox.location, position=self.vozbox.position,
        )

    def test_lookup_finds_calibrations_outside_the_pipeline(self):
        from camp.apps.monitors.aqlite.models import AQLite
        from camp.apps.monitors.vozbox.models import VOZBox

        calibrated = entry_models.O3.Stage.CALIBRATED
        assert VOZBox.get_published_lookup(entry_models.O3) == {
            'stage': calibrated, 'processor': 'VOZBox_QuinnCal'}
        assert AQLite.get_published_lookup(entry_models.O3) == {
            'stage': calibrated, 'processor': 'AQLiteHourlyAggregator'}

    def test_at_shows_the_published_calibration_not_the_newest(self):
        kwargs = {'entry_type': 'o3'}
        url = reverse('api:v2:monitors:monitor-at', kwargs=kwargs)
        request = self.factory.get(url, {'timestamp': self.now.isoformat()})
        response = monitors_at(request, **kwargs)
        assert response.status_code == 200
        [monitor] = [m for m in get_response_data(response)['data'] if m['id'] == str(self.vozbox.pk)]
        assert monitor['latest']['processor'] == 'VOZBox_QuinnCal'
        assert Decimal(str(monitor['latest']['value'])) == Decimal('35.0')
