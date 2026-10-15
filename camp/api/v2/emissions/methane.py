"""
The public API side of Carbon Mapper's methane data (camp/apps/emissions/methane.py
does the reading, models.py the licence text): the sources GeoJSON the maps'
overlay used to fetch same-origin, plus a source's plumes for the popup's
image stepper. Carbon Mapper's terms are non-commercial with share-alike
redistribution, so every response here carries MethaneSource.ATTRIBUTION and
LICENSE -- the terms require it on every rendering, this one included.
"""
from django.contrib.gis.geos import Point
from django.http import Http404
from resticus import generics, http

from camp.apps.emissions import methane
from camp.apps.emissions.models import MethaneSource
from camp.utils.views import CachedEndpointMixin

from .mapareas import get_shape


class MethaneCachedEndpointMixin(CachedEndpointMixin):
    """Response caching that a Carbon Mapper import (methane.clear_caches) invalidates."""

    def get_view_cache_key(self):
        return f'{super().get_view_cache_key()}|g:{methane.generation()}'


class MethaneGeoJSONBase(generics.Endpoint):
    # get() lives on this un-cached base so the mixin's get() on the
    # subclass is the one dispatched to (the explorer endpoints' pattern).
    def get(self, request):
        if not methane.enabled():
            raise Http404('No methane sources imported.')
        collection = methane.collection()
        # An area page's map: only the sources inside its (perhaps widened) area.
        shape, _, error = get_shape(request)
        if error:
            return http.Http400({'error': error})
        if shape is not None:
            inside = shape.prepared
            collection = dict(collection, features=[
                feature for feature in collection['features'] if inside.contains(Point(*feature['geometry']['coordinates'], srid=4326))
            ])
        return collection


class MethaneGeoJSON(MethaneCachedEndpointMixin, MethaneGeoJSONBase):
    """
    Every CH4 source Carbon Mapper has published for the covered counties,
    as GeoJSON points for the map overlay: sector group, Carbon Mapper's
    rate estimate and uncertainty, and detection counts; ?region= or
    ?lat=&lng=&radius= (with ?buffer=) narrows them to an area page's. The
    collection's properties carry MethaneSource.ATTRIBUTION and LICENSE.
    404 until an import has run. Cached a day; a re-import
    (methane.clear_caches) invalidates it.
    """
    cache_timeout = 60 * 60 * 24


class SourcePlumesBase(generics.Endpoint):
    def get(self, request, sqid):
        source = MethaneSource.objects.filter(sqid=sqid, gas=MethaneSource.Gas.CH4).first()
        if source is None:
            raise Http404('No such methane source.')
        return methane.source_plumes(source)


class SourcePlumes(MethaneCachedEndpointMixin, SourcePlumesBase):
    """
    One source's plumes (Carbon Mapper detections), newest first: platform,
    instrument, rate/uncertainty (+ `rate_text`), wind speed/direction, and
    `bounds` as the 4 corner coordinates ([[minlon,maxlat],[maxlon,maxlat],
    [maxlon,minlat],[minlon,minlat]]) a MapLibre image source wants for
    draping the plume PNG, plus `image_url` (the stored image's URL, null
    when there isn't one yet). 404 for an unknown source. Cached under the
    methane generation; a re-import invalidates it.
    """
    cache_timeout = 60 * 60 * 24
