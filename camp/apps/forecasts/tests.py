from datetime import date, datetime, timezone as dt_timezone
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase

from camp.apps.regions.models import Region

from .models import Forecast
from .tasks import fetch_forecasts


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

    def test_color_matches_aqi_levels_for_value(self):
        region = Region.objects.get(name='Fresno County')
        forecast = Forecast.objects.create(
            region=region, zone_name='Fresno',
            forecast_date=date(2026, 7, 11), issued_date=date(2026, 7, 11),
            published_at=datetime(2026, 7, 11, 21, 31, 9, tzinfo=dt_timezone.utc),
            aqi_value=101, aqi_category='Unhealthy for Sensitive Groups',
            pollutant=Forecast.Pollutant.OZONE,
            burn_status='Discouraged', burn_status_text='Discouraged: Burning Discouraged',
        )
        # 101 is exactly the levels.AQI.UNHEALTHY_SENSITIVE breakpoint, so this
        # should be that tier's color with no blending toward the next tier.
        assert forecast.color == '#ff7e00'

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


FIXED_NOW = datetime(2026, 7, 11, 19, 0, 0, tzinfo=dt_timezone.utc)


SAMPLE_FEED_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"   xmlns:burnStatus="https://ww2.valleyair.org/" xmlns:AQI="https://ww2.valleyair.org/">
<title>SJVAPCD mobile app Status</title>
<subtitle>SJVAPCD Air Quality Information</subtitle>
<link rel="self" href="https://ww2.valleyair.org/aqinfo/AirStatus.xml"/>
<link href="https://ww2.valleyair.org/"/>
<author><name>SJVAPCD</name></author>
<icon>/favicon.ico</icon>
<channel>
<title>Air Quality Status</title>
<description>SJVAPCD Air Quality Status by County</description>
<link>https://ww2.valleyair.org/air-quality-information/real-time-air-advisory-network-raan/real-time-air-monitoring-stations/</link>
<language>en-us</language>
<copyright>Copyright 2013 SJVAPCD</copyright>
<lastBuildDate>2026-07-11T21:31:09 -7:00</lastBuildDate>
<generator>SJVAPCD</generator>
<webMaster>webmaster@valleyair.org</webMaster>
<ttl>1440</ttl>
<item>
<guid>http://www.valleyair.org/aqinfo/San Joaquin</guid>
<title>San Joaquin Air Quality Status</title>
<county>San Joaquin</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Yellow">55 Moderate (PM2.5)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">51 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Stanislaus</guid>
<title>Stanislaus Air Quality Status</title>
<county>Stanislaus</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Yellow">77 Moderate (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">58 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Merced</guid>
<title>Merced Air Quality Status</title>
<county>Merced</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Yellow">80 Moderate (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">61 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Madera</guid>
<title>Madera Air Quality Status</title>
<county>Madera</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Yellow">100 Moderate (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">80 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Fresno</guid>
<title>Fresno Air Quality Status</title>
<county>Fresno</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Orange">101 Unhealthy for Sensitive Groups (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">100 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Kings</guid>
<title>Kings Air Quality Status</title>
<county>Kings</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Yellow">71 Moderate (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">53 Moderate (PM2.5)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Tulare</guid>
<title>Tulare Air Quality Status</title>
<county>Tulare</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Orange">105 Unhealthy for Sensitive Groups (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">84 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Kern (SJV Air Basin portion)</guid>
<title>Kern (SJV Air Basin portion) Air Quality Status</title>
<county>Kern (SJV Air Basin portion)</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Orange">115 Unhealthy for Sensitive Groups (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">100 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Sequoia National Park and Forest</guid>
<title>Sequoia National Park and Forest Air Quality Status</title>
<county>Sequoia National Park and Forest</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Orange">129 Unhealthy for Sensitive Groups (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">100 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
</channel>
</rss>
"""


def mock_response(content=SAMPLE_FEED_XML):
    response = Mock()
    response.content = content
    response.raise_for_status = Mock()
    return response


class FetchForecastsTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        patcher = patch('django.utils.timezone.now', return_value=FIXED_NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_creates_forecast_for_each_mapped_zone(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        # 8 mapped zones x 2 horizons (today/tomorrow) = 16 rows; Sequoia dropped.
        assert Forecast.objects.count() == 16

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_skips_unmapped_zone(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        assert not Forecast.objects.filter(zone_name='Sequoia National Park and Forest').exists()

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_kern_alias_maps_to_kern_county_region(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        kern = Region.objects.get(name='Kern County')
        forecast = Forecast.objects.get(
            region=kern, zone_name='Kern (SJV Air Basin portion)', forecast_date=date(2026, 7, 11),
        )
        assert forecast.aqi_value == 115
        assert forecast.pollutant == 'O3'

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_sets_fields_correctly_for_fresno_today(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        fresno = Region.objects.get(name='Fresno County')
        forecast = Forecast.objects.get(region=fresno, forecast_date=date(2026, 7, 11))
        assert forecast.aqi_value == 101
        assert forecast.aqi_category == 'Unhealthy for Sensitive Groups'
        assert forecast.pollutant == 'O3'
        assert forecast.burn_status == 'Discouraged'
        assert forecast.burn_status_text == 'Discouraged: Burning Discouraged'
        assert forecast.air_alert is False
        assert forecast.air_alert_start is None
        assert forecast.air_alert_end is None
        assert forecast.issued_date == date(2026, 7, 11)
        assert forecast.published_at.year == 2026

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_tomorrow_row_has_next_day_forecast_date(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        fresno = Region.objects.get(name='Fresno County')
        forecast = Forecast.objects.get(region=fresno, forecast_date=date(2026, 7, 12))
        assert forecast.aqi_value == 100
        assert forecast.aqi_category == 'Moderate'
        assert forecast.issued_date == date(2026, 7, 11)

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_pm25_zone_parses_correctly(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        san_joaquin = Region.objects.get(name='San Joaquin County')
        forecast = Forecast.objects.get(region=san_joaquin, forecast_date=date(2026, 7, 11))
        assert forecast.pollutant == 'PM2.5'
        assert forecast.aqi_value == 55

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_idempotent_rerun_does_not_duplicate(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        count = Forecast.objects.count()
        assert count == 16
        fetch_forecasts.call_local()
        assert Forecast.objects.count() == count

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_malformed_zone_is_skipped_without_aborting_the_run(self, mock_get):
        # Kings' <AQI:today> text no longer matches AQI_TEXT_RE, simulating a
        # plausible "Unavailable" feed state. This should only drop Kings'
        # rows, not roll back the other 7 (already-good) zones.
        broken_xml = SAMPLE_FEED_XML.replace(
            b'<AQI:today date="2026-07-11T00:00:00 -7:00" status="Yellow">71 Moderate (O3)</AQI:today>',
            b'<AQI:today date="2026-07-11T00:00:00 -7:00" status="Yellow">Unavailable</AQI:today>',
        )
        assert broken_xml != SAMPLE_FEED_XML
        mock_get.return_value = mock_response(broken_xml)

        fetch_forecasts.call_local()  # must not raise

        assert Forecast.objects.count() == 14
        assert not Forecast.objects.filter(zone_name='Kings').exists()

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_db_error_for_one_zone_does_not_abort_other_zones(self, mock_get):
        # Simulates a DB-level failure (e.g. a value that violates a field
        # constraint) for a single zone. The nested savepoint around each
        # zone's writes should isolate this: Kings' rows are dropped, but the
        # other 7 (already-committed-to-the-savepoint) zones must still land.
        mock_get.return_value = mock_response()
        original_create = Forecast.objects.create

        def flaky_create(**kwargs):
            if kwargs.get('zone_name') == 'Kings':
                raise IntegrityError('simulated db error')
            return original_create(**kwargs)

        with patch.object(Forecast.objects, 'create', side_effect=flaky_create):
            fetch_forecasts.call_local()  # must not raise

        assert Forecast.objects.count() == 14
        assert not Forecast.objects.filter(zone_name='Kings').exists()


class FetchForecastsCommandTests(TestCase):
    fixtures = ['regions.yaml']

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_command_ingests_forecasts(self, mock_get):
        mock_get.return_value = mock_response()
        out = StringIO()
        call_command('fetch_forecasts', stdout=out)
        assert Forecast.objects.count() == 16
        assert 'Done' in out.getvalue()
