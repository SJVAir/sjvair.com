"""
Derives lat/lon geometry for the SJVAPCD daily forecast zones that don't
map 1:1 to an existing county Region, from a locally-saved copy of the
forecast map's SVG (see datafiles/sjvapcd-forecast-areas.svg).

The SVG's 9 named shapes are in an arbitrary rendered pixel space, not
lat/lon. Six of them (San Joaquin, Stanislaus, Merced, Madera, Fresno,
Kings) correspond 1:1 to real SJV counties already in the Region table --
those six are used as ground-control points to fit an affine transform
from SVG pixel space to lat/lon (validated to IoU >= 0.98 against the real
county boundaries for all six, which is why a plain affine transform is
sufficient here -- the SJV's geographic extent is small enough that map
projection curvature is negligible).

The other three shapes -- Kern (SJV Air Basin portion), Tulare, and
Sequoia National Park and Forest -- don't have a matching political
county, or (for Kern and Tulare) only cover part of one. For those, the
transform is used only to find the *dividing line* between the SJVAPCD
zone and the real county, and the real county boundary (already accurate,
already in the database) supplies the outer edge:

- Kern (SJV Air Basin portion) = real Kern County boundary, intersected
  with the transformed SVG shape (the SVG shape's own outline is not
  trusted beyond providing this cut line).
- Tulare (SJV Valley portion) = same approach against real Tulare County.
- Sequoia National Park and Forest = real Tulare County minus the Tulare
  zone above. Verified (see import_forecast_zones command) that Sequoia's
  transformed SVG shape overlaps ~100% of this leftover piece and ~0% of
  Kern's leftover piece -- i.e. Sequoia is carved entirely from Tulare,
  not Kern -- so defining it this way makes Tulare and Sequoia tile the
  real county exactly, with no gap or overlap between them.
"""
import json
import re

import numpy as np
from shapely.geometry import Polygon, shape


# SVG shape id -> Region.name of the county it maps to 1:1, used as
# ground-control points for the affine fit.
GROUND_CONTROL_COUNTIES = {
    'san-joaquin': 'San Joaquin County',
    'stanislaus': 'Stanislaus County',
    'merced': 'Merced County',
    'madera': 'Madera County',
    'fresno': 'Fresno County',
    'kings': 'Kings County',
}

MIN_ACCEPTABLE_IOU = 0.95


def parse_svg_path(d):
    """Parses a flat SVG path 'd' string (M/L commands, straight lines
    only, no curves) into a list of (x, y) points."""
    tokens = d.split()
    points = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ('M', 'L', 'Z'):
            i += 1
            continue
        x, y = float(tok), float(tokens[i + 1])
        points.append((x, y))
        i += 2
    return points


def load_svg_shapes(svg_path):
    """Returns {shape_id: shapely.Polygon} for every named <path> in the
    (already-flattened, see datafiles/sjvapcd-forecast-areas.svg) SVG."""
    with open(svg_path) as f:
        content = f.read()
    shapes = {}
    for name, d in re.findall(r'<path id="([^"]+)" d="([^"]+)"', content):
        shapes[name] = Polygon(parse_svg_path(d))
    return shapes


def fit_affine(gcp_svg, gcp_real):
    """Least-squares fit of lon = a*x + b*y + c, lat = d*x + e*y + f from
    corresponding (x, y) SVG points and (lon, lat) real points."""
    design = np.array([[x, y, 1] for x, y in gcp_svg])
    lon_targets = np.array([lon for lon, lat in gcp_real])
    lat_targets = np.array([lat for lon, lat in gcp_real])
    lon_coef, *_ = np.linalg.lstsq(design, lon_targets, rcond=None)
    lat_coef, *_ = np.linalg.lstsq(design, lat_targets, rcond=None)
    return lon_coef, lat_coef


def transform_polygon(poly, lon_coef, lat_coef):
    def tf(x, y):
        return (
            lon_coef[0] * x + lon_coef[1] * y + lon_coef[2],
            lat_coef[0] * x + lat_coef[1] * y + lat_coef[2],
        )
    return Polygon([tf(x, y) for x, y in poly.exterior.coords])


def iou(a, b):
    union = a.union(b).area
    return a.intersection(b).area / union if union else 0.0


def region_boundary_shape(region_name, region_type=None):
    from camp.apps.regions.models import Region

    if region_type is None:
        region_type = Region.Type.COUNTY
    region = Region.objects.filter(type=region_type, name=region_name).select_related('boundary').first()
    if region is None or region.boundary is None:
        raise RuntimeError(f'No boundary found for {region_type} Region {region_name!r}')
    return shape(json.loads(region.boundary.geometry.geojson))


def derive_forecast_zones(svg_path):
    """
    Returns a dict with the validation report and the three derived
    shapely geometries:
        {
            'gcp_iou': {shape_id: iou_score, ...},
            'kern_airbasin': shapely.Polygon,
            'tulare_valley': shapely.Polygon,
            'sequoia': shapely.Polygon,
        }
    Raises RuntimeError if the affine fit doesn't validate well (any
    ground-control county's IoU falls below MIN_ACCEPTABLE_IOU) -- a poor
    fit here means the derived Kern/Tulare/Sequoia geometry can't be
    trusted either.
    """
    svg_shapes = load_svg_shapes(svg_path)

    gcp_svg, gcp_real = [], []
    real_boundaries = {}
    for svg_id, region_name in GROUND_CONTROL_COUNTIES.items():
        real = region_boundary_shape(region_name)
        real_boundaries[region_name] = real
        svg_poly = svg_shapes[svg_id]
        gcp_svg.append((svg_poly.centroid.x, svg_poly.centroid.y))
        gcp_real.append((real.centroid.x, real.centroid.y))

    lon_coef, lat_coef = fit_affine(gcp_svg, gcp_real)

    gcp_iou = {}
    for svg_id, region_name in GROUND_CONTROL_COUNTIES.items():
        transformed = transform_polygon(svg_shapes[svg_id], lon_coef, lat_coef)
        score = iou(transformed, real_boundaries[region_name])
        gcp_iou[svg_id] = score
        if score < MIN_ACCEPTABLE_IOU:
            raise RuntimeError(
                f'Affine fit validation failed: {svg_id} IoU={score:.4f} '
                f'is below the minimum acceptable {MIN_ACCEPTABLE_IOU}. '
                'Refusing to derive Kern/Tulare/Sequoia geometry from an '
                'untrustworthy fit.'
            )

    real_kern = region_boundary_shape('Kern County')
    real_tulare = region_boundary_shape('Tulare County')

    kern_svg_transformed = transform_polygon(svg_shapes['kern-(sjv air basin portion)'], lon_coef, lat_coef)
    tulare_svg_transformed = transform_polygon(svg_shapes['tulare'], lon_coef, lat_coef)

    # ~1km buffer so the affine fit's small imprecision doesn't leave a
    # hairline gap along the edges that DO follow the real county border.
    BUFFER_DEG = 0.01

    kern_airbasin = real_kern.intersection(kern_svg_transformed.buffer(BUFFER_DEG))
    tulare_valley = real_tulare.intersection(tulare_svg_transformed.buffer(BUFFER_DEG))
    sequoia = real_tulare.difference(tulare_valley)

    return {
        'gcp_iou': gcp_iou,
        'kern_airbasin': kern_airbasin,
        'tulare_valley': tulare_valley,
        'sequoia': sequoia,
    }
