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
from camp.apps.pesticides import stats
from camp.apps.pesticides.models import PesticideNotice, PesticideUseRollup, PesticideUseTotal
from camp.apps.regions.models import Region

PLACE_REGION_TYPES = (
    Region.Type.COUNTY, Region.Type.CITY, Region.Type.ZIPCODE, Region.Type.PLACE, Region.Type.SCHOOL_DISTRICT,
)
WITHIN_KEY = 'pesticides:within'
WITHIN_TTL = 60 * 60 * 24
RADIUS_CHOICES = (1, 3, 5)
AREA_SECTIONS_TTL = 60 * 60 * 24
SCHOOLS_NEARBY_TTL = 60 * 60 * 24
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

    def total_rows(self):
        """
        The pre-summed PesticideUseTotal rows for this area, or None when the
        area isn't a whole county (totals are only binned by county, so a
        city, ZIP, or radius still has to go through the rollup). Restricted
        to the chemical rows, which carry each application's pounds once.
        """
        county = self.county
        if county is None:
            return None
        return PesticideUseTotal.objects.filter(county=county, chemical__isnull=False)

    def cache_key(self):
        """Stable identity for this area, for keying its cached all-years aggregates."""
        if self.kind == 'region':
            return f'region:{self.region.pk}'
        return f'point:{self.point.y:.4f}:{self.point.x:.4f}:{self.radius}'

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

    def records_url(self, year, all_years=False):
        params = self._area_params()
        params['year'] = stats.ALL_YEARS if all_years else year
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
        # Cities, ZIPs, and places are drawn on the map from the regions API
        # (counties already have outlines on every map).
        return {
            'center': center, 'zoom': 11, 'radius': None, 'county': None,
            'outline_url': f'/api/2.0/regions/{self.region.sqid}/',
        }


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


def regions_within(region):
    """
    Quick-navigation lists for a place page: the counties, cities and places,
    school districts, and ZIP codes related to `region`. For a county that is
    everything whose boundary centroid falls inside it; for any other region
    it is everything whose boundary overlaps it (sharing only an edge doesn't
    count), plus the county or counties it lies in. The region itself and
    its same-name twin (a city and its synthetic place) are left out. Each
    entry is {'name', 'url'}; cities and places are merged by name. Cached a
    day per region.
    """
    from django.contrib.gis.db.models.functions import Centroid

    key = f'{WITHIN_KEY}:{region.pk}'
    data = cache.get(key)
    if data is not None:
        return data
    geometry = region.boundary.geometry
    kinds = (Region.Type.CITY, Region.Type.PLACE, Region.Type.SCHOOL_DISTRICT, Region.Type.ZIPCODE)
    if region.type == Region.Type.COUNTY:
        rows = (
            Region.objects.filter(type__in=kinds, boundary__isnull=False)
            .annotate(centroid=Centroid('boundary__geometry'))
            .filter(centroid__within=geometry)
        )
    else:
        rows = (
            Region.objects.filter(type__in=kinds + (Region.Type.COUNTY,), boundary__isnull=False)
            .filter(boundary__geometry__intersects=geometry)
            .exclude(boundary__geometry__touches=geometry)
            .exclude(pk=region.pk)
            .exclude(type__in=(Region.Type.CITY, Region.Type.PLACE), name=region.name)
        )
    groups = {'counties': [], 'places': {}, 'school_districts': [], 'zipcodes': []}
    for other in rows.order_by('name'):
        entry = {
            'name': other.name,
            'url': reverse('pesticides:region', kwargs={'sqid': other.sqid, 'slug': other.slug}),
        }
        if other.type == Region.Type.COUNTY:
            groups['counties'].append(entry)
        elif other.type == Region.Type.SCHOOL_DISTRICT:
            groups['school_districts'].append(entry)
        elif other.type == Region.Type.ZIPCODE:
            groups['zipcodes'].append(entry)
        elif other.type == Region.Type.CITY or other.name not in groups['places']:
            # A city wins over the synthetic place of the same name.
            groups['places'][other.name] = entry
    data = {
        'counties': groups['counties'],
        'places': [groups['places'][name] for name in sorted(groups['places'])],
        'school_districts': groups['school_districts'],
        'zipcodes': groups['zipcodes'],
        'any': bool(groups['counties'] or groups['places'] or groups['school_districts'] or groups['zipcodes']),
    }
    cache.set(key, data, WITHIN_TTL)
    return data


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


def schools_nearby(region, year, all_years=False, county=None):
    """
    The schools and child care centers in a school district, each with the
    pesticide use reported in the 3x3 block of sections around it (see
    stats.block_totals) -- the "Schools in this district" panel. Sorted by
    pounds, heaviest first, then by name.

    Each entry is {'location', 'lbs', 'applications', 'section_sqid',
    'section_mtrs'}. Every location needs its own block lookup, so the whole
    list is cached for a day per district and year; it only changes on import.
    """
    key = ':'.join([
        'pesticides:schools-nearby',
        str(region.pk),
        stats.year_param(year, all_years) or 'none',
        str(county.pk) if county is not None else '',
    ])

    def build():
        rows = PesticideUseRollup.objects.all()
        if county is not None:
            rows = rows.filter(county=county)
        entries = []
        for location in region.schools.all().order_by('name', 'pk'):
            totals = stats.block_totals(rows, location.point, year, all_years)
            section = totals['section']
            entries.append({
                'location': location,
                'lbs': totals['lbs'],
                'applications': totals['applications'],
                'section_sqid': section.sqid if section is not None else None,
                'section_mtrs': (section.external_id or section.name) if section is not None else None,
            })
        entries.sort(key=lambda entry: (-entry['lbs'], entry['location'].name))
        return entries

    return stats.cached(key, build, ttl=SCHOOLS_NEARBY_TTL)


def _place_stats(area, year, all_years):
    """
    The year-binned half of a place page. Across every loaded year a county
    spans millions of rollup rows, so the whole block is cached per area --
    it only changes on import. The stat row's pounds and applications come
    from PesticideUseTotal when the area is a whole county; the section and
    chemical counts and the month bars have to read the rollup either way.
    """
    rows = area.rollup_rows()
    scoped = stats.in_year(rows, year, all_years)
    # Only across every year: a single year's rollup rows are cheap, and a
    # totals row exists only where a chemical was identified, so switching
    # sources would quietly drop unattributed applications from the count.
    total_rows = area.total_rows() if all_years else None
    totals_source = rows if total_rows is None else total_rows
    summed = stats.year_totals(totals_source, year, all_years=all_years)

    by_month = stats.by_month(rows, year, all_years=all_years)
    peak_month = None
    if by_month and any(month['lbs'] for month in by_month):
        peak = max(by_month, key=lambda month: month['lbs'])
        peak_month = calendar.month_name[peak['month']]

    return {
        'totals': {
            'lbs': summed['lbs'],
            'applications': summed['applications'],
            'sections_used': scoped.filter(mtrs__isnull=False).values('mtrs').distinct().count(),
            'sections_total': len(area.section_pks),
            'chemicals': stats.real_chemicals(scoped.filter(chemical__isnull=False)).values('chemical').distinct().count(),
        },
        'by_month': by_month,
        'peak_month': peak_month,
        'top_chemicals': stats.top_related(rows, year, 'chemical', limit=10, all_years=all_years),
        'top_commodities': stats.top_related(rows, year, 'commodity', limit=10, all_years=all_years),
        'top_products': stats.top_related(rows, year, 'product', lbs_field='lbs_product', limit=10, all_years=all_years),
    }


def place_context(area, year, all_years=False):
    from camp.apps.pesticides.views import section_map_config

    def build():
        return _place_stats(area, year, all_years)

    if all_years:
        data = stats.cached(stats.all_years_key('place', area.cache_key()), build)
    else:
        data = build()
    totals = data['totals']

    notices = area.notices()
    upcoming_qs = stats._upcoming(notices)
    upcoming = list(
        upcoming_qs
        .select_related('county')
        .prefetch_related('chemicals', 'products')
        .order_by('scheduled_application')[:20]
    )
    upcoming_count = upcoming_qs.count()

    # The district's own schools are the subject of a school-district page,
    # so its map opens with the markers on and the page lists them.
    is_district = area.kind == 'region' and area.region.type == Region.Type.SCHOOL_DISTRICT

    # The by-year series is the same whatever year is selected, so it's
    # cached per area rather than per scope -- across every loaded year a
    # county spans millions of rollup rows.
    by_year = stats.cached(
        stats.all_years_key('place-by-year', area.cache_key()),
        lambda: stats.by_year(area.rollup_rows()),
    )

    context = {
        'area': area,
        **data,
        'by_year': by_year,
        'upcoming': upcoming,
        'upcoming_count': upcoming_count,
        'records_url': area.records_url(year, all_years),
        'notices_url': area.notices_url(),
        'map_config': section_map_config(year, all_years=all_years, show_locations=is_district, **area.map_kwargs()),
        'spraydays_url': SPRAYDAYS_URL,
        'is_school_district': is_district,
    }

    if is_district:
        context['schools_nearby'] = schools_nearby(area.region, year, all_years)

    # A single-county area's per-county breakdown is just that one county
    # (== the total); only surface it when the area spans multiple counties.
    if area.kind == 'region' and area.region.type != Region.Type.COUNTY:
        context['upcoming_by_county'] = stats.upcoming_by_county(notices)

    return context
