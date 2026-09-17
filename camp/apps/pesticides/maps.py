"""
County choropleth for the pesticides explorer, built on camp.utils.leaflet.

County boundaries are simplified and cached because the raw multipolygons
run to thousands of points each; simplified, all eight fit in ~33 KB.

Shading uses quantile classes rather than equal steps of the maximum:
pounds by county are heavily skewed, and equal steps would put one county in
the darkest bin and everyone else in the lightest. Quantiles rank the
counties so the whole ramp is always used; the legend shows the real pound
range each shade covers so close-but-different shades are not misread. The
ramp is single-hue, sequential, and luminance-monotonic (colorblind and
grayscale safe); no-data counties are drawn grey and kept out of the classes.
"""
import math
from dataclasses import dataclass, field

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.cache import cache
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from camp.apps.regions.models import Region
from camp.utils import leaflet

COUNTY_GEOJSON_KEY = 'pesticides:county-geometries'
COUNTY_GEOJSON_TTL = 60 * 60 * 24
SIMPLIFY_TOLERANCE = 0.005
RAMP = ['#deebf7', '#9ecae1', '#6baed6', '#3182bd', '#08519c']
NO_DATA = '#f0f0f0'
CLASSES = len(RAMP)


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


@dataclass
class QuantileClasses:
    """
    Quantile classification of positive values. `breaks[i]` is the upper
    bound (inclusive) of class i; `colors[i]` is its fill. Classes are cut on
    distinct values, so ties always share a class and there is never an
    empty class.
    """
    breaks: list = field(default_factory=list)
    colors: list = field(default_factory=list)
    members: list = field(default_factory=list)   # per class: sorted member values

    def index_for(self, value):
        for i, upper in enumerate(self.breaks):
            if value <= upper:
                return i
        return len(self.breaks) - 1

    def color_for(self, value):
        if not value or not self.breaks:
            return NO_DATA
        return self.colors[self.index_for(value)]

    def legend(self):
        return [
            {'color': self.colors[i], 'low': values[0], 'high': values[-1]}
            for i, values in enumerate(self.members)
        ]


def quantile_classes(values_by_key, classes=CLASSES):
    """
    Build QuantileClasses from a {key: pounds} mapping. Zero/None values are
    treated as no data and excluded. The number of classes is the smaller of
    `classes` and the number of distinct positive values, and the darkest
    ramp color is always assigned to the top class.
    """
    values = sorted(v for v in values_by_key.values() if v)
    distinct = sorted(set(values))
    if not distinct:
        return QuantileClasses()
    count = min(classes, len(distinct))

    breaks = []
    for i in range(1, count + 1):
        position = math.ceil(i * len(distinct) / count) - 1
        breaks.append(distinct[position])

    # Spread the chosen class count across the ramp, always ending on the darkest.
    if count == 1:
        colors = [RAMP[-1]]
    else:
        colors = [RAMP[round(i * (len(RAMP) - 1) / (count - 1))] for i in range(count)]

    result = QuantileClasses(breaks=breaks, colors=colors, members=[[] for _ in breaks])
    for value in values:
        result.members[result.index_for(value)].append(value)
    return result


def county_map(by_county, width=600, height=420):
    geometries = county_geometries()
    if not geometries:
        return None
    names = dict(Region.objects.filter(pk__in=geometries).values_list('pk', 'name'))
    lbs_by_pk = {row['county_id']: (row['lbs'] or 0) for row in by_county}
    classes = quantile_classes(lbs_by_pk)

    lmap = leaflet.LeafletMap(width=width, height=height, padding=10)
    for pk, geojson in geometries.items():
        lbs = lbs_by_pk.get(pk)
        label = f'{names[pk]}: {int(round(lbs)):,} lbs' if lbs else f'{names[pk]}: no data'
        lmap.add(leaflet.Area(
            geometry=GEOSGeometry(geojson, srid=4326),
            fill_color=classes.color_for(lbs),
            fill_opacity=0.75,
            border_color='#555',
            border_width=1,
            label=label,
        ))
    legend = render_to_string('pesticides/includes/county-legend.html', {
        'legend': classes.legend(),
        'no_data': NO_DATA,
    })
    return mark_safe(lmap.render() + legend)
