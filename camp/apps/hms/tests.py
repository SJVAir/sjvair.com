from datetime import datetime

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from .models import Fire, Smoke
from .tasks import fetch_fire, fetch_fire_final, fetch_smoke, fetch_smoke_final, parse_timestamp


TEST_DATE = datetime(2025, 9, 1).date()


class ParseTimestampTests(TestCase):
    def test_julian_date_format(self):
        result = parse_timestamp('2025244 0600')
        assert result.year == 2025
        assert result.month == 9
        assert result.day == 1
        assert result.hour == 6
        assert result.minute == 0
        assert result.tzinfo is not None


class FetchSmokeTests(TestCase):
    fixtures = ['regions.yaml']

    def test_fetch_smoke(self):
        assert Smoke.objects.count() == 0
        fetch_smoke.call_local(TEST_DATE)
        assert Smoke.objects.filter(date=TEST_DATE).count() > 0

    def test_fetch_smoke_sets_fields(self):
        fetch_smoke.call_local(TEST_DATE)
        smoke = Smoke.objects.filter(date=TEST_DATE).first()
        assert smoke.satellite
        assert smoke.density in ('light', 'medium', 'heavy')
        assert smoke.start is not None
        assert smoke.end is not None
        assert smoke.geometry is not None

    def test_fetch_smoke_replaces_existing(self):
        fetch_smoke.call_local(TEST_DATE)
        count = Smoke.objects.filter(date=TEST_DATE).count()
        assert count > 0
        fetch_smoke.call_local(TEST_DATE)
        assert Smoke.objects.filter(date=TEST_DATE).count() == count

    def test_fetch_smoke_final(self):
        fetch_smoke_final.call_local(TEST_DATE)
        assert Smoke.objects.filter(date=TEST_DATE).count() > 0


class FetchFireTests(TestCase):
    fixtures = ['regions.yaml']

    def test_fetch_fire(self):
        assert Fire.objects.count() == 0
        fetch_fire.call_local(TEST_DATE)
        assert Fire.objects.filter(date=TEST_DATE).count() > 0

    def test_fetch_fire_sets_fields(self):
        fetch_fire.call_local(TEST_DATE)
        fire = Fire.objects.filter(date=TEST_DATE).first()
        assert fire.satellite
        assert fire.timestamp is not None
        assert fire.frp is not None
        assert fire.ecosystem is not None
        assert fire.method
        assert fire.geometry is not None

    def test_fetch_fire_replaces_existing(self):
        fetch_fire.call_local(TEST_DATE)
        count = Fire.objects.filter(date=TEST_DATE).count()
        assert count > 0
        fetch_fire.call_local(TEST_DATE)
        assert Fire.objects.filter(date=TEST_DATE).count() == count

    def test_fetch_fire_final(self):
        fetch_fire_final.call_local(TEST_DATE)
        assert Fire.objects.filter(date=TEST_DATE).count() > 0
