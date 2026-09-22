import csv

from urllib.parse import urlencode

from django.conf import settings
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

import vanilla

from camp.apps.emissions import stats
from camp.apps.emissions.models import Facility
from camp.apps.emissions.pollutants import CRITERIA, TOXICS
from camp.apps.regions.models import Region

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
            'section': self.section,
            'hide_scope': self.hide_scope,
        }
        context.update(kwargs)
        return super().get_context_data(**context)


def list_filters(get):
    """The facility table's own filters (beyond the scope), validated."""
    sector = get.get('sector')
    sort = get.get('sort')
    return {
        'sector': sector if sector in Facility.Sector.values else None,
        'district': get.get('district') or None,
        'city': get.get('city') or None,
        'q': (get.get('q') or '').strip() or None,
        'sort': sort if sort in stats.SORTS else '-value',
    }


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
            sector_options=Facility.Sector.choices,
            district_options=(
                Region.objects.filter(type=Region.Type.AIR_DISTRICT, district_facilities__isnull=False)
                .distinct().order_by('name')
            ),
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
        rows = [dict(row, trend=trends.get(row['sector'], [])) for row in stats.sector_breakdown(scope)]
        return super().get_context_data(rows=rows, **kwargs)


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


MAP_STYLE = 'dataviz'


def facility_map_config(scope, *, mode='full', highlight=None, sector=None, params=None):
    """The data-* attributes of a `.facility-map` container (see assets/js/emissions/facility-map.js)."""
    params = dict(params) if params is not None else scope.params()
    if sector:
        params['sector'] = sector
    point = highlight.point if highlight is not None else None
    return {
        'mode': mode,
        'geojson_url': reverse('api:v2:emissions:geojson'),
        'districts_url': reverse('api:v2:emissions:districts'),
        # The covered counties' outlines; the pesticides endpoint serves them for every explorer.
        'counties_url': reverse('api:v2:pesticides:county-list'),
        'query': urlencode(params),
        # The bare-sqid route redirects to the slugged page, so the JS needs no slug.
        'facility_url': reverse('emissions:facility-redirect', args=['__id__']).replace('__id__', '{id}'),
        'maptiler_key': settings.MAPTILER_API_KEY,
        'style': MAP_STYLE,
        'highlight': highlight.sqid if highlight is not None else '',
        'center': f'{point.y},{point.x}' if point is not None else '',
        'zoom': 11 if point is not None else '',
        'label': scope.pollutant.label,
        'unit': scope.pollutant.unit,
        'sector': sector or '',
    }


class MapPage(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/map.html'
    section = 'map'

    def get_context_data(self, **kwargs):
        sector = self.request.GET.get('sector')
        sector = sector if sector in Facility.Sector.values else None
        return super().get_context_data(
            map_config=facility_map_config(self.get_scope(), sector=sector),
            sector_options=Facility.Sector.choices,
            **kwargs,
        )
