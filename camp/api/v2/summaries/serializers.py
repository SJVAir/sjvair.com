from django.conf import settings

from resticus import serializers


def _timestamp(s):
    return s.timestamp.astimezone(settings.DEFAULT_TIMEZONE).isoformat()


class MonitorSummarySerializer(serializers.Serializer):
    fields = [
        ('timestamp', _timestamp),
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
        ('timestamp', _timestamp),
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
