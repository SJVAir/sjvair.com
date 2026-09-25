"""
The Dairies tab: CARB's dairy database (CADD) on a map, in a table and as a
trend for the scope's year and county, beside CARB's county dairy-cattle
emissions. The scope options that don't apply to dairies stay in the scope
bar, disabled (emissions/includes/scope-picker.html).
"""
import csv
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.urls import reverse

import vanilla

from camp.apps.emissions import areas, dairies, stats, views
from camp.apps.emissions.models import HERD_FIELDS
from camp.apps.emissions.pollutants import CRITERIA
from camp.apps.emissions.views import AREA_PAGE_TYPES, ScopeMixin, radius_area, radius_label, region_title
from camp.apps.regions.models import Region
from camp.utils import mapconfig

PAGE_SIZE = 50
# The table's region filter: every region page type but county (the scope's
# county picker is that), so each region page's "All dairies here" works.
FILTER_TYPES = tuple(region_type for region_type in AREA_PAGE_TYPES if region_type != Region.Type.COUNTY)
NEAR_KEYS = ('lat', 'lng', 'radius', 'label')
VIEW_OPTIONS = (('dairies', 'Dairies'), ('counties', 'Counties'))
MEASURE_OPTIONS = (
    ('emissions', 'Dairy emissions'),
    ('emissions_per_sq_mi', 'Dairy emissions per sq mi'),
    ('mature_cows', 'Mature dairy cows'),
    ('mature_cows_per_sq_mi', 'Mature dairy cows per sq mi'),
)


def table_filters(get):
    """The table's own filters, validated: a name search, a region (by point) or else near-me's radius, and the sort."""
    region = views.get_filter_region(get.get('region'), types=FILTER_TYPES)
    sort = get.get('sort')
    return {
        'area': areas.RegionArea(region) if region else radius_area(get),
        'q': (get.get('q') or '').strip() or None,
        'sort': sort if sort in dairies.TABLE_SORTS else dairies.DEFAULT_SORT,
    }


def near_label(get, area):
    """The radius filter's tag: 'Within 1 mi of Tower District'."""
    if not isinstance(area, areas.RadiusArea):
        return None
    return f'Within {area.radius} mi of {radius_label(get, area.lat, area.lng)}'


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
    """The map's view and measure from a request's GET, validated; defaults when unknown."""
    view = get.get('view')
    measure = get.get('measure')
    return {
        'view': view if view in dairies.VIEWS else dairies.DEFAULT_VIEW,
        'measure': measure if measure in dairies.MEASURES else dairies.DEFAULT_MEASURE,
    }


def dairy_map_config(scope, view):
    """The data-* attributes of the Dairies tab's `.dairy-map` (see assets/js/emissions/dairy-map.js)."""
    year_qs = urlencode({'year': scope.year})
    config = {
        'geojson_url': f"{reverse('api:v2:emissions:dairy-geojson')}?{year_qs}",
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
        'view': view['view'],
        'measure': view['measure'],
        'source_note': dairies.CEPAM_NOTE,
        'view_options': VIEW_OPTIONS,
        'measure_options': MEASURE_OPTIONS,
    }
    # The options are for the toolbar template, which reads them off map_config.
    template_only = {'view_options', 'measure_options'}
    config['map'] = mapconfig.map_config(
        'dairy-map',
        data={key.replace('_', '-'): value for key, value in config.items() if key not in template_only},
        features={'toolbar': True, 'expand': True, 'legend': True},
        toolbar_template='emissions/includes/dairy-map-toolbar.html',
        legend_template='emissions/includes/dairy-map-legend.html',
        container_id='dairy-map',
    )
    return config


class DairyList(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/dairy-list.html'
    section = 'dairies'

    def get(self, request, *args, **kwargs):
        self._scope, self.notes = dairies.resolve_scope(request.GET)
        # The fallbacks are the page's scope: every link built from the query
        # (the scope bar, sort headers, pages, the CSV) carries them.
        request.GET = canonical_query(request.GET, self._scope)
        if request.GET.get('format') == 'csv':
            return self.csv_response()
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        known = dairies.years()
        filters = table_filters(self.request.GET)
        area = filters['area']
        rows = dairies.table(scope.year, county=scope.county, **filters)
        page = Paginator(rows, PAGE_SIZE).get_page(self.request.GET.get('page'))
        # No CADD years at all yet (before any import): the no-data state
        # covers the page, and the scope bar's year picker has nothing of
        # its own to offer, so it's hidden rather than showing every
        # explorer year as a dead "None" fallback.
        year_options = sorted(set(stats.available_years()) | set(known)) if known else []
        span = f'{known[0]}–{known[-1]}' if known else ''
        params = page_params(scope)
        near = isinstance(area, areas.RadiusArea)
        return super().get_context_data(
            notes=self.notes,
            has_data=bool(known),
            summary=dairies.summary(scope.year, county=scope.county),
            rows=page.object_list,
            page_obj=page,
            is_paginated=page.has_other_pages(),
            sort=filters['sort'],
            filters=filters,
            region={'sqid': area.region.sqid, 'name': region_title(area.region)} if isinstance(area, areas.RegionArea) else None,
            near=near_label(self.request.GET, area),
            near_params={key: self.request.GET[key] for key in NEAR_KEYS if key in self.request.GET} if near else {},
            trend=dairies.trend(county=scope.county),
            coverage_note=scope.year is not None and scope.year < dairies.COVERAGE_CHANGE_YEAR,
            coverage_year=dairies.COVERAGE_CHANGE_YEAR,
            map_config=dairy_map_config(scope, dairy_map_view(self.request.GET)) if known else None,
            scope_params=params,
            scope_qs=f'?{urlencode(params)}' if params else '',
            # The scope bar: what doesn't apply to dairies is shown, disabled.
            # (year_options is [] with no CADD data yet, so this is naturally {}.)
            year_options=year_options,
            disabled_years={year: f'CADD has herd data for {span}' for year in year_options if year not in known},
            pollutant_options=CRITERIA,
            disabled_pollutants={
                pollutant.key: f'CARB reports no {pollutant.label} from dairy cattle'
                for pollutant in CRITERIA if pollutant.key not in dairies.POLLUTANT_KEYS
            },
            disabled_toggles={
                'toxics': 'CARB reports no toxic air contaminants for dairy cattle',
                'minor': 'Minor sources are small permitted facilities; dairies have none',
            },
            **kwargs,
        )

    def csv_response(self):
        scope = self.get_scope()
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="dairies-{scope.year}.csv"'
        writer = csv.writer(response)
        writer.writerow(
            ['cadd_id', 'dairy', 'id', 'street', 'city', 'zipcode', 'county', 'year']
            + list(HERD_FIELDS)
            + ['mature_cows', 'other_cattle', 'size_class']
            + ['milk_cows_ref_code', 'non_milking_ref_code', 'digester_operating', 'digester_since']
        )
        for herd in dairies.table(scope.year, county=scope.county, **table_filters(self.request.GET)):
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
