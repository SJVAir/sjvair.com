/*
 * Turns every `.map-figure` container rendered by
 * camp.utils.mapfigure.MapFigure into a non-interactive map figure on the
 * MapTiler SDK (MapLibre GL): a basemap, the payload's areas and markers,
 * fitted once and left alone. Feature clicks (a linked area) and hover
 * labels still work; nothing pans, zooms or rotates.
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
 *   data-style         MapTiler style id (see TILE_STYLE_PATHS)
 *   data-maptiler-key  the MapTiler API key
 *   data-padding       pixels of padding when fitting bounds
 *   data-zoom          zoom level to use when the bounds are a single point
 *
 * The style keys are flat rather than nested because MapLibre re-serialises
 * a nested property value to a JSON string on its way through
 * queryRenderedFeatures, which both breaks the paint expressions reading it
 * and hands every hover handler a string where an object was put in.
 *
 * A map is built only once its container is scrolled into view, and is
 * released again once the container has left the document (htmx swaps on
 * the pesticides explorer), so a page with several figures below the fold
 * is cheap and repeated navigation can't pile up WebGL contexts.
 *
 * Plain ES2017, no framework/bundler; exposes `window.SJVAirMapFigures`.
 */
(function () {
  'use strict';

  // An htmx history restore (back to a page whose snapshot wasn't cached)
  // replaces the whole body, which re-runs this tag. A second copy of the
  // module would own `window.SJVAirMapFigures` while the first still held
  // the live maps, leaving neither able to sweep the other's: the one
  // already loaded takes the restored containers instead.
  if (window.SJVAirMapFigures) {
    window.SJVAirMapFigures.init(document);
    return;
  }

  var EMPTY = { type: 'FeatureCollection', features: [] };
  // How far below the fold a figure is built ahead of being scrolled to.
  var BUILD_AHEAD = '200px';

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

  // The marker's element: the shape as an inline SVG, filled and stroked
  // from the feature's style, handed to the SDK's Marker (the analogue of
  // Leaflet's divIcon).
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

  // The basemap styles the `?tiles=<id>` experiment switch offers, each
  // mapped to its entry in the SDK's style catalogue (a path under
  // maptilersdk.MapStyle), as on the explorer's section map. An id the
  // table doesn't know is handed to the SDK as is, which reads it as a
  // MapTiler style id.
  var TILE_STYLE_PATHS = {
    streets: ['STREETS'],
    'basic-v2': ['BASIC'],
    'bright-v2': ['BRIGHT'],
    dataviz: ['DATAVIZ'],
    'dataviz-light': ['DATAVIZ', 'LIGHT'],
    'topo-v2': ['TOPO'],
    'outdoor-v2': ['OUTDOOR'],
    'toner-v2': ['TONER'],
    hybrid: ['HYBRID'],
  };
  function styleFor(id) {
    var path = TILE_STYLE_PATHS[id];
    var style = path ? maptilersdk.MapStyle : null;
    for (var i = 0; style && i < path.length; i++) style = style[path[i]];
    return style || id;
  }

  // The SDK draws on WebGL; without it there's no map to make, and the
  // container says so instead (see showUnavailable). Checked once: the
  // probe makes a throwaway GL context, and init() runs on every swap.
  var webglSupport = null;
  function webglAvailable() {
    if (webglSupport === null) {
      try {
        var canvas = document.createElement('canvas');
        webglSupport = !!(window.WebGLRenderingContext && (canvas.getContext('webgl2') || canvas.getContext('webgl')));
      } catch (err) {
        webglSupport = false;
      }
    }
    return webglSupport;
  }

  function showUnavailable(el) {
    el.classList.add('is-unavailable');
    el.innerHTML = '<p class="map-figure-note">This map needs WebGL, which this browser has turned off or doesn\'t support.</p>';
  }

  function logError(message, err) {
    if (window.console && console.error) console.error('map-figure: ' + message, err);
  }

  // Bounds are [[west, south], [east, north]], which the SDK takes as is.
  function extendBounds(bounds, coordinates) {
    if (typeof coordinates[0] === 'number') {
      if (coordinates[0] < bounds[0][0]) bounds[0][0] = coordinates[0];
      if (coordinates[0] > bounds[1][0]) bounds[1][0] = coordinates[0];
      if (coordinates[1] < bounds[0][1]) bounds[0][1] = coordinates[1];
      if (coordinates[1] > bounds[1][1]) bounds[1][1] = coordinates[1];
      return;
    }
    for (var i = 0; i < coordinates.length; i++) extendBounds(bounds, coordinates[i]);
  }

  // The bounding box of a GeoJSON geometry, feature, or feature collection;
  // null for nothing (an empty collection, a null geometry).
  function geometryBounds(geojson) {
    if (!geojson) return null;
    var bounds = [[Infinity, Infinity], [-Infinity, -Infinity]];
    var items = geojson.type === 'FeatureCollection' ? geojson.features : [geojson];
    for (var i = 0; i < items.length; i++) {
      var geometry = items[i].type === 'Feature' ? items[i].geometry : items[i];
      if (!geometry) continue;
      var parts = geometry.type === 'GeometryCollection' ? geometry.geometries : [geometry];
      for (var j = 0; j < parts.length; j++) {
        if (parts[j] && parts[j].coordinates) extendBounds(bounds, parts[j].coordinates);
      }
    }
    return bounds[0][0] === Infinity ? null : bounds;
  }

  // A ring's planar centroid (shoelace), with its signed area, so the
  // largest ring of a multipolygon can be picked.
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

  // Where a feature's label sits: a point's own position; a polygon's
  // centroid (of its largest outer ring), where Leaflet's tooltip opened;
  // anything else, the middle of its bounds.
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
    var bounds = geometryBounds(geometry);
    return bounds ? [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2] : null;
  }

  // The outline an interactive area takes while the cursor is over it.
  // Same dark stroke the explorer's section map uses for a hovered cell.
  var HOVER_COLOR = '#222';
  var HOVER_WIDTH = 2;

  // A paint value read off the feature's properties.
  function styled(key) {
    return ['get', key];
  }

  // `on` while the cursor is over the feature, `off` otherwise.
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

  function MapFigure(el) {
    this.el = el;
    this.markers = [];
    this.labels = [];
    this.hoverLabel = null;
    this.hoverId = null;
    this.areaHoverId = null;

    var dataNode = document.getElementById(el.dataset.geojson);
    var geojson = dataNode ? JSON.parse(dataNode.textContent) : EMPTY;
    var padding = parseInt(el.dataset.padding || '20', 10);
    var zoom = parseInt(el.dataset.zoom || '14', 10);

    // Points become markers; everything else goes into one GeoJSON source
    // drawn by a fill and a line layer, painted per feature from its style.
    // Features get ids (`promoteId`) so a hovered area can be told apart.
    var points = [], areas = [];
    this.anchors = {};
    for (var i = 0; i < geojson.features.length; i++) {
      var feature = geojson.features[i];
      feature.properties = feature.properties || {};
      feature.properties.id = i;
      // Only a labelled feature needs an anchor, and finding one costs a
      // centroid per ring -- the report maps carry a thousand unlabelled
      // tracts.
      this.anchors[i] = feature.properties.label ? labelAnchor(feature) : null;
      if (feature.geometry && feature.geometry.type === 'Point') points.push(feature);
      else areas.push(feature);
    }
    this.areas = { type: 'FeatureCollection', features: areas };

    var tilesMatch = /[?&]tiles=([a-z0-9-]+)/.exec(window.location.search || '');
    var tileStyle = tilesMatch ? tilesMatch[1] : (el.dataset.style || 'dataviz');

    // The view is set here, once, with no motion: the fitted bounds with
    // the padding, or, for a single point, that point at `data-zoom`.
    var bounds = geometryBounds(geojson);
    var view = {};
    if (bounds && bounds[0][0] === bounds[1][0] && bounds[0][1] === bounds[1][1]) {
      view = { center: bounds[0], zoom: zoom };
    } else if (bounds) {
      view = { bounds: bounds, fitBoundsOptions: { padding: padding } };
    }

    maptilersdk.config.apiKey = el.dataset.maptilerKey || '';
    this.map = new maptilersdk.Map(Object.assign({
      container: el,
      style: styleFor(tileStyle),
      // A figure, not a map to move: every handler off and no furniture
      // but the attribution (and the MapTiler logo where the key calls for
      // one). The canvas still takes clicks and hovers for the features.
      dragPan: false,
      scrollZoom: false,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      touchZoomRotate: false,
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
      navigationControl: false,
      geolocateControl: false,
      terrainControl: false,
      attributionControl: { compact: 'auto' },
      logoPosition: 'bottom-right',
    }, view));
    // For debugging from the console: document.querySelector('.map-figure').mapFigure
    el.mapFigure = this;

    // Our source and layers are part of the style, so they're (re)added
    // whenever a style has loaded, the first time included.
    this.map.on('style.load', this.addLayers.bind(this));
    this.map.once('load', this.collapseAttribution.bind(this));
    this.addMarkers(points);
    this.bindAreaEvents();
  }

  // Added on top of the whole basemap, labels included: these figures exist
  // to show their own geometry, and a place name over a shaded area
  // competes with it. Idempotent, so it can run on every style load.
  MapFigure.prototype.addLayers = function () {
    var map = this.map;
    if (!map.getSource('areas')) {
      map.addSource('areas', { type: 'geojson', data: this.areas, promoteId: 'id' });
    }
    if (!map.getLayer('areas-fill')) {
      map.addLayer({
        id: 'areas-fill',
        type: 'fill',
        source: 'areas',
        paint: {
          'fill-color': styled('fillColor'),
          'fill-opacity': styled('fillOpacity'),
        },
      });
    }
    if (!map.getLayer('areas-line')) {
      map.addLayer({
        id: 'areas-line',
        type: 'line',
        source: 'areas',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: {
          'line-color': hovered(HOVER_COLOR, styled('color')),
          'line-width': hovered(HOVER_WIDTH, styled('weight')),
        },
      });
    }
    // Permanent area labels, once (markers carry their own).
    if (!this.areaLabelsAdded) {
      this.areaLabelsAdded = true;
      for (var i = 0; i < this.areas.features.length; i++) {
        var props = this.areas.features[i].properties;
        if (props.label && props.labelOnHover !== true && this.anchors[props.id]) {
          this.labels.push(makeLabel(props.label, this.anchors[props.id], 0).addTo(map));
        }
      }
    }
  };

  MapFigure.prototype.addMarkers = function (points) {
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

  MapFigure.prototype.bindAreaEvents = function () {
    var self = this;
    var map = this.map;
    // An area with a url is a link: pointer cursor, click to follow. One
    // with a hover label shows it at the area's anchor while the cursor is
    // over it (not following the cursor, as Leaflet's non-sticky tooltip).
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

  // The hovered area's outline, as feature state so the paint expression
  // does the work and no layer is restyled.
  MapFigure.prototype.setAreaHover = function (featureId) {
    if (this.areaHoverId === featureId) return;
    if (this.areaHoverId != null && this.map.getSource('areas')) {
      this.map.setFeatureState({ source: 'areas', id: this.areaHoverId }, { hover: false });
    }
    this.areaHoverId = featureId;
    if (featureId != null) {
      this.map.setFeatureState({ source: 'areas', id: featureId }, { hover: true });
    }
  };

  MapFigure.prototype.showHover = function (id, text, lngLat, offset) {
    if (this.hoverId === id || !lngLat) return;
    this.hideHover();
    this.hoverId = id;
    this.hoverLabel = makeLabel(text, lngLat, offset).addTo(this.map);
  };

  MapFigure.prototype.hideHover = function () {
    if (this.hoverLabel) this.hoverLabel.remove();
    this.hoverLabel = null;
    this.hoverId = null;
  };

  // The SDK opens the compact attribution on load; fold it, as its own
  // toggle does, so the figure starts with just the (i).
  MapFigure.prototype.collapseAttribution = function () {
    if (!this.map) return;
    var attrib = this.el.querySelector('.maplibregl-ctrl-attrib.maplibregl-compact');
    if (attrib && attrib.classList.contains('maplibregl-compact-show')) {
      attrib.classList.remove('maplibregl-compact-show');
      attrib.setAttribute('open', '');
    }
  };

  // Releases the map (its WebGL context with it) once its container is
  // gone. The labels go first: a Popup is appended to the map's container,
  // not to the canvas Map.remove() takes with it, so a permanent label
  // would outlive a destroy whose container is still in the document.
  MapFigure.prototype.destroy = function () {
    this.hideHover();
    this.labels.forEach(function (label) { label.remove(); });
    this.labels = [];
    this.markers.forEach(function (marker) { marker.remove(); });
    this.markers = [];
    this.map.remove();
    this.map = null;
  };

  // -- lifecycle --

  var figures = [];   // built
  var pending = [];   // waiting to be scrolled into view
  var observer = null;

  function containersUnder(root) {
    var found = [];
    if (root.matches && root.matches('.map-figure')) found.push(root);
    var nested = root.querySelectorAll ? root.querySelectorAll('.map-figure') : [];
    for (var i = 0; i < nested.length; i++) found.push(nested[i]);
    return found;
  }

  function build(el) {
    try {
      figures.push(new MapFigure(el));
    } catch (err) {
      logError('failed to initialize', err);
    }
  }

  function unschedule(el) {
    var at = pending.indexOf(el);
    if (at !== -1) pending.splice(at, 1);
    if (observer) observer.unobserve(el);
  }

  // Builds the map once the container comes into view (a little before,
  // BUILD_AHEAD), so the figures below the fold on an admin page cost
  // nothing until they're scrolled to. Without IntersectionObserver every
  // figure is built at once.
  function schedule(el) {
    if (!('IntersectionObserver' in window)) {
      build(el);
      return;
    }
    if (!observer) {
      observer = new IntersectionObserver(function (entries) {
        for (var i = 0; i < entries.length; i++) {
          if (!entries[i].isIntersecting) continue;
          var target = entries[i].target;
          unschedule(target);
          build(target);
        }
      }, { rootMargin: BUILD_AHEAD });
    }
    pending.push(el);
    observer.observe(el);
  }

  // Maps whose container has left the document (an htmx swap took the page
  // they were on) are released, and containers still waiting for their
  // turn are forgotten. Judged against the whole document, not `root`: a
  // swap fires htmx:load per swapped element, out-of-band fragments too.
  function sweep() {
    var live = [];
    for (var i = 0; i < figures.length; i++) {
      if (document.body.contains(figures[i].el)) live.push(figures[i]);
      else figures[i].destroy();
    }
    figures = live;
    for (var j = pending.length - 1; j >= 0; j--) {
      if (!document.body.contains(pending[j])) unschedule(pending[j]);
    }
  }

  // Idempotent: containers already claimed carry `data-rendered`, so this
  // can run on every htmx:load over the swapped content.
  function init(root) {
    if (typeof maptilersdk === 'undefined') return;
    sweep();
    var containers = containersUnder(root || document);
    for (var i = 0; i < containers.length; i++) {
      var el = containers[i];
      // An htmx history restore re-parses the page with scripting off,
      // which turns the markup inside <noscript> -- the section map's
      // static fallback, the same choropleth -- into real elements. They
      // are display:none and are not ours to draw.
      if (el.closest && el.closest('noscript')) continue;
      if (el.dataset.rendered) continue;
      el.dataset.rendered = '1';
      if (!webglAvailable()) {
        showUnavailable(el);
        continue;
      }
      schedule(el);
    }
  }

  // Exposed so content swapped in later (htmx on the pesticides explorer)
  // can render the maps it brought with it.
  window.SJVAirMapFigures = {
    init: init,
    instances: function () { return figures.slice(); },
    pending: function () { return pending.slice(); },
  };

  function initDocument() {
    init(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDocument);
  } else {
    initDocument();
  }
})();
