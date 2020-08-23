from resticus import serializers

from camp.apps.monitors.models import Entry
from camp.apps.monitors.purpleair.models import PurpleAir

MONITOR_FIELDS = {
    PurpleAir: ['purple_id'],
}


class EntrySerializer(serializers.Serializer):
    fields = ['timestamp', 'sensor']
    value_fields = [
        'celcius', 'fahrenheit', 'humidity', 'pressure',
        'pm10_env', 'pm25_env', 'pm100_env',
        'pm10_standard', 'pm25_standard', 'pm100_standard',
        'pm25_avg_15', 'pm25_avg_60', 'pm25_aqi', 'pm100_aqi',
        'particles_03um', 'particles_05um', 'particles_100um',
        'particles_10um', 'particles_25um', 'particles_50um',
    ]


class MonitorSerializer(serializers.Serializer):
    fields = [
        'id',
        'name',
        'device',
        'is_active',
        'is_sjvair',
        'position',
        'location',
        'latest',
    ]

    def fixup(self, instance, data):
        fields = MONITOR_FIELDS.get(instance.__class__)
        if fields is not None:
            extra = serializers.serialize(instance, MONITOR_FIELDS[instance.__class__])
            data.update(**extra)
        return data
