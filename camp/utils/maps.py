import json
import os

from io import BytesIO
from typing import Literal, Optional, Union

import contextily as ctx
import geopandas as gpd
import matplotlib.pyplot as plt
import pyproj

from shapely.geometry import box, shape, Point
from shapely.ops import transform
from django.contrib.gis.geos import GEOSGeometry


def from_geometries(*geometries, **kwargs):
    # Normalize geometries, convert to shapely
    shapely_geoms = []
    for g in geometries:
        if isinstance(g, GEOSGeometry):
            g = shape(json.loads(g.geojson))
        shapely_geoms.append(g)

    gdf = gpd.GeoDataFrame(geometry=shapely_geoms, crs='EPSG:4326').to_crs(epsg=3857)
    return from_gdf(gdf, **kwargs)


def from_gdf(
    gdf: gpd.GeoDataFrame,
    width: int = 800,
    height: int = 600,
    buffer: Optional[float] = None,
    out_path: Optional[str] = None,
    format: Optional[str] = None,
    dpi: int = 100,
    alpha: float = 0.4,
    edgecolor: str = 'black',
    point_color: str = 'blue',
):
    """
    Render a static map from a list of geometries and return a BytesIO buffer or save to disk.

    Args:
        gdf: A GeoDataFrame that we want to render.
        width: Image width in pixels.
        height: Image height in pixels.
        zoom: Optional tile zoom level.
        out_path: If given, save to this path. Otherwise returns BytesIO buffer.
        dpi: Dots per inch for output image.
        alpha: Polygon fill transparency.
        edgecolor: Color for polygon outlines.
        point_color: Color for points.

    Returns:
        BytesIO buffer of PNG if out_path is None, else None.
    """

    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    polygon_gdf = gdf[gdf.geometry.type.isin(['Polygon', 'MultiPolygon'])]
    if not polygon_gdf.empty:
        polygon_gdf.plot(
            ax=ax, alpha=alpha, edgecolor=edgecolor
        )

    points_gdf = gdf[gdf.geometry.type == 'Point']
    if not points_gdf.empty:
        points_gdf.plot(
            ax=ax, color=point_color, markersize=100, zorder=3
        )

    # if len(gdf) == 1 and gdf.geometry.iloc[0].geom_type == 'Point':
    extent = adjust_bounds_to_aspect(get_bounds_with_buffer(gdf, buffer=buffer), width, height)
    ax.set_xlim(extent[0], extent[2])
    ax.set_ylim(extent[1], extent[3])

    ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, attribution=False)
    ax.axis('off')

    if out_path and not format:
        format = os.path.splitext(out_path)[-1].lstrip('.').lower()
    if not format:
        format = 'png'

    if out_path:
        plt.savefig(out_path, format=format)
        plt.close(fig)
        return None
    else:
        buf = BytesIO()
        plt.savefig(buf, format=format)
        plt.close(fig)
        buf.seek(0)
        return buf


def adjust_bounds_to_aspect(bounds, width, height):
    minx, miny, maxx, maxy = bounds
    current_aspect = (maxx - minx) / (maxy - miny)
    target_aspect = width / height

    if current_aspect > target_aspect:
        # Add vertical padding
        new_height = (maxx - minx) / target_aspect
        center_y = (miny + maxy) / 2
        miny = center_y - new_height / 2
        maxy = center_y + new_height / 2
    else:
        # Add horizontal padding
        new_width = (maxy - miny) * target_aspect
        center_x = (minx + maxx) / 2
        minx = center_x - new_width / 2
        maxx = center_x + new_width / 2

    return (minx, miny, maxx, maxy)


def get_bounds_with_buffer(gdf, buffer: Optional[float] = None) -> tuple[float, float, float, float]:
    """
    Return appropriate extent bounds for contextily basemap rendering.

    If the GeoDataFrame contains a single point, apply a fixed buffer in map units.
    Otherwise, apply a percentage-based padding to the total bounds.

    Args:
        gdf: GeoDataFrame with projected geometry column.
        buffer:
            - If None, auto-selects:
                • 500 meters for single points
                • 10% padding for other geometries
            - If >= 1.0: interpreted as fixed buffer in map units (meters)
            - If < 1.0: interpreted as percentage of bounding box size

    Returns:
        Tuple (minx, miny, maxx, maxy) with padded bounds.
    """
    if len(gdf) == 1 and gdf.geometry.iloc[0].geom_type == 'Point':
        buf = buffer if buffer is not None else 500  # meters
        x, y = gdf.geometry.iloc[0].x, gdf.geometry.iloc[0].y
        return box(x - buf, y - buf, x + buf, y + buf).bounds

    # Multi-feature or polygon-based
    minx, miny, maxx, maxy = gdf.total_bounds

    if buffer is None:
        buffer = 0.10  # 10% default

    if buffer <= 1.0:
        pad_x = (maxx - minx) * buffer
        pad_y = (maxy - miny) * buffer
    else:
        pad_x = pad_y = buffer

    return (minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y)

