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
from camp.apps.emissions import areas, compliance, dairies, ghg, methane, nei, schools, stats, wells
from camp.apps.emissions.models import AirComplianceFacility, Facility, SourceImport, Well
from camp.apps.emissions.pollutants import CRITERIA, PRECURSORS
from camp.apps.regions import nearby
from camp.apps.regions import schools as region_schools
from camp.apps.regions import shapes
from camp.apps.regions.models import Location, Region
from camp.utils import mapconfig

# The "In and around <place>" lists (camp.apps.regions.nearby), linked with
# emissions pages; separate cache namespace from the pesticides explorer's,
# since the two link different pages.
WITHIN_KEY = 'emissions:within:v1'


def region_within(region):
    # ab617=True: the emissions explorer's "In and around" lists an AB 617
    # community a region overlaps (and, on an AB 617 page, the city/county
    # it's in) -- the pesticides explorer, sharing nearby.regions_within(),
    # doesn't have AB 617 pages and leaves this off.
    return nearby.regions_within(region, url_method='get_emissions_url', cache_prefix=WITHIN_KEY, ab617=True)


# The dairy region pages' own lists, linking other areas' dairy pages.
WITHIN_DAIRIES_KEY = 'emissions:within-dairies:v1'


def region_within_dairies(region):
    return nearby.regions_within(region, url_method='get_emissions_dairies_url', cache_prefix=WITHIN_DAIRIES_KEY)


PAGE_SIZE = 50
SECTOR_PAGE_ROWS = 25
METHANE_LIST_ROWS = 25
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


def page_of(rows, raw):
    """
    A list's page for `?page=` (PAGE_SIZE rows): Paginator.get_page's, except
    a zero or negative page goes to the first rather than the last, as the
    pesticides explorer's lists do (NearestPageMixin). Junk is page 1, a page
    past the end the last.
    """
    try:
        if int(raw) < 1:
            raw = 1
    except (TypeError, ValueError):
        pass
    return Paginator(rows, PAGE_SIZE).get_page(raw)


def sector_options():
    """Sectors A–Z for the pickers, the catch-all "Other" last."""
    return sorted(Facility.Sector.choices, key=lambda choice: (choice[0] == Facility.Sector.OTHER, choice[1]))


def list_filters(get):
    """The facility table's own filters (beyond the scope), validated."""
    sector = get.get('sector')
    sort = get.get('sort')
    compliance_value = get.get('compliance')
    return {
        'sector': sector if sector in Facility.Sector.values else None,
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
        top_sectors = reporting_sectors(scope)[:6]
        return super().get_context_data(
            totals=totals,
            total=totals['value'],
            context_bar=stats.county_context(scope),
            nei_context=nei.context(scope),
            toxics_breakdown=stats.toxics_breakdown(scope) if scope.toxics else None,
            top_sectors=top_sectors,
            facility_board=facility_board(scope),
            sector_board=sector_board(scope, top_sectors),
            by_year=stats.by_year(scope),
            find_area_places=find_area_places(),
            find_area_counties=[p for p in find_area_places() if p['type'] == Region.Type.COUNTY],
            find_area_ab617=[p for p in find_area_places() if p['type'] == Region.Type.AB617_COMMUNITY],
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
        # ?region= was the list's place filter; a place has its own Facilities tab now.
        region = get_filter_region(request.GET.get('region'), types=AREA_PAGE_TYPES)
        if region is not None:
            query = request.GET.copy()
            for name in ('region', 'page'):
                query.pop(name, None)
            encoded = query.urlencode()
            return redirect(region.get_emissions_tab_url('facilities') + (f'?{encoded}' if encoded else ''), permanent=True)
        if request.GET.get('format') == 'csv':
            return self.csv_response()
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        filters = list_filters(self.request.GET)
        places = find_area_places('emissions:region-facilities')
        page = page_of(stats.facility_table(scope, **filters), self.request.GET.get('page'))
        return super().get_context_data(
            rows=stats.with_ranks(page.object_list, stats.ranks(scope)),
            page_obj=page,
            is_paginated=page.has_other_pages(),
            sort=filters['sort'],
            filters=filters,
            sector_options=sector_options(),
            compliance_options=compliance.FILTER_LABELS,
            # "Find your area", the filter box's first field: a place's own Facilities tab.
            find_field=True,
            find_area_places=places,
            find_area_counties=[p for p in places if p['type'] == Region.Type.COUNTY],
            find_area_qs=scope.query(county=None),
            find_near_url=reverse('emissions:near-me-facilities'),
            maptiler_key=settings.MAPTILER_API_KEY,
            **kwargs,
        )

    def csv_response(self):
        scope = self.get_scope()
        return facility_csv(scope, stats.facility_table(scope, **list_filters(self.request.GET)), f'facility-emissions-{scope.year}.csv')


def area_geometry(area):
    """An area's shape: a region's boundary or a radius's circle."""
    region = getattr(area, 'region', None)
    return region.boundary.geometry if region is not None else area.geometry


def oil_gas_methane_in(area):
    """methane.oil_gas_sources() inside the area (a few hundred Valley-wide, so tested in Python); all of them for the Valley."""
    if isinstance(area, areas.ValleyArea):
        return methane.oil_gas_sources()
    shape = area_geometry(area)
    return [row for row in methane.oil_gas_sources() if shape.contains(row['source'].point)]


def wells_csv(wells_qs, filename):
    """A wells table (wells.table) as a CSV download: the Oil & gas tab's."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(['api', 'lease', 'well_number', 'status', 'well_type', 'operator', 'field', 'county', 'spud_date',
                     'health_protection_zone', 'latitude', 'longitude', 'calgem_url'])
    for well in wells_qs.select_related('county'):
        writer.writerow([well.api, well.lease_name, well.well_number, well.status, well.well_type_label, well.operator_name,
                         well.field_name, well.county.name, well.spud_date or '', well.in_hpz,
                         f'{well.point.y:.5f}', f'{well.point.x:.5f}', well.calgem_url])
    return response


def sites_csv(rows, scope, filename):
    """The Schools tab's sites (schools.area_sites rows) as CSV, the pollutant's column named for the scope."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    unit = 'share' if scope.pollutant.unit == 'share' else f'{scope.pollutant.unit}_per_year'
    writer.writerow([
        'name', 'type', 'latitude', 'longitude', 'facilities_within_1000ft', 'facilities_within_quarter_mile',
        f'{scope.pollutant.key}_{unit}_within_quarter_mile_{scope.year}', 'wells_within_3200ft', 'dairies_within_1_mile',
    ])
    for row in rows:
        writer.writerow([
            row['name'], row['type_label'], f"{row['lat']:.5f}", f"{row['lng']:.5f}", row['notice'], row['quarter'],
            '' if row['value'] is None else row['value'], row['wells'], row['dairies'],
        ])
    return response


def facility_csv(scope, records, filename):
    """A facility table (stats.facility_table records) as a CSV download: the list's and an area's Facilities tab's."""
    rank_map = stats.ranks(scope)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
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
    for record in records:
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


# The facility page's toxics table: the rest behind "Show all".
TOXICS_SHOWN = 10


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
        ranks = stats.facility_ranks(facility, shown_year)
        ghg_card = ghg.facility_card(facility)
        # The toxics, and the largest by cancer-weighted share for the stat row.
        toxics_rows = stats.facility_toxics(facility, shown_year)
        weighted = [row for row in toxics_rows if row['has_cancer_value'] and row['share']]
        trend = stats.by_year(scope, facility=facility)
        return super().get_context_data(
            facility=facility,
            # The stat row: the page's pollutant for this facility (its row
            # in the ranks table, None if it reported none) and its newest
            # greenhouse-gas report.
            headline=next((row for row in ranks if row['pollutant'].key == scope.pollutant.key and row['value']), None),
            ghg_latest=ghg_card[0] if ghg_card else None,
            district=facility.air_district,
            shown_year=shown_year,
            # Pollutants it reported get a row; the rest are named in one line under the table.
            ranks=[row for row in ranks if row['value']],
            unreported=[row['pollutant'] for row in ranks if not row['value']],
            trend=trend,
            # The trend chart only when the page's pollutant is a criteria one this facility has reported.
            show_trend=not scope.pollutant.toxic and any(point['value'] for point in trend),
            toxics_rows=toxics_rows,
            top_toxic=max(weighted, key=lambda row: row['share']) if weighted else None,
            toxics_shown=TOXICS_SHOWN,
            changes=stats.large_changes(facility, shown_year),
            hot_spots=stats.hot_spots(record),
            health_values=SourceImport.latest('contable'),
            area_links=area_links(facility_regions),
            facility_ces=ces_stats.tract_record(tract),
            ab617_region=areas.facility_ab617_region(facility),
            compliance_card=compliance.facility_card(facility),
            ghg_card=ghg_card,
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
        rows = stats.with_ranks(table[:SECTOR_PAGE_ROWS], stats.ranks(scope))
        return super().get_context_data(
            sector=self.sector,
            summary=summary,
            trend=stats.by_year(scope, sector=self.sector),
            counties=stats.county_breakdown(scope, sector=self.sector),
            rows=rows,
            columns=dict(uniform_columns(rows), hide_sector=True),
            facility_count=table.count(),
            map_config=facility_map_config(
                scope, mode='compact', sector=self.sector, fit=True,
                # Facilities only, a dataset page: the wells and methane
                # sources have the Oil & gas tab (OilGasPage).
            ),
            oil_gas_url=reverse('emissions:oil-gas') + scope.query(county=None) if self.sector == Facility.Sector.OIL_GAS else None,
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
    (an area's Oil & gas tab, the oil-gas sector page), off elsewhere;
    ?wells=1|0 overrides either way so the state can be shared.
    """
    raw = get.get('wells')
    on = raw == '1' if raw in ('0', '1') else default
    return {'on': on, 'default': default}


def is_kern(region):
    """Kern County's page: its Oil & gas tab carries the oil & gas facilities' callout."""
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


# The area tabs whose map has the Areas view (a facility choropleth): the
# ones about facilities.
AREAS_VIEW_TABS = ('overview', 'facilities')


def area_tab_layers(get, tab, scope, *, area_params, nearby=None):
    """
    An area tab's map layers (facility_map_config kwargs): each dataset page
    maps only its dataset and what goes with it. The Overview has them all,
    as the main map does (locations_layers), the wells a checkbox away (Kern's
    66,000 are too many to load by default); Facilities, only facilities; Oil
    & gas, only the wells and methane, both on; Schools, the sites with the
    facilities, and the wells one checkbox away (both are what it counts near
    a site).
    """
    if tab == 'oil-gas':
        return {'main_layer': None, 'wells': wells_overlay(get, default=True), 'methane': methane_overlay(get, default=True)}
    if tab == 'facilities':
        return {}
    if tab == 'schools':
        return {'wells': wells_overlay(get), 'nearby': nearby}
    return {
        'wells': wells_overlay(get), 'methane': methane_overlay(get, default=True),
        'locations': locations_layers(get, scope, area_params=area_params),
    }


def methane_overlay(get, *, default=False):
    """
    The maps' Methane sources (Carbon Mapper) overlay: nothing (None) until
    an import has run; else off unless the page says otherwise, with
    ?methane=1|0 overriding either way so the state can be shared.
    """
    if not methane.enabled():
        return None
    raw = get.get('methane')
    on = raw == '1' if raw in ('0', '1') else default
    return {'on': on, 'default': default}


def locations_layers(get, scope, *, area_params=None):
    """
    The main map's and an area Overview's locations layers (facility-map.js's
    locations mode): every point the same size, a hue per dataset and shades
    for each one's own scale. Dairies (CADD's year nearest the scope's;
    `area_params`, a region's sqid or a point, narrows them to the area) and
    schools and child care, both on unless ?dairies=0 / ?schools=0.
    """
    known = dairies.years()
    year = scope.year if scope.year in known else (known[-1] if known else None)
    return {
        'locations': '1',
        'dairies_url': f"{reverse('api:v2:emissions:dairy-geojson')}?{urlencode({'year': year, **(area_params or {})})}" if year else '',
        'dairy_popup_url': reverse('api:v2:emissions:dairy-detail', args=['__id__']).replace('__id__', '{id}') + f'?{urlencode({"year": year})}' if year else '',
        'dairies': '' if get.get('dairies') == '0' else '1',
        'schools_url': with_query(reverse('api:v2:emissions:schools-geojson'), area_params),
        'schools': '' if get.get('schools') == '0' else '1',
        # A school's popup links its own Schools tab: a mile around it.
        'school_near_url': reverse('emissions:near-me-schools'),
    }


def with_query(url, params):
    """`url` with `params` as its query string, or bare without any."""
    query = urlencode(params or {})
    return f'{url}?{query}' if query else url


def area_map_params(area, buffer=0):
    """An area page's map data URLs' area: a region's sqid (and ?buffer= past it), or a near-me point and radius."""
    if isinstance(area, areas.RadiusArea):
        return {'lat': f'{area.lat:.4f}', 'lng': f'{area.lng:.4f}', 'radius': area.radius}
    return {'region': area.region.sqid, **({'buffer': buffer} if buffer else {})}


def methane_map_data(overlay, area_params=None):
    """The data-* values both map configs carry for the overlay; empty strings when it isn't offered. `area_params` limits it to an area page's area."""
    if not overlay:
        return {
            'methane_url': '', 'methane_plumes_url': '', 'methane': '',
            'methane_default': '',
        }
    return {
        'methane_url': with_query(reverse('api:v2:emissions:methane-geojson'), area_params),
        'methane_plumes_url': reverse('api:v2:emissions:methane-plumes', args=['__id__']).replace('__id__', '{id}'),
        'methane': '1' if overlay['on'] else '',
        'methane_default': '1' if overlay['default'] else '',
    }


HOME_BOARD_ROWS = 5


def series(points):
    """A by-year series' values in year order, for a sparkline."""
    return [row['value'] for row in sorted(points, key=lambda row: row['year'])]


def facility_board(scope):
    """The home page's top facilities card: each one's link, its value and its by-year line."""
    return [
        {'label': record.facility.name, 'url': record.facility.get_absolute_url(), 'value': record.value,
         'series': series(stats.by_year(scope, facility=record.facility))}
        for record in stats.facility_table(scope)[:HOME_BOARD_ROWS]
    ]


def sector_board(scope, rows):
    """The home page's top sectors card, from reporting_sectors() rows, with each sector's line and share."""
    trends = stats.sector_trends(scope)
    return [
        {'label': row['label'], 'url': reverse('emissions:sector-detail', args=[row['sector']]), 'value': row['value'],
         'share': row['share'], 'series': series(trends.get(row['sector'], []))}
        for row in rows[:HOME_BOARD_ROWS]
    ]


def uniform_columns(rows):
    """
    The facility table's columns to hide because every row says the same
    thing (a city page's City, a county page's County): {'hide_city': bool,
    'hide_county': bool}. Decided from the rows, not the page type, since a
    school district or a ZIP can cross a county line.
    """
    facilities = [record.facility for _, record in rows]
    cities = {facility.city_id or (facility.address.get('city') or '').lower() for facility in facilities}
    counties = {facility.county_id for facility in facilities}
    return {'hide_city': len(facilities) > 1 and len(cities) == 1, 'hide_county': len(facilities) > 1 and len(counties) == 1}


def reporting_sectors(scope):
    """sector_breakdown() without the sectors that reported none of the pollutant (a row of 0.0 and 0%)."""
    return [row for row in stats.sector_breakdown(scope) if row['value']]


def facility_map_config(scope, *, mode='full', highlight=None, sector=None, params=None, areas_view=None,
                        outline_url='', center='', zoom='', radius='', nearby=None, wells=None, methane=None, fit=False,
                        main_layer=True, locations=None, area_params=None, buffer_options=None):
    """
    The data-* attributes of a `.facility-map` container (see
    assets/js/emissions/facility-map.js). `nearby` is a FeatureCollection
    (schools.geojson) for the facility page's schools-and-child-care overlay,
    or None. `wells` (views.wells_overlay's return, or None) offers the Oil &
    gas wells overlay and its initial state; None (a facility's own map)
    leaves it off with no URL at all. `methane` (views.methane_overlay's
    return, or None) offers the Methane sources (Carbon Mapper) overlay the
    same way. `area_params` (area_map_params) limits every layer's points to
    an area page's area, perhaps widened (?buffer=); `buffer_options` are
    the region page toolbar's choices for how far past the boundary.
    """
    params = dict(params) if params is not None else scope.params()
    if sector:
        params['sector'] = sector
    point = highlight.point if highlight is not None else None
    config = {
        'mode': mode,
        'geojson_url': reverse('api:v2:emissions:geojson'),
        # The air district lines: on the Valley-wide maps only, not an area
        # page's or a facility's own (they're about one place).
        'districts_url': reverse('api:v2:emissions:districts') if area_params is None and highlight is None else '',
        # The covered counties' outlines, from the regions API.
        'counties_url': f"{reverse('api:v2:regions:region-geojson')}?type=county",
        'query': urlencode(params),
        # An area page's area, for the data URLs only (the query above also
        # builds facility and region links, which mustn't carry it).
        'area_query': urlencode(area_params or {}),
        # The widened edge to draw, when the map reaches past the area.
        # (the shared regions detail endpoint, ?buffer= widening its boundary)
        'buffer_url': with_query(reverse('api:v2:regions:region-detail', args=[area_params['region']]), {'buffer': area_params['buffer']}) if (area_params or {}).get('buffer') else '',
        # The bare-sqid route redirects to the slugged page, so the JS needs no slug.
        'facility_url': reverse('emissions:facility-redirect', args=['__id__']).replace('__id__', '{id}'),
        'maptiler_key': settings.MAPTILER_API_KEY,
        'style': mapconfig.MAP_STYLE,
        'highlight': highlight.sqid if highlight is not None else '',
        # Where to pin the highlighted facility (a facility page), lng,lat.
        # Frame the loaded facilities rather than the Valley (a sector page).
        'fit': '1' if fit else '',
        # The facilities layer: on (''), offered but off ('0'), or not on this
        # map at all ('none': an Oil & gas map, only wells and methane).
        'main_layer': 'none' if main_layer is None else ('' if main_layer else '0'),
        'highlight_point': f'{point.x:.5f},{point.y:.5f}' if point is not None else '',
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
        'wells_url': with_query(reverse('api:v2:emissions:wells-geojson'), area_params) if wells else '',
        'well_url': reverse('api:v2:emissions:well-detail', args=['__id__']).replace('__id__', '{id}') if wells else '',
        'wells': '1' if wells and wells['on'] else '',
        'wells_default': '1' if wells and wells['default'] else '',
        # The Methane sources (Carbon Mapper) overlay (methane.py): offered
        # where `methane` is set, including a facility's own map -- unlike
        # wells, a nearby plume is relevant there.
        **methane_map_data(methane, area_params),
        # The main map's and Overviews' locations layers (locations_layers), or none.
        **(locations or {'locations': '', 'dairies_url': '', 'schools_url': ''}),
        # The facility page's schools and child care within 1/4 mile (a
        # FeatureCollection, JSON in the attribute) and the ring to draw.
        'nearby': json.dumps(nearby) if nearby else '',
        # The ring is the facility page's 1/4 mile; an area's Schools tab has none.
        'ring_miles': schools.QUARTER_MILE_FT / schools.FEET_PER_MILE if nearby and highlight is not None else '',
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
    config['buffer_options'] = buffer_options or []
    template_only = {'sector', 'sector_label', 'level_options', 'measure_options', 'compare_options', 'disabled_measures', 'buffer_options'}
    config['map'] = mapconfig.map_config(
        'facility-map',
        data={key.replace('_', '-'): value for key, value in config.items() if key not in template_only},
        features={'toolbar': True, 'expand': True, 'legend': True},
        toolbar_template='emissions/includes/map-toolbar.html' if mode == 'full' or areas_view or buffer_options else None,
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
                # Every location, the 66,000 wells a checkbox away.
                wells=wells_overlay(self.request.GET),
                methane=methane_overlay(self.request.GET, default=True),
                locations=locations_layers(self.request.GET, scope),
            ),
            sector_options=sector_options(),
            **kwargs,
        )


AREA_PAGE_TYPES = (
    Region.Type.COUNTY, *Region.COMMUNITY_TYPES, Region.Type.ZIPCODE,
    Region.Type.SCHOOL_DISTRICT, Region.Type.TRACT, Region.Type.AB617_COMMUNITY,
)
# The search box lists every page type but tracts: a tract's name is its GEOID.
# Each community layer (city, urban area, CDP) is listed as-is, labelled, so
# "Fresno" is both "Fresno · City" and "Fresno · Urban area".
FIND_AREA_TYPE_LABELS = {
    Region.Type.COUNTY: 'County',
    **Region.COMMUNITY_LABELS,
    Region.Type.ZIPCODE: 'ZIP',
    Region.Type.SCHOOL_DISTRICT: 'School district',
    Region.Type.AB617_COMMUNITY: 'AB 617 community',
}
# :v2 -- the synthetic places are gone; a list cached before then must not be served.
FIND_AREA_PLACES_KEY = f'emissions:v{stats.CACHE_VERSION}:find-area-places:v3'
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
    community region (city, urban area, CDP) or an AB 617 community --
    Fresno the city and Fresno the urban area otherwise both read as plain
    "Fresno" in a browser tab or a breadcrumb, where the page's own heading
    line (type · county · population) isn't visible; Shafter the city and
    Shafter the AB 617 community share a name the same way. Counties, ZIPs,
    tracts, and school districts are already unambiguous on their own. The
    visible h1 stays the plain name (AreaPage's `name`).
    """
    name = region_title(region)
    if region.type in Region.COMMUNITY_TYPES or region.type == Region.Type.AB617_COMMUNITY:
        return f'{name} ({region.type_label})'
    return name


def ab617_notice(region):
    """
    The top-of-page notice on an AB 617 community's own page (its metadata,
    from import_ab617_communities: cerp_selected_year, community_url,
    storymaps_url), or None off one.
    """
    if region.type != Region.Type.AB617_COMMUNITY:
        return None
    metadata = region.metadata or {}
    return {
        'year': metadata.get('cerp_selected_year') or '',
        'community_url': metadata.get('community_url') or '',
        'storymaps_url': metadata.get('storymaps_url') or '',
    }


def area_header(context):
    """
    What the shared area-page templates (regions/area-tab.html and
    regions/includes/area-header.html) take beyond the page's own context,
    from an area page's or its dairy page's context: the grey line under the
    name (its kind, an AB 617 community's selection year, the county a
    smaller area sits in, its population), an AB 617 community's links, the
    breadcrumb before the tab and the explorer's base template.
    """
    region = getattr(context['area'], 'region', None)
    county = context.get('county_region')
    ab617 = context.get('ab617')
    population = context.get('population')
    in_county = county is not None and county != region
    kind = [context['kind']]
    if ab617 and ab617['year']:
        kind.append(f"selected by CARB in {ab617['year']}")
    if in_county:
        kind.append(county.name)
    if population:
        kind.append(f'{round(float(population)):,} people')
    links = []
    if ab617 and ab617['community_url']:
        links.append({'label': 'Community page', 'url': ab617['community_url']})
    if ab617 and ab617['storymaps_url']:
        links.append({'label': 'CARB story map', 'url': ab617['storymaps_url']})
    crumbs = [{'label': county.name, 'url': county.get_emissions_url() + context.get('scope_qs', '')}] if in_county else []
    crumbs.append({'label': context['title'], 'url': context['overview_url']})
    return {
        'kind': ' · '.join(kind), 'header_links': links, 'area_crumbs': crumbs, 'explorer_base': 'emissions/base.html',
        'tab_links': pesticides_tab_links(context),
    }


# An emissions tab and the pesticides tab for the same thing; any other opens its Overview.
PESTICIDES_TABS = {'schools': 'schools', 'community': 'community'}


def pesticides_tab_links(context):
    """
    The tab row's right-aligned link to the same place in the pesticides
    explorer (regions/includes/area-header.html's `tab_links`): a region it
    has pages for, or the same point and radius. None for a region it has no
    page for (a census tract).
    """
    from camp.apps.pesticides.places import PLACE_REGION_TYPES

    area = context['area']
    tab = PESTICIDES_TABS.get(context.get('tab'))
    region = getattr(area, 'region', None)
    if region is not None:
        if region.type not in PLACE_REGION_TYPES:
            return []
        url = region.get_pesticides_tab_url(tab) if tab else region.get_pesticides_url()
    else:
        view = context.get('view')
        params = view.near_params() if hasattr(view, 'near_params') else {
            'lat': f'{area.lat:.4f}', 'lng': f'{area.lng:.4f}', 'radius': area.radius,
        }
        url = f"{reverse(f'pesticides:near-me-{tab}' if tab else 'pesticides:near-me')}?{urlencode(params)}"
    return [{'label': 'Pesticides', 'url': url, 'icon': 'fa-spray-can-sparkles', 'icon_class': 'is-products'}]


def with_tract_urls(community):
    """A CalEnviroScreen summary (ces.stats.tract_summary) with each tract row linking its page here, for regions/includes/community-card.html."""
    if not community:
        return community
    def linked(row):
        return dict(row, url=row['region'].get_emissions_url()) if row else row
    return dict(
        community, highest=linked(community.get('highest')), lowest=linked(community.get('lowest')),
        containing=linked(community.get('containing')), top=[linked(row) for row in community.get('top') or []],
    )


def area_links(regions):
    """The facility page's "Area" line: each region it counts in, labelled, linking to its page."""
    labels = {Region.Type.ZIPCODE: 'ZIP {}'}
    return [{
        'label': labels.get(region.type, '{}').format(region_title(region)),
        'url': region.get_emissions_url(),
    } for region in regions]


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


# An area page's tabs, in order. Overview is the page itself; Dairies is its
# dairy page (dairy_views); the rest are this module's *Facilities, *OilGas
# and *Community views. A tab shows only where the area has something for it.
# Each with its Font Awesome icon and explorer-icon colour class, the same
# as the explorer's own tabs (base.html) and In and around's headings.
AREA_TABS = (
    ('overview', 'Overview', 'fa-map', 'is-map'),
    ('facilities', 'Facilities', 'fa-industry-windows', 'is-facilities'),
    ('dairies', 'Dairies', 'fa-cow', 'is-dairies'),
    ('oil-gas', 'Oil & gas', 'fa-oil-well', 'is-wells'),
    ('schools', 'Schools', 'fa-school', 'is-schools'),
    ('community', 'Community', 'fa-city', 'is-chemicals'),
)


def area_tabs(view, area, current):
    """
    The tab row for an area page or its dairy page: [{key, label, icon,
    icon_class, url, current}]. `view` provides area_tab_url(key, query), tab_query(key) and
    has_community(); the current tab always shows.
    """
    available = {
        'overview': True,
        'facilities': True,
        'dairies': bool(dairies.years()) and bool(dairies.trend(area=area)),
        'oil-gas': wells.area_summary(area) is not None,
        'schools': Location.objects.filter(wells.location_q(area)).exists(),
        'community': view.has_community(),
    }
    return [
        {'key': key, 'label': label, 'icon': icon, 'icon_class': icon_class,
         'url': view.area_tab_url(key, view.tab_query(key)), 'current': key == current}
        for key, label, icon, icon_class in AREA_TABS if available[key] or key == current
    ]


class OilGasTabMixin:
    """
    An Oil & gas tab's context, an area's (AreaPage) or the whole Valley's
    (OilGasPage): the wells table, filters, pages and CSV; drilling by year
    and wells by type; the operators and fields with the most wells; the
    area's oil & gas permit groupings; and the oil & gas methane sources.
    The view provides area_tab_url(key, query) and tab_query(key), so the
    leader rows and the table's links stay on the page they're on.
    """

    def well_leaders(self, area):
        """wells.leaders() as rank-card rows, each linking this tab filtered to it."""
        query = self.tab_query('oil-gas')
        def rows(name, param):
            return [
                {'label': row['label'], 'value': row['count'],
                 'url': self.area_tab_url('oil-gas', '&'.join(filter(None, [query, urlencode({param: row['label']})])))}
                for row in leaders[name]
            ]
        leaders = wells.leaders(area)
        return {'operators': rows('operators', 'operator'), 'fields': rows('fields', 'field')}

    def oil_gas_context(self, area, scope, *, facilities_url):
        well_filters = wells.table_filters(self.request.GET)
        well_page = page_of(wells.table(area, **well_filters), self.request.GET.get('page'))
        return dict(
            page_obj=well_page, is_paginated=well_page.has_other_pages(), well_rows=well_page.object_list,
            sort=well_filters['sort'], filters=well_filters, well_options=wells.filter_options(area),
            status_options=Well.Status.choices, spud=wells.spud_by_year(area), well_types=wells.by_type(area),
            oil_gas_card=[
                {'label': record.facility.name, 'url': record.facility.get_absolute_url(), 'value': record.value}
                for record in stats.facility_table(scope, sector=Facility.Sector.OIL_GAS)[:5]
            ],
            well_leaders=self.well_leaders(area),
            oil_gas_facilities_url=facilities_url,
            methane_oil_gas=oil_gas_methane_in(area) if methane.enabled() else None,
            methane_list_rows=METHANE_LIST_ROWS,
            # An area's list drops the County column; the Valley's keeps it.
            methane_list_here=not isinstance(area, areas.ValleyArea),
        )


class AreaPage(OilGasTabMixin, ScopeMixin, vanilla.TemplateView):
    """
    What a region page and near-me share: one area's page, one tab of it
    (`tab`, AREA_TABS) -- Overview's totals, map, sectors and trend, or the
    Facilities, Oil & gas or Community tab -- under the same header and tab row.
    """
    template_name = 'emissions/area.html'
    tab = 'overview'

    def get(self, request, *args, **kwargs):
        # The page is the area: a stray ?county= would ride along on the
        # scope-picker links (built from request.GET), so drop it here.
        if 'county' in request.GET:
            params = request.GET.copy()
            params.pop('county')
            request.GET = params
        if self.tab == 'facilities' and request.GET.get('format') == 'csv':
            return self.facilities_csv()
        if self.tab == 'oil-gas' and request.GET.get('format') == 'csv':
            return wells_csv(wells.table(self.get_area(), **wells.table_filters(request.GET)), f'wells-{self.csv_slug()}.csv')
        if self.tab == 'schools' and request.GET.get('format') == 'csv':
            scope = self.area_scope()
            rows = schools.area_sites(self.get_area(), scope, **schools.site_filters(request.GET))
            return sites_csv(rows, scope, f'schools-{self.csv_slug()}-{scope.year}.csv')
        return super().get(request, *args, **kwargs)

    def area_scope(self):
        """The page's scope narrowed to its area, county-free (the page is the area)."""
        base = self.get_scope()
        return stats.Scope(year=base.year, county=None, pollutant=base.pollutant, minor=base.minor, area=self.get_area())

    def area_filters(self):
        """The Facilities tab's filters: the facility list's, less its region (the page is the area)."""
        return {key: value for key, value in list_filters(self.request.GET).items() if key != 'area'}

    def facilities_csv(self):
        scope = self.area_scope()
        return facility_csv(scope, stats.facility_table(scope, **self.area_filters()), f'facility-emissions-{self.csv_slug()}-{scope.year}.csv')

    def csv_slug(self):
        raise NotImplementedError

    def point_params(self):
        """The query parameters that say where the page is (near-me's point); none for a region."""
        return {}

    def get_area(self):
        raise NotImplementedError

    def get_county(self):
        """The county the page's share is of."""
        raise NotImplementedError

    def get_map_config(self, scope):
        raise NotImplementedError

    def tab_query(self, key):
        """A tab link's query: the scope, or for Dairies the dairy page's (CADD's year)."""
        base = self.get_scope()
        if key == 'dairies':
            known = dairies.years()
            return dairy_page_query(base, base.year if base.year in known else (known[-1] if known else base.year))
        return base.query(county=None).lstrip('?')

    def get_context_data(self, **kwargs):
        base = self.get_scope()
        area = self.get_area()
        tab = self.tab
        scope = self.area_scope()
        summary = compliance.area_summary(scope) if tab == 'facilities' else None
        compliance_line = dict(summary, url=self.area_tab_url('facilities', '&'.join(filter(None, [self.tab_query('facilities'), 'compliance=hpv'])))) if summary else None
        totals = stats.totals(scope)
        total = totals['value'] or 0
        county = self.get_county()
        county_scope = stats.Scope(year=base.year, county=county, pollutant=base.pollutant, minor=base.minor)
        county_total = stats.totals(county_scope)['value'] if county and tab in ('overview', 'facilities') else None
        if tab == 'facilities':
            # The facility list's table, filters, sorts, pages and CSV, for the area.
            filters = self.area_filters()
            table = stats.facility_table(scope, **filters)
            page = page_of(table, self.request.GET.get('page'))
            top_rows = stats.with_ranks(page.object_list, stats.ranks(scope))
            kwargs.update(
                page_obj=page, is_paginated=page.has_other_pages(), sort=filters['sort'], filters=filters,
                sector_options=sector_options(), compliance_options=compliance.FILTER_LABELS,
                reporting=stats.facility_table(scope).filter(value__gt=0).count(),
            )
        elif tab == 'oil-gas':
            kwargs.update(self.oil_gas_context(
                area, scope,
                facilities_url=self.area_tab_url('facilities', '&'.join(filter(None, [self.tab_query('facilities'), 'sector=oil-gas']))),
            ))
            top_rows = []
        elif tab == 'schools':
            # Every school and child-care center in the area with what's near it:
            # the table (filtered, sorted, paged, CSV), the stat row (unfiltered)
            # and the sites on the map.
            site_filters = schools.site_filters(self.request.GET)
            all_sites = schools.area_sites(area, scope)
            sites = schools.filter_sites(all_sites, **site_filters)
            site_page = page_of(sites, self.request.GET.get('page'))
            region = getattr(area, 'region', None)
            # The districts the area overlaps, beside the map; not on a district's own page.
            districts = [] if region is not None and region.type == Region.Type.SCHOOL_DISTRICT else region_schools.area_districts(
                area.geometry if region is None else region.boundary.geometry,
                cache_key=f'emissions:area-districts:v1:{area.key}', url_method='get_emissions_url',
            )
            kwargs.update(
                page_obj=site_page, is_paginated=site_page.has_other_pages(), site_rows=site_page.object_list,
                sort=site_filters['sort'], filters=site_filters, site_summary=schools.site_summary(all_sites),
                site_count=len(sites), site_types=[('school', 'Schools'), ('child-care', 'Child care')],
                sites_filtered=bool(site_filters['q'] or site_filters['type'] or site_filters['district'] or site_filters['near']),
                site_districts=schools.district_options(all_sites),
                school_districts=districts, districts_hidden=sum(1 for d in districts if d['is_collapsed']),
            )
            self.site_geojson = schools.sites_geojson(all_sites)
            top_rows = []
        elif tab == 'overview':
            top_rows = stats.with_ranks(stats.facility_table(scope)[:5], stats.ranks(scope))
        else:
            top_rows = []
        top_sectors = reporting_sectors(scope) if tab in ('overview', 'facilities') else []
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
        # The AB 617 top-of-page notice (RegionPage sets it on an AB 617
        # community's own page); a near-me page has none.
        kwargs.setdefault('ab617', None)
        context = super().get_context_data(
            area=area,
            county_region=county,
            totals=totals,
            total=total,
            per_sq_mi=total / area.sq_miles if area.sq_miles else None,
            county_share=total / county_total if county_total else None,
            tab=tab,
            tab_label=dict((key, label) for key, label, *_ in AREA_TABS)[tab],
            tabs=area_tabs(self, area, tab),
            overview_url=self.area_tab_url('overview', self.tab_query('overview')),
            # A tab's own form keeps the page's point (near-me) and clears to the tab, scope kept.
            point_params=self.point_params(),
            clear_filters_url=self.area_tab_url(tab, self.tab_query(tab)),
            facilities_tab_url=self.area_tab_url('facilities', self.tab_query('facilities')),
            top_rows=top_rows,
            top_columns=uniform_columns(top_rows),
            top_sectors=top_sectors,
            # The Overview's two cards (rank-card.html): five facilities, every sector.
            facility_card=[
                {'label': record.facility.name, 'url': record.facility.get_absolute_url(), 'value': record.value}
                for _, record in top_rows[:5]
            ] if tab == 'overview' else [],
            sector_card=[
                {'label': row['label'], 'url': reverse('emissions:sector-detail', args=[row['sector']]), 'value': row['value'], 'share': row['share']}
                for row in top_sectors
            ],
            by_year=stats.by_year(scope) if tab in ('overview', 'facilities') else [],
            sector_stack=stats.sector_stack(scope) if tab == 'overview' else None,
            map_config=self.get_map_config(base) if tab in ('overview', 'facilities', 'oil-gas', 'schools') else None,
            compliance_line=compliance_line,
            toxics_breakdown=stats.toxics_breakdown(scope) if scope.toxics and tab == 'overview' else None,
            share_unit=scope.pollutant.unit == 'share',
            # The page is the area: no county picker, and the scope links
            # leave the county out.
            county_options=[],
            scope_qs=base.query(county=None),
            scope_params=base.params(county=None),
            **kwargs,
            community_about_url=reverse('emissions:about') + '#calenviroscreen',
        )
        context.update(area_header(context))
        context['community'] = with_tract_urls(context['community'])
        return context


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

    def area_tab_url(self, key, query):
        url = self.region.get_emissions_tab_url(key)
        return f'{url}?{query}' if query else url

    def has_community(self):
        """The Community tab: CalEnviroScreen and In and around both need the boundary."""
        return bool(self.region.boundary_id)

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

    def csv_slug(self):
        return self.region.slug

    def get_county(self):
        if self.region.type == Region.Type.COUNTY:
            return self.region
        return Region.objects.get_county_region(self.region)

    def get_map_config(self, scope):
        buffer = areas.buffer_param(self.request.GET)
        area_params = area_map_params(areas.RegionArea(self.region), buffer)
        level = areas.NEXT_LEVEL.get(self.region.type)
        return facility_map_config(
            scope, mode='compact', params=scope.params(county=None),
            areas_view=map_view(self.request.GET, level, year=scope.year, share=scope.pollutant.unit == 'share') if level and self.tab in AREAS_VIEW_TABS else None,
            outline_url=reverse('api:v2:regions:region-detail', args=[self.region.sqid]),
            # Every layer limited to the region, or a mile or three past it.
            area_params=area_params, buffer_options=shapes.buffer_options(self.request, buffer),
            **area_tab_layers(self.request.GET, self.tab, scope, area_params=area_params, nearby=getattr(self, 'site_geojson', None)),
        )

    def get_context_data(self, **kwargs):
        region = self.region
        tab = self.tab
        extra = {}
        if region.type == Region.Type.COUNTY:
            # The context bar names `county`; on a county page that's the page's own.
            extra['county'] = region
        if tab == 'community':
            if region.type == Region.Type.TRACT:
                extra['tract_ces'] = ces_stats.tract_record(region)
            elif region.boundary_id:
                extra['community'] = ces_stats.tract_summary(region.boundary.geometry)
                extra['show_top_tracts'] = region.type == Region.Type.COUNTY
            extra['within'] = region_within(region) if region.boundary_id else None
        if tab == 'oil-gas':
            extra['wells_block'] = wells_block(areas.RegionArea(region), self.get_scope(), kern=is_kern(region))
        extra['ab617'] = ab617_notice(region)
        county_scope = stats.Scope(
            year=self.get_scope().year, county=region, pollutant=self.get_scope().pollutant, minor=self.get_scope().minor,
        ) if region.type == Region.Type.COUNTY and tab == 'overview' else None
        return super().get_context_data(
            # `name` is the plain heading (h1); `title` (the <title> tag and
            # the breadcrumb, which have no identifiers line under them to
            # disambiguate) adds the type for a community region.
            name=region_title(region),
            title=region_page_title(region),
            tab_title_suffix=f'in {region_page_title(region)}',
            kind=region.type_label,
            population=(region.metadata or {}).get('population'),
            context_bar=stats.county_context(county_scope) if county_scope else None,
            context_trend=stats.county_context_trend(county_scope) if county_scope else [],
            nei_context=nei.context(county_scope) if county_scope else None,
            ghg_table=ghg.county_table(region) if region.type == Region.Type.COUNTY and tab == 'facilities' else None,
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

    # AREA_TABS key -> URL name.
    TAB_URLS = {
        'overview': 'emissions:near-me', 'facilities': 'emissions:near-me-facilities', 'dairies': 'emissions:near-me-dairies',
        'oil-gas': 'emissions:near-me-oil-gas', 'schools': 'emissions:near-me-schools', 'community': 'emissions:near-me-community',
    }

    def area_tab_url(self, key, query):
        """The tab for the same point: the point's parameters, then the tab's query."""
        point = urlencode(self.near_params())
        return f'{reverse(self.TAB_URLS[key])}?{point}' + (f'&{query}' if query else '')

    def has_community(self):
        return True

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

    def csv_slug(self):
        return f'near-{self.near.lat:.4f}-{self.near.lng:.4f}-{self.near.radius}'

    def point_params(self):
        return self.near_params()

    def get_county(self):
        return self.county

    def get_map_config(self, scope):
        return facility_map_config(
            scope, mode='compact', params=scope.params(county=None),
            areas_view=map_view(self.request.GET, Region.Type.TRACT, year=scope.year, share=scope.pollutant.unit == 'share') if self.tab in AREAS_VIEW_TABS else None,
            center=f'{self.near.lat:.4f},{self.near.lng:.4f}', zoom=RADIUS_ZOOMS[self.near.radius],
            radius=self.near.radius,
            area_params=area_map_params(self.near),
            **area_tab_layers(self.request.GET, self.tab, scope, area_params=area_map_params(self.near), nearby=getattr(self, 'site_geojson', None)),
        )

    def get_context_data(self, **kwargs):
        # Not a region, so nothing to disambiguate with a type -- `name`
        # (the h1) and `title` (the <title> tag and breadcrumb) are the same.
        title = self.near_title()
        return super().get_context_data(
            name=title,
            title=title,
            tab_title_suffix=self.near_phrase(),
            kind='Near me',
            population=None,
            context_bar=None,
            radius_options=self.radius_options(),
            community=ces_stats.tract_summary(self.near.geometry) if self.tab == 'community' else None,
            wells_block=wells_block(self.near, self.get_scope()) if self.tab == 'oil-gas' else None,
            **kwargs,
        )


# An area page's other tabs (AREA_TABS): the same views on another tab.

class RegionFacilities(RegionPage):
    tab = 'facilities'
    template_name = 'emissions/area-facilities.html'


class RegionOilGas(RegionPage):
    tab = 'oil-gas'
    template_name = 'emissions/area-oil-gas.html'


class RegionSchools(RegionPage):
    tab = 'schools'
    template_name = 'emissions/area-schools.html'


class RegionCommunity(RegionPage):
    tab = 'community'


class NearMeFacilities(NearMe):
    tab = 'facilities'
    template_name = 'emissions/area-facilities.html'


class NearMeOilGas(NearMe):
    tab = 'oil-gas'
    template_name = 'emissions/area-oil-gas.html'


class NearMeSchools(NearMe):
    tab = 'schools'
    template_name = 'emissions/area-schools.html'


class NearMeCommunity(NearMe):
    tab = 'community'



class OilGasPage(OilGasTabMixin, ScopeMixin, vanilla.TemplateView):
    """
    The top-level Oil & gas tab: an area's Oil & gas tab (area-oil-gas.html)
    for every covered county at once (areas.ValleyArea), with the wells and
    methane overlays on, Kern's callout, and a find box into an area's own
    tab. The oil & gas sector page stays about the permit groupings' emissions.
    """
    template_name = 'emissions/oil-gas.html'
    section = 'oil-gas'

    def get(self, request, *args, **kwargs):
        scope = self.get_scope()
        if scope.county is not None:
            # A county picked in the scope bar is that county's own tab.
            return redirect(scope.county.get_emissions_tab_url('oil-gas') + scope.query(county=None))
        if request.GET.get('format') == 'csv':
            return wells_csv(wells.table(areas.ValleyArea(), **wells.table_filters(request.GET)), 'wells-valley.csv')
        return super().get(request, *args, **kwargs)

    def tab_query(self, key):
        return self.get_scope().query(county=None).lstrip('?')

    def area_tab_url(self, key, query):
        url = reverse('emissions:oil-gas')
        return f'{url}?{query}' if query else url

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        area = areas.ValleyArea()
        places = find_area_places('emissions:region-oil-gas')
        with_wells = set(Well.objects.values_list('county__name', flat=True).distinct())
        sector_url = reverse('emissions:sector-detail', args=[Facility.Sector.OIL_GAS]) + scope.query(county=None)
        return super().get_context_data(
            **self.oil_gas_context(area, scope, facilities_url=sector_url),
            area=area,
            # The shared area-tab skeleton and header (regions/area-tab.html).
            explorer_base='emissions/base.html', area_crumbs=[], tab_label='Oil & gas',
            name='San Joaquin Valley', kind='All covered counties',
            header_links=[], tabs=[], tab_links=[],
            wells_block=wells_block(area, scope, kern=True),
            map_config=facility_map_config(
                scope, mode='compact', params=scope.params(county=None),
                wells=wells_overlay(self.request.GET, default=True), main_layer=None,
                methane=methane_overlay(self.request.GET, default=True),
            ),
            point_params={}, clear_filters_url=self.area_tab_url('oil-gas', self.tab_query('oil-gas')),
            scope_qs=scope.query(county=None), scope_params=scope.params(county=None), county_options=[],
            find_field=True,
            find_area_places=places,
            find_area_counties=[p for p in places if p['type'] == Region.Type.COUNTY and p['name'] in with_wells],
            find_area_qs=scope.query(county=None),
            find_near_url=reverse('emissions:near-me-oil-gas'),
            maptiler_key=settings.MAPTILER_API_KEY,
            **kwargs,
        )
