from resticus import serializers


class MonitorSummarySerializer(serializers.Serializer):
    fields = [
        ('timestamp', lambda s: s.timestamp.isoformat()),
        'entry_type',
        'processor',
        'count',
        'expected_count',
        'minimum',
        'maximum',
        'mean',
        'stddev',
        'p25',
        'p75',
        'is_complete',
    ]


class RegionSummarySerializer(serializers.Serializer):
    fields = [
        ('timestamp', lambda s: s.timestamp.isoformat()),
        'entry_type',
        'count',
        'expected_count',
        'minimum',
        'maximum',
        'mean',
        'stddev',
        'p25',
        'p75',
        'is_complete',
        'station_count',
    ]
