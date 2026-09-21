"""
Browser-rendered (Leaflet) maps for the Django admin.

The static map generator in ``camp.utils.maps`` downloads basemap tiles
server-side on every request, which is slow enough to time out admin
pages. This module produces the same kind of map as a lightweight HTML
container plus a GeoJSON payload; ``assets/js/admin/leaflet-maps.js``
turns each container into a non-interactive Leaflet map in the browser,
where the tiles load lazily and in parallel.

Usage::

    lmap = LeafletMap(width=600, height=400)
    lmap.add(Area(geometry=boundary.geometry, fill_color='dodgerblue'))
    lmap.add(Marker(geometry=monitor.position, shape='star'))
    html = lmap.render()  # SafeString for a readonly admin field
"""

import json

from dataclasses import dataclass
from typing import Literal, Optional, Union
from uuid import uuid4

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.template.loader import render_to_string

from shapely.geometry.base import BaseGeometry

from camp.utils.maps import to_geos

# The same MapTiler raster tiles the realtime map uses ("streets", 256px).
# The scripts accept a `?tiles=<style>` override for trying other styles.
TILE_URL = 'https://api.maptiler.com/maps/streets/256/{z}/{x}/{y}.png?key={key}'
TILE_ATTRIBUTION = (
    '<a href="https://www.maptiler.com/copyright/" target="_blank">&copy; MapTiler</a> '
    '<a href="https://www.openstreetmap.org/copyright" target="_blank">&copy; OpenStreetMap contributors</a>'
)

Geometry = Union[GEOSGeometry, BaseGeometry]


@dataclass
class Marker:
    geometry: Geometry

    fill_color: str = 'dodgerblue'
    fill_opacity: float = 1.0
    border_color: str = 'white'
    border_width: float = 1.5
    size: int = 14
    shape: Literal['circle', 'square', 'triangle', 'star'] = 'circle'
    label: Optional[str] = None
    label_on_hover: bool = False

    def properties(self) -> dict:
        return {
            'kind': 'marker',
            'shape': self.shape,
            'size': self.size,
            'label': self.label,
            'labelOnHover': self.label_on_hover,
            'style': {
                'fillColor': self.fill_color,
                'fillOpacity': self.fill_opacity,
                'color': self.border_color,
                'weight': self.border_width,
            },
        }


@dataclass
class Area:
    geometry: Geometry

    fill_color: str = 'lightgray'
    fill_opacity: float = 0.4
    border_color: str = 'black'
    border_width: float = 1
    label: Optional[str] = None
    label_on_hover: bool = False
    # A click on the area goes here (the script marks it interactive).
    url: Optional[str] = None

    def properties(self) -> dict:
        return {
            'kind': 'area',
            'label': self.label,
            'labelOnHover': self.label_on_hover,
            'url': self.url,
            'style': {
                'fillColor': self.fill_color,
                'fillOpacity': self.fill_opacity,
                'color': self.border_color,
                'weight': self.border_width,
            },
        }


class LeafletMap:
    template_name = 'admin/_includes/leaflet_map.html'

    def __init__(self, width: int = 600, height: int = 400, padding: int = 20, zoom: int = 14):
        """
        Args:
            width, height: Pixel size of the map container.
            padding: Pixels of padding around the fitted bounds.
            zoom: Zoom level used when the bounds collapse to a single
                point (e.g. a map with one marker and nothing else).
        """
        self.width = width
        self.height = height
        self.padding = padding
        self.zoom = zoom
        self.elements: list[Union[Marker, Area]] = []

    def add(self, *elements: Union[Marker, Area]) -> 'LeafletMap':
        self.elements.extend(elements)
        return self

    def to_geojson(self) -> dict:
        features = []
        for element in self.elements:
            geometry = to_geos(element.geometry)
            if geometry.srid and geometry.srid != 4326:
                geometry = geometry.transform(4326, clone=True)
            features.append({
                'type': 'Feature',
                'geometry': json.loads(geometry.geojson),
                'properties': element.properties(),
            })
        return {'type': 'FeatureCollection', 'features': features}

    def render(self) -> str:
        if not self.elements:
            raise ValueError('Cannot render a map with no elements.')

        return render_to_string(self.template_name, {
            'map_id': f'leaflet-map-{uuid4().hex}',
            'width': self.width,
            'height': self.height,
            'padding': self.padding,
            'zoom': self.zoom,
            'tile_url': TILE_URL.format(key=settings.MAPTILER_API_KEY, z='{z}', x='{x}', y='{y}'),
            'attribution': TILE_ATTRIBUTION,
            'geojson': self.to_geojson(),
        })
