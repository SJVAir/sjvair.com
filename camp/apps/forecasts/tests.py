from datetime import date, datetime, timezone as dt_timezone

from django.test import TestCase

from camp.apps.regions.models import Region

from .models import Forecast


class ForecastModelTests(TestCase):
    fixtures = ['regions.yaml']

    def test_create_forecast(self):
        region = Region.objects.get(name='Fresno County')
        forecast = Forecast.objects.create(
            region=region,
            zone_name='Fresno',
            forecast_date=date(2026, 7, 11),
            issued_date=date(2026, 7, 11),
            published_at=datetime(2026, 7, 11, 21, 31, 9, tzinfo=dt_timezone.utc),
            aqi_value=101,
            aqi_category='Unhealthy for Sensitive Groups',
            pollutant=Forecast.Pollutant.OZONE,
            burn_status='Discouraged',
            burn_status_text='Discouraged: Burning Discouraged',
            air_alert=False,
        )
        assert forecast.sqid
        assert forecast.pollutant == 'O3'
        assert str(forecast) == 'Fresno forecast for 2026-07-11 (issued 2026-07-11)'
        assert Forecast.objects.filter(region=region).count() == 1

    def test_ordering_is_newest_issued_first(self):
        region = Region.objects.get(name='Fresno County')
        older = Forecast.objects.create(
            region=region, zone_name='Fresno',
            forecast_date=date(2026, 7, 10), issued_date=date(2026, 7, 10),
            published_at=datetime(2026, 7, 10, 21, 31, 9, tzinfo=dt_timezone.utc),
            aqi_value=90, aqi_category='Moderate', pollutant=Forecast.Pollutant.OZONE,
            burn_status='Discouraged', burn_status_text='Discouraged: Burning Discouraged',
        )
        newer = Forecast.objects.create(
            region=region, zone_name='Fresno',
            forecast_date=date(2026, 7, 11), issued_date=date(2026, 7, 11),
            published_at=datetime(2026, 7, 11, 21, 31, 9, tzinfo=dt_timezone.utc),
            aqi_value=101, aqi_category='Unhealthy for Sensitive Groups', pollutant=Forecast.Pollutant.OZONE,
            burn_status='Discouraged', burn_status_text='Discouraged: Burning Discouraged',
        )
        assert list(Forecast.objects.all()) == [newer, older]
