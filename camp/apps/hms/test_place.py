from datetime import date, datetime, timedelta, timezone as dt_timezone

import pytest

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Point
from django.test import TestCase

from camp.apps.hms.models import Smoke
from camp.apps.hms.place import FINAL_PASS_UTC, LEVELS, is_day_settled, smoke_days


# Squares in degrees near Fresno; PLACE is 0.2° x 0.2°.
PLACE = 'POLYGON((-119.9 36.7, -119.7 36.7, -119.7 36.9, -119.9 36.9, -119.9 36.7))'
LEFT_HALF = 'POLYGON((-120.0 36.6, -119.8 36.6, -119.8 37.0, -120.0 37.0, -120.0 36.6))'
WHOLE = 'POLYGON((-120.0 36.6, -119.6 36.6, -119.6 37.0, -120.0 37.0, -120.0 36.6))'
FAR = 'POLYGON((-118.5 36.5, -118.0 36.5, -118.0 37.0, -118.5 37.0, -118.5 36.5))'
D = date(2026, 10, 27)


def smoke(day, density, wkt):
    midday = datetime.combine(day, datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(hours=20)
    row = Smoke(
        date=day,
        start=midday - timedelta(hours=2),
        end=midday + timedelta(hours=2),
        satellite='TestSatellite',
        density=density,
        geometry=MultiPolygon(GEOSGeometry(wkt, srid=4326)),
    )
    row.full_clean()
    row.save()
    return row


def place():
    return GEOSGeometry(PLACE, srid=4326)


class SmokeDaysTests(TestCase):
    def test_levels_match_model(self):
        assert list(LEVELS) == [c.value for c in Smoke.Density]

    def test_one_row_per_day_no_holes(self):
        rows = smoke_days(place(), D, D + timedelta(days=2))
        assert [r['date'] for r in rows] == ['2026-10-27', '2026-10-28', '2026-10-29']
        assert rows[0] == {'date': '2026-10-27', 'density': None,
                           'coverage': {'light': 0.0, 'medium': 0.0, 'heavy': 0.0}}

    def test_heaviest_density_and_cumulative_coverage(self):
        smoke(D, 'light', WHOLE)
        smoke(D, 'heavy', LEFT_HALF)
        with self.assertNumQueries(1):
            row = smoke_days(place(), D, D)[0]
        assert row['density'] == 'heavy'
        assert row['coverage']['light'] == pytest.approx(1.0, abs=0.01)
        assert row['coverage']['medium'] == pytest.approx(0.5, abs=0.01)  # heavy counts as at least medium
        assert row['coverage']['heavy'] == pytest.approx(0.5, abs=0.01)

    def test_overlapping_same_density_not_double_counted(self):
        smoke(D, 'light', WHOLE)
        smoke(D, 'light', LEFT_HALF)
        smoke(D, 'light', WHOLE)
        row = smoke_days(place(), D, D)[0]
        assert row['coverage']['light'] == pytest.approx(1.0, abs=0.01)

    def test_outline_elsewhere_is_no_smoke(self):
        smoke(D, 'heavy', FAR)
        assert smoke_days(place(), D, D)[0]['density'] is None

    def test_other_days_outlines_ignored(self):
        smoke(D + timedelta(days=1), 'heavy', WHOLE)
        assert smoke_days(place(), D, D)[0]['density'] is None

    def test_point_coverage_is_zero_or_one(self):
        smoke(D, 'medium', LEFT_HALF)
        inside = smoke_days(Point(-119.85, 36.8, srid=4326), D, D)[0]
        outside = smoke_days(Point(-119.75, 36.8, srid=4326), D, D)[0]
        assert inside == {'date': '2026-10-27', 'density': 'medium',
                          'coverage': {'light': 1.0, 'medium': 1.0, 'heavy': 0.0}}
        assert outside['density'] is None and outside['coverage']['light'] == 0.0

    def test_point_on_edge_counts(self):
        smoke(D, 'light', LEFT_HALF)
        assert smoke_days(Point(-119.8, 36.8, srid=4326), D, D)[0]['density'] == 'light'

    def test_no_geometry_all_null(self):
        smoke(D, 'heavy', WHOLE)
        with self.assertNumQueries(0):
            assert smoke_days(None, D, D)[0]['density'] is None

    def test_unknown_density_ignored(self):
        row = smoke(D, 'light', WHOLE)
        Smoke.objects.filter(pk=row.pk).update(density='bogus')
        out = smoke_days(place(), D, D)[0]
        assert out['density'] is None and out['coverage']['light'] == 0.0
        assert smoke_days(Point(-119.8, 36.8, srid=4326), D, D)[0]['density'] is None

    def test_self_intersecting_outline_counts(self):
        bowtie = 'POLYGON((-120.0 36.6, -119.6 37.0, -119.6 36.6, -120.0 37.0, -120.0 36.6))'
        Smoke.objects.create(
            date=D, start=datetime(2026, 10, 27, 18, tzinfo=dt_timezone.utc),
            end=datetime(2026, 10, 27, 22, tzinfo=dt_timezone.utc), satellite='TestSatellite',
            density='heavy', geometry=MultiPolygon(GEOSGeometry(bowtie, srid=4326)))
        row = smoke_days(place(), D, D)[0]
        assert row['density'] == 'heavy'
        assert 0 < row['coverage']['heavy'] < 1

    def test_settle_rule(self):
        utc = dt_timezone.utc
        assert not is_day_settled(D, datetime(2026, 10, 28, 21, 59, tzinfo=utc))
        assert is_day_settled(D, datetime(2026, 10, 28, 22, 0, tzinfo=utc))

    def test_final_pass_constant_matches_schedule(self):
        from camp.apps.hms.tasks import fetch_smoke_final
        at = datetime.combine(D, FINAL_PASS_UTC)  # naive UTC, as Huey validates
        assert fetch_smoke_final.task_class().validate_datetime(at)
        assert not fetch_smoke_final.task_class().validate_datetime(at - timedelta(hours=1))
