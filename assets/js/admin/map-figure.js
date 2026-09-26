/*
 * Map figures on the map core (assets/js/maps/): every `.map-figure`
 * container rendered by camp.utils.mapfigure.MapFigure becomes a
 * non-interactive map -- a basemap, the payload's areas and markers, fitted
 * once and left alone. Feature clicks (a linked area) and hover labels still
 * work; nothing pans, zooms or rotates. The core builds each figure once it's
 * scrolled into view and releases it once its container has left the
 * document (the 'figure' lifecycle).
 *
 * The container carries:
 *   data-geojson       id of a <script type="application/json"> holding a
 *                      FeatureCollection; each feature's `properties` has
 *                      `kind` ('marker' | 'area'), the style as four flat
 *                      keys (`fillColor`, `fillOpacity`, `color`,
 *                      `weight`), for markers `shape` and `size`, for
 *                      areas optionally a `url` to follow on click, and
 *                      optionally a `label` shown permanently, or only on
 *                      hover when `labelOnHover` is true.
 *   data-style         MapTiler style id (the core's TILE_STYLE_PATHS)
 *   data-maptiler-key  the MapTiler API key
 *   data-padding       pixels of padding when fitting bounds
 *   data-zoom          zoom level to use when the bounds are a single point
 *
 * The style keys are flat rather than nested because MapLibre re-serialises
 * a nested property value to a JSON string on its way through
 * queryRenderedFeatures, which both breaks the paint expressions reading it
 * and hands every hover handler a string where an object was put in.
 *
 * Plain ES2017; keeps `window.SJVAirMapFigures` for the smoke script and the
 * console.
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M || !M.register) return;

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

  // An attribute value for markup built by hand.
  function attr(value) {
    return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // The marker's element: the shape as an inline SVG, filled and stroked from
  // the feature's style, handed to the SDK's Marker.
  function markerElement(props) {
    var size = parseInt(props.size, 10) || 14;
    var draw = SHAPES[props.shape] || SHAPES.circle;
    var el = document.createElement('div');
    el.className = 'map-figure-marker';
    el.style.width = size + 'px';
    el.style.height = size + 'px';
    el.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="' + size + '" height="' + size + '" ' +
      'viewBox="0 0 ' + size + ' ' + size + '" ' +
      'fill="' + attr(props.fillColor || 'dodgerblue') + '" ' +
      'fill-opacity="' + attr(props.fillOpacity == null ? 1 : props.fillOpacity) + '" ' +
      'stroke="' + attr(props.color || 'white') + '" ' +
      'stroke-width="' + attr(props.weight == null ? 1.5 : props.weight) + '" ' +
      'stroke-linejoin="round">' + draw(size) + '</svg>';
    // Hover labels need pointer events; every other marker stays inert, so
    // it neither shows a cursor nor takes a click from the area under it.
    if (props.labelOnHover !== true) el.style.pointerEvents = 'none';
    return el;
  }

  // A ring's planar centroid (shoelace), with its signed area, so the largest
  // ring of a multipolygon can be picked.
  function ringCentroid(ring) {
    var area = 0, cx = 0, cy = 0;
    for (var i = 0, n = ring.length; i < n; i++) {
      var p = ring[i], q = ring[(i + 1) % n];
      var cross = p[0] * q[1] - q[0] * p[1];
      area += cross;
      cx += (p[0] + q[0]) * cross;
      cy += (p[1] + q[1]) * cross;
    }
    if (!area) return null;
    return { point: [cx / (3 * area), cy / (3 * area)], area: Math.abs(area) };
  }

  // Where a feature's label sits: a point's own position; a polygon's centroid
  // (of its largest outer ring); anything else, the middle of its bounds.
  function labelAnchor(feature) {
    var geometry = feature.geometry;
    if (!geometry) return null;
    if (geometry.type === 'Point') return geometry.coordinates;
    var rings = [];
    if (geometry.type === 'Polygon') rings = [geometry.coordinates[0]];
    if (geometry.type === 'MultiPolygon') {
      for (var i = 0; i < geometry.coordinates.length; i++) rings.push(geometry.coordinates[i][0]);
    }
    var best = null;
    for (var j = 0; j < rings.length; j++) {
      var c = ringCentroid(rings[j]);
      if (c && (!best || c.area > best.area)) best = c;
    }
    if (best) return best.point;
    var bounds = M.geometryBounds(geometry);
    return bounds ? [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2] : null;
  }

  // The outline an interactive area takes while the cursor is over it.
  var HOVER_COLOR = '#222';
  var HOVER_WIDTH = 2;

  function styled(key) {
    return ['get', key];
  }

  function hovered(on, off) {
    return ['case', ['boolean', ['feature-state', 'hover'], false], on, off];
  }

  // A label: the SDK's popup, closed only by us, never taking focus (a
  // permanent label opening on page load must not scroll the page to it).
  function makeLabel(text, lngLat, offset) {
    return new maptilersdk.Popup({
      closeButton: false,
      closeOnClick: false,
      closeOnMove: false,
      focusAfterOpen: false,
      anchor: 'bottom',
      offset: offset,
      maxWidth: 'none',
      className: 'map-figure-label',
    }).setLngLat(lngLat).setText(text);
  }

  // The payload, parsed once per container (mapOptions and create both read it).
  function payload(el) {
    if (!el.figurePayload) {
      var node = document.getElementById(el.dataset.geojson);
      el.figurePayload = node ? JSON.parse(node.textContent) : M.EMPTY;
    }
    return el.figurePayload;
  }

  // The view, set once with no motion: the fitted bounds with the padding,
  // or, for a single point, that point at data-zoom.
  function figureView(el) {
    var bounds = M.geometryBounds(payload(el));
    var padding = parseInt(el.dataset.padding || '20', 10);
    var zoom = parseInt(el.dataset.zoom || '14', 10);
    if (bounds && bounds[0][0] === bounds[1][0] && bounds[0][1] === bounds[1][1]) {
      return { center: bounds[0], zoom: zoom };
    }
    if (bounds) return { bounds: bounds, fitBoundsOptions: { padding: padding } };
    return {};
  }

  function Figure(shell) {
    var self = this;
    this.shell = shell;
    this.el = shell.el;
    this.map = shell.map;
    this.markers = [];
    this.labels = [];
    this.hoverLabel = null;
    this.hoverId = null;
    this.areaHoverId = null;
    // For debugging from the console: document.querySelector('.map-figure').mapFigure
    this.el.mapFigure = this;

    // Points become markers; everything else goes into one GeoJSON source
    // drawn by a fill and a line layer, painted per feature from its style.
    var geojson = payload(this.el);
    var points = [];
    var areas = [];
    this.anchors = {};
    for (var i = 0; i < geojson.features.length; i++) {
      var feature = geojson.features[i];
      feature.properties = feature.properties || {};
      feature.properties.id = i;
      // Only a labelled feature needs an anchor, and finding one costs a
      // centroid per ring -- the report maps carry a thousand unlabelled tracts.
      this.anchors[i] = feature.properties.label ? labelAnchor(feature) : null;
      if (feature.geometry && feature.geometry.type === 'Point') points.push(feature);
      else areas.push(feature);
    }
    shell.sourceData.areas = { type: 'FeatureCollection', features: areas };
    // Kept as a direct alias (same object as shell.sourceData.areas) for the
    // smoke script and the console, which read a figure's drawn areas here.
    this.areas = shell.sourceData.areas;
    this.addMarkers(points);
    this.bindAreaEvents();
    this.map.once('load', function () { self.loaded = true; });
  }

  // Added on top of the whole basemap, labels included: these figures exist to
  // show their own geometry. Idempotent, so it can run on every style load.
  Figure.prototype.addLayers = function () {
    var shell = this.shell;
    shell.ensureSource('areas');
    shell.ensureLayer({
      id: 'areas-fill',
      type: 'fill',
      source: 'areas',
      paint: {
        'fill-color': styled('fillColor'),
        'fill-opacity': styled('fillOpacity'),
      },
    });
    shell.ensureLayer({
      id: 'areas-line',
      type: 'line',
      source: 'areas',
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: {
        'line-color': hovered(HOVER_COLOR, styled('color')),
        'line-width': hovered(HOVER_WIDTH, styled('weight')),
      },
    });
    // Permanent area labels, once (markers carry their own).
    if (!this.areaLabelsAdded) {
      this.areaLabelsAdded = true;
      var features = shell.sourceData.areas.features;
      for (var i = 0; i < features.length; i++) {
        var props = features[i].properties;
        if (props.label && props.labelOnHover !== true && this.anchors[props.id]) {
          this.labels.push(makeLabel(props.label, this.anchors[props.id], 0).addTo(this.map));
        }
      }
    }
  };

  Figure.prototype.addMarkers = function (points) {
    var self = this;
    points.forEach(function (feature) {
      var props = feature.properties;
      var lngLat = feature.geometry.coordinates;
      var el = markerElement(props);
      var marker = new maptilersdk.Marker({ element: el, anchor: 'center' }).setLngLat(lngLat).addTo(self.map);
      self.markers.push(marker);
      if (!props.label) return;
      var offset = (parseInt(props.size, 10) || 14) / 2 + 2;
      if (props.labelOnHover === true) {
        el.addEventListener('mouseenter', function () { self.showHover(props.id, props.label, lngLat, offset); });
        el.addEventListener('mouseleave', function () { self.hideHover(); });
      } else {
        self.labels.push(makeLabel(props.label, lngLat, offset).addTo(self.map));
      }
    });
  };

  Figure.prototype.bindAreaEvents = function () {
    var self = this;
    var map = this.map;
    // An area with a url is a link: pointer cursor, click to follow. One with a
    // hover label shows it at the area's anchor while the cursor is over it.
    map.on('mousemove', 'areas-fill', function (event) {
      var feature = event.features && event.features[0];
      if (!feature) return;
      var props = feature.properties;
      map.getCanvas().style.cursor = props.url ? 'pointer' : '';
      // Only an area that answers the cursor takes the outline: a backdrop
      // drawn purely for context shouldn't look clickable.
      self.setAreaHover(props.url || (props.labelOnHover === true && props.label) ? feature.id : null);
      if (props.labelOnHover === true && props.label) {
        self.showHover(props.id, props.label, self.anchors[props.id], 0);
      } else {
        self.hideHover();
      }
    });
    map.on('mouseleave', 'areas-fill', function () {
      map.getCanvas().style.cursor = '';
      self.setAreaHover(null);
      self.hideHover();
    });
    map.on('click', 'areas-fill', function (event) {
      var feature = event.features && event.features[0];
      if (feature && feature.properties.url) window.location.assign(feature.properties.url);
    });
  };

  // The hovered area's outline, as feature state, so the paint expression does
  // the work and no layer is restyled.
  Figure.prototype.setAreaHover = function (featureId) {
    if (this.areaHoverId === featureId) return;
    if (this.areaHoverId != null && this.map.getSource('areas')) {
      this.map.setFeatureState({ source: 'areas', id: this.areaHoverId }, { hover: false });
    }
    this.areaHoverId = featureId;
    if (featureId != null) {
      this.map.setFeatureState({ source: 'areas', id: featureId }, { hover: true });
    }
  };

  Figure.prototype.showHover = function (id, text, lngLat, offset) {
    if (this.hoverId === id || !lngLat) return;
    this.hideHover();
    this.hoverId = id;
    this.hoverLabel = makeLabel(text, lngLat, offset).addTo(this.map);
  };

  Figure.prototype.hideHover = function () {
    if (this.hoverLabel) this.hoverLabel.remove();
    this.hoverLabel = null;
    this.hoverId = null;
  };

  // The labels go first: a Popup is appended to the map's container, not to
  // the canvas Map.remove() takes with it, so a permanent label would outlive
  // a destroy whose container is still in the document.
  Figure.prototype.destroy = function () {
    this.hideHover();
    this.labels.forEach(function (label) { label.remove(); });
    this.labels = [];
    this.markers.forEach(function (marker) { marker.remove(); });
    this.markers = [];
    this.map = null;
  };

  M.register('figure', {
    selector: '.map-figure',
    lifecycle: 'figure',
    features: { interactive: false },
    mapOptions: figureView,
    create: function (shell) { return new Figure(shell); },
  });

  // The smoke script and the console still reach the figures here.
  window.SJVAirMapFigures = {
    init: M.init,
    instances: function () { return M.instances('figure'); },
    pending: function () { return M.pending('figure'); },
  };
})();
