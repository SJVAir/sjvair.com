from resticus import serializers


class GranuleSerializer(serializers.Serializer):
    fields = (
        'sqid',
        'timestamp',
        'is_final',
        'version',
        'bounds',
        ('preview_url', lambda granule: granule.preview.url if granule.preview else None),
    )
