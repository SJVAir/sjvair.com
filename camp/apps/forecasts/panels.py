"""Today's SJVAPCD forecast for a county, on its Region admin page."""

from django.utils import timezone

from camp.apps.forecasts.models import Forecast
from camp.apps.regions.models import Region
from camp.apps.regions.panels import Panel, register


@register
class ForecastPanel(Panel):
    types = (Region.Type.COUNTY,)
    title = "Today's forecast"
    template_name = 'admin/regions/panels/forecast.html'
    order = 5

    def get_context(self):
        today = timezone.localdate()
        latest = (Forecast.objects
            .filter(region=self.region, forecast_date__gte=today)
            .order_by('-issued_date')
            .values_list('issued_date', flat=True)
            .first())
        days = []
        if latest is not None:
            rows = (Forecast.objects
                .filter(region=self.region, forecast_date__gte=today, issued_date=latest)
                .order_by('forecast_date', 'pollutant'))
            by_date = {}
            for row in rows:
                by_date.setdefault(row.forecast_date, []).append({
                    'pollutant': row.pollutant,
                    'label': row.get_pollutant_display(),
                    'aqi': row.aqi_value,
                    'category': row.aqi_category,
                    'color': row.color,
                    'burn': row.burn_status_text or row.burn_status,
                    'alert': row.air_alert,
                    'alert_start': row.air_alert_start,
                    'alert_end': row.air_alert_end,
                })
            days = [{'date': date, 'items': items} for date, items in sorted(by_date.items())]
        return {'issued': latest, 'days': days}

    def tiles(self):
        days = self.context['days']
        if not days or days[0]['date'] != timezone.localdate():
            return []
        worst = max(days[0]['items'], key=lambda item: item['aqi'])
        return [(f"Forecast today (AQI {worst['aqi']})", worst['category'])]
