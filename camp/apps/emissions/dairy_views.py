"""
The Dairies tab: CARB's dairy database (CADD) on a map, in a table and as a
trend for the scope's year and county, beside CARB's county dairy-cattle
emissions. The scope options that don't apply to dairies stay in the scope
bar, disabled (emissions/includes/scope-picker.html). `DairyAreaPage` and its
two concrete pages (`RegionDairies`, `NearMeDairies`) are the same layout
scoped to one area instead of the whole valley or a county.
"""
import csv
from urllib.parse import urlencode

from django.conf import settings
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

import vanilla

from camp.apps.emissions import areas, dairies, methane, nei, stats, views
from camp.apps.emissions.models import HERD_FIELDS
from camp.apps.emissions.pollutants import CRITERIA
from camp.apps.emissions.views import AREA_PAGE_TYPES, ScopeMixin, radius_area, region_page_title, region_title
from camp.apps.regions.models import Region
from camp.utils import mapconfig

PAGE_SIZE = 50
VIEW_OPTIONS = (('dairies', 'Dairies'), ('counties', 'Counties'))
MEASURE_OPTIONS = (
    ('mature_cows', 'Mature dairy cows'),
    ('mature_cows_per_sq_mi', 'Mature dairy cows per sq mi'),
    ('emissions', 'Dairy emissions'),
    ('emissions_per_sq_mi', 'Dairy emissions per sq mi'),
)
# The Dairies view's own toolbar filters: the map draws to these client-side
# (a MapLibre layer filter, dairy-map.js), so the server only needs to know
# them for the initial render (a bookmarked or shared link).
SIZE_OPTIONS = (('small', 'Small'), ('medium', 'Medium'), ('large', 'Large'))
SIZE_VALUES = frozenset(value for value, label in SIZE_OPTIONS)
DIGESTER_OPTIONS = (('', 'All dairies'), ('yes', 'With a digester'), ('no', 'Without a digester'))
DIGESTER_VALUES = frozenset(value for value, label in DIGESTER_OPTIONS if value)


def search_filters(get):
    """The table's own filters, validated: a name search, the sort, and the methane checkbox."""
    sort = get.get('sort')
    return {
        'q': (get.get('q') or '').strip() or None,
        'sort': sort if sort in dairies.TABLE_SORTS else dairies.DEFAULT_SORT,
        'methane': get.get('methane') if get.get('methane') in dairies.METHANE_FILTERS else None,
    }


def page_params(scope):
    """The scope as query parameters with the year always in: CADD's latest year needn't be the explorer's."""
    params = {key: value for key, value in scope.params().items() if key != 'year'}
    return {'year': scope.year, **params} if scope.year is not None else params


def canonical_query(get, scope):
    """The request's GET with the page's scope in it: the fallbacks in, the toggles that don't apply out."""
    params = get.copy()
    for key in ('toxics', 'minor'):
        params.pop(key, None)
    if scope.year is None:
        params.pop('year', None)
    else:
        params['year'] = str(scope.year)
    params['pollutant'] = scope.pollutant.key
    return params


def dairy_map_view(get):
    """
    The map's view, measure, and Dairies-view filters (size classes,
    digester) from a request's GET, validated; defaults when unknown. `sizes`
    absent means all three; present (even blank) is exactly what's listed,
    unknown values dropped -- so a link can name none of them.
    """
    view = get.get('view')
    measure = get.get('measure')
    raw_sizes = get.get('sizes')
    sizes = SIZE_VALUES if raw_sizes is None else {value for value in raw_sizes.split(',') if value in SIZE_VALUES}
    digester = get.get('digester')
    return {
        'view': view if view in dairies.VIEWS else dairies.DEFAULT_VIEW,
        'measure': measure if measure in dairies.MEASURES else dairies.DEFAULT_MEASURE,
        'sizes': sizes,
        'digester': digester if digester in DIGESTER_VALUES else '',
    }


def csv_response(rows, filename):
    """The dairy table (dairies.table rows) as CSV, one row per herd."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(
        ['cadd_id', 'dairy', 'id', 'street', 'city', 'zipcode', 'county', 'year']
        + list(HERD_FIELDS)
        + ['mature_cows', 'other_cattle', 'size_class']
        + ['milk_cows_ref_code', 'non_milking_ref_code', 'digester_operating', 'digester_since']
    )
    for herd in rows:
        dairy = herd.dairy
        writer.writerow(
            [dairy.cadd_id, dairy.name, dairy.sqid, dairy.address.get('street', ''), dairy.address.get('city', ''),
             dairy.address.get('zipcode', ''), dairy.county.name, herd.year]
            + ['' if getattr(herd, field) is None else getattr(herd, field) for field in HERD_FIELDS]
            + [herd.mature_cows, herd.other_cattle, herd.size_class]
            + [herd.milk_cows_ref_code, herd.non_milking_ref_code,
               'yes' if herd.digester else 'no', herd.digester_since or '']
        )
    return response


def dairy_map_config(scope, view, *, area_params=None, outline_url='', center='', zoom='', radius=''):
    """
    The data-* attributes of a `.dairy-map` (see assets/js/emissions/dairy-map.js):
    the Dairies tab's, or a dairy area page's with `area_params` (the GeoJSON
    endpoint's region= or lat/lng/radius, so the points are the area's
    dairies) and the area's frame -- `outline_url` (a region's boundary,
    outlined and masked) or `center`/`zoom`/`radius` (near-me's circle). An
    area page has the Dairies view only: no view switch, no Counties.
    """
    area = area_params is not None
    year_qs = urlencode({'year': scope.year})
    config = {
        'geojson_url': f"{reverse('api:v2:emissions:dairy-geojson')}?{urlencode({'year': scope.year, **(area_params or {})})}",
        'counties_url': f"{reverse('api:v2:emissions:dairy-counties')}?{urlencode({'year': scope.year, 'pollutant': scope.pollutant.key})}",
        'shapes_url': f"{reverse('api:v2:regions:region-geojson')}?type=county&simplify=1",
        'popup_url': reverse('api:v2:emissions:dairy-detail', args=['__id__']).replace('__id__', '{id}') + f'?{year_qs}',
        'region_url': reverse('emissions:region-redirect', args=['__id__']).replace('__id__', '{id}'),
        # What the popups' links to region pages carry: the scope, less the county.
        'query': urlencode(scope.params(county=None)),
        'county': scope.county.slug if scope.county else '',
        'year': scope.year,
        'label': scope.pollutant.label,
        'unit': scope.pollutant.unit,
        'view': 'dairies' if area else view['view'],
        'measure': view['measure'],
        'source_note': dairies.CEPAM_NOTE,
        # The year CARB's Valley dairy estimate stops changing ('' when it doesn't).
        'flat_since': dairies.flat_since(dairies.emissions_trend(scope.pollutant)) or '',
        # The region or circle the page is about (dairy region pages, near-me).
        'outline_url': outline_url,
        'center': center,
        'zoom': zoom,
        'radius': radius,
        'view_options': () if area else VIEW_OPTIONS,
        'measure_options': MEASURE_OPTIONS,
        # Canonical (small, medium, large) order, whatever order the query named them in.
        'sizes': [value for value, label in SIZE_OPTIONS if value in view['sizes']],
        'digester': view['digester'],
        'size_options': SIZE_OPTIONS,
        'digester_options': DIGESTER_OPTIONS,
    }
    config['size_label'] = (
        'All sizes' if len(config['sizes']) == len(SIZE_OPTIONS)
        else ', '.join(label for value, label in SIZE_OPTIONS if value in config['sizes']) or 'No sizes'
    )
    config['digester_label'] = dict(DIGESTER_OPTIONS)[config['digester']]
    # The options (and the labels built from them) are for the toolbar
    # template, which reads them off map_config; `sizes` goes to the
    # container as a comma-joined string, same as every other data-* value.
    template_only = {'view_options', 'measure_options', 'size_options', 'digester_options', 'size_label', 'digester_label'}
    data = {key.replace('_', '-'): value for key, value in config.items() if key not in template_only}
    # `sizes` is a list above (so the template can test membership); the
    # container wants it the same shape as the `sizes=` URL param.
    data['sizes'] = ','.join(config['sizes'])
    if area:
        # An area page's scope has no county (it's dropped before the scope
        # resolves) and no Counties view to shade by it, so the attribute is
        # left off rather than rendered empty.
        del data['county']
    config['map'] = mapconfig.map_config(
        'dairy-map',
        data=data,
        features={'toolbar': True, 'expand': True, 'legend': True},
        toolbar_template='emissions/includes/dairy-map-toolbar.html',
        # Shared with the facility map (emissions/includes/map-options.html),
        # Tiles only: the dairy colours are the fixed EPA size classes, no
        # ramp to pick.
        options_template='emissions/includes/map-options.html',
        options_ramp=False,
        legend_template='emissions/includes/dairy-map-legend.html',
        container_id='dairy-map',
    )
    return config


class DairyScopeMixin(ScopeMixin):
    """
    A page on the dairies scope: dairies.resolve_scope() (CADD's years, the
    pollutants dairies report, with a note for each fallback), the request's
    GET rewritten to the canonical query so every link built from it carries
    the fallbacks, and the scope bar showing what doesn't apply, disabled.
    """
    section = 'dairies'

    def resolve(self, request):
        self._scope, self.notes = dairies.resolve_scope(request.GET)
        request.GET = canonical_query(request.GET, self._scope)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        known = dairies.years()
        # No CADD years at all yet (before any import): the no-data state
        # covers the page, and the scope bar's year picker has nothing of
        # its own to offer, so it's hidden rather than showing every
        # explorer year as a dead "None" fallback.
        year_options = sorted(set(stats.available_years()) | set(known)) if known else []
        span = f'{known[0]}–{known[-1]}' if known else ''
        params = page_params(scope)
        context = {
            'notes': self.notes,
            'has_data': bool(known),
            'coverage_note': scope.year is not None and scope.year < dairies.COVERAGE_CHANGE_YEAR,
            'coverage_year': dairies.COVERAGE_CHANGE_YEAR,
            'scope_params': params,
            'scope_qs': f'?{urlencode(params)}' if params else '',
            'year_options': year_options,
            'disabled_years': {year: f'CADD has herd data for {span}' for year in year_options if year not in known},
            'pollutant_options': CRITERIA,
            'disabled_pollutants': {
                pollutant.key: f'CARB reports no {pollutant.label} from dairy cattle'
                for pollutant in CRITERIA if pollutant.key not in dairies.POLLUTANT_KEYS
            },
            'disabled_toggles': {
                'toxics': 'CARB reports no toxic air contaminants for dairy cattle',
                'minor': 'Minor sources are small permitted facilities; dairies have none',
            },
            # The methane column/filter/tile are offered only once an
            # import has run (methane.stamp() is None before then).
            'methane_stamp': methane.stamp(),
            'methane_attribution': methane.attribution(),
        }
        context.update(kwargs)
        return super().get_context_data(**context)


class DairyList(DairyScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/dairy-list.html'

    def get(self, request, *args, **kwargs):
        response = self.redirect_to_area(request)
        if response is not None:
            return response
        self.resolve(request)
        if request.GET.get('format') == 'csv':
            scope = self.get_scope()
            return csv_response(dairies.table(scope.year, county=scope.county, **search_filters(request.GET)), f'dairies-{scope.year}.csv')
        return super().get(request, *args, **kwargs)

    def redirect_to_area(self, request):
        """
        ?region= and ?lat=&lng= were the tab's filters; each area has its own
        dairy page now. 301 there with the rest of the query (view=counties
        and page= dropped: the pages have no Counties view and no shared page
        numbering). An unknown region falls back to a valid point, if one was
        also given. An unknown region with no usable point, or a bad point,
        is ignored and the tab renders unfiltered, as it always did.
        """
        get = request.GET
        target = None
        region_won = False
        if get.get('region'):
            region = views.get_filter_region(get['region'], types=AREA_PAGE_TYPES)
            if region is not None:
                target = region.get_emissions_dairies_url()
                region_won = True
        if target is None and ('lat' in get or 'lng' in get):
            if radius_area(get) is not None:
                target = reverse('emissions:near-me-dairies')
        if target is None:
            return None
        params = get.copy()
        params.pop('region', None)
        params.pop('page', None)
        if params.get('view') == 'counties':
            params.pop('view')
        if region_won:
            for key in ('lat', 'lng', 'radius', 'label'):
                params.pop(key, None)
        query = params.urlencode()
        return redirect(target + (f'?{query}' if query else ''), permanent=True)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        filters = search_filters(self.request.GET)
        page = Paginator(dairies.table(scope.year, county=scope.county, **filters), PAGE_SIZE).get_page(self.request.GET.get('page'))
        # The find box: every page type's dairy page, and the county jump
        # links; the links carry the scope less the county (the page is the
        # county), the same as the home page's.
        places = views.find_area_places('emissions:region-dairies')
        return super().get_context_data(
            summary=dairies.summary(scope.year, county=scope.county, methane=filters['methane']),
            rows=page.object_list,
            page_obj=page,
            is_paginated=page.has_other_pages(),
            sort=filters['sort'],
            filters=filters,
            trend=dairies.trend(county=scope.county),
            # CARB's estimate is by county: the scope's county, else all of them.
            emissions_trend=dairies.emissions_trend(scope.pollutant, county=scope.county),
            digester_trend=dairies.digester_chart_points(county=scope.county),
            map_config=dairy_map_config(scope, dairy_map_view(self.request.GET)) if dairies.years() else None,
            find_area_places=places,
            find_area_counties=[p for p in places if p['type'] == Region.Type.COUNTY],
            find_area_qs=scope.query(county=None),
            find_near_url=reverse('emissions:near-me-dairies'),
            maptiler_key=settings.MAPTILER_API_KEY,
            **kwargs,
        )


class DairyAreaPage(DairyScopeMixin, vanilla.TemplateView):
    """
    What a region's and a near-me dairy page share: one area's dairies for
    the resolved year -- the tiles, the map framed on the area, the table
    with its search, sort, pages and CSV, and the charts.
    """
    template_name = 'emissions/dairy-area.html'

    def get(self, request, *args, **kwargs):
        # The page is the area: a stray ?county= would ride along on every
        # link built from request.GET, so drop it before the scope resolves.
        if 'county' in request.GET:
            params = request.GET.copy()
            params.pop('county')
            request.GET = params
        self.resolve(request)
        if request.GET.get('format') == 'csv':
            return csv_response(self.rows(), self.csv_name(self.get_scope().year))
        return super().get(request, *args, **kwargs)

    def get_area(self):
        raise NotImplementedError

    def carb_county(self):
        """The county whose CARB dairy-cattle estimate the page shows (county pages), else None."""
        raise NotImplementedError

    def get_map_config(self, scope):
        raise NotImplementedError

    def csv_name(self, year):
        raise NotImplementedError

    def rows(self):
        return dairies.table(self.get_scope().year, area=self.get_area(), **search_filters(self.request.GET))

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        area = self.get_area()
        county = self.carb_county()
        filters = search_filters(self.request.GET)
        page = Paginator(self.rows(), PAGE_SIZE).get_page(self.request.GET.get('page'))
        summary = dairies.summary(scope.year, area=area, methane=filters['methane'])
        trend = dairies.trend(area=area)
        # [] off county pages and for a pollutant CARB doesn't report (the
        # scope has already fallen back to one it does, so a county page
        # always has the chart when CEPAM has the county).
        emissions_trend = dairies.emissions_trend(scope.pollutant, county=county) if county is not None else []
        this_year = next((row for row in emissions_trend if row['year'] == scope.year), None)
        flat_since = dairies.flat_since(emissions_trend)
        # A region page overrides this with its own "In and around" lists;
        # a near-me page (a point, not a region) has none.
        kwargs.setdefault('within', None)
        return super().get_context_data(
            area=area,
            summary=summary,
            has_dairies=bool(summary['dairies']),
            # The charts stay while any CADD year had a counted herd here (a dairy that closed).
            has_history=bool(trend),
            rows=page.object_list,
            page_obj=page,
            is_paginated=page.has_other_pages(),
            sort=filters['sort'],
            filters=filters,
            trend=trend,
            emissions_trend=emissions_trend,
            digester_trend=dairies.digester_chart_points(area=area),
            carb_estimate={'tons': this_year['value'], 'share': this_year['share'], 'place': county.name, 'flat_since': flat_since if flat_since and scope.year >= flat_since else None} if this_year else None,
            nei_dairy=nei.dairy_tile(county) if county is not None else None,
            hide_county=county is not None,
            map_config=self.get_map_config(scope) if dairies.years() else None,
            # The page is the area: no county picker.
            county_options=[],
            **kwargs,
        )


class RegionDairiesRedirect(views.RegionRedirect):
    """`region/<sqid>/dairies/` -> the slugged dairy page, keeping the query string."""
    url_method = 'get_emissions_dairies_url'


class RegionDairies(views.RegionLookupMixin, DairyAreaPage):
    def region_url(self, region):
        return region.get_emissions_dairies_url()

    def get(self, request, sqid, slug):
        response = self.lookup_region(request, sqid, slug)
        if response is not None:
            return response
        return super().get(request, sqid=sqid, slug=slug)

    def get_area(self):
        return areas.RegionArea(self.region)

    def carb_county(self):
        return self.region if self.region.type == Region.Type.COUNTY else None

    def get_map_config(self, scope):
        return dairy_map_config(
            scope, dairy_map_view(self.request.GET), area_params={'region': self.region.sqid},
            outline_url=reverse('api:v2:regions:region-detail', args=[self.region.sqid]),
        )

    def csv_name(self, year):
        return f'dairies-{self.region.slug}-{year}.csv'

    def get_context_data(self, **kwargs):
        region = self.region
        county = region if region.type == Region.Type.COUNTY else Region.objects.get_county_region(region)
        return super().get_context_data(
            # `name` is the plain heading (h1); `title` (the <title> tag and
            # the breadcrumb) adds the type for a community region.
            name=region_title(region),
            title=region_page_title(region),
            dairies_label=f'in {region_page_title(region)}',
            kind=region.type_label,
            population=(region.metadata or {}).get('population'),
            county_region=county,
            region_page_url=region.get_emissions_url(),
            # Non-county pages point at the county's dairy page for CARB's estimate.
            county_dairies_url=county.get_emissions_dairies_url() if county is not None and county != region else None,
            within=views.region_within_dairies(region),
            **kwargs,
        )


class NearMeDairies(views.NearLookupMixin, DairyAreaPage):
    """The dairy page for a point and a 1, 3 or 5 mile radius (views.NearLookupMixin)."""

    def get(self, request, *args, **kwargs):
        response = self.lookup_near(request)
        if response is not None:
            return response
        return super().get(request, *args, **kwargs)

    def get_area(self):
        return self.near

    def carb_county(self):
        return None

    def get_map_config(self, scope):
        return dairy_map_config(
            scope, dairy_map_view(self.request.GET), area_params=self.near_params_for_api(),
            center=f'{self.near.lat:.4f},{self.near.lng:.4f}', zoom=views.RADIUS_ZOOMS[self.near.radius],
            radius=self.near.radius,
        )

    def near_params_for_api(self):
        """The point without its label: the GeoJSON endpoint doesn't take one."""
        return {key: value for key, value in self.near_params().items() if key != 'label'}

    def csv_name(self, year):
        return f'dairies-near-{self.near.lat:.4f}-{self.near.lng:.4f}-{self.near.radius}-{year}.csv'

    def get_context_data(self, **kwargs):
        title = self.near_title()
        scope = self.get_scope()
        return super().get_context_data(
            name=title,
            title=title,
            dairies_label=self.near_phrase(),
            kind='Near me',
            population=None,
            county_region=None,
            radius_options=self.radius_options(),
            # The emissions near-me page for the breadcrumb: the point, then the page's scope.
            near_page_url=f"{reverse('emissions:near-me')}?{urlencode({**self.near_params(), **page_params(scope)})}",
            privacy_note=True,
            **kwargs,
        )
