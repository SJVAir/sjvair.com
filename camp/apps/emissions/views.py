import csv
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

from camp.apps.emissions import areas, stats
from camp.apps.emissions.models import Facility
from camp.apps.emissions.pollutants import CRITERIA, TOXICS
from camp.apps.regions.models import Region
from camp.utils import mapconfig

PAGE_SIZE = 50
SECTOR_PAGE_ROWS = 25


class ScopeMixin:
    """Resolves the explorer scope (year, county, pollutant, toxics, minor) and puts the scope bar's context on every page."""

    section = None
    hide_scope = False

    def get_scope(self):
        if not hasattr(self, '_scope'):
            self._scope = stats.resolve_scope(self.request.GET)
        return self._scope

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        context = {
            'scope': scope,
            'year': scope.year,
            'year_options': stats.available_years(),
            'county': scope.county,
            'county_options': list(Region.objects.counties().order_by('name').values_list('slug', 'name')),
            'pollutant': scope.pollutant,
            'pollutant_options': TOXICS if scope.toxics else CRITERIA,
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
    return {
        'sector': sector if sector in Facility.Sector.values else None,
        'area': areas.RegionArea(region) if region else None,
        'q': (get.get('q') or '').strip() or None,
        'sort': sort if sort in stats.SORTS else '-value',
    }


def get_filter_region(sqid, types=None):
    """
    The ?region= of a table's region filter, or None for a missing or
    unsearchable one. `types` narrows which region page types are accepted;
    the facility list's default is areas.FILTER_REGION_TYPES (cities, places
    and ZIPs), and the Dairies tab passes its own (dairy_views.FILTER_TYPES).
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
            total=totals[scope.pollutant.key],
            context_bar=stats.county_context(scope),
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
            **kwargs,
        )

    def csv_response(self):
        scope = self.get_scope()
        rank_map = stats.ranks(scope)
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="facility-emissions-{scope.year}.csv"'
        writer = csv.writer(response)
        writer.writerow(
            ['rank', 'facility', 'id', 'air_district', 'county', 'city', 'sector', 'sic_code', 'year']
            + [f'{pollutant.key}_tons' for pollutant in CRITERIA]
            + [f'{pollutant.key}_lbs' for pollutant in TOXICS]
        )
        for record in stats.facility_table(scope, **list_filters(self.request.GET)):
            facility = record.facility
            values = [pollutant.display(getattr(record, pollutant.key)) for pollutant in CRITERIA + TOXICS]
            writer.writerow(
                [rank_map.get(record.facility_id, ''), facility.name, facility.sqid, facility.air_district.name,
                 facility.get_county() or '', facility.get_city(), facility.get_sector_display(),
                 facility.sic_code or '', record.year]
                + ['' if value is None else value for value in values]
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
        return super().get_context_data(
            facility=facility,
            district=facility.air_district,
            shown_year=shown_year,
            ranks=stats.facility_ranks(facility, shown_year),
            trend=stats.by_year(scope, facility=facility),
            toxics_rows=stats.facility_toxics(facility, shown_year),
            changes=stats.large_changes(facility, shown_year),
            criteria=CRITERIA,
            area_links=area_links(areas.facility_areas(facility)),
            # The facility's own map always includes it: the page scope can
            # exclude it (a minor source with `minor` off, no record in the
            # scope year, or a different `county`), but its map shouldn't.
            map_config=facility_map_config(
                scope, mode='compact', highlight=facility,
                params=scope.params(year=shown_year, minor='1', county=None),
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
            map_config=facility_map_config(scope, mode='compact', sector=self.sector),
            **kwargs,
        )


def map_view(get, default_level=areas.DEFAULT_LEVEL):
    """
    The map's view, level and measure from a request's GET, validated; defaults
    when unknown. Also the page's default level: the map leaves defaults out of
    the URLs it writes, so it needs to know it.
    """
    view = get.get('view')
    level = get.get('level')
    measure = get.get('measure')
    return {
        'view': view if view in ('facilities', 'areas') else 'facilities',
        'level': level if level in areas.LEVELS else default_level,
        'measure': measure if measure in areas.MEASURES else areas.DEFAULT_MEASURE,
        'default_level': default_level,
    }


def facility_map_config(scope, *, mode='full', highlight=None, sector=None, params=None, areas_view=None,
                        outline_url='', center='', zoom='', radius=''):
    """The data-* attributes of a `.facility-map` container (see assets/js/emissions/facility-map.js)."""
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
        # The Areas view (the map page, region pages): off where it's None.
        'areas': '1' if areas_view else '',
        'areas_url': reverse('api:v2:emissions:areas') if areas_view else '',
        'shapes_url': reverse('api:v2:regions:region-geojson') if areas_view else '',
        'region_url': reverse('emissions:region-redirect', args=['__id__']).replace('__id__', '{id}') if areas_view else '',
        'view': areas_view['view'] if areas_view else 'facilities',
        'level': areas_view['level'] if areas_view else '',
        'measure': areas_view['measure'] if areas_view else '',
        'default_level': areas_view['default_level'] if areas_view else '',
        'label': scope.pollutant.label,
        'unit': scope.pollutant.unit,
        'sector': sector or '',
        'sector_label': Facility.Sector(sector).label if sector else '',
        'level_options': [(level, label) for level, label in (
            (Region.Type.COUNTY, 'Counties'), (Region.Type.ZIPCODE, 'ZIP areas'), (Region.Type.TRACT, 'Census tracts'))],
        'measure_options': [('density', 'Per square mile'), ('total', 'Total'), ('per_resident', 'Per 1,000 residents')],
    }
    # The container's data attributes; the sector, its label and the level and
    # measure options are for the toolbar template, which reads them off map_config.
    template_only = {'sector', 'sector_label', 'level_options', 'measure_options'}
    config['map'] = mapconfig.map_config(
        'facility-map',
        data={key.replace('_', '-'): value for key, value in config.items() if key not in template_only},
        features={'toolbar': True, 'expand': True, 'legend': True},
        toolbar_template='emissions/includes/map-toolbar.html' if mode == 'full' or areas_view else None,
        legend_template='emissions/includes/facility-map-legend.html',
        compact=mode == 'compact',
    )
    return config


class MapPage(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/map.html'
    section = 'map'

    def get_context_data(self, **kwargs):
        sector = self.request.GET.get('sector')
        sector = sector if sector in Facility.Sector.values else None
        return super().get_context_data(
            map_config=facility_map_config(self.get_scope(), sector=sector, areas_view=map_view(self.request.GET)),
            sector_options=sector_options(),
            **kwargs,
        )


AREA_PAGE_TYPES = (
    Region.Type.COUNTY, Region.Type.CITY, Region.Type.ZIPCODE, Region.Type.PLACE,
    Region.Type.SCHOOL_DISTRICT, Region.Type.TRACT,
)
# The search box lists every page type but tracts: a tract's name is its GEOID.
FIND_AREA_TYPE_LABELS = {
    Region.Type.COUNTY: 'County',
    Region.Type.CITY: 'City',
    Region.Type.ZIPCODE: 'ZIP',
    Region.Type.PLACE: 'Place',
    Region.Type.SCHOOL_DISTRICT: 'School district',
}
FIND_AREA_PLACES_KEY = f'emissions:v{stats.CACHE_VERSION}:find-area-places'
RADIUS_CHOICES = (1, 3, 5)
RADIUS_ZOOMS = {1: 13, 3: 12, 5: 11}
MAX_LABEL = 120
NEAR_PREFIX = re.compile(r'^near\s+', re.IGNORECASE)


def find_area_places():
    """Every region page but tracts, as {name, type, type_label, short_name, url}, for the search box."""
    def compute():
        regions = (
            Region.objects.filter(type__in=FIND_AREA_TYPE_LABELS, boundary__isnull=False)
            .order_by('name').values_list('sqid', 'slug', 'name', 'type')
        )
        places = [{
            'name': name,
            'type': region_type,
            'type_label': FIND_AREA_TYPE_LABELS[region_type],
            'short_name': name[:-len(' County')] if name.endswith(' County') else name,
            'url': reverse('emissions:region', kwargs={'sqid': sqid, 'slug': slug}),
        } for sqid, slug, name, region_type in regions]
        # Synthetic places share their names with the cities they were built
        # from; "Selma · City" beside "Selma · Place" only confuses.
        cities = {place['name'] for place in places if place['type'] == Region.Type.CITY}
        return [p for p in places if not (p['type'] == Region.Type.PLACE and p['name'] in cities)]
    return cache.get_or_set(FIND_AREA_PLACES_KEY, compute, stats.CACHE_TIMEOUT)


def region_title(region):
    if region.type == Region.Type.TRACT:
        return (region.metadata or {}).get('namelsad') or f'Census tract {region.name}'
    return region.name


def area_links(regions):
    """The facility page's "Area" line: each region it counts in, labelled, linking to its page."""
    labels = {Region.Type.ZIPCODE: 'ZIP {}'}
    return [{
        'label': labels.get(region.type, '{}').format(region_title(region)),
        'url': region.get_emissions_url(),
    } for region in regions]


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

    def get_context_data(self, **kwargs):
        base = self.get_scope()
        area = self.get_area()
        scope = stats.Scope(year=base.year, county=None, pollutant=base.pollutant, minor=base.minor, area=area)
        field = scope.pollutant.key
        totals = stats.totals(scope)
        total = totals[field] or 0
        county = self.get_county()
        county_scope = stats.Scope(year=base.year, county=county, pollutant=base.pollutant, minor=base.minor)
        county_total = stats.totals(county_scope)[field] if county else None
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
            # The page is the area: no county picker, and the scope links
            # leave the county out.
            county_options=[],
            scope_qs=base.query(county=None),
            scope_params=base.params(county=None),
            **kwargs,
        )


class RegionRedirect(vanilla.View):
    """`region/<sqid>/` -> the slugged URL, keeping the query string (the map's popups link here)."""

    def get(self, request, sqid):
        region = (
            Region.objects.filter(sqid=sqid, type__in=AREA_PAGE_TYPES, boundary__isnull=False)
            .current_vintage().first()
        )
        if region is None:
            raise Http404('No such region.')
        query = request.GET.urlencode()
        return redirect(region.get_emissions_url() + (f'?{query}' if query else ''), permanent=True)


class RegionPage(AreaPage):
    def get(self, request, sqid, slug):
        self.region = (
            Region.objects.filter(sqid=sqid, type__in=AREA_PAGE_TYPES, boundary__isnull=False)
            .current_vintage().select_related('boundary').first()
        )
        if self.region is None:
            raise Http404('No such region.')
        if slug != self.region.slug:
            query = request.GET.urlencode()
            return redirect(self.region.get_emissions_url() + (f'?{query}' if query else ''), permanent=True)
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
            areas_view=map_view(self.request.GET, level) if level else None,
            outline_url=reverse('api:v2:regions:region-detail', args=[self.region.sqid]),
        )

    def get_context_data(self, **kwargs):
        region = self.region
        extra = {}
        if region.type == Region.Type.COUNTY:
            # The context bar names `county`; on a county page that's the page's own.
            extra['county'] = region
        return super().get_context_data(
            title=region_title(region),
            kind=region.get_type_display(),
            population=(region.metadata or {}).get('population'),
            context_bar=stats.county_context(stats.Scope(
                year=self.get_scope().year, county=region, pollutant=self.get_scope().pollutant,
                minor=self.get_scope().minor,
            )) if region.type == Region.Type.COUNTY else None,
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
    page title and the Dairies tab's near-me filter tag (dairy_views.near_label).
    """
    label = (get.get('label') or f'{lat:.3f}, {lng:.3f}')[:MAX_LABEL]
    return NEAR_PREFIX.sub('', label)


class NearMe(AreaPage):
    """
    The area page for a point and a 1, 3 or 5 mile radius, from the address
    bar (?lat=&lng=&radius=&label=); never stored. Anything invalid, or a
    point outside the covered counties, bounces to the home page's find form.
    """

    def get(self, request, *args, **kwargs):
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
        return super().get(request, *args, **kwargs)

    def bounce(self):
        return redirect(reverse('emissions:home') + '?find=1')

    def get_area(self):
        return self.near

    def get_county(self):
        return self.county

    def get_map_config(self, scope):
        return facility_map_config(
            scope, mode='compact', params=scope.params(county=None),
            areas_view=map_view(self.request.GET, Region.Type.TRACT),
            center=f'{self.near.lat:.4f},{self.near.lng:.4f}', zoom=RADIUS_ZOOMS[self.near.radius],
            radius=self.near.radius,
        )

    def radius_url(self, miles):
        params = self.request.GET.copy()
        params['radius'] = miles
        return f'{self.request.path}?{params.urlencode()}'

    def get_context_data(self, **kwargs):
        label = radius_label(self.request.GET, self.near.lat, self.near.lng)
        return super().get_context_data(
            # find-area.js labels read "near X"; the title already says "of".
            title=f'Within {self.near.radius} mile{"s" if self.near.radius != 1 else ""} of {label}',
            kind='Near me',
            population=None,
            context_bar=None,
            radius_options=[
                {'miles': miles, 'url': self.radius_url(miles), 'current': miles == self.near.radius}
                for miles in RADIUS_CHOICES
            ],
            privacy_note=True,
            **kwargs,
        )
