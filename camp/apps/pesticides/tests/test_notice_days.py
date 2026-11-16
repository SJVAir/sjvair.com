from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

from camp.apps.pesticides import stats
from camp.apps.pesticides.models import PesticideNotice

PACIFIC = settings.DEFAULT_TIMEZONE


def make_notice(n, when):
    return PesticideNotice.objects.create(
        application_id=n, comtrs=f'M00S00N{n:04d}', scheduled_application=when,
    )


class NoticeDayTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_bounds_are_pacific_midnights(self):
        start, end = stats.notice_day_bounds(date(2026, 6, 15))
        assert start == datetime(2026, 6, 11, tzinfo=PACIFIC)
        assert end == datetime(2026, 6, 16, tzinfo=PACIFIC)

    def test_window_edges(self):
        day = date(2026, 6, 15)
        start, end = stats.notice_day_bounds(day)
        one = timedelta(seconds=1)
        a = make_notice(1, start)
        b = make_notice(2, end - one)
        make_notice(3, end)
        make_notice(4, start - one)
        found = stats.notices_on(PesticideNotice.objects.all(), day)
        assert sorted(n.pk for n in found) == sorted([a.pk, b.pk])

    def test_dst_spring_forward_day(self):
        day = date(2026, 3, 8)
        inside = make_notice(1, datetime(2026, 3, 8, 23, 30, tzinfo=PACIFIC))
        make_notice(2, datetime(2026, 3, 9, 0, 0, tzinfo=PACIFIC))
        found = stats.notices_on(PesticideNotice.objects.all(), day)
        assert [n.pk for n in found] == [inside.pk]

    def test_settled_at_normal_week(self):
        assert stats.notice_day_settled_at(date(2026, 6, 15)) == datetime(2026, 6, 20, tzinfo=PACIFIC)

    def test_settled_at_dst_week(self):
        # 96 real hours past Mar 6 00:00 PST is Mar 10 01:00 PDT, later than Mar 10 00:00.
        assert stats.notice_day_settled_at(date(2026, 3, 5)) == datetime(2026, 3, 10, 1, tzinfo=PACIFIC)

    def test_settled_at_fall_back_week(self):
        # 96 real hours past Oct 30 00:00 PDT is Nov 2 23:00 PST, earlier than Nov 3 00:00.
        assert stats.notice_day_settled_at(date(2026, 10, 29)) == datetime(2026, 11, 3, tzinfo=PACIFIC)

    def test_notices_version_bumps(self):
        v = stats.notices_version()
        stats.bump_notices_version()
        assert stats.notices_version() != v
        cache.delete(stats.NOTICES_VERSION_KEY)
        assert stats.notices_version()
