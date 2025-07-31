import json
import tempfile

from dataclasses import dataclass
from typing import List, Optional, Union

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.utils import timezone

import contextily as ctx
import geopandas as gpd
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt

from shapely.geometry.base import BaseGeometry
from shapely.geometry import box, shape, Point, Polygon, MultiPolygon


from io import BytesIO

# Set a contant cache directory to prevent it from being lost
ctx.tile.set_cache_dir(f'{tempfile.tempdir}/contextily-cache_{timezone.now().strftime("%Y%m")}')

# CRS Constants
CRS_LATLON = 'EPSG:4326'
CRS_WEBMERCATOR = 'EPSG:3857'


@dataclass
class MapElement:
    geometry: BaseGeometry
    label: Optional[str] = None
    fill_color: Optional[str] = None
    border_color: Optional[str] = None
    alpha: Optional[float] = None

    outline: bool = False
    shadow: bool = False


@dataclass
class Marker(MapElement):
    size: int = 100
    shape: str = 'o'  # default: circle
    fill_color: Optional[str] = 'blue'
    border_color: Optional[str] = 'white'
    border_width: float = 1.5
    alpha: Optional[float] = 1.0

    outline_color: str = 'black'
    outline_alpha: float = 0.3
    outline_width: float = 3.0

    shadow_color: str = 'black'
    shadow_alpha: float = 0.2
    shadow_offset: tuple[float, float] = (1, -1)


@dataclass
class Area(MapElement):
    fill_color: Optional[str] = 'lightgray'
    border_color: Optional[str] = 'black'
    alpha: Optional[float] = 0.4

    outline_color: str = 'white'
    outline_width: float = 2.0
    outline_alpha: float = 1.0

    shadow_color: str = 'black'
    shadow_alpha: float = 0.2
    shadow_offset: tuple[float, float] = (2, -2)


class StaticMap:
    def __init__(
        self,
        width: int = 800,
        height: int = 600,
        dpi: int = 100,
        buffer: Optional[float] = None,
        # basemap=ctx.providers.OpenStreetMap.Mapnik,
        basemap=ctx.providers.MapTiler.Bright,
        crs: str = CRS_WEBMERCATOR,
    ):
        self.width = width
        self.height = height
        self.dpi = dpi
        self.buffer = buffer

        self.basemap = basemap
        if self.basemap.get('name', '').startswith('MapTiler'):
            self.basemap['key'] = settings.MAPTILER_API_KEY
        # self.basemap['zoomOffset'] = 0

        self.crs = crs
        self.elements: List[MapElement] = []

    @property
    def areas(self):
        return [e for e in self.elements if isinstance(e.geometry, (Polygon, MultiPolygon))]

    @property
    def markers(self):
        return [e for e in self.elements if isinstance(e.geometry, Point)]

    def add(self, element: MapElement):
        element.geometry = to_shape(element.geometry)
        self.elements.append(element)

    def get_path_effects(self, element: MapElement):
        effects = []

        if element.outline:
            effects.append(
                pe.withStroke(
                    linewidth=element.outline_width,
                    foreground=element.outline_color,
                    alpha=element.outline_alpha,
                )
            )

        if element.shadow:
            effects.append(
                pe.withSimplePatchShadow(
                    offset=element.shadow_offset,
                    shadow_rgbFace=element.shadow_color,
                    alpha=element.shadow_alpha,
                )
            )

        return effects

    def render(self, out_path: Optional[str] = None, format: Optional[str] = None):
        if not self.elements:
            raise ValueError('No map elements added.')

        fig, ax = plt.subplots(
            figsize=(self.width / self.dpi, self.height / self.dpi),
            dpi=self.dpi
        )
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

        # Plot polygons
        for area in self.areas:
            gpd.GeoSeries([area.geometry]).plot(
                ax=ax,
                alpha=area.alpha if area.alpha is not None else 0.4,
                facecolor=area.fill_color or 'gray',
                edgecolor=area.border_color or 'black',
                path_effects=self.get_path_effects(area),
                linewidth=1,
            )

            if area.label:
                center = area.geometry.centroid
                ax.text(center.x, center.y, area.label, ha='center', va='center', fontsize=10)

        # Plot points
        for marker in self.markers:
            x, y = marker.geometry.x, marker.geometry.y
            ax.scatter(
                x, y,
                s=marker.size,
                color=marker.fill_color or 'blue',
                edgecolors=marker.border_color or 'white',
                linewidths=marker.border_width,
                marker=marker.shape,
                path_effects=self.get_path_effects(marker),
                zorder=3,
            )

            if marker.label:
                ax.text(x, y, marker.label, ha='left', va='bottom', fontsize=9)

        # Set map bounds
        geometries = [e.geometry for e in self.elements if e.geometry and not e.geometry.is_empty]
        if not geometries:
            raise ValueError('No valid geometries to render map.')

        series = gpd.GeoSeries(geometries, crs=CRS_LATLON)
        extent = self._compute_extent(series, buffer=self.buffer)
        ax.set_xlim(extent[0], extent[2])
        ax.set_ylim(extent[1], extent[3])

        ctx.add_basemap(ax, source=self.basemap, attribution=False, zoom_adjust=-1)
        ax.axis('off')

        if out_path and not format:
            format = out_path.split('.')[-1]
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
            return buf.getvalue()

    def _adjust_bounds_to_aspect(self, bounds):
        minx, miny, maxx, maxy = bounds
        current_aspect = (maxx - minx) / (maxy - miny)
        target_aspect = self.width / self.height

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

    def _compute_extent(
        self,
        series: gpd.GeoSeries,
        buffer: Optional[float] = None,
    ) -> tuple[float, float, float, float]:
        """
        Compute extent bounds for rendering from a GeoSeries,
        applying buffer and adjusting for aspect ratio.

        Args:
            series: A GeoSeries of geometries in EPSG:3857.
            buffer: Amount of padding in map units (>=1.0 = meters, <1.0 = percent of extent).
                Defaults to:
                - 500m for a single Point
                - 10% for all others

        Returns:
            Bounds tuple (minx, miny, maxx, maxy), adjusted to match image aspect ratio.
        """
        if len(series) == 1 and series.iloc[0].geom_type == 'Point':
            buf = buffer if buffer is not None else 500
            x, y = series.iloc[0].x, series.iloc[0].y
            bounds = box(x - buf, y - buf, x + buf, y + buf).bounds
        else:
            minx, miny, maxx, maxy = series.total_bounds
            if buffer is None:
                buffer = 0.10
            if buffer <= 1.0:
                pad_x = (maxx - minx) * buffer
                pad_y = (maxy - miny) * buffer
            else:
                pad_x = pad_y = buffer
            bounds = (minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y)

        return self._adjust_bounds_to_aspect(bounds)


def to_shape(geometry):
    if isinstance(geometry, GEOSGeometry):
        geometry = shape(json.loads(geometry.geojson))
    return gpd.GeoSeries([geometry], crs=CRS_LATLON).to_crs(CRS_WEBMERCATOR).iloc[0]


def from_geometries(
    *geometries: Union[GEOSGeometry, BaseGeometry],

    width: int = 800,
    height: int = 600,
    dpi: int = 100,
    buffer: Optional[float] = None,

    marker_size: int = Marker.size,
    marker_shape: str = Marker.shape,
    marker_fill_color: Optional[str] = Marker.fill_color,
    marker_border_color: Optional[str] = Marker.border_color,
    marker_border_width: float = Marker.border_width,
    marker_alpha: Optional[float] = Marker.alpha,
    marker_outline: bool = Marker.outline,
    marker_shadow: bool = Marker.shadow,

    area_fill_color: Optional[str] = Area.fill_color,
    area_border_color: Optional[str] = Area.border_color,
    area_alpha: Optional[float] = Area.alpha,
    area_outline: bool = Area.outline,
    area_shadow: bool = Area.shadow,

    out_path: Optional[str] = None,
    format: Optional[str] = None,
):
    """
    Render a static map from a list of geometries and return a BytesIO buffer or save to disk.

    Args:
        gdf: A GeoDataFrame that we want to render.
        width: Image width in pixels.
        height: Image height in pixels.
        dpi: Dots per inch for output image.
        buffer: Amount of buffer space surrounding the geometries on the map (<=1.0 for percent, else meters).
        alpha: Polygon fill transparency.
        edgecolor: Color for polygon outlines.
        point_color: Color for points.
        out_path: If given, save to this path. Otherwise returns BytesIO buffer.
        format: If given, create image in this format. Otherwise, derive from out_path or default to png

    Returns:
        BytesIO buffer of PNG if out_path is None, else None.
    """
    # Make sure input is geographic

    static_map = StaticMap(width=width, height=height, dpi=dpi, buffer=buffer)

    for geometry in geometries:
        if geometry.geom_type == 'Point':
            static_map.add(Marker(
                geometry=geometry,
                size=marker_size,
                shape=marker_shape,

                fill_color=marker_fill_color,
                border_color=marker_border_color,
                border_width=marker_border_width,
                alpha=marker_alpha,

                outline=marker_outline,
                shadow=marker_shadow,
            ))
        elif geometry.geom_type in ('Polygon', 'MultiPolygon'):
            static_map.add(Area(
                geometry=geometry,

                fill_color=area_fill_color,
                border_color=area_border_color,
                alpha=area_alpha,

                outline=area_outline,
                shadow=area_shadow,
            ))

    return static_map.render(out_path=out_path, format=format)

