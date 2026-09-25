"""
County choropleth for the pesticides explorer, built on camp.utils.mapfigure.

County boundaries are simplified and cached because the raw multipolygons
run to thousands of points each; simplified, all eight fit in ~33 KB.

Shading uses quantile classes rather than equal steps of the maximum:
pounds by county are heavily skewed, and equal steps would put one county in
the darkest bin and everyone else in the lightest. Quantiles rank the
counties so the whole ramp is always used; the legend shows the real pound
range each shade covers so close-but-different shades are not misread. The
ramp is single-hue, sequential, and luminance-monotonic (colorblind and
grayscale safe); no-data counties are drawn grey and kept out of the classes.

Comparing two years shades the change instead, which needs a diverging ramp
(diverging_classes): the magnitudes are quantiled and mirrored around zero so
equal changes up and down get equal saturation. Those ramps can't be
luminance-monotonic -- both ends are dark and the middle is light -- so hue
alone carries the direction, and a greyscale print loses the sign. There are
three states rather than two: a county with no rows in either year is grey as
before, while one whose total didn't move is a real "no change" and takes the
ramp's neutral centre.
"""
import math
from dataclasses import dataclass, field

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.cache import cache
from django.utils.safestring import mark_safe

from camp.apps.regions.models import Region
from camp.utils import mapfigure

COUNTY_GEOJSON_KEY = 'pesticides:county-geometries:v2'
COUNTY_GEOJSON_TTL = 60 * 60 * 24
# The county outlines are served at full precision to the interactive map:
# a shared border belongs to both counties, and simplifying each polygon on
# its own keeps different vertices in each, so the two copies of that border
# drift apart -- two lines where there is one. The small choropleth figure
# draws the whole valley a few hundred pixels wide, where this tolerance is
# about a pixel, so it takes the simplified set and stays light.
FIGURE_SIMPLIFY_TOLERANCE = 0.005
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
    # Sickly greens: pale bile through olive to a murky bottle green.
    'putrid': ['#f4f6c6', '#e4ea9b', '#cfd96e', '#b3c24a', '#93a52f', '#72871f', '#546816', '#3a4a12'],
    # ...and a yellower, more acid take on the same.
    'bile': ['#f7f5b6', '#e6e57a', '#cbd249', '#a9b62e', '#88951d', '#6b7615', '#4f5810', '#353b0b'],
}
RAMP = RAMPS['blues']
NO_DATA = '#f0f0f0'
CLASSES = len(RAMP)


def ramp_for(name):
    """A candidate ramp by `?ramp=` name, or the default."""
    return RAMPS.get(name or '', RAMP)

# Diverging ramps for the year-over-year change maps, stored already reversed
# so index 0 is the largest decrease and index -1 the largest increase.
# Unlike the sequential ramps these cannot be luminance-monotonic -- both ends
# are dark and the middle is light -- so hue alone carries the direction. All
# three are colorblind-safe, but a greyscale print loses the sign.
DIVERGING_RAMPS = {
    'rdbu': ['#2166ac', '#67a9cf', '#d1e5f0', '#f7f7f7', '#fddbc7', '#ef8a62', '#b2182b'],
    'puor': ['#542788', '#998ec3', '#d8daeb', '#f7f7f7', '#fee0b6', '#f1a340', '#b35806'],
    'brbg': ['#01665e', '#5ab4ac', '#c7eae5', '#f5f5f5', '#f6e8c3', '#d8b365', '#8c510a'],
}
DIVERGING_RAMP = DIVERGING_RAMPS['rdbu']
# The middle stop of a diverging ramp: the "no change" class.
DIVERGING_CENTER = len(DIVERGING_RAMP) // 2


def diverging_ramp_for(name):
    """
    A diverging ramp by `?ramp=` name, or the default. A sequential name never
    resolves here, so a change map can't be drawn with a one-sided ramp.
    """
    return DIVERGING_RAMPS.get(name or '', DIVERGING_RAMP)


def sample_ramp(ramp, count):
    """
    `count` colors spread across `ramp`, interpolating between its stops --
    the same algorithm as sampleRamp() in section-map.js. Selecting the
    nearest stop instead silently repeats colors once `count` passes the
    number of stops, which the diverging ramps (seven stops, eight classes)
    would hit.
    """
    if count <= 1:
        return [ramp[-1]]
    stops = [(int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)) for h in ramp]
    colors = []
    for i in range(count):
        position = i * (len(stops) - 1) / (count - 1)
        low = math.floor(position)
        high = min(len(stops) - 1, low + 1)
        fraction = position - low
        colors.append('#%02x%02x%02x' % tuple(
            round(stops[low][channel] + (stops[high][channel] - stops[low][channel]) * fraction)
            for channel in range(3)
        ))
    return colors

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


def _build_county_geometries(tolerance=None):
    data = {}
    regions = Region.objects.filter(type=Region.Type.COUNTY, boundary__isnull=False).select_related('boundary')
    for region in regions:
        geometry = region.boundary.geometry
        if geometry.srid and geometry.srid != 4326:
            geometry = geometry.transform(4326, clone=True)
        if tolerance:
            geometry = geometry.simplify(tolerance, preserve_topology=True)
        if geometry.geom_type != 'MultiPolygon':
            geometry = MultiPolygon(geometry)
        data[region.pk] = geometry.geojson
    return data


def county_geometries(tolerance=None):
    """
    `{region pk: GeoJSON string}` for the eight counties, cached for a day.
    Full precision by default; pass a tolerance for a lighter set (see
    FIGURE_SIMPLIFY_TOLERANCE), which is cached separately.
    """
    key = COUNTY_GEOJSON_KEY if not tolerance else f'{COUNTY_GEOJSON_KEY}:{tolerance}'
    data = cache.get(key)
    if data is None:
        data = _build_county_geometries(tolerance)
        cache.set(key, data, COUNTY_GEOJSON_TTL)
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
    colors = sample_ramp(ramp, count)

    result = QuantileClasses(breaks=breaks, colors=colors, members=[[] for _ in breaks])
    for value in values:
        result.members[result.index_for(value)].append(value)
    return result


@dataclass
class DivergingClasses(QuantileClasses):
    """
    Change classified around zero: `breaks` ascend from the most negative
    class through the neutral one to the most positive, so the inherited
    `index_for` scan still works. Three states, not two -- a delta of None
    (no rows in either year) is no data, while 0.0 is a real "no change" and
    takes the ramp's neutral centre.
    """
    neutral: str = NO_DATA

    def color_for(self, value):
        if value is None:
            return NO_DATA
        if not self.breaks:
            return self.neutral
        return self.colors[self.index_for(value)]


def diverging_classes(deltas_by_key, classes=CLASSES, ramp=None):
    """
    Build DivergingClasses from a {key: delta} mapping, where a delta of None
    means neither year had rows. The magnitudes are quantiled and mirrored
    around zero, so equal changes up and down get equal saturation and one
    outlier can't flatten the map -- the same "quantile, not equal steps"
    reasoning as quantile_classes, applied to both signs.
    """
    ramp = ramp or DIVERGING_RAMP
    neutral = ramp[DIVERGING_CENTER]
    magnitudes = sorted({abs(v) for v in deltas_by_key.values() if v})
    if not magnitudes:
        return DivergingClasses(neutral=neutral)

    per_side = max(1, min(classes // 2, len(magnitudes)))
    bounds = []
    for i in range(1, per_side + 1):
        position = math.ceil(i * len(magnitudes) / per_side) - 1
        bounds.append(magnitudes[position])

    breaks = [-bound for bound in reversed(bounds)] + [0.0] + bounds
    # Both halves include the centre stop, then drop it, so the two sides
    # mirror each other and the neutral class keeps the ramp's middle.
    decreasing = sample_ramp(ramp[:DIVERGING_CENTER + 1], per_side + 1)[:-1]
    increasing = sample_ramp(ramp[DIVERGING_CENTER:], per_side + 1)[1:]
    colors = decreasing + [neutral] + increasing

    result = DivergingClasses(breaks=breaks, colors=colors,
        members=[[] for _ in breaks], neutral=neutral)
    for value in deltas_by_key.values():
        if value is not None:
            result.members[result.index_for(value)].append(value)
    for members in result.members:
        members.sort()
    return result


def county_map(by_county, width=600, height=420, query='', metric='lbs', ramp=None):
    """
    The county choropleth, shaded by `metric` (see COUNTY_METRICS) as a
    ranking: darker is more. Each county links to its page; `query` (a scope
    query string such as 'year=2020&concern=1') is carried on those links.
    It leaves out `county=` -- the link is what picks the county. The table
    beside it (rank_counties) is the legend.
    """
    geometries = county_geometries(FIGURE_SIMPLIFY_TOLERANCE)
    if not geometries:
        return None
    metric = county_metric(metric)
    unit = COUNTY_METRICS[metric]
    counties = {region.pk: region for region in Region.objects.filter(pk__in=geometries)}
    value_by_pk = {row['county_id']: (row.get(metric) or 0) for row in by_county}
    classes = quantile_classes(value_by_pk, ramp=ramp)

    figure = mapfigure.MapFigure(width=width, height=height, padding=10)
    for pk, geojson in geometries.items():
        county = counties[pk]
        value = value_by_pk.get(pk)
        label = f'{county.name}: {int(round(value)):,} {unit}' if value else f'{county.name}: no data'
        url = county.get_pesticides_url()
        figure.add(mapfigure.Area(
            geometry=GEOSGeometry(geojson, srid=4326),
            fill_color=classes.color_for(value),
            fill_opacity=0.75,
            border_color='#555',
            border_width=1,
            label=label,
            label_on_hover=True,
            url=f'{url}?{query}' if query else url,
        ))
    return mark_safe(figure.render())
