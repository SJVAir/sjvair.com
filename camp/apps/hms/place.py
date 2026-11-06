"""Per-day HMS smoke over a place: the heaviest density and how much of the
place lies under each level."""

from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.contrib.gis.geos import GEOSGeometry
from django.db import connection
from django.utils import timezone

from .models import Smoke

# Rank order, lightest first; matches Smoke.Density.
LEVELS = ('light', 'medium', 'heavy')

# fetch_smoke_final re-fetches the previous day at this UTC time; a day is
# settled once that pass plus a margin has gone by.
FINAL_PASS_UTC = time(21, 0)
SETTLE_MARGIN = timedelta(hours=1)

# Polygon place: union the candidate outlines per (date, at-least level) so
# overlapping outlines count once, clip each union to the place once (in 4326,
# so the clipped edges are the place's own vertices), then measure in
# EPSG:3310. Unioning first keeps the costly clip against the place's many
# vertices to one per group instead of one per outline.
POLYGON_SQL = '''
WITH place AS (
    SELECT g, ST_Area(ST_Transform(g, 3310)) AS area
    FROM (SELECT %(geom)s::geometry AS g) p
),
smoke AS MATERIALIZED (
    SELECT s.date,
           array_position(%(levels)s::text[], s.density::text) AS rank,
           ST_MakeValid(s.geometry) AS g
    FROM {table} s, place
    WHERE s.date BETWEEN %(start)s AND %(end)s
      AND ST_Intersects(s.geometry, place.g)
),
merged AS (
    SELECT sm.date, lvl.rank, ST_Union(sm.g) AS g
    FROM smoke sm
    JOIN generate_series(1, {count}) AS lvl(rank) ON sm.rank >= lvl.rank
    GROUP BY sm.date, lvl.rank
)
SELECT m.date, m.rank,
       ST_Area(ST_Transform(ST_Intersection(m.g, place.g), 3310)) AS area,
       place.area AS place_area
FROM merged m, place
'''


# Point place (a monitor): an outline covers it or not; the edge counts.
POINT_SQL = '''
SELECT DISTINCT s.date, lvl.rank
FROM {table} s
JOIN generate_series(1, {count}) AS lvl(rank)
  ON array_position(%(levels)s::text[], s.density::text) >= lvl.rank
WHERE s.date BETWEEN %(start)s AND %(end)s
  AND ST_Intersects(s.geometry, %(geom)s::geometry)
'''


def _empty_row(day):
    return {
        'date': day.isoformat(),
        'density': None,
        'coverage': {level: 0.0 for level in LEVELS},
    }


def _query(geometry, start, end):
    """Return {(date, rank): coverage} for the days in range."""
    is_point = geometry.geom_type in ('Point', 'MultiPoint')
    sql = (POINT_SQL if is_point else POLYGON_SQL).format(
        table=connection.ops.quote_name(Smoke._meta.db_table),
        count=len(LEVELS),
    )
    params = {
        'geom': geometry.ewkt,
        'levels': list(LEVELS),
        'start': start,
        'end': end,
    }
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    shares = {}
    for row in rows:
        if is_point:
            day, rank = row
            shares[(day, rank)] = 1.0
        else:
            day, rank, area, place_area = row
            if not place_area or not area:
                continue
            shares[(day, rank)] = round(min(max(area / place_area, 0.0), 1.0), 4)
    return shares


def smoke_days(geometry: GEOSGeometry | None, start: date, end: date) -> list[dict]:
    """One row per day from start to end inclusive, ascending.

    `density` is the heaviest level with any coverage (None for no smoke);
    `coverage[level]` is the share of the place under at least that level.
    """
    days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    rows = [_empty_row(day) for day in days]
    if geometry is None or not rows:
        return rows

    shares = _query(geometry, start, end)
    for day, row in zip(days, rows):
        for rank, level in enumerate(LEVELS, start=1):
            share = shares.get((day, rank), 0.0)
            row['coverage'][level] = share
            if share > 0:
                row['density'] = level
    return rows


def is_day_settled(day: date, now: datetime | None = None) -> bool:
    """True once the final re-fetch of `day` (the next day at FINAL_PASS_UTC)
    plus SETTLE_MARGIN has passed."""
    if now is None:
        now = timezone.now()
    final_pass = datetime.combine(day + timedelta(days=1), FINAL_PASS_UTC, tzinfo=dt_timezone.utc)
    return now >= final_pass + SETTLE_MARGIN
