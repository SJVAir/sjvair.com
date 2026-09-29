import csv
import json
import math
import re

from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

import vanilla

from camp.apps.ces import stats as ces_stats
from camp.apps.emissions import areas, compliance, dairies, ghg, nei, schools, stats, wells
from camp.apps.emissions.models import AirComplianceFacility, Facility, SourceImport
from camp.apps.emissions.pollutants import CRITERIA, PRECURSORS
from camp.apps.regions import nearby
from camp.apps.regions.models import Region
from camp.utils import mapconfig

# The "In and around <place>" lists (camp.apps.regions.nearby), linked with
# emissions pages; separate cache namespace from the pesticides explorer's,
# since the two link different pages.
WITHIN_KEY = 'emissions:within:v1'


def region_within(region):
    return nearby.regions_within(region, url_method='get_emissions_url', cache_prefix=WITHIN_KEY)


# The dairy region pages' own lists, linking other areas' dairy pages.
WITHIN_DAIRIES_KEY = 'emissions:within-dairies:v1'


def region_within_dairies(region):
    return nearby.regions_within(region, url_method='get_emissions_dairies_url', cache_prefix=WITHIN_DAIRIES_KEY)


PAGE_SIZE = 50
SECTOR_PAGE_ROWS = 25
# The Areas view forces `measure=total` for a weighted toxics measure (its
# density and per-resident measures have no meaning for a share); the
# toolbar shows why with this tooltip instead of hiding the options.
SHARE_MEASURE_TOOLTIP = 'Weighted toxics are shown as a share of the Valley total, not per square mile.'


class ScopeMixin:
    """Resolves the explorer scope (year, county, pollutant, toxics, minor) and puts the scope bar's context on every page."""

    section = None
    hide_scope = False

    def get_scope(self):
        if not hasattr(self, '_scope'):
            self._scope = stats.resolve_scope(self.request.GET)
        return self._scope

    def dispatch(self, request, *args, **kwargs):
        # The ten toxics that used to be columns had their own picker keys;
        # an old link 301s to the pollutant's slug (the API resolves the
        # old key quietly instead).
        slug = stats.legacy_toxic_slug(request.GET)
        if slug:
            params = request.GET.copy()
            params['pollutant'] = slug
            return redirect(f'{request.path}?{params.urlencode()}', permanent=True)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        context = {
            'scope': scope,
            'year': scope.year,
            'year_options': stats.available_years(),
            'county': scope.county,
            'county_options': list(Region.objects.counties().order_by('name').values_list('slug', 'name')),
            'pollutant': scope.pollutant,
            'pollutant_options': stats.toxic_options(scope.year) if scope.toxics else CRITERIA + PRECURSORS,
            'toxics': scope.toxics,
            'minor': scope.minor,
            'scope_qs': scope.query(),
            'scope_params': scope.params(),
            # For links to region pages: the page is the area, so no ?county=.
            'region_qs': scope.query(county=None),
            'section': self.section,
            'hide_scope': self.hide_scope,
        }
        context.update(kwargs)
        return super().get_context_data(**context)


def sector_options():
    """Sectors A–Z for the pickers, the catch-all "Other" last."""
    return sorted(Facility.Sector.choices, key=lambda choice: (choice[0] == Facility.Sector.OTHER, choice[1]))


def list_filters(get):
    """The facility table's own filters (beyond the scope), validated."""
    sector = get.get('sector')
    sort = get.get('sort')
    region = get_filter_region(get.get('region'))
    compliance_value = get.get('compliance')
    return {
        'sector': sector if sector in Facility.Sector.values else None,
        'area': areas.RegionArea(region) if region else None,
        'q': (get.get('q') or '').strip() or None,
        'sort': sort if sort in stats.SORTS else '-value',
        'compliance': compliance_value if compliance_value in compliance.FILTERS else None,
    }


def get_filter_region(sqid, types=None):
    """
    The ?region= of a table's region filter, or None for a missing or
    unsearchable one. `types` narrows which region page types are accepted;
    the facility list's default is areas.FILTER_REGION_TYPES (cities, urban
    areas, CDPs and ZIPs), and the Dairies tab redirect and the dairy GeoJSON
    endpoint pass AREA_PAGE_TYPES.
    """
    if not sqid:
        return None
    return (
        Region.objects.filter(sqid=sqid, type__in=types or areas.FILTER_REGION_TYPES, boundary__isnull=False)
        .current_vintage().select_related('boundary').first()
    )


class Home(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/home.html'

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        totals = stats.totals(scope)
        return super().get_context_data(
            totals=totals,
            total=totals['value'],
            context_bar=stats.county_context(scope),
            nei_context=nei.context(scope),
            toxics_breakdown=stats.toxics_breakdown(scope) if scope.toxics else None,
            top_rows=stats.with_ranks(stats.facility_table(scope)[:10], stats.ranks(scope)),
            top_sectors=stats.sector_breakdown(scope)[:6],
            by_year=stats.by_year(scope),
            find_area_places=find_area_places(),
            find_area_counties=[p for p in find_area_places() if p['type'] == Region.Type.COUNTY],
            focus_find=self.request.GET.get('find') == '1',
            # The jump links go to county pages: the page is the county, so no ?county=.
            find_area_qs=scope.query(county=None),
            maptiler_key=settings.MAPTILER_API_KEY,
            **kwargs,
        )


class About(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/about.html'
    section = 'about'
    hide_scope = True

    def get_context_data(self, **kwargs):
        dairies_before, dairies_after = dairies.coverage_counts()
        return super().get_context_data(
            dairy_span=dairies.coverage_span(),
            dairy_count=dairies.dairy_count(),
            dairies_before=dairies_before,
            dairies_after=dairies_after,
            dairy_size_classes=dairies.size_classes(),
            health_values=SourceImport.latest('contable'),
            toxics_import=SourceImport.latest('ceidars-toxics'),
            compliance_stamp=compliance.stamp(),
            nei_stamp=SourceImport.latest(nei.SOURCE),
            wells_stamp=wells.stamp(),
            ghg_stamps=ghg.stamps(),
            **kwargs,
        )


class FacilityList(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/facility-list.html'
    section = 'facilities'

    def get(self, request, *args, **kwargs):
        if request.GET.get('format') == 'csv':
            return self.csv_response()
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        filters = list_filters(self.request.GET)
        page = Paginator(stats.facility_table(scope, **filters), PAGE_SIZE).get_page(self.request.GET.get('page'))
        return super().get_context_data(
            rows=stats.with_ranks(page.object_list, stats.ranks(scope)),
            page_obj=page,
            is_paginated=page.has_other_pages(),
            sort=filters['sort'],
            filters=filters,
            region=filters['area'].region if filters['area'] else None,
            sector_options=sector_options(),
            compliance_options=compliance.FILTER_LABELS,
            **kwargs,
        )

    def csv_response(self):
        scope = self.get_scope()
        rank_map = stats.ranks(scope)
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="facility-emissions-{scope.year}.csv"'
        writer = csv.writer(response)
        # One extra column for a pollutant that isn't a criteria column: a
        # toxic (lbs or share) or ammonia (tons), the scope's `value`.
        criteria_keys = {pollutant.key for pollutant in CRITERIA}
        extra_column = [] if scope.pollutant.key in criteria_keys else [
            f"{scope.pollutant.key}_{'share' if scope.pollutant.weighted else scope.pollutant.unit}"
        ]
        writer.writerow(
            ['rank', 'facility', 'id', 'air_district', 'county', 'city', 'sector', 'sic_code', 'year']
            + [f'{pollutant.key}_tons' for pollutant in CRITERIA] + extra_column
            + ['epa_tracked', 'hpv_status']
        )
        tracked = {row.facility_id: row for row in AirComplianceFacility.objects.exclude(facility=None).order_by('reported_through')}
        for record in stats.facility_table(scope, **list_filters(self.request.GET)):
            facility = record.facility
            values = [pollutant.display(getattr(record, pollutant.key)) for pollutant in CRITERIA] + ([record.value] if extra_column else [])
            writer.writerow(
                [rank_map.get(record.facility_id, ''), facility.name, facility.sqid, facility.air_district.name,
                 facility.get_county() or '', facility.get_city(), facility.get_sector_display(),
                 facility.sic_code or '', record.year]
                + ['' if value is None else value for value in values]
                + ['yes' if facility.pk in tracked else '', tracked[facility.pk].hpv_status if facility.pk in tracked else '']
            )
        return response


def get_facility(sqid):
    facility = Facility.objects.filter(sqid=sqid).first()
    if facility is None:
        raise Http404('No such facility.')
    return facility


class FacilityRedirect(vanilla.View):
    """`facilities/<sqid>/` -> the slugged URL, keeping the query string."""

    def get(self, request, sqid):
        facility = get_facility(sqid)
        query = request.GET.urlencode()
        return redirect(facility.get_absolute_url() + (f'?{query}' if query else ''), permanent=True)


def nearby_groups(nearby):
    """(heading, rows, hidden count) per group of schools.near(), for the card's template."""
    if not nearby:
        return []
    return [
        (heading, rows, max(len(rows) - schools.SHOWN, 0))
        for heading, rows in (('Within 1,000 ft', nearby['within_1000ft']), ('1,000 ft to ¼ mile', nearby['within_quarter_mile']))
    ]


class FacilityDetail(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/facility-detail.html'
    section = 'facilities'

    def get(self, request, sqid, slug):
        self.facility = get_facility(sqid)
        if request.path != self.facility.get_absolute_url():
            query = request.GET.urlencode()
            return redirect(self.facility.get_absolute_url() + (f'?{query}' if query else ''), permanent=True)
        return super().get(request, sqid=sqid, slug=slug)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        facility = self.facility
        record = facility.emissions.filter(year=scope.year).first() or facility.emissions.order_by('-year').first()
        shown_year = record.year if record else scope.year
        nearby = schools.near(facility)
        facility_regions = areas.facility_areas(facility)
        tract = next((region for region in facility_regions if region.type == Region.Type.TRACT), None)
        return super().get_context_data(
            facility=facility,
            district=facility.air_district,
            shown_year=shown_year,
            ranks=stats.facility_ranks(facility, shown_year),
            trend=stats.by_year(scope, facility=facility),
            toxics_rows=stats.facility_toxics(facility, shown_year),
            changes=stats.large_changes(facility, shown_year),
            hot_spots=stats.hot_spots(record),
            health_values=SourceImport.latest('contable'),
            area_links=area_links(facility_regions),
            facility_ces=ces_stats.tract_record(tract),
            compliance_card=compliance.facility_card(facility),
            ghg_card=ghg.facility_card(facility),
            nearby=nearby,
            nearby_shown=schools.SHOWN,
            nearby_groups=nearby_groups(nearby),
            # The facility's own map always includes it: the page scope can
            # exclude it (a minor source with `minor` off, no record in the
            # scope year, or a different `county`), but its map shouldn't.
            map_config=facility_map_config(
                scope, mode='compact', highlight=facility,
                params=scope.params(year=shown_year, minor='1', county=None),
                nearby=schools.geojson(nearby) if nearby else None,
            ),
            **kwargs,
        )


class SectorList(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/sector-list.html'
    section = 'sectors'

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        trends = stats.sector_trends(scope)
        sort = self.request.GET.get('sort')
        sort = sort if sort in stats.SECTOR_SORTS else '-value'
        rows = [dict(row, trend=trends.get(row['sector'], [])) for row in stats.sector_breakdown(scope)]
        return super().get_context_data(rows=stats.sort_sectors(rows, sort), sort=sort, **kwargs)


class SectorDetail(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/sector-detail.html'
    section = 'sectors'

    def get(self, request, sector):
        if sector not in Facility.Sector.values:
            raise Http404('No such sector.')
        self.sector = Facility.Sector(sector)
        return super().get(request, sector=sector)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        summary = next((row for row in stats.sector_breakdown(scope) if row['sector'] == self.sector), None)
        table = stats.facility_table(scope, sector=self.sector)
        return super().get_context_data(
            sector=self.sector,
            summary=summary,
            trend=stats.by_year(scope, sector=self.sector),
            counties=stats.county_breakdown(scope, sector=self.sector),
            rows=stats.with_ranks(table[:SECTOR_PAGE_ROWS], stats.ranks(scope)),
            facility_count=table.count(),
            map_config=facility_map_config(
                scope, mode='compact', sector=self.sector,
                wells=wells_overlay(self.request.GET, default=self.sector == Facility.Sector.OIL_GAS),
            ),
            kern_callout=wells.kern_callout(scope.year) if self.sector == Facility.Sector.OIL_GAS else None,
            wells_stamp=wells.stamp(),
            **kwargs,
        )


def map_view(get, default_level=areas.DEFAULT_LEVEL, year=None, *, share=False):
    """
    The map's view, level, measure and compared year (Compare applies to
    both the Facilities and Areas views) from a request's GET, validated;
    defaults when unknown. Also the page's default level: the map leaves
    defaults out of the URLs it writes, so it needs to know it. `year` (the
    scope's) resolves `compare` and its option list; a caller with no year
    to compare against (none passed) gets neither. `share` (a weighted
    toxics measure) forces `measure` to 'total': density and per-resident
    have no meaning for a share of the Valley total.
    """
    view = get.get('view')
    level = get.get('level')
    measure = get.get('measure')
    compare = stats.resolve_compare_param(get.get('compare'), year) if year is not None else None
    measure = measure if measure in areas.MEASURES else areas.DEFAULT_MEASURE
    if share:
        measure = 'total'
    return {
        'view': view if view in ('facilities', 'areas') else 'facilities',
        'level': level if level in areas.LEVELS else default_level,
        'measure': measure,
        'default_level': default_level,
        'compare': compare or '',
        # Every other loaded year, newest first, for the toolbar's picker;
        # none until there's a year to compare against.
        'compare_options': [y for y in reversed(stats.available_years()) if y != year] if year else [],
    }


def wells_overlay(get, *, default=False):
    """
    The map's Oil & gas wells overlay: on by default where `default` says
    (Kern County's page, the oil-gas sector page), off elsewhere; ?wells=1|0
    overrides either way so the state can be shared.
    """
    raw = get.get('wells')
    on = raw == '1' if raw in ('0', '1') else default
    return {'on': on, 'default': default}


def is_kern(region):
    """Kern County's page: the overlay's default is on and the block carries the oil & gas callout."""
    return region.type == Region.Type.COUNTY and region.slug == wells.KERN_SLUG


def wells_block(area, scope, *, kern=False):
    """
    The "Oil & gas wells" section on a region or near-me page, or None when
    the area has no wells: the counts, the schools and child-care centers
    with a well within 3,200 ft, and on Kern County's page what the oil & gas
    permit groupings report (wells.kern_callout).
    """
    summary = wells.area_summary(area)
    if summary is None:
        return None
    return {
        'summary': summary,
        'schools': wells.schools_near_wells(area),
        'kern': wells.kern_callout(scope.year) if kern else None,
        'stamp': wells.stamp(),
        # Wells are today's snapshot, not the scope year's: the caveat is louder on a past year.
        'year': scope.year,
        'past_year': scope.year is not None and scope.year != stats.latest_year(),
    }


def facility_map_config(scope, *, mode='full', highlight=None, sector=None, params=None, areas_view=None,
                        outline_url='', center='', zoom='', radius='', nearby=None, wells=None):
    """
    The data-* attributes of a `.facility-map` container (see
    assets/js/emissions/facility-map.js). `nearby` is a FeatureCollection
    (schools.geojson) for the facility page's schools-and-child-care overlay,
    or None. `wells` (views.wells_overlay's return, or None) offers the Oil &
    gas wells overlay and its initial state; None (a facility's own map)
    leaves it off with no URL at all.
    """
    params = dict(params) if params is not None else scope.params()
    if sector:
        params['sector'] = sector
    point = highlight.point if highlight is not None else None
    config = {
        'mode': mode,
        'geojson_url': reverse('api:v2:emissions:geojson'),
        'districts_url': reverse('api:v2:emissions:districts'),
        # The covered counties' outlines, from the regions API.
        'counties_url': f"{reverse('api:v2:regions:region-geojson')}?type=county",
        'query': urlencode(params),
        # The bare-sqid route redirects to the slugged page, so the JS needs no slug.
        'facility_url': reverse('emissions:facility-redirect', args=['__id__']).replace('__id__', '{id}'),
        'maptiler_key': settings.MAPTILER_API_KEY,
        'style': mapconfig.MAP_STYLE,
        'highlight': highlight.sqid if highlight is not None else '',
        'center': center or (f'{point.y},{point.x}' if point is not None else ''),
        'zoom': zoom or (11 if point is not None else ''),
        'bounds': mapconfig.covered_bounds(),
        # The region or circle the page is about (region pages, near-me).
        'outline_url': outline_url,
        'radius': radius,
        # The Oil & gas wells overlay (CalGEM WellSTAR, wells.py): offered where
        # `wells` is set (the map page, region, near-me and sector pages) and
        # never on a facility's own map. `wells` is its initial state, `wells_default`
        # the page's default (the JS writes ?wells= only when they differ).
        'wells_url': reverse('api:v2:emissions:wells-geojson') if wells else '',
        'well_url': reverse('api:v2:emissions:well-detail', args=['__id__']).replace('__id__', '{id}') if wells else '',
        'wells': '1' if wells and wells['on'] else '',
        'wells_default': '1' if wells and wells['default'] else '',
        # The facility page's schools and child care within 1/4 mile (a
        # FeatureCollection, JSON in the attribute) and the ring to draw.
        'nearby': json.dumps(nearby) if nearby else '',
        'ring_miles': schools.QUARTER_MILE_FT / schools.FEET_PER_MILE if nearby else '',
        # The Areas view (the map page, region pages): off where it's None.
        'areas': '1' if areas_view else '',
        'areas_url': reverse('api:v2:emissions:areas') if areas_view else '',
        'shapes_url': reverse('api:v2:regions:region-geojson') if areas_view else '',
        'region_url': reverse('emissions:region-redirect', args=['__id__']).replace('__id__', '{id}') if areas_view else '',
        'view': areas_view['view'] if areas_view else 'facilities',
        'level': areas_view['level'] if areas_view else '',
        'measure': areas_view['measure'] if areas_view else '',
        'default_level': areas_view['default_level'] if areas_view else '',
        # The year Compare shades the change against, in both views (a
        # facility's own circle too, not just Areas): a toolbar control
        # (like the pesticides map's), not explorer scope -- it stays out
        # of scope_params, so no other page offers or carries it.
        'compare': areas_view['compare'] if areas_view else '',
        # Only for the Compare legend's "change <compare> to <year>" title.
        'year': scope.year or '',
        'label': scope.pollutant.label,
        'name': scope.pollutant.name,
        'unit': scope.pollutant.unit,
        'sector': sector or '',
        'sector_label': Facility.Sector(sector).label if sector else '',
        'level_options': [(level, label) for level, label in (
            (Region.Type.COUNTY, 'Counties'), (Region.Type.ZIPCODE, 'ZIP codes'), (Region.Type.TRACT, 'Census tracts'))],
        'measure_options': [('density', 'Per square mile'), ('total', 'Total'), ('per_resident', 'Per 1,000 residents')],
        'compare_options': areas_view['compare_options'] if areas_view else [],
        'disabled_measures': {'density': SHARE_MEASURE_TOOLTIP, 'per_resident': SHARE_MEASURE_TOOLTIP} if scope.pollutant.unit == 'share' else {},
    }
    # The container's data attributes; the sector, its label and the level,
    # measure and compare options are for the toolbar template, which reads
    # them off map_config.
    template_only = {'sector', 'sector_label', 'level_options', 'measure_options', 'compare_options', 'disabled_measures'}
    config['map'] = mapconfig.map_config(
        'facility-map',
        data={key.replace('_', '-'): value for key, value in config.items() if key not in template_only},
        features={'toolbar': True, 'expand': True, 'legend': True},
        toolbar_template='emissions/includes/map-toolbar.html' if mode == 'full' or areas_view else None,
        options_template='emissions/includes/map-options.html',
        legend_template='emissions/includes/facility-map-legend.html',
        compact=mode == 'compact',
    )
    return config


class MapPage(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/map.html'
    section = 'map'

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        sector = self.request.GET.get('sector')
        sector = sector if sector in Facility.Sector.values else None
        return super().get_context_data(
            map_config=facility_map_config(
                scope, sector=sector,
                areas_view=map_view(self.request.GET, year=scope.year, share=scope.pollutant.unit == 'share'),
                wells=wells_overlay(self.request.GET),
            ),
            sector_options=sector_options(),
            **kwargs,
        )


AREA_PAGE_TYPES = (
    Region.Type.COUNTY, *Region.COMMUNITY_TYPES, Region.Type.ZIPCODE,
    Region.Type.SCHOOL_DISTRICT, Region.Type.TRACT,
)
# The search box lists every page type but tracts: a tract's name is its GEOID.
# Each community layer (city, urban area, CDP) is listed as-is, labelled, so
# "Fresno" is both "Fresno · City" and "Fresno · Urban area".
FIND_AREA_TYPE_LABELS = {
    Region.Type.COUNTY: 'County',
    **Region.COMMUNITY_LABELS,
    Region.Type.ZIPCODE: 'ZIP',
    Region.Type.SCHOOL_DISTRICT: 'School district',
}
# :v2 -- the synthetic places are gone; a list cached before then must not be served.
FIND_AREA_PLACES_KEY = f'emissions:v{stats.CACHE_VERSION}:find-area-places:v2'
RADIUS_CHOICES = (1, 3, 5)
RADIUS_ZOOMS = {1: 13, 3: 12, 5: 11}
MAX_LABEL = 120
NEAR_PREFIX = re.compile(r'^near\s+', re.IGNORECASE)


def find_area_places(url_name='emissions:region'):
    """
    Every region page but tracts, as {name, type, type_label, short_name,
    url}, for the search box. `url_name` picks the page the box lands on:
    the emissions region pages (the home page) or the dairy pages (the
    Dairies tab); each is cached under its own key.
    """
    def compute():
        regions = (
            Region.objects.filter(type__in=FIND_AREA_TYPE_LABELS, boundary__isnull=False)
            .order_by('name').values_list('sqid', 'slug', 'name', 'type')
        )
        return [{
            'name': name,
            'type': region_type,
            'type_label': FIND_AREA_TYPE_LABELS[region_type],
            'short_name': name[:-len(' County')] if name.endswith(' County') else name,
            'url': reverse(url_name, kwargs={'sqid': sqid, 'slug': slug}),
        } for sqid, slug, name, region_type in regions]
    return cache.get_or_set(f'{FIND_AREA_PLACES_KEY}:{url_name}', compute, stats.CACHE_TIMEOUT)


def region_title(region):
    if region.type == Region.Type.TRACT:
        return (region.metadata or {}).get('namelsad') or f'Census tract {region.name}'
    return region.name


def region_page_title(region):
    """
    The <title> and breadcrumb text: `region_title()`, plus its type for a
    community region (city, urban area, CDP) -- Fresno the city and Fresno
    the urban area otherwise both read as plain "Fresno" in a browser tab or
    a breadcrumb, where the page's own heading line (type · county ·
    population) isn't visible. Counties, ZIPs, tracts, and school districts
    are already unambiguous on their own. The visible h1 stays the plain
    name (AreaPage's `name`).
    """
    name = region_title(region)
    if region.type in Region.COMMUNITY_TYPES:
        return f'{name} ({region.type_label})'
    return name


def area_links(regions):
    """The facility page's "Area" line: each region it counts in, labelled, linking to its page."""
    labels = {Region.Type.ZIPCODE: 'ZIP {}'}
    return [{
        'label': labels.get(region.type, '{}').format(region_title(region)),
        'url': region.get_emissions_url(),
    } for region in regions]


def compliance_list_url(scope, area):
    """
    The facility list filtered to unaddressed HPVs, narrowed to the area where
    the list can be: ?county= for a county, ?region= for the types its region
    filter searches (cities, urban areas, CDPs, ZIPs), nothing for the rest.
    """
    params = dict(scope.params(county=None), compliance='hpv')
    region = getattr(area, 'region', None)
    if region is not None:
        if region.type == Region.Type.COUNTY:
            params['county'] = region.slug
        elif region.type in areas.FILTER_REGION_TYPES:
            params['region'] = region.sqid
    return f"{reverse('emissions:facility-list')}?{urlencode(params)}"


def dairy_page_query(scope, year):
    """
    The area's dairy page's query from an emissions scope: the year, and the
    pollutant only when dairies report it (else the page falls back to ROG
    quietly, and the link needn't carry a pollutant it will drop).
    """
    params = {'year': year}
    if scope.pollutant.key in dairies.POLLUTANT_KEYS:
        params['pollutant'] = scope.pollutant.key
    return urlencode(params)


def dairy_block(scope, area, dairy_url, *, county=None):
    """
    The one-line Dairies summary on a region or near-me page, or None before
    CARB's dairy database is imported. `dairy_url(query)` builds the area's
    dairy page URL. Outside CADD's years it only says so (the template greys
    it) and links the dairy page at CADD's last year. `county` (county
    pages) adds CARB's county dairy-cattle emissions in the scope pollutant.
    """
    known = dairies.years()
    if not known:
        return None
    block = {
        'first_year': known[0],
        'last_year': known[-1],
        'in_range': scope.year in known,
        'is_county': county is not None,
        'last_year_url': dairy_url(dairy_page_query(scope, known[-1])),
    }
    if not block['in_range']:
        return block
    reported = scope.pollutant.key in dairies.POLLUTANT_KEYS
    summary = dairies.summary(scope.year, area=area)
    block.update(
        summary=summary,
        has_dairies=bool(summary['dairies']),
        page_url=dairy_url(dairy_page_query(scope, scope.year)),
        county_pollutant=reported,
        county_tons=dairies.county_emissions(scope.year, scope.pollutant).get(county.pk) if county is not None and reported else None,
    )
    return block


class AreaPage(ScopeMixin, vanilla.TemplateView):
    """What a region page and near-me share: one area's facilities, totals, map, sectors and trend."""
    template_name = 'emissions/area.html'

    def get(self, request, *args, **kwargs):
        # The page is the area: a stray ?county= would ride along on the
        # scope-picker links (built from request.GET), so drop it here.
        if 'county' in request.GET:
            params = request.GET.copy()
            params.pop('county')
            request.GET = params
        return super().get(request, *args, **kwargs)

    def get_area(self):
        raise NotImplementedError

    def get_county(self):
        """The county the page's share is of."""
        raise NotImplementedError

    def get_map_config(self, scope):
        raise NotImplementedError

    def dairy_url(self, query):
        """The area's dairy page, with `query` (year, pollutant) on it."""
        raise NotImplementedError

    def dairy_county(self):
        """The county whose CARB dairy emissions the page shows (county pages only)."""
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        base = self.get_scope()
        area = self.get_area()
        scope = stats.Scope(year=base.year, county=None, pollutant=base.pollutant, minor=base.minor, area=area)
        summary = compliance.area_summary(scope)
        compliance_line = dict(summary, url=compliance_list_url(base, area)) if summary else None
        totals = stats.totals(scope)
        total = totals['value'] or 0
        county = self.get_county()
        county_scope = stats.Scope(year=base.year, county=county, pollutant=base.pollutant, minor=base.minor)
        county_total = stats.totals(county_scope)['value'] if county else None
        # A region page overrides this with its own "In and around" lists;
        # a near-me page (a point, not a region) has none.
        kwargs.setdefault('within', None)
        kwargs.setdefault('ghg_table', None)
        # The Community card (CalEnviroScreen): a summary of the tracts the
        # area covers, or on a tract page the tract's own row. Subclasses set
        # them; None hides the card.
        kwargs.setdefault('community', None)
        kwargs.setdefault('tract_ces', None)
        kwargs.setdefault('show_top_tracts', False)
        # The "Oil & gas wells" section (region and near-me pages); a
        # near-me page's own get_context_data sets it, so this default only
        # matters for whichever subclass doesn't.
        kwargs.setdefault('wells_block', None)
        return super().get_context_data(
            area=area,
            county_region=county,
            totals=totals,
            total=total,
            per_sq_mi=total / area.sq_miles if area.sq_miles else None,
            county_share=total / county_total if county_total else None,
            top_rows=stats.with_ranks(stats.facility_table(scope)[:10], stats.ranks(scope)),
            top_sectors=stats.sector_breakdown(scope),
            by_year=stats.by_year(scope),
            map_config=self.get_map_config(base),
            compliance_line=compliance_line,
            dairy_block=dairy_block(base, area, self.dairy_url, county=self.dairy_county()),
            toxics_breakdown=stats.toxics_breakdown(scope) if scope.toxics else None,
            share_unit=scope.pollutant.unit == 'share',
            # The page is the area: no county picker, and the scope links
            # leave the county out.
            county_options=[],
            scope_qs=base.query(county=None),
            scope_params=base.params(county=None),
            **kwargs,
        )


def get_page_region(sqid):
    """A region with a page (AREA_PAGE_TYPES, a boundary, the current tract vintage), or None."""
    return (
        Region.objects.filter(sqid=sqid, type__in=AREA_PAGE_TYPES, boundary__isnull=False)
        .current_vintage().select_related('boundary').first()
    )


class RegionRedirect(vanilla.View):
    """`region/<sqid>/` -> the slugged URL, keeping the query string (the map's popups link here)."""

    # The Region method that builds the slugged URL; the dairy pages' redirect overrides it.
    url_method = 'get_emissions_url'

    def get(self, request, sqid):
        region = get_page_region(sqid)
        if region is None:
            raise Http404('No such region.')
        query = request.GET.urlencode()
        return redirect(getattr(region, self.url_method)() + (f'?{query}' if query else ''), permanent=True)


class RegionLookupMixin:
    """
    `region/<sqid>/<slug>/` for a page about one region: a page type with a
    boundary and a current vintage (get_page_region), else a 404; a wrong
    slug redirected to the right one with the query kept. The emissions
    region page and the dairy region page share it so the rules can't drift.
    """

    def region_url(self, region):
        return region.get_emissions_url()

    def lookup_region(self, request, sqid, slug):
        """Sets self.region; None when the URL is right, else the redirect. Raises Http404."""
        self.region = get_page_region(sqid)
        if self.region is None:
            raise Http404('No such region.')
        if slug != self.region.slug:
            query = request.GET.urlencode()
            return redirect(self.region_url(self.region) + (f'?{query}' if query else ''), permanent=True)
        return None


class RegionPage(RegionLookupMixin, AreaPage):
    def get(self, request, sqid, slug):
        response = self.lookup_region(request, sqid, slug)
        if response is not None:
            return response
        return super().get(request, sqid=sqid, slug=slug)

    def get_area(self):
        return areas.RegionArea(self.region)

    def get_county(self):
        if self.region.type == Region.Type.COUNTY:
            return self.region
        return Region.objects.get_county_region(self.region)

    def get_map_config(self, scope):
        level = areas.NEXT_LEVEL.get(self.region.type)
        return facility_map_config(
            scope, mode='compact', params=scope.params(county=None),
            areas_view=map_view(self.request.GET, level, year=scope.year, share=scope.pollutant.unit == 'share') if level else None,
            outline_url=reverse('api:v2:regions:region-detail', args=[self.region.sqid]),
            wells=wells_overlay(self.request.GET, default=is_kern(self.region)),
        )

    def dairy_url(self, query):
        return f'{self.region.get_emissions_dairies_url()}?{query}'

    def dairy_county(self):
        return self.region if self.region.type == Region.Type.COUNTY else None

    def get_context_data(self, **kwargs):
        region = self.region
        extra = {}
        if region.type == Region.Type.COUNTY:
            # The context bar names `county`; on a county page that's the page's own.
            extra['county'] = region
        if region.type == Region.Type.TRACT:
            extra['tract_ces'] = ces_stats.tract_record(region)
        elif region.boundary_id:
            extra['community'] = ces_stats.tract_summary(region.boundary.geometry)
            extra['show_top_tracts'] = region.type == Region.Type.COUNTY
        extra['wells_block'] = wells_block(areas.RegionArea(region), self.get_scope(), kern=is_kern(region))
        county_scope = stats.Scope(
            year=self.get_scope().year, county=region, pollutant=self.get_scope().pollutant, minor=self.get_scope().minor,
        ) if region.type == Region.Type.COUNTY else None
        return super().get_context_data(
            # `name` is the plain heading (h1); `title` (the <title> tag and
            # the breadcrumb, which have no identifiers line under them to
            # disambiguate) adds the type for a community region.
            name=region_title(region),
            title=region_page_title(region),
            # The Dairies block's link text ("Dairies in <name> →"); a
            # near-me page overrides this with its own lowercase phrase.
            dairies_label=f'in {region_title(region)}',
            kind=region.type_label,
            population=(region.metadata or {}).get('population'),
            context_bar=stats.county_context(county_scope) if county_scope else None,
            nei_context=nei.context(county_scope) if county_scope else None,
            within=region_within(region) if region.boundary_id else None,
            ghg_table=ghg.county_table(region) if region.type == Region.Type.COUNTY else None,
            **extra,
            **kwargs,
        )


def radius_area(get):
    """A RadiusArea from ?lat=&lng=&radius= (1, 3 or 5 miles; 1 when left out), or None when any of it is missing or bad."""
    try:
        lat = float(get['lat'])
        lng = float(get['lng'])
        radius = int(get.get('radius', 1))
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    if radius not in RADIUS_CHOICES:
        return None
    return areas.RadiusArea(round(lat, 4), round(lng, 4), radius)


def radius_label(get, lat, lng):
    """
    The near-me point's display label from ?label= or the point itself, with
    a stray "near " prefix stripped and long labels cut. Shared by NearMe's
    page title and the dairy near-me page's.
    """
    label = (get.get('label') or f'{lat:.3f}, {lng:.3f}')[:MAX_LABEL]
    return NEAR_PREFIX.sub('', label)


class NearLookupMixin:
    """
    ?lat=&lng=&radius=&label= for a page about a point and a 1, 3 or 5 mile
    radius, from the address bar, never stored: `self.near` (a RadiusArea)
    and `self.county` (the covered county the point is in). Anything invalid,
    or a point outside the covered counties, bounces to the home page's find
    form. The emissions near-me page and the dairy near-me page share it.
    """

    def lookup_near(self, request):
        """Sets self.near and self.county; None when the point is good, else the bounce."""
        self.near = radius_area(request.GET)
        if self.near is None:
            return self.bounce()
        self.county = Region.objects.counties().filter(boundary__geometry__intersects=self.near.point).first()
        if self.county is None:
            return self.bounce()
        # Cut an over-long label in the query itself, so the links built from
        # it (the scope picker, the radius buttons) don't carry it either.
        label = request.GET.get('label') or ''
        if len(label) > MAX_LABEL:
            params = request.GET.copy()
            params['label'] = label[:MAX_LABEL]
            request.GET = params
        return None

    def bounce(self):
        return redirect(reverse('emissions:home') + '?find=1')

    def near_phrase(self):
        """'within 3 miles of <label>' -- lowercase, for use mid-sentence (near_title() capitalizes it for a heading)."""
        label = radius_label(self.request.GET, self.near.lat, self.near.lng)
        return f'within {self.near.radius} mile{"s" if self.near.radius != 1 else ""} of {label}'

    def near_title(self):
        """'Within 3 miles of <label>' -- find-area.js labels read "near X"; the title already says "of"."""
        phrase = self.near_phrase()
        return phrase[0].upper() + phrase[1:]

    def near_params(self):
        """The point as query parameters, for links to the other near-me page."""
        params = {'lat': f'{self.near.lat:.4f}', 'lng': f'{self.near.lng:.4f}', 'radius': self.near.radius}
        label = (self.request.GET.get('label') or '')[:MAX_LABEL]
        if label:
            params['label'] = label
        return params

    def radius_url(self, miles):
        params = self.request.GET.copy()
        params['radius'] = miles
        # A paginated dairy page's radius button would otherwise carry a page
        # number the new radius's table may not have (Paginator clamps it to
        # the last page, landing the reader mid-list instead of at the top).
        params.pop('page', None)
        return f'{self.request.path}?{params.urlencode()}'

    def radius_options(self):
        return [
            {'miles': miles, 'url': self.radius_url(miles), 'current': miles == self.near.radius}
            for miles in RADIUS_CHOICES
        ]


class NearMe(NearLookupMixin, AreaPage):
    """The area page for a point and a 1, 3 or 5 mile radius (NearLookupMixin)."""

    def get(self, request, *args, **kwargs):
        response = self.lookup_near(request)
        if response is not None:
            return response
        return super().get(request, *args, **kwargs)

    def get_area(self):
        return self.near

    def get_county(self):
        return self.county

    def get_map_config(self, scope):
        return facility_map_config(
            scope, mode='compact', params=scope.params(county=None),
            areas_view=map_view(self.request.GET, Region.Type.TRACT, year=scope.year, share=scope.pollutant.unit == 'share'),
            center=f'{self.near.lat:.4f},{self.near.lng:.4f}', zoom=RADIUS_ZOOMS[self.near.radius],
            radius=self.near.radius,
            wells=wells_overlay(self.request.GET),
        )

    def dairy_url(self, query):
        return f"{reverse('emissions:near-me-dairies')}?{query}&{urlencode(self.near_params())}"

    def dairy_county(self):
        return None

    def get_context_data(self, **kwargs):
        # Not a region, so nothing to disambiguate with a type -- `name`
        # (the h1) and `title` (the <title> tag and breadcrumb) are the same.
        title = self.near_title()
        return super().get_context_data(
            name=title,
            title=title,
            dairies_label=self.near_phrase(),
            kind='Near me',
            population=None,
            context_bar=None,
            radius_options=self.radius_options(),
            privacy_note=True,
            community=ces_stats.tract_summary(self.near.geometry),
            wells_block=wells_block(self.near, self.get_scope()),
            **kwargs,
        )
