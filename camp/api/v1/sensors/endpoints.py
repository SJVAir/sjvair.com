from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property

from resticus import generics

from .filters import SensorFilter, SensorDataFilter
from .forms import PayloadForm
from ..endpoints import CSVExport
from camp.apps.sensors.models import Sensor, SensorData


class SensorMixin():
    model = Sensor
    fields = [
        'id',
        'name',
        'is_active',
        'position',
        'location',
        'epa_pm25_aqi',
        'epa_pm100_aqi',
        ('latest', {
            'fields': [
                'id',
                'timestamp',
                'celcius',
                'fahrenheit',
                'humidity',
                'pressure',
                'pm2_a',
                'pm2_b',
            ]
        })
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.select_related('latest')
        return queryset


class SensorList(SensorMixin, generics.ListEndpoint):
    # streaming = False
    filter_class = SensorFilter
    paginate = False

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.exclude(latest__isnull=True)
        return queryset


class SensorDetail(SensorMixin, generics.DetailUpdateEndpoint):
    lookup_url_kwarg = 'sensor_id'


class SensorData(generics.ListCreateEndpoint):
    model = SensorData
    form_class = PayloadForm
    filter_class = SensorDataFilter
    fields = ['id', 'timestamp', 'position', 'location', 'altitude',
        'celcius', 'fahrenheit', 'humidity', 'pressure', 'pm2_a', 'pm2_b']
    page_size = 2880 # 10 days worth of data

    @cached_property
    def sensor(self):
        return get_object_or_404(Sensor, pk=self.kwargs['sensor_id'])

    def get_queryset(self):
        return self.model.objects.filter(
            sensor_id=self.sensor.pk,
            is_processed=True,
        ).order_by('-timestamp')

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.sensor = self.sensor
        self.object.position = self.sensor.position
        self.object.location = self.sensor.location
        self.object.process()  # TODO: Background task
        self.sensor.update_latest()
        return {'data': self.serialize(self.object, include=['sensor'])}


class DataExport(CSVExport, generics.ListEndpoint):
    columns = [
        ('id', lambda i: i.pk),
        ('device_id', lambda i: i.sensor_id),
        ('timestamp', lambda i: int(i.timestamp.timestamp())),
        ('date', lambda i: i.timestamp.date()),
        ('time', lambda i: i.timestamp.time()),
        ('celcius', lambda i: i.celcius),
        ('fahrenheit', lambda i: i.fahrenheit),
        ('humidity', lambda i: i.humidity),
        ('pressure', lambda i: i.pressure),

        ('pm10_standard (A)', lambda i: i.pm2_a.get('pm10_standard') if i.pm2_a else ''),
        ('pm25_standard (A)', lambda i: i.pm2_a.get('pm25_standard') if i.pm2_a else ''),
        ('pm100_standard (A)', lambda i: i.pm2_a.get('pm100_standard') if i.pm2_a else ''),
        ('pm10_env (A)', lambda i: i.pm2_a.get('pm10_env') if i.pm2_a else ''),
        ('pm25_env (A)', lambda i: i.pm2_a.get('pm25_env') if i.pm2_a else ''),
        ('pm100_env (A)', lambda i: i.pm2_a.get('pm100_env') if i.pm2_a else ''),
        ('particles_03um (A)', lambda i: i.pm2_a.get('particles_03um') if i.pm2_a else ''),
        ('particles_05um (A)', lambda i: i.pm2_a.get('particles_05um') if i.pm2_a else ''),
        ('particles_10um (A)', lambda i: i.pm2_a.get('particles_10um') if i.pm2_a else ''),
        ('particles_25um (A)', lambda i: i.pm2_a.get('particles_25um') if i.pm2_a else ''),
        ('particles_50um (A)', lambda i: i.pm2_a.get('particles_50um') if i.pm2_a else ''),
        ('particles_100um (A)', lambda i: i.pm2_a.get('particles_100um') if i.pm2_a else ''),

        ('pm10_standard (B)', lambda i: i.pm2_b.get('pm10_standard') if i.pm2_a else ''),
        ('pm25_standard (B)', lambda i: i.pm2_b.get('pm25_standard') if i.pm2_a else ''),
        ('pm100_standard (B)', lambda i: i.pm2_b.get('pm100_standard') if i.pm2_a else ''),
        ('pm10_env (B)', lambda i: i.pm2_b.get('pm10_env') if i.pm2_a else ''),
        ('pm25_env (B)', lambda i: i.pm2_b.get('pm25_env') if i.pm2_a else ''),
        ('pm100_env (B)', lambda i: i.pm2_b.get('pm100_env') if i.pm2_a else ''),
        ('particles_03um (B)', lambda i: i.pm2_b.get('particles_03um') if i.pm2_a else ''),
        ('particles_05um (B)', lambda i: i.pm2_b.get('particles_05um') if i.pm2_a else ''),
        ('particles_10um (B)', lambda i: i.pm2_b.get('particles_10um') if i.pm2_a else ''),
        ('particles_25um (B)', lambda i: i.pm2_b.get('particles_25um') if i.pm2_a else ''),
        ('particles_50um (B)', lambda i: i.pm2_b.get('particles_50um') if i.pm2_a else ''),
        ('particles_100um (B)', lambda i: i.pm2_b.get('particles_100um') if i.pm2_a else ''),
    ]

    @cached_property
    def model(self):
        # Ugghhh...
        from camp.apps.sensors.models import SensorData
        return SensorData

    @cached_property
    def sensor(self):
        return get_object_or_404(Sensor, pk=self.kwargs['sensor_id'])

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        queryset = queryset.filter(sensor_id=self.sensor.pk)
        return queryset
