/*
 * Turns every `.admin-leaflet-map` container rendered by
 * camp.utils.leaflet.LeafletMap into a static (non-interactive) Leaflet map.
 *
 * The container carries:
 *   data-geojson      id of a <script type="application/json"> holding a
 *                     FeatureCollection; each feature's `properties` has
 *                     `kind` ('marker' | 'area'), a Leaflet `style` object,
 *                     and for markers `shape` and `size`.
 *   data-tiles        raster tile URL template
 *   data-attribution  attribution HTML
 *   data-padding      pixels of padding when fitting bounds
 *   data-zoom         zoom level to use when the bounds are a single point
 */
(function () {
  'use strict';

  var SHAPES = {
    circle: function (s) {
      return '<circle cx="' + s / 2 + '" cy="' + s / 2 + '" r="' + (s / 2 - 1) + '"/>';
    },
    square: function (s) {
      return '<rect x="1" y="1" width="' + (s - 2) + '" height="' + (s - 2) + '"/>';
    },
    triangle: function (s) {
      return '<polygon points="' + s / 2 + ',1 ' + (s - 1) + ',' + (s - 1) + ' 1,' + (s - 1) + '"/>';
    },
    star: function (s) {
      var points = [];
      var cx = s / 2, cy = s / 2, outer = s / 2 - 1, inner = outer * 0.45;
      for (var i = 0; i < 10; i++) {
        var r = i % 2 === 0 ? outer : inner;
        var a = -Math.PI / 2 + (i * Math.PI) / 5;
        points.push((cx + r * Math.cos(a)).toFixed(2) + ',' + (cy + r * Math.sin(a)).toFixed(2));
      }
      return '<polygon points="' + points.join(' ') + '"/>';
    }
  };

  function markerIcon(props) {
    var size = props.size || 14;
    var style = props.style || {};
    var draw = SHAPES[props.shape] || SHAPES.circle;
    var svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="' + size + '" height="' + size + '" ' +
      'viewBox="0 0 ' + size + ' ' + size + '" ' +
      'fill="' + (style.fillColor || 'dodgerblue') + '" ' +
      'fill-opacity="' + (style.fillOpacity == null ? 1 : style.fillOpacity) + '" ' +
      'stroke="' + (style.color || 'white') + '" ' +
      'stroke-width="' + (style.weight == null ? 1.5 : style.weight) + '" ' +
      'stroke-linejoin="round">' + draw(size) + '</svg>';
    return L.divIcon({
      html: svg,
      className: 'admin-leaflet-marker',
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2]
    });
  }

  function buildMap(container) {
    var dataNode = document.getElementById(container.dataset.geojson);
    if (!dataNode) return;
    var geojson = JSON.parse(dataNode.textContent);
    var padding = parseInt(container.dataset.padding || '20', 10);
    var zoom = parseInt(container.dataset.zoom || '14', 10);

    var map = L.map(container, {
      attributionControl: true,
      zoomControl: false,
      dragging: false,
      touchZoom: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      tapHold: false
    });

    L.tileLayer(container.dataset.tiles, {
      attribution: container.dataset.attribution,
      maxZoom: 21
    }).addTo(map);

    var layer = L.geoJSON(geojson, {
      style: function (feature) {
        return feature.properties.style || {};
      },
      pointToLayer: function (feature, latlng) {
        return L.marker(latlng, {
          icon: markerIcon(feature.properties),
          interactive: false,
          keyboard: false
        });
      },
      onEachFeature: function (feature, featureLayer) {
        if (feature.properties.label) {
          featureLayer.bindTooltip(feature.properties.label, {
            permanent: true,
            direction: 'top',
            className: 'admin-leaflet-label'
          });
        }
      }
    }).addTo(map);

    var bounds = layer.getBounds();
    if (!bounds.isValid()) return;
    if (bounds.getNorthEast().equals(bounds.getSouthWest())) {
      map.setView(bounds.getCenter(), zoom);
    } else {
      map.fitBounds(bounds, { padding: [padding, padding] });
    }
  }

  function init() {
    if (typeof L === 'undefined') return;
    var containers = document.querySelectorAll('.admin-leaflet-map');
    for (var i = 0; i < containers.length; i++) {
      if (!containers[i].dataset.rendered) {
        containers[i].dataset.rendered = '1';
        buildMap(containers[i]);
      }
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
