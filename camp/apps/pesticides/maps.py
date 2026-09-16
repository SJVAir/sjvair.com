"""
County choropleth for the pesticides explorer, built on camp.utils.leaflet.
County boundaries are simplified and cached because the raw multipolygons
run to thousands of points each; simplified, all eight fit in ~33 KB.
"""
import math

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.cache import cache

from camp.apps.regions.models import Region
from camp.utils import leaflet

COUNTY_GEOJSON_KEY = 'pesticides:county-geometries'
COUNTY_GEOJSON_TTL = 60 * 60 * 24
SIMPLIFY_TOLERANCE = 0.005
RAMP = ['#deebf7', '#9ecae1', '#6baed6', '#3182bd', '#08519c']
NO_DATA = '#f0f0f0'


def _build_county_geometries():
    data = {}
    regions = Region.objects.filter(type=Region.Type.COUNTY, boundary__isnull=False).select_related('boundary')
    for region in regions:
        geometry = region.boundary.geometry
        if geometry.srid and geometry.srid != 4326:
            geometry = geometry.transform(4326, clone=True)
        simplified = geometry.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
        if simplified.geom_type != 'MultiPolygon':
            simplified = MultiPolygon(simplified)
        data[region.pk] = simplified.geojson
    return data


def county_geometries():
    data = cache.get(COUNTY_GEOJSON_KEY)
    if data is None:
        data = _build_county_geometries()
        cache.set(COUNTY_GEOJSON_KEY, data, COUNTY_GEOJSON_TTL)
    return data


def ramp_color(value, maximum):
    if not value or not maximum:
        return NO_DATA
    step = math.ceil(value / maximum * len(RAMP)) - 1
    return RAMP[max(0, min(step, len(RAMP) - 1))]


def county_map(by_county, year=None, width=600, height=420):
    geometries = county_geometries()
    if not geometries:
        return None
    names = dict(Region.objects.filter(pk__in=geometries).values_list('pk', 'name'))
    lbs_by_pk = {row['county_id']: (row['lbs'] or 0) for row in by_county}
    maximum = max(lbs_by_pk.values(), default=0)

    lmap = leaflet.LeafletMap(width=width, height=height, padding=10)
    for pk, geojson in geometries.items():
        lbs = lbs_by_pk.get(pk)
        label = f'{names[pk]}: {int(round(lbs)):,} lbs' if lbs else f'{names[pk]}: no data'
        lmap.add(leaflet.Area(
            geometry=GEOSGeometry(geojson, srid=4326),
            fill_color=ramp_color(lbs, maximum),
            fill_opacity=0.75,
            border_color='#555',
            border_width=1,
            label=label,
        ))
    return lmap.render()
