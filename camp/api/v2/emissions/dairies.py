from resticus import generics, http

from camp.apps.emissions import areas, dairies
from camp.apps.emissions.models import Dairy
from camp.apps.emissions.pollutants import POLLUTANTS
from camp.apps.emissions.views import AREA_PAGE_TYPES, area_links, get_filter_region, radius_area
from camp.utils.views import CachedEndpointMixin


def get_year(request):
    """(year, error): ?year= when CADD covers it, CADD's latest when it's left out, else an error message."""
    raw = (request.GET.get('year') or '').strip()
    if not raw:
        return dairies.latest_year(), None
    known = dairies.years()
    try:
        year = int(raw)
    except ValueError:
        year = None
    if year not in known:
        span = f'{known[0]}–{known[-1]}' if known else 'none yet'
        return None, f'year must be one CADD has herd data for ({span}).'
    return year, None


def get_pollutant(request):
    raw = (request.GET.get('pollutant') or '').strip() or dairies.DEFAULT_POLLUTANT
    if raw not in dairies.POLLUTANT_KEYS:
        return None, f"pollutant must be one of {', '.join(dairies.POLLUTANT_KEYS)}: CARB reports no NOx, SOx, CO or toxics for dairy cattle."
    return POLLUTANTS[raw], None


class DairyCachedEndpointMixin(CachedEndpointMixin):
    """Response caching that a re-import (dairies.clear_caches) invalidates."""

    def get_view_cache_key(self):
        return f'{super().get_view_cache_key()}|g:{dairies.generation()}'


def get_area(request):
    """
    (area, error): a RegionArea for ?region= (any region page type with a
    boundary: the dairy region pages' map), a RadiusArea for
    ?lat=&lng=&radius= (the near-me dairy page's), (None, None) with neither;
    an unknown region or a bad point is an error message.
    """
    sqid = (request.GET.get('region') or '').strip()
    if sqid:
        region = get_filter_region(sqid, types=AREA_PAGE_TYPES)
        if region is None:
            return None, 'region must be the id of a county, community, ZIP code, school district or census tract with a page.'
        return areas.RegionArea(region), None
    if 'lat' in request.GET or 'lng' in request.GET:
        near = radius_area(request.GET)
        if near is None:
            return None, 'lat and lng must be a point, and radius 1, 3 or 5 (miles).'
        return near, None
    return None, None


class DairyGeoJSONBase(generics.Endpoint):
    # get() lives on this un-cached base so the mixin's get() on the subclass
    # is the one dispatched to (the explorer endpoints' pattern).
    def get(self, request):
        year, error = get_year(request)
        if error:
            return http.Http400({'error': error})
        area, error = get_area(request)
        if error:
            return http.Http400({'error': error})
        features = []
        for herd in dairies.table(year, area=area):
            dairy = herd.dairy
            features.append({
                'type': 'Feature',
                'id': dairy.sqid,
                'geometry': {'type': 'Point', 'coordinates': [round(dairy.point.x, 5), round(dairy.point.y, 5)]},
                'properties': {
                    'id': dairy.sqid,
                    'name': dairy.name,
                    'mature_cows': herd.mature_cows,
                    'other_cattle': herd.other_cattle,
                    'size_class': herd.size_class,
                    'digester': bool(herd.digester),
                    'county': dairy.county.slug,
                },
            })
        return {
            'type': 'FeatureCollection',
            'properties': {'year': year, 'size_classes': dairies.size_classes()},
            'features': features,
        }


class DairyGeoJSON(DairyCachedEndpointMixin, DairyGeoJSONBase):
    """
    The year's dairies (CADD, a counted herd) as GeoJSON points: mature dairy
    cows, other cattle and the EPA size class, whether a digester ran that
    year, and the county slug; the collection's properties carry the size
    classes' labels and thresholds for a legend. ?year= defaults to CADD's latest.
    ?region=<sqid> or ?lat=&lng=&radius= narrows to the area's dairies only,
    by the region pages' membership rule (RegionArea.dairy_q() / RadiusArea.dairy_q()).
    """
    cache_timeout = 60 * 60 * 24
    # v3 -- a response cached under ?region= before this change was unfiltered.
    cache_key_version = 3


class DairyCountiesBase(generics.Endpoint):
    def get(self, request):
        year, error = get_year(request)
        if error:
            return http.Http400({'error': error})
        pollutant, error = get_pollutant(request)
        if error:
            return http.Http400({'error': error})
        measure = (request.GET.get('measure') or '').strip() or dairies.DEFAULT_MEASURE
        if measure not in dairies.MEASURES:
            return http.Http400({'error': f"measure must be one of {', '.join(dairies.MEASURES)}."})
        return {
            'year': year,
            'pollutant': pollutant.key,
            'label': pollutant.label,
            'unit': pollutant.unit,
            'measure': measure,
            'source': dairies.CEPAM_NOTE,
            'counties': [dict(row, value=row[measure]) for row in dairies.county_values(year, pollutant)],
        }


class DairyCounties(DairyCachedEndpointMixin, DairyCountiesBase):
    """
    Per covered county: CARB's dairy cattle emissions (CEPAM, tons/yr, and per
    square mile) and CADD's mature dairy cows (total and per square mile), plus
    `value` for ?measure=. ?year= (CADD's), ?pollutant= (rog, pm, pm10, tog).
    """
    cache_timeout = 60 * 60 * 24
    cache_key_version = 2


class DairyDetail(generics.Endpoint):
    """One dairy for a map popup: its herd by class in ?year=, its digesters, and the region pages it counts in."""

    def get(self, request, sqid):
        dairy = Dairy.objects.filter(sqid=sqid).select_related('county').first()
        if dairy is None:
            return http.Http404({'error': 'No such dairy.'})
        year, error = get_year(request)
        if error:
            return http.Http400({'error': error})
        herd = dairy.herds.filter(year=year).first() if year is not None else None
        return {
            'id': dairy.sqid,
            'name': dairy.name,
            'address': dairy.address,
            'county': dairy.county.name,
            'year': year,
            'herd': None if herd is None else {
                'mature_cows': herd.mature_cows,
                'other_cattle': herd.other_cattle,
                'size_class': herd.size_class,
                'size_label': herd.get_size_class_display(),
                'classes': [{
                    'key': field,
                    'label': label,
                    'count': getattr(herd, field),
                    'estimated': herd.estimated(field),
                } for field, label in dairies.HERD_CLASSES],
            },
            'digesters': [{
                'operational_year': digester.operational_year,
                'shutdown_year': digester.shutdown_year,
                'source': digester.source,
                'operating': digester.operating_in(year) if year is not None else False,
            } for digester in dairy.digesters.order_by('operational_year')],
            'areas': area_links(dairies.dairy_areas(dairy)),
            'grants': [{
                'project_name': g.project_name,
                'amount': float(g.grant_amount) if g.grant_amount is not None else None,
                'awarded_year': g.awarded.year if g.awarded else None,
                'end_use': g.end_use,
                'reduction': g.est_reduction_tco2e,
            } for g in dairy.grants.all()],
        }
