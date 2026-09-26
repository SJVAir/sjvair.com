/*
 * SJVAir map core: the namespace every map builds on, and the helpers the
 * maps used to copy three times. The rest of the core (controls.js,
 * chrome.js, shell.js, registry.js) extends window.SJVAirMaps; map modules
 * register with it (see registry.js).
 *
 * Plain ES2017, no framework/bundler. An htmx history restore re-runs every
 * script tag; a second copy of this file defers to the first.
 */
(function () {
  'use strict';

  if (window.SJVAirMaps) return;

  // The basemap styles the `?tiles=<id>` experiment switch offers, each
  // mapped to its entry in the SDK's style catalogue (a path under
  // maptilersdk.MapStyle). An id the table doesn't know is handed to the SDK
  // as is, which reads it as a MapTiler style id.
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
  var PHONE_QUERY = '(max-width: 768px)';
  var EMPTY = { type: 'FeatureCollection', features: [] };

  function styleFor(id) {
    var path = TILE_STYLE_PATHS[id];
    var style = path ? maptilersdk.MapStyle : null;
    for (var i = 0; style && i < path.length; i++) style = style[path[i]];
    return style || id;
  }

  // The style a map opens with: `?tiles=<id>` (the basemap experiment), else
  // the container's data-style, else dataviz.
  function tileStyle(el) {
    var match = /[?&]tiles=([a-z0-9-]+)/.exec(window.location.search || '');
    return match ? match[1] : ((el && el.dataset.style) || 'dataviz');
  }

  // The SDK draws on WebGL; without it there's no map to make, and the
  // container says so instead. Checked once: the probe makes a throwaway GL
  // context, and init runs on every swap.
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
    el.innerHTML = '<p class="map-note">This map needs WebGL, which this browser has turned off or doesn\'t support.</p>';
  }

  // "36.75,-119.80" (lat,lng, as the data attributes speak) -> [lng, lat]
  // for the SDK; null when blank or malformed.
  function parseCenter(value) {
    if (!value || !String(value).trim()) return null;
    var parts = String(value).split(',').map(Number);
    if (parts.length !== 2 || !isFinite(parts[0]) || !isFinite(parts[1])) return null;
    return [parts[1], parts[0]];
  }

  // "west,south,east,north" -> [[west, south], [east, north]]; null when
  // blank or malformed.
  function parseBounds(value) {
    if (!value || !String(value).trim()) return null;
    var parts = String(value).split(',').map(Number);
    if (parts.length !== 4 || !parts.every(isFinite)) return null;
    return [[parts[0], parts[1]], [parts[2], parts[3]]];
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

  function unionBounds(a, b) {
    if (!a) return b;
    if (!b) return a;
    return [
      [Math.min(a[0][0], b[0][0]), Math.min(a[0][1], b[0][1])],
      [Math.max(a[1][0], b[1][0]), Math.max(a[1][1], b[1][1])],
    ];
  }

  function escapeHtml(value) {
    var div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  function isPhone() {
    try {
      return !!window.matchMedia && window.matchMedia(PHONE_QUERY).matches;
    } catch (err) {
      return false;
    }
  }

  function prefersReducedMotion() {
    try {
      return !!window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (err) {
      return false;
    }
  }

  function logger(prefix) {
    return function (message, err) {
      if (window.console && console.error) console.error(prefix + ': ' + message, err);
    };
  }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      var args = arguments;
      var ctx = this;
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () {
        timer = null;
        fn.apply(ctx, args);
      }, wait);
    };
  }

  // The covered counties' outlines (a FeatureCollection whose features carry
  // `properties.slug`): each county's bounds by slug, and all of them together.
  var counties = {
    bounds: function (geojson) {
      var bySlug = {};
      var all = null;
      ((geojson && geojson.features) || []).forEach(function (feature) {
        var bounds = geometryBounds(feature);
        if (!bounds) return;
        var slug = feature.properties && feature.properties.slug;
        if (slug) bySlug[slug] = bounds;
        all = unionBounds(all, bounds);
      });
      return { bySlug: bySlug, all: all };
    },
  };

  window.SJVAirMaps = {
    TILE_STYLES: Object.keys(TILE_STYLE_PATHS),
    EMPTY: EMPTY,
    styleFor: styleFor,
    tileStyle: tileStyle,
    webglAvailable: webglAvailable,
    showUnavailable: showUnavailable,
    parseCenter: parseCenter,
    parseBounds: parseBounds,
    extendBounds: extendBounds,
    geometryBounds: geometryBounds,
    unionBounds: unionBounds,
    escapeHtml: escapeHtml,
    isPhone: isPhone,
    prefersReducedMotion: prefersReducedMotion,
    logger: logger,
    debounce: debounce,
    counties: counties,
  };
})();
