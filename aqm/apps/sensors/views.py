from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property

from resticus import generics

from .filters import SensorFilter
from .forms import PayloadForm
from .models import Sensor, SensorData


class SensorList(generics.ListEndpoint):
    model = Sensor
    filter_class = SensorFilter
    fields = [
        'id',
        'name',
        'position',
        # ('latest_data', {
        #     'timestamp',
        #     'celcius',
        #     'fahrenheit',
        #     'humidity',
        #     'pm2_a',
        #     'pm2_b',
        # })
    ]


class SensorDetail(generics.DetailUpdateEndpoint):
    model = Sensor
    fields = ['id', 'name', 'position']
    lookup_url_kwarg = 'sensor_id'


class SensorData(generics.ListCreateEndpoint):
    model = SensorData
    form_class = PayloadForm
    fields = ['timestamp', 'position', 'celcius', 'fahrenheit',
        'humidity', 'pm2']

    @cached_property
    def sensor(self):
        get_object_or_404(Sensor, pk=self.kwargs['pk'])

    def get_queryset(self):
        return self.model.objects.filter(sensor_id=self.sensor.pk)

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.sensor = self.sensor
        self.object.position = self.sensor.position
        self.object.save()
        return {'object': self.serialize(self.object)}
