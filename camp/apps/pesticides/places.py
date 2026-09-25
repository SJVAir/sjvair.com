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
from camp.apps.regions.models import Location, Region

PLACE_REGION_TYPES = (
    Region.Type.COUNTY, Region.Type.CITY, Region.Type.ZIPCODE, Region.Type.PLACE, Region.Type.SCHOOL_DISTRICT,
)
WITHIN_KEY = 'pesticides:within'
WITHIN_TTL = 60 * 60 * 24
RADIUS_CHOICES = (1, 3, 5)
AREA_SECTIONS_TTL = 60 * 60 * 24
SCHOOLS_NEARBY_TTL = 60 * 60 * 24
SPRAYDAYS_URL = 'https://spraydays.cdpr.ca.gov/'

# -- The district page's schools table --

# Rows past this many are rendered collapsed, with a control to show them.
SCHOOLS_VISIBLE = 15
# The table's own filter and sort state, prefixed so it can't collide with
# the page's own `sort` (the place page has none today; a list page would).
SCHOOLS_Q_PARAM = 'schools_q'
SCHOOLS_TYPE_PARAM = 'schools_type'
SCHOOLS_RUN_BY_PARAM = 'schools_run_by'
SCHOOLS_SORT_PARAM = 'schools_sort'
SCHOOLS_SORT_DEFAULT = '-lbs'
SCHOOLS_SORT_KEYS = ('name', 'type', 'city', 'lbs', 'applications')
SCHOOLS_TYPE_OPTIONS = (
    ('', 'All types'),
    (Location.Type.PUBLIC_SCHOOL, 'Public schools'),
    (Location.Type.PRIVATE_SCHOOL, 'Private schools'),
    (Location.Type.CHILD_CARE, 'Child care'),
)

# The "Who goes to school here" tiles, in the order they're shown: where the
# percentage lives in the district Region's metadata, and its label.
DISTRICT_METRICS = (
    ('demographics', 'hispanic_latino', 'Hispanic/Latino'),
    ('subgroups', 'english_learners', 'English learners'),
    ('subgroups', 'socioeconomically_disadvantaged', 'Low-income students'),
    ('subgroups', 'migrant', 'Migrant students'),
)

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

    def records_url(self, year, all_years=False, concern=False):
        params = self._area_params()
        params['year'] = stats.ALL_YEARS if all_years else year
        if concern:
            params[stats.CONCERN_PARAM] = 1
        return reverse('pesticides:records') + '?' + urlencode(params)

    def notices_url(self, concern=False):
        params = self._area_params()
        if concern:
            params[stats.CONCERN_PARAM] = 1
        return reverse('pesticides:notice-list') + '?' + urlencode(params)

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
            'url': other.get_pesticides_url(),
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


def schools_nearby(region, year, all_years=False, concern=False):
    """
    The schools and child care centers of a school district, each with the
    pesticide use reported in the 3x3 block of sections around it (see
    stats.block_totals) -- the rows behind the district page's schools table.

    Two groups, because the table can be filtered down to the first: `run_by`,
    the public schools this district actually runs, and `others` -- charters
    run elsewhere, county-office schools, private schools, and child care that
    merely sit inside its boundary. A district runs its charters wherever they
    stand, so `run_by` is every public school whose `district_code` is this
    district's, not only the ones inside its boundary; `others` is what's left
    of the locations that resolved to it. Each group is sorted by pounds,
    heaviest first, then name.

    Each entry carries its Location plus what the table prints: the display
    name and city (CDE writes names properly, the CDSS child care directory
    shouts them), the administering district, the block totals, and the
    section it sits in. `show_city` says whether the City column is worth
    printing at all -- most districts sit in one postal city.

    Every location needs its own block lookup, so the whole thing is cached
    for a day per district and year; it only changes on import.
    """
    key = ':'.join([
        # v3: entries gained their display fields and the run-by district.
        'pesticides:schools-nearby:v3',
        str(region.pk),
        stats.year_param(year, all_years) or 'none',
        stats.CONCERN_PARAM if concern else '',
    ])

    district_code = (region.external_id or '')[:7]

    def build():
        rows = PesticideUseRollup.objects.all()
        if concern:
            rows = stats.concern_rows(rows)

        # select_related: the table prints each location's city.
        run_by = list(Location.objects
            .filter(type=Location.Type.PUBLIC_SCHOOL,
                metadata__district_code=district_code)
            .select_related('city')
            .order_by('name', 'pk')
        ) if district_code else []
        others = list(region.district_locations
            .exclude(pk__in=[location.pk for location in run_by])
            .select_related('city')
            .order_by('name', 'pk')
        )

        groups = {
            'run_by': [_school_entry(location, rows, year, all_years, is_run_by=True)
                for location in run_by],
            'others': [_school_entry(location, rows, year, all_years, is_run_by=False)
                for location in others],
        }
        for entries in groups.values():
            entries.sort(key=lambda entry: (-entry['lbs'], entry['display_name']))

        # The City column only earns its width where the district's sites
        # actually sit in more than one postal city (56 of 161 do).
        cities = {entry['display_city'].lower()
            for entries in groups.values() for entry in entries
            if entry['display_city']}
        groups['show_city'] = len(cities) > 1
        return groups

    return stats.cached(key, build, ttl=SCHOOLS_NEARBY_TTL)


def _school_entry(location, rows, year, all_years, is_run_by):
    totals = stats.block_totals(rows, location.point, year, all_years)
    section = totals['section']
    metadata = location.metadata or {}
    return {
        'location': location,
        'display_name': _display_name(location, location.name),
        'display_city': _display_name(location, location.get_city() or ''),
        'type': location.type,
        'type_label': str(location.short_type),
        'run_by_name': metadata.get('district_name') or '',
        'is_run_by': is_run_by,
        'lbs': totals['lbs'],
        'applications': totals['applications'],
        'section_sqid': section.sqid if section is not None else None,
        'section_mtrs': (section.external_id or section.name) if section is not None else None,
    }


def _display_name(location, text):
    """
    A name or city as the table should print it. Only the CDSS child care
    directory shouts its text -- drive it off the source rather than the
    text's own case, so a school CDE deliberately wrote in capitals keeps it.
    """
    from camp.apps.pesticides.templatetags.pesticides_explorer import title_case_name

    if location.source != 'cdss-ccl':
        return text
    return title_case_name(text)


def schools_panel(region, groups, params=None):
    """
    The one table a district page draws from `schools_nearby`'s groups:
    filtered (name search, type, run-by-only), sorted, and marked up for the
    collapse. All of it happens here rather than in the database -- the list
    is cached whole and a few hundred entries at most.

    `params` is the request's GET. Rows past SCHOOLS_VISIBLE carry
    `is_collapsed`, so the template can render them all into one <tbody> and
    let a click reveal the rest without another request.
    """
    params = params or {}
    rows = list(groups['run_by']) + list(groups['others'])

    query = (params.get(SCHOOLS_Q_PARAM) or '').strip()
    if query:
        needle = query.lower()
        rows = [entry for entry in rows if needle in entry['display_name'].lower()]

    type_value = (params.get(SCHOOLS_TYPE_PARAM) or '').strip()
    if type_value not in Location.Type.values:
        type_value = ''
    if type_value:
        rows = [entry for entry in rows if entry['type'] == type_value]

    run_by_only = (params.get(SCHOOLS_RUN_BY_PARAM) or '') in ('1', 'on', 'true')
    if run_by_only:
        rows = [entry for entry in rows if entry['is_run_by']]

    sort = (params.get(SCHOOLS_SORT_PARAM) or '').strip() or SCHOOLS_SORT_DEFAULT
    if sort.lstrip('-') not in SCHOOLS_SORT_KEYS:
        sort = SCHOOLS_SORT_DEFAULT
    rows = _schools_sorted(rows, sort)

    return {
        'rows': [dict(entry, is_collapsed=index >= SCHOOLS_VISIBLE)
            for index, entry in enumerate(rows)],
        'show_city': groups.get('show_city', False),
        'total': len(groups['run_by']) + len(groups['others']),
        'run_by_count': len(groups['run_by']),
        'matched': len(rows),
        'hidden': max(len(rows) - SCHOOLS_VISIBLE, 0),
        'sort': sort,
        'sort_is_default': sort == SCHOOLS_SORT_DEFAULT,
        'query': query,
        'type': type_value,
        'run_by_only': run_by_only,
        'type_options': [{'value': value, 'label': label, 'selected': value == type_value}
            for value, label in SCHOOLS_TYPE_OPTIONS],
        'is_filtered': bool(query or type_value or run_by_only),
        'district_name': region.short_name,
    }


# How each sortable column reads a row. The name is the tiebreaker for all of
# them, applied as a first pass -- Python's sort is stable, so the column's
# own pass keeps it.
_SCHOOLS_SORT_KEYS = {
    'name': lambda entry: entry['display_name'].lower(),
    'type': lambda entry: entry['type_label'].lower(),
    'city': lambda entry: entry['display_city'].lower(),
    'lbs': lambda entry: entry['lbs'],
    'applications': lambda entry: entry['applications'],
}


def _schools_sorted(rows, sort):
    descending = sort.startswith('-')
    key = _SCHOOLS_SORT_KEYS[sort.lstrip('-')]
    rows = sorted(rows, key=_SCHOOLS_SORT_KEYS['name'])
    rows.sort(key=key, reverse=descending)
    return rows


def district_demographics(region):
    """
    The enrollment and student-subgroup percentages CDE publishes with the
    district boundaries, for the stat strip on a district page. None when
    the Region carries none of it, so the strip stays off rather than
    printing a row of dashes.
    """
    metadata = region.metadata or {}
    enrollment = (metadata.get('enrollment') or {}).get('total')
    metrics = []
    for group, field_name, label in DISTRICT_METRICS:
        value = ((metadata.get(group) or {}).get(field_name) or {}).get('pct')
        if value is not None:
            metrics.append({'label': label, 'pct': value})

    if enrollment is None and not metrics:
        return None

    # The academic year the district data was published for.
    year = region.boundary.version if region.boundary_id else ''
    return {
        'enrollment': enrollment,
        'metrics': metrics,
        'year': year,
        'year_label': _academic_year_label(year),
    }


def _academic_year_label(year):
    """'2025-2026' as a source stamp: "CDE, 2025-26" (with an en dash)."""
    parts = str(year or '').split('-')
    if len(parts) == 2 and len(parts[1]) == 4:
        return f'CDE, {parts[0]}\u2013{parts[1][2:]}'
    return f'CDE, {year}' if year else ''


def _place_stats(area, year, all_years, concern=False):
    """
    The year-binned half of a place page. Across every loaded year a county
    spans millions of rollup rows, so the whole block is cached per area --
    it only changes on import. The stat row's pounds and applications come
    from PesticideUseTotal when the area is a whole county; the section and
    chemical counts and the month bars have to read the rollup either way.
    """
    rows = area.rollup_rows()
    if concern:
        rows = stats.concern_rows(rows)
    scoped = stats.in_year(rows, year, all_years)
    # Only across every year: a single year's rollup rows are cheap, and a
    # totals row exists only where a chemical was identified, so switching
    # sources would quietly drop unattributed applications from the count.
    total_rows = area.total_rows() if all_years else None
    if total_rows is not None and concern:
        total_rows = stats.concern_rows(total_rows)
    totals_source = rows if total_rows is None else total_rows
    summed = stats.year_totals(totals_source, year, all_years=all_years)

    by_month = stats.by_month(rows, year, all_years=all_years)
    peak_month = None
    if by_month and any(month['lbs'] for month in by_month):
        peak = max(by_month, key=lambda month: month['lbs'])
        peak_month = calendar.month_name[peak['month']]

    # Fetched fifty deep so the chemicals-of-concern board can be filtered out
    # of the same group-by instead of paying for a second one.
    top_chemicals = stats.top_related(rows, year, 'chemical', limit=50, all_years=all_years)

    data = {
        'totals': {
            'lbs': summed['lbs'],
            'applications': summed['applications'],
            'sections_used': scoped.filter(mtrs__isnull=False).values('mtrs').distinct().count(),
            'sections_total': len(area.section_pks),
            'chemicals': stats.real_chemicals(scoped.filter(chemical__isnull=False)).values('chemical').distinct().count(),
        },
        'by_month': by_month,
        'peak_month': peak_month,
        'top_chemicals': top_chemicals[:10],
        'top_commodities': stats.top_related(rows, year, 'commodity', limit=10, all_years=all_years),
        'top_products': stats.top_related(rows, year, 'product', lbs_field='lbs_product', limit=10, all_years=all_years),
    }

    # Under the concern scope every board is already of concern, so the
    # dedicated one would just restate the top chemicals.
    if not concern:
        data['top_chemicals_of_concern'] = stats.top_chemicals_of_concern(
            top_chemicals, rows, year, all_years=all_years,
        )
    return data


def place_context(area, year, all_years=False, concern=False, params=None):
    from camp.apps.pesticides.views import section_map_config

    def build():
        return _place_stats(area, year, all_years, concern)

    # The concern scope gets its own cache entries; without it the keys stay
    # exactly what they were.
    scope_key = (stats.CONCERN_PARAM,) if concern else ()
    if all_years:
        data = stats.cached(stats.all_years_key('place-v2', area.cache_key(), *scope_key), build)
    else:
        data = build()
    totals = data['totals']

    notices = area.notices()
    if concern:
        notices = stats.concern_notices(notices)
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
    # cached per area rather than per scope. A whole county reads it off the
    # totals table -- one row per year, county, and chemical instead of the
    # millions of rollup rows those years span. The pounds match the rollup's
    # exactly; only the application counts differ (a totals row exists only
    # where a chemical was identified), and the chart plots pounds.
    # Sub-county areas have no totals rows, and the concern scope stays on
    # the rollup, so a page under it counts the same rows as the rest of the
    # page does.
    def build_by_year():
        if concern:
            return stats.by_year(stats.concern_rows(area.rollup_rows()))
        rows = area.total_rows()
        # `or` would evaluate the queryset; None is the only "no totals" case.
        return stats.by_year(area.rollup_rows() if rows is None else rows)

    by_year = stats.cached(
        stats.all_years_key('place-by-year', area.cache_key(), *scope_key),
        build_by_year,
    )

    context = {
        'area': area,
        **data,
        'by_year': by_year,
        'upcoming': upcoming,
        'upcoming_count': upcoming_count,
        'records_url': area.records_url(year, all_years, concern),
        # The chemicals-of-concern card's "Show all" narrows the records
        # browser the way the card does, whatever the page's own scope is.
        'concern_records_url': area.records_url(year, all_years, concern=True),
        'notices_url': area.notices_url(concern),
        'map_config': section_map_config(
            year, all_years=all_years, show_locations=is_district, concern=concern, **area.map_kwargs(),
        ),
        'spraydays_url': SPRAYDAYS_URL,
        'is_school_district': is_district,
    }

    if is_district:
        groups = schools_nearby(area.region, year, all_years, concern=concern)
        context['schools'] = schools_panel(area.region, groups, params)
        context['district_demographics'] = district_demographics(area.region)

    # A single-county area's per-county breakdown is just that one county
    # (== the total); only surface it when the area spans multiple counties.
    if area.kind == 'region' and area.region.type != Region.Type.COUNTY:
        context['upcoming_by_county'] = stats.upcoming_by_county(notices)

    return context
