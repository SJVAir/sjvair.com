from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property

from resticus import generics

from .filters import SensorFilter
from .forms import PayloadForm
from camp.apps.sensors.models import Sensor, SensorData


class SensorMixin():
    model = Sensor
    fields = [
        'id',
        'name',
        'is_active',
        'position',
        'location',
        'altitude',
        ('latest', {
            'fields': [
                'id',
                'timestamp',
                'celcius',
                'fahrenheit',
                'humidity',
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


class SensorDetail(SensorMixin, generics.DetailUpdateEndpoint):
    lookup_url_kwarg = 'sensor_id'


class SensorData(generics.ListCreateEndpoint):
    model = SensorData
    form_class = PayloadForm
    fields = ['id', 'sensor_id', 'timestamp', 'position', 'location', 'altitude',
        'celcius', 'fahrenheit', 'humidity', 'pressure', 'pm2_a', 'pm2_b']

    @cached_property
    def sensor(self):
        return get_object_or_404(Sensor, pk=self.kwargs['sensor_id'])

    def get_queryset(self):
        return self.model.objects.filter(sensor_id=self.sensor.pk)

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.sensor = self.sensor
        self.object.position = self.sensor.position
        self.object.location = self.sensor.location
        self.object.altitude = self.sensor.altitude
        self.object.process()  # TODO: Background task
        self.sensor.update_latest()
        return {'data': self.serialize(self.object, include=['sensor'])}
