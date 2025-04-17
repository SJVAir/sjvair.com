from resticus import serializers

from camp.apps.monitors.models import Entry
from camp.apps.monitors.purpleair.models import PurpleAir


class EntrySerializer(serializers.Serializer):
    fields = [
        'timestamp',
        'sensor',
    ]

    def fixup(self, instance, data):
        data.update(instance.declared_data())
        if instance.is_calibratable:
            data['calibration'] = instance.calibration
        return data
    

class MonitorSerializer(serializers.Serializer):
    fields = [
        'id',
        'name',
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
    }

    def fixup(self, instance, data):
        fields = self.monitor_extras.get(instance.__class__)
        if fields is not None:
            extra = serializers.serialize(instance, fields)
            data.update(**extra)

        try:
            data['latest'] = EntrySerializer(instance.latest_entry).serialize()
            data['latest']['label'] = instance.latest_entry.label
        except AttributeError:
            pass

        return data