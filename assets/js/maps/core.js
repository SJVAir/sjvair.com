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

  // A same-origin JSON fetch that rejects on an HTTP error.
  function getJson(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    });
  }

  // Numbers as the maps' popups and legends write them.
  var format = {
    // A data value, by the same rules as the `quantity` template filter:
    // always one decimal, thousands separators, '<0.1' for a nonzero value
    // under 0.05, '—' for none.
    quantity: function (value) {
      if (value === null || value === undefined) return '—';
      if (value && Math.abs(value) < 0.05) return '<0.1';
      return value.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    },
    // A legend's round number (a class boundary, a size in the circle key):
    // no forced decimals, so 0.01 reads '0.01', 10 reads '10', 1456 '1,456'.
    // A nonzero value under 0.01 reads '<0.01', or with `precise` its two
    // significant digits ('0.0025').
    round: function (value, precise) {
      if (value && Math.abs(value) < 0.01) return precise ? String(Number(value.toPrecision(2))) : '<0.01';
      return value.toLocaleString('en-US', { maximumFractionDigits: 2 });
    },
  };

  // Classed colour ramps: `breaks` are the ascending boundaries between
  // breaks.length + 1 classes.
  var classes = {
    index: function (value, breaks) {
      var index = 0;
      while (index < breaks.length && value >= breaks[index]) index++;
      return index;
    },
    // "under 0.1", "0.1–1", ..., "100 and up"; `round` writes the boundaries
    // (format.round by default).
    label: function (index, breaks, round) {
      round = round || format.round;
      if (index === 0) return 'under ' + round(breaks[0]);
      if (index === breaks.length) return round(breaks[index - 1]) + ' and up';
      return round(breaks[index - 1]) + '–' + round(breaks[index]);
    },
    // A legend's classes, largest first: a swatch from `ramp` (one colour
    // per class) and its label, with `swatchClass` on each swatch and
    // `round` passed on to label().
    bins: function (breaks, ramp, swatchClass, round) {
      var bins = '';
      for (var i = breaks.length; i >= 0; i--) {
        bins += '<span class="legend-bin"><span class="legend-swatch' + (swatchClass ? ' ' + swatchClass : '') +
          '" style="background:' + ramp[i] + '"></span>' + classes.label(i, breaks, round) + '</span>';
      }
      return '<div class="legend-bins">' + bins + '</div>';
    },
  };

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

  // A geometry's own point: a Point's coordinates; a (Multi)Polygon's
  // centroid (of its largest outer ring, by planar area); anything else (or
  // a degenerate ring), the middle of its bounds. Used to place a permanent
  // or hover label steadily, independent of the cursor.
  function geometryCentroid(geometry) {
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

  // Hovering an interactive area: the outline it takes while the cursor is
  // over it (via feature-state), and the label that follows. Shared by every
  // map that highlights a feature under the cursor (map-figure.js, the
  // dairy map's counties), so the paint expression, the popup and the
  // feature-state toggle are written once.
  var HOVER_COLOR = '#222';
  var HOVER_WIDTH = 2;

  // A paint expression: `on` while the feature-state `hover` is true, else `off`.
  function hoverPaint(on, off) {
    return ['case', ['boolean', ['feature-state', 'hover'], false], on, off];
  }

  // A label: the SDK's popup, closed only by us, never taking focus (a
  // permanent label opening on page load must not scroll the page to it).
  // `extraClass` adds to the shared `map-hover-label` look (its CSS is in
  // assets/css/maps/map.css) when a caller needs its own hook, e.g. for a
  // smoke script's selector.
  function hoverLabel(text, lngLat, offset, extraClass) {
    return new maptilersdk.Popup({
      closeButton: false,
      closeOnClick: false,
      closeOnMove: false,
      focusAfterOpen: false,
      anchor: 'bottom',
      offset: offset,
      maxWidth: 'none',
      className: extraClass ? 'map-hover-label ' + extraClass : 'map-hover-label',
    }).setLngLat(lngLat).setText(text);
  }

  // Toggles a source's hover feature-state from `previousId` to `id` (either
  // may be null/undefined for none), and returns `id` -- the caller keeps
  // that as its own "currently hovered" field. A no-op source (already
  // removed by a style swap) is skipped rather than throwing.
  function setHoverState(map, source, previousId, id) {
    if (previousId === id) return previousId;
    if (previousId != null && map.getSource(source)) {
      map.setFeatureState({ source: source, id: previousId }, { hover: false });
    }
    if (id != null) {
      map.setFeatureState({ source: source, id: id }, { hover: true });
    }
    return id;
  }

  // `path` (a URL or path) with its query rewritten by write(URLSearchParams),
  // as a same-origin path; null for another origin, or with `samePage` for
  // another page than this one. A map writes its state (view, measure, ...)
  // onto links rendered before the reader changed it.
  function rewriteQuery(path, write, samePage) {
    var url = new URL(path, window.location.href);
    if (url.origin !== window.location.origin) return null;
    if (samePage && url.pathname !== window.location.pathname) return null;
    write(url.searchParams);
    var search = url.searchParams.toString();
    return url.pathname + (search ? '?' + search : '') + url.hash;
  }

  // The address bar's query rewritten by write(URLSearchParams), in place
  // (replaceState): a map's view follows it, so it can be shared.
  function syncUrl(write) {
    var path = rewriteQuery(window.location.pathname + window.location.search, write);
    window.history.replaceState(window.history.state, '', path);
  }

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
    geometryCentroid: geometryCentroid,
    unionBounds: unionBounds,
    escapeHtml: escapeHtml,
    isPhone: isPhone,
    prefersReducedMotion: prefersReducedMotion,
    logger: logger,
    debounce: debounce,
    counties: counties,
    getJson: getJson,
    format: format,
    classes: classes,
    rewriteQuery: rewriteQuery,
    syncUrl: syncUrl,
    hover: {
      COLOR: HOVER_COLOR,
      WIDTH: HOVER_WIDTH,
      paint: hoverPaint,
      label: hoverLabel,
      setState: setHoverState,
    },
  };
})();
