from resticus import serializers


class CalHeatScoreSerializer(serializers.Serializer):
    fields = (
        ('zip_code', lambda r: r.region.external_id),
        'date',
        'score',
        ('score_display', lambda r: r.get_score_display()),
    )
