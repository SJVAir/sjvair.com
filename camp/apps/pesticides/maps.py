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
from django.urls import reverse
from django.utils.safestring import mark_safe

from camp.apps.regions.models import Region
from camp.utils import leaflet

COUNTY_GEOJSON_KEY = 'pesticides:county-geometries'
COUNTY_GEOJSON_TTL = 60 * 60 * 24
SIMPLIFY_TOLERANCE = 0.005
# Eight steps (ColorBrewer, minus the near-white): one per county, so the
# county map is a straight ranking -- darker is more. Blues is the ramp;
# the others are candidates, selectable with ?ramp=<name> while we pick.
RAMPS = {
    'blues': ['#deebf7', '#c6dbef', '#9ecae1', '#6baed6', '#4292c6', '#2171b5', '#08519c', '#08306b'],
    'purd': ['#f1eef6', '#d4b9da', '#c994c7', '#df65b0', '#e7298a', '#ce1256', '#980043', '#67001f'],
    'bupu': ['#e0ecf4', '#bfd3e6', '#9ebcda', '#8c96c6', '#8c6bb1', '#88419d', '#810f7c', '#4d004b'],
    'ylorbr': ['#fff7bc', '#fee391', '#fec44f', '#fe9929', '#ec7014', '#cc4c02', '#993404', '#662506'],
    'greens': ['#e5f5e0', '#c7e9c0', '#a1d99b', '#74c476', '#41ab5d', '#238b45', '#006d2c', '#00441b'],
    'viridis': ['#fde725', '#b5de2b', '#6ece58', '#35b779', '#1f9e89', '#26828e', '#31688e', '#3e4989'],
}
RAMP = RAMPS['blues']
NO_DATA = '#f0f0f0'
CLASSES = len(RAMP)


def ramp_for(name):
    """A candidate ramp by `?ramp=` name, or the default."""
    return RAMPS.get(name or '', RAMP)

# What the county map and table can rank counties by: by_county row key ->
# the unit its labels say.
COUNTY_METRICS = {'lbs': 'lbs', 'acres': 'acres treated', 'applications': 'applications'}


def county_metric(value):
    """A `?rank=` value narrowed to a known metric (pounds by default)."""
    return value if value in COUNTY_METRICS else 'lbs'


def rank_counties(by_county, metric='lbs', ramp=None):
    """
    `by_county` rows sorted by `metric`, most to least (name breaks ties),
    each with a `color` (the map's fill for it) so a table beside the map
    can carry the swatches. No-data rows sort last.
    """
    metric = county_metric(metric)
    rows = sorted(by_county, key=lambda row: (-(row.get(metric) or 0), row['county_name']))
    classes = quantile_classes({row['county_id']: (row.get(metric) or 0) for row in rows}, ramp=ramp)
    return [{**row, 'color': classes.color_for(row.get(metric) or 0)} for row in rows]


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


def quantile_classes(values_by_key, classes=CLASSES, ramp=None):
    """
    Build QuantileClasses from a {key: pounds} mapping. Zero/None values are
    treated as no data and excluded. The number of classes is the smaller of
    `classes` and the number of distinct positive values, and the darkest
    ramp color is always assigned to the top class.
    """
    ramp = ramp or RAMP
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
        colors = [ramp[-1]]
    else:
        colors = [ramp[round(i * (len(ramp) - 1) / (count - 1))] for i in range(count)]

    result = QuantileClasses(breaks=breaks, colors=colors, members=[[] for _ in breaks])
    for value in values:
        result.members[result.index_for(value)].append(value)
    return result


def county_map(by_county, width=600, height=420, query='', metric='lbs', ramp=None):
    """
    The county choropleth, shaded by `metric` (see COUNTY_METRICS) as a
    ranking: darker is more. Each county links to its page; `query` (a scope
    query string such as 'year=2020') is carried on those links. The table
    beside it (rank_counties) is the legend.
    """
    geometries = county_geometries()
    if not geometries:
        return None
    metric = county_metric(metric)
    unit = COUNTY_METRICS[metric]
    counties = {region.pk: region for region in Region.objects.filter(pk__in=geometries)}
    value_by_pk = {row['county_id']: (row.get(metric) or 0) for row in by_county}
    classes = quantile_classes(value_by_pk, ramp=ramp)

    lmap = leaflet.LeafletMap(width=width, height=height, padding=10)
    for pk, geojson in geometries.items():
        county = counties[pk]
        value = value_by_pk.get(pk)
        label = f'{county.name}: {int(round(value)):,} {unit}' if value else f'{county.name}: no data'
        url = reverse('pesticides:region', kwargs={'sqid': county.sqid, 'slug': county.slug})
        lmap.add(leaflet.Area(
            geometry=GEOSGeometry(geojson, srid=4326),
            fill_color=classes.color_for(value),
            fill_opacity=0.75,
            border_color='#555',
            border_width=1,
            label=label,
            label_on_hover=True,
            url=f'{url}?{query}' if query else url,
        ))
    return mark_safe(lmap.render())
