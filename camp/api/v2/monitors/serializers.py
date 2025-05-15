from resticus import serializers

from camp.apps.monitors.airgradient.models import AirGradient
from camp.apps.monitors.purpleair.models import PurpleAir


class EntrySerializer(serializers.Serializer):
    fields = [
        ('timestamp', lambda entry: entry.timestamp_pst),
        'sensor',
        'stage',
        'processor',
    ]

    def fixup(self, instance, data):
        data.update(instance.serialized_data())
        return data


class MonitorSerializer(serializers.Serializer):
    fields = [
        'id',
        'name',
        ('type', lambda monitor: monitor.monitor_type),
        ('device', lambda monitor: monitor.get_device()),
        'is_active',
        'is_sjvair',
        'position',
        ('last_active_limit', lambda monitor: monitor.LAST_ACTIVE_LIMIT),
        'location',
        'county',
        'data_source',
        'data_providers',
    ]

    monitor_extras = {
        PurpleAir: ['purple_id'],
        AirGradient: [
            'location_id',
            ('dual_channel', lambda monitor: monitor.is_dual_channel)
        ],
    }

    def fixup(self, instance, data):
        fields = self.monitor_extras.get(instance.__class__)
        if fields is not None:
            extra = serializers.serialize(instance, fields)
            data.update(**extra)
        return data
