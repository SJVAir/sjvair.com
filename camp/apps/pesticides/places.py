"""
Area resolution and place-page context for the near-me and region pages.

An `Area` is either a point + radius (near-me) or a `Region` (county, city,
ZIP, or synthetic place). Both boil down to the same three things every
place page needs: a set of MTRS section pks to scope the section map and
"sections used" stat, a rollup-row filter for the year-binned stats, and a
`PesticideNotice` filter for "what's scheduled nearby". County regions filter
rollup rows by the `county` FK (matching the by-county table exactly);
everything else -- other region types and points -- filters spatially by
MTRS section, since `PesticideUseRollup`/`PesticideNotice` don't carry
arbitrary geometry.
"""
import calendar
from dataclasses import dataclass, field
from urllib.parse import urlencode

from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.core.cache import cache
from django.urls import reverse

from camp.api.v2.pesticides.sections import radius_bbox
from camp.apps.pesticides import notes as notes_module
from camp.apps.pesticides import stats
from camp.apps.pesticides.models import PesticideNotice, PesticideUseRollup
from camp.apps.regions.models import Region

PLACE_REGION_TYPES = (Region.Type.COUNTY, Region.Type.CITY, Region.Type.ZIPCODE, Region.Type.PLACE)
RADIUS_CHOICES = (1, 3, 5)
AREA_SECTIONS_TTL = 60 * 60 * 24
SPRAYDAYS_URL = 'https://spraydays.cdpr.ca.gov/'

# Prefixed onto the region's own name for the page's <h1>/label. Counties,
# cities, and places already carry a legible name ("Fresno County",
# "Selma"); a bare ZIP code doesn't read as a place without it.
_REGION_LABEL_PREFIX = {
    Region.Type.ZIPCODE: 'ZIP ',
}


@dataclass
class Area:
    label: str
    kind: str  # 'point' | 'region'
    region: Region | None = None
    point: Point | None = None  # SRID 4326
    radius: int | None = None  # miles
    section_pks: list[int] = field(default_factory=list)

    @property
    def county(self):
        """The county FK filter, when this area *is* a county region."""
        if self.kind == 'region' and self.region.type == Region.Type.COUNTY:
            return self.region
        return None

    def rollup_rows(self):
        county = self.county
        if county is not None:
            return PesticideUseRollup.objects.filter(county=county)
        return PesticideUseRollup.objects.filter(mtrs__in=self.section_pks)

    def notices(self):
        # Imported here, not at module scope, to avoid a circular import --
        # views.py imports `places` and calls `place_context()`.
        from camp.apps.pesticides.views import area_filter

        county = self.county
        if county is not None:
            return area_filter(PesticideNotice.objects.all(), county=county)
        if self.kind == 'region':
            return area_filter(PesticideNotice.objects.all(), region=self.region)
        return area_filter(PesticideNotice.objects.all(), point=self.point, radius=self.radius)

    def _area_params(self):
        county = self.county
        if county is not None:
            return {'county': county.slug}
        if self.kind == 'region':
            return {'region': self.region.sqid}
        return {'lat': self.point.y, 'lng': self.point.x, 'radius': self.radius}

    def records_url(self, year):
        params = self._area_params()
        params['year'] = year
        return reverse('pesticides:records') + '?' + urlencode(params)

    def notices_url(self):
        return reverse('pesticides:notice-list') + '?' + urlencode(self._area_params())

    def map_kwargs(self):
        if self.kind == 'point':
            return {
                'center': f'{self.point.y:.4f},{self.point.x:.4f}',
                'zoom': 12,
                'radius': self.radius,
                'county': None,
            }
        centroid = self.region.boundary.geometry.centroid
        center = f'{centroid.y:.4f},{centroid.x:.4f}'
        if self.region.type == Region.Type.COUNTY:
            return {'center': center, 'zoom': 9, 'radius': None, 'county': self.region.slug}
        return {'center': center, 'zoom': 11, 'radius': None, 'county': None}


def point_area(lat, lng, radius, label=''):
    point = Point(lng, lat, srid=4326)
    section_pks = list(
        Region.objects.filter(
            type=Region.Type.MTRS,
            boundary__isnull=False,
            # Bbox prefilter first -- see radius_bbox's docstring: without it
            # the planner can't use the geometry GiST index on a raw
            # distance_lte and forces a full table scan.
            boundary__geometry__bboverlaps=radius_bbox(lat, lng, radius),
            boundary__geometry__distance_lte=(point, D(mi=radius)),
        )
        .order_by('pk')
        .values_list('pk', flat=True)
    )
    return Area(label=label, kind='point', point=point, radius=radius, section_pks=section_pks)


def region_area(region):
    cache_key = f'pesticides:area-sections:{region.pk}'
    section_pks = cache.get(cache_key)
    if section_pks is None:
        if region.boundary_id:
            section_pks = list(
                Region.objects.filter(
                    type=Region.Type.MTRS,
                    boundary__isnull=False,
                    boundary__geometry__intersects=region.boundary.geometry,
                )
                .order_by('pk')
                .values_list('pk', flat=True)
            )
        else:
            section_pks = []
        cache.set(cache_key, section_pks, AREA_SECTIONS_TTL)

    label = _REGION_LABEL_PREFIX.get(region.type, '') + region.name
    return Area(label=label, kind='region', region=region, section_pks=section_pks)


def place_context(area, year):
    from camp.apps.pesticides.views import section_map_config

    rows = area.rollup_rows()
    year_rows = rows.filter(year=year)
    year_totals = stats.year_totals(rows, year)

    totals = {
        'lbs': year_totals['lbs'],
        'applications': year_totals['applications'],
        'sections_used': year_rows.filter(mtrs__isnull=False).values('mtrs').distinct().count(),
        'sections_total': len(area.section_pks),
        'chemicals': year_rows.filter(chemical__isnull=False).values('chemical').distinct().count(),
    }

    by_month = stats.by_month(rows, year)
    peak_month = None
    if by_month and any(month['lbs'] for month in by_month):
        peak = max(by_month, key=lambda month: month['lbs'])
        peak_month = calendar.month_name[peak['month']]

    top_chemicals = stats.top_related(rows, year, 'chemical', limit=10)
    top_commodities = stats.top_related(rows, year, 'commodity', limit=10)
    top_products = stats.top_related(rows, year, 'product', lbs_field='lbs_product', limit=10)

    notices = area.notices()
    upcoming_qs = stats._upcoming(notices)
    upcoming = list(
        upcoming_qs
        .select_related('county')
        .prefetch_related('chemicals', 'products')
        .order_by('scheduled_application')[:20]
    )
    upcoming_count = upcoming_qs.count()

    context = {
        'area': area,
        'totals': totals,
        'by_month': by_month,
        'peak_month': peak_month,
        'top_chemicals': top_chemicals,
        'top_commodities': top_commodities,
        'top_products': top_products,
        'upcoming': upcoming,
        'upcoming_count': upcoming_count,
        'records_url': area.records_url(year),
        'notices_url': area.notices_url(),
        'map_config': section_map_config(year, **area.map_kwargs()),
        'spraydays_url': SPRAYDAYS_URL,
        'notes': notes_module.notes_for(notes_module.keys_for_chemicals(row.obj for row in top_chemicals)),
    }

    # A single-county area's per-county breakdown is just that one county
    # (== the total); only surface it when the area spans multiple counties.
    if area.kind == 'region' and area.region.type != Region.Type.COUNTY:
        context['upcoming_by_county'] = stats.upcoming_by_county(notices)

    return context
