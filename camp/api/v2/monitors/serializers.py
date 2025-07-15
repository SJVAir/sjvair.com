from resticus import serializers

from camp.apps.monitors.airgradient.models import AirGradient
from camp.apps.monitors.purpleair.models import PurpleAir


class EntrySerializer(serializers.Serializer):
    fields = [
        ('timestamp', lambda entry: entry.timestamp_pst),
        'sensor',
        'stage',
        'processor',
        'entry_type',
    ]

    def fixup(self, instance, data):
        data.update(instance.serialized_data())
        return data


class HealthCheckSerializer(serializers.Serializer):
    fields = [
        'hour',
        'score',
        'rpd_pairwise',
        'correlation',
        'channel_a_sanity',
        'channel_b_sanity',
        'grade',
    ]


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
        if instance.supports_health_checks() and instance.health:
            data['health'] = HealthCheckSerializer(instance.health).serialize()
        return data
