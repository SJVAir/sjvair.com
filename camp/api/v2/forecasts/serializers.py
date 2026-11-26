from resticus import serializers


def region_json(region):
    return {
        'id': region.sqid,
        'type': region.type,
        'external_id': region.external_id,
        'name': region.name,
    }


class ForecastSerializer(serializers.Serializer):
    fields = (
        ('id', lambda f: f.sqid),
        ('region', lambda f: region_json(f.region)),
        'zone_name', 'forecast_date', 'issued_date', 'published_at',
        'aqi_value',
        ('aqi_category', lambda f: str(f.level.label)),
        'pollutant', 'color',
        'burn_status', 'burn_status_text',
        'air_alert', 'air_alert_start', 'air_alert_end',
    )
