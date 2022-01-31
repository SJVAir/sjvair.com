from resticus import serializers

from camp.apps.monitors.models import Entry
from camp.apps.monitors.purpleair.models import PurpleAir

MONITOR_FIELDS = {
    PurpleAir: ['purple_id'],
}


class EntrySerializer(serializers.Serializer):
    base_fields = ['timestamp', 'sensor']
    value_fields = [
        'celcius', 'fahrenheit', 'humidity', 'pressure',
        'pm10', 'pm25', 'pm100', 'pm25_avg_15', 'pm25_avg_60',
        'particles_03um', 'particles_05um', 'particles_100um',
        'particles_10um', 'particles_25um', 'particles_50um',
    ]

    fields = base_fields + value_fields


class MonitorSerializer(serializers.Serializer):
    fields = [
        'id',
        'name',
        'device',
        'is_active',
        'is_sjvair',
        'position',
        ('last_active_limit', lambda monitor: monitor.LAST_ACTIVE_LIMIT),
        'location',
        ('latest', EntrySerializer),
        'county'
    ]

    def fixup(self, instance, data):
        fields = MONITOR_FIELDS.get(instance.__class__)
        extra = serializers.serialize(instance, MONITOR_FIELDS.get(instance.__class__, []))
        data.update(**extra)
        return data
