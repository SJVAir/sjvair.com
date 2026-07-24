from resticus import serializers

from camp.api.v2.regions.serializers import RegionSerializer


class ForecastSerializer(serializers.Serializer):
    fields = (
        ('id', lambda f: f.sqid),
        ('region', lambda f: RegionSerializer(f.region).serialize()),
        'zone_name', 'forecast_date', 'issued_date', 'published_at',
        'aqi_value', 'aqi_category', 'pollutant', 'color',
        'burn_status', 'burn_status_text',
        'air_alert', 'air_alert_start', 'air_alert_end',
    )
