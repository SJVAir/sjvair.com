/*
 * Interactive pesticide section map for the Pesticides Explorer, on the
 * MapTiler SDK (MapLibre GL).
 *
 * Turns each `.section-map` container into a live map: square-mile (MTRS)
 * sections shaded by a metric (pounds or application count), plus SprayDays
 * notice-of-intent markers and, where the page asks for them, school and
 * child care markers. Config comes entirely from the container's `data-*`
 * attributes (see `pesticides/includes/section-map.html` and
 * `views.section_map_config`), so this script has no server-rendered state
 * baked in beyond that.
 *
 * While the port from Leaflet is in progress this module loads beside the
 * Leaflet one under `?gl=1` and claims only the containers marked `data-gl`
 * (the Leaflet script skips those). The behaviour it is held to is the
 * parity checklist, docs/superpowers/specs/2026-09-21-section-map-inventory.md.
 *
 * Plain ES2017, no framework/bundler, single global side effect: none (IIFE).
 */
(function () {
  'use strict';

  // At this zoom and closer the map draws square-mile (MTRS) sections; further
  // out it draws the 6x6 mile township grid instead, so there's always a grid.
  // It's a floor: a wide viewport needs to be closer still, or the sections
  // in view would exceed what the endpoint returns (see sectionZoom()).
  var SECTION_ZOOM = 11;
  // The most sections a viewport should ask for at once, under the API's
  // 2,500 cap with room for the padded bbox fetch to fall back unpadded.
  var MAX_VIEWPORT_SECTIONS = 2000;
  var METERS_PER_MILE = 1609.34;
  var DEBOUNCE_MS = 300;
  // How long the cursor must rest on an uncached township before its lens
  // sections are fetched, so a sweep across the map doesn't fetch for every
  // township it passes over.
  var LENS_FETCH_DELAY_MS = 50;
  // The grace between leaving a township (or one of its lens sections) and
  // dropping the lens, so moving between the two doesn't flicker it away.
  var LENS_CLEAR_DELAY_MS = 120;
  // Candidate ramps, selectable with ?ramp=<name> while we pick one.
  var RAMPS = {
    blues: ['#deebf7', '#9ecae1', '#6baed6', '#3182bd', '#08519c'],
    purd: ['#f1eef6', '#d7b5d8', '#df65b0', '#dd1c77', '#980043'],
    bupu: ['#edf8fb', '#b3cde3', '#8c96c6', '#8856a7', '#810f7c'],
    ylorbr: ['#ffffd4', '#fed98e', '#fe9929', '#d95f0e', '#993404'],
    putrid: ['#eef2b8', '#cfd96e', '#a3b53c', '#72871f', '#3f4f12'],
    bile: ['#f5f2a4', '#d9d95a', '#a9b62e', '#6b7615', '#3a400c'],
    // Putrid with a paler, greyer light end and the middle steps spread apart.
    putrid2: ['#eceedc', '#c9d18c', '#98ab3f', '#5f7a1c', '#2f3f0e'],
    // Multi-hue sequential: yellow-green through teal to navy (ColorBrewer YlGnBu).
    ylgnbu: ['#ffffcc', '#a1dab4', '#41b6c4', '#2c7fb8', '#253494'],
    // Cool teal-to-green (ColorBrewer PuBuGn).
    pubugn: ['#f6eff7', '#bdc9e1', '#67a9cf', '#1c9099', '#016c59'],
    // Perceptually uniform (matplotlib): mako and cividis.
    mako: ['#def5e5', '#60ceac', '#3497a9', '#3e5ba9', '#382a54'],
    cividis: ['#fde725', '#c7b76e', '#7f7c75', '#4b5a6a', '#00224e'],
  };
  var rampMatch = /[?&]ramp=([a-z]+)/.exec(window.location.search || '');
  var RAMP = RAMPS[rampMatch && rampMatch[1]] || RAMPS.blues;
  // How many quantile classes: ?bins=4|5|6|8|10 (quartiles ... deciles).
  var BIN_OPTIONS = [[4, 'Quartiles'], [5, 'Quintiles'], [6, 'Sextiles'], [8, 'Octiles'], [10, 'Deciles']];
  var binsMatch = /[?&]bins=(\d+)/.exec(window.location.search || '');
  var DEFAULT_BINS = 6;
  var NUM_CLASSES = binsMatch && BIN_OPTIONS.some(function (o) { return o[0] === +binsMatch[1]; }) ? +binsMatch[1] : DEFAULT_BINS;
  var NO_DATA_COLOR = '#f0f0f0';
  // A full 6x6 mile township in degrees around 36°N, for the lens reach
  // and the "all sections" blocks.
  var TOWNSHIP_DEGREES = { lat: 0.087, lng: 0.108 };
  // "All sections" mode: how many section blocks load at once...
  var ALL_SECTIONS_CONCURRENCY = 4;
  // ...and how often the growing layer is reshaded while they land.
  var ALL_SECTIONS_REDRAW_MS = 600;
  // Below this zoom, sections drawn at township level (the lens, "all
  // sections") are a few pixels each: their hairline strokes would outweigh
  // the fills and grey the map, so they draw fill-only.
  var SECTION_LINES_MIN_ZOOM = 10;

  var METRIC_UNITS = {
    lbs_chemical: 'lbs',
    applications: 'applications',
  };

  // Fetch a bbox padded by half a viewport on each side, then skip the next
  // fetch while the viewport is still inside what we already have, so a pan
  // (or a popup opening near the edge) doesn't rebuild the grid under an
  // open popup.
  var BBOX_PAD = 0.5;

  // Wide enough for the top-chemicals table.
  var POPUP_MAX_WIDTH = '320px';

  var LEVEL_TEXT = {
    section: 'Each square is one square-mile section.',
    township: 'Each square is a 6 × 6 mile township; zoom in for square-mile sections.',
    allSections: 'Each square is one square-mile section, across every township in view.',
  };

  // The base grid: present, but barely, so the fills read as a surface.
  var GRID_LINE = { color: '#1f2d3d', opacity: 0.18 };
  // The section whose popup is open keeps a modest outline until it closes.
  var SELECTED_LINE = { color: '#1f2d3d', opacity: 0.9, width: 1.5 };
  // The page's own section (a section page), in the notices orange.
  var HIGHLIGHT_LINE = { color: '#d35400', opacity: 1, width: 3 };
  // Fill opacities [with data, without]: the grid, and sections drawn at
  // the township zoom (the lens, "all sections").
  var GRID_OPACITY = [0.7, 0.25];
  var LENS_OPACITY = [0.85, 0.35];

  // `count` colours evenly spaced along a ramp, interpolated in RGB
  // between its stops, so a ramp serves any number of classes.
  function sampleRamp(ramp, count) {
    if (count <= 1) return [ramp[ramp.length - 1]];
    var stops = ramp.map(function (hex) {
      return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
    });
    var out = [];
    for (var i = 0; i < count; i++) {
      var t = (i * (stops.length - 1)) / (count - 1);
      var lo = Math.floor(t), hi = Math.min(stops.length - 1, lo + 1), f = t - lo;
      var rgb = stops[lo].map(function (v, ch) { return Math.round(v + (stops[hi][ch] - v) * f); });
      out.push('#' + rgb.map(function (v) { return ('0' + v.toString(16)).slice(-2); }).join(''));
    }
    return out;
  }

  // Same algorithm as camp.apps.pesticides.maps.quantile_classes: distinct
  // sorted positive values, cut at ceil(i*n/k), darkest ramp color for the
  // top class.
  function quantileClasses(values) {
    var positive = [];
    for (var i = 0; i < values.length; i++) {
      if (values[i]) positive.push(values[i]);
    }
    positive.sort(function (a, b) { return a - b; });
    var distinct = [];
    for (var j = 0; j < positive.length; j++) {
      if (j === 0 || positive[j] !== positive[j - 1]) distinct.push(positive[j]);
    }
    if (!distinct.length) {
      return { breaks: [], colors: [], members: [] };
    }
    var count = Math.min(NUM_CLASSES, distinct.length);
    var breaks = [];
    for (var k = 1; k <= count; k++) {
      var position = Math.ceil((k * distinct.length) / count) - 1;
      breaks.push(distinct[position]);
    }
    var colors = sampleRamp(RAMP, count);
    var members = [];
    for (var m = 0; m < breaks.length; m++) members.push([]);
    for (var v = 0; v < positive.length; v++) {
      members[indexFor(breaks, positive[v])].push(positive[v]);
    }
    return { breaks: breaks, colors: colors, members: members };
  }

  function indexFor(breaks, value) {
    for (var i = 0; i < breaks.length; i++) {
      if (value <= breaks[i]) return i;
    }
    return breaks.length - 1;
  }

  function colorFor(classes, value) {
    if (!value || !classes.breaks.length) return NO_DATA_COLOR;
    return classes.colors[indexFor(classes.breaks, value)];
  }

  function renderLegend(el, classes, unit) {
    el.innerHTML = '';
    for (var i = 0; i < classes.members.length; i++) {
      var values = classes.members[i];
      if (!values.length) continue;
      var low = values[0];
      var high = values[values.length - 1];
      var li = document.createElement('li');
      var range = low === high
        ? formatNumber(low) + ' ' + unit
        : formatNumber(low) + '–' + formatNumber(high) + ' ' + unit;
      li.innerHTML =
        '<span class="swatch" style="background-color: ' + classes.colors[i] + ';"></span>' +
        '<span class="range">' + escapeHtml(range) + '</span>';
      el.appendChild(li);
    }
    var noDataLi = document.createElement('li');
    noDataLi.innerHTML =
      '<span class="swatch" style="background-color: ' + NO_DATA_COLOR + ';"></span>' +
      '<span class="range">No data</span>';
    el.appendChild(noDataLi);
  }

  // "Fresno County" -> "Fresno", where the label already says county.
  function shortCounty(name) {
    return /\sCounty$/.test(name) ? name.slice(0, -' County'.length) : name;
  }

  function escapeHtml(value) {
    var div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  // Page URLs come from the container as patterns with `{id}` in them (see
  // views.section_map_config), so the routes live in the URLconf only.
  function fillUrl(pattern, id) {
    if (!pattern) return '';
    return pattern.replace('{id}', encodeURIComponent(id));
  }

  function linkHtml(url, text, extraClass) {
    if (!url) return escapeHtml(text);
    return '<a' + (extraClass ? ' class="' + extraClass + '"' : '') +
      ' href="' + escapeHtml(url) + '">' + escapeHtml(text) + '</a>';
  }

  function formatNumber(value) {
    try {
      return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
    } catch (err) {
      return String(value);
    }
  }

  // -- paint expressions --
  // The grids are shaded from properties the classing step writes on each
  // feature (`fill`, `opacity`, and `value`, the metric or 0), and hover is
  // a feature state, so a metric or hover change never touches the layers.
  var HAS_VALUE = ['>', ['to-number', ['get', 'value']], 0];

  function hoverCase(hovered, rest) {
    return ['case', ['boolean', ['feature-state', 'hover'], false], hovered, rest];
  }

  // Hovering a cell darkens and thickens its border so the reader can see
  // which square a click would open. The fill is left alone: it carries the
  // value. A cell with no reported use gets a lighter one, so the pointer
  // still lands somewhere visible (a reader finding their own square mile)
  // without drawing attention to nothing.
  var GRID_HOVER_COLOR = ['case', HAS_VALUE, '#222', '#999'];
  var LENS_HOVER_COLOR = ['case', HAS_VALUE, '#111', '#999'];

  // The townships under the lens lose their fill while it's up (a feature
  // state, see setHostFills), so the section shades aren't stacked on the
  // township shade beneath them.
  var LENS_HOST = ['boolean', ['feature-state', 'lensHost'], false];
  var GRID_FILL_OPACITY = ['case', LENS_HOST, 0, ['get', 'opacity']];

  // Sections drawn at the township zoom (the lens, "all sections"). Zoomed
  // out past SECTION_LINES_MIN_ZOOM the sections are a pixel or two:
  // no-data sections draw nothing at all (their pale wash would veil the
  // basemap across every section without use), and the rest get a hairline
  // seam in their own fill colour, which closes the gaps between
  // neighbouring fills without the grey a grid line would add.
  function sectionsFillPaint() {
    return {
      'fill-color': ['get', 'fill'],
      'fill-opacity': ['step', ['zoom'],
        ['case', HAS_VALUE, ['get', 'opacity'], 0],
        SECTION_LINES_MIN_ZOOM, ['get', 'opacity']],
    };
  }

  function sectionsLinePaint() {
    return {
      'line-color': ['step', ['zoom'],
        hoverCase(LENS_HOVER_COLOR, ['get', 'fill']),
        SECTION_LINES_MIN_ZOOM, hoverCase(LENS_HOVER_COLOR, GRID_LINE.color)],
      'line-opacity': ['step', ['zoom'],
        hoverCase(1, ['case', HAS_VALUE, ['get', 'opacity'], 0]),
        SECTION_LINES_MIN_ZOOM, hoverCase(1, GRID_LINE.opacity)],
      'line-width': ['step', ['zoom'], hoverCase(2, 1), SECTION_LINES_MIN_ZOOM, hoverCase(2, 0.5)],
    };
  }

  // The basemap styles the experiment control offers (?tiles=<id>), each
  // mapped to its entry in the SDK's style catalogue (a path under
  // maptilersdk.MapStyle). An id the table doesn't know is handed to the SDK
  // as is, which reads it as a MapTiler style id.
  var TILE_STYLES = ['streets', 'basic-v2', 'bright-v2', 'dataviz', 'dataviz-light', 'topo-v2', 'outdoor-v2', 'toner-v2', 'hybrid'];
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

  var COUNTY_COLOR = '#1f2d3d';
  // Dashed county lines once the section grid is on (see restyleCounties);
  // dash lengths are in line widths, so this is Leaflet's "4 3" at 1.5px.
  var COUNTY_DASH = [2.5, 2];
  // The page's own region (a city, ZIP, or place), in the notices orange.
  var OUTLINE_COLOR = '#d35400';
  // The locate radius circle, in Leaflet's default path style.
  var RADIUS_COLOR = '#3388ff';
  // How many vertices approximate the radius circle.
  var RADIUS_CIRCLE_POINTS = 64;
  // The reader's own position after a locate: a small blue dot ringed white.
  var LOCATE_COLOR = '#3273dc';

  var EMPTY = { type: 'FeatureCollection', features: [] };

  function prefersReducedMotion() {
    try {
      return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (err) {
      return false;
    }
  }

  // The SDK draws on WebGL; without it there's no map to make, and the page
  // says so in the container instead (see showUnavailable). Checked once:
  // the probe makes a throwaway GL context, and init() runs on every swap.
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
    el.innerHTML = '<p class="section-map-note">This map needs WebGL, which this browser has turned off or doesn\'t support.</p>';
  }

  function milesToMeters(miles) {
    return miles * METERS_PER_MILE;
  }

  function buildQuery(params) {
    var pairs = [];
    Object.keys(params).forEach(function (key) {
      var value = params[key];
      if (value === '' || value === null || value === undefined) return;
      pairs.push(encodeURIComponent(key) + '=' + encodeURIComponent(value));
    });
    return pairs.join('&');
  }

  // One fetch shape for every endpoint: `params` (empty values dropped) go on
  // the query string, a non-OK response rejects with its status on the error
  // (a 400 from the grid endpoints means "bbox too large", which callers
  // handle), and an AbortController can cut the request short.
  function fetchJson(url, params, abort) {
    var query = params ? buildQuery(params) : '';
    if (query) url += (url.indexOf('?') === -1 ? '?' : '&') + query;
    return fetch(url, abort ? { signal: abort.signal } : {})
      .then(function (response) {
        if (!response.ok) {
          var err = new Error('bad response');
          err.status = response.status;
          throw err;
        }
        return response.json();
      });
  }

  function isAbort(err) {
    return !!err && err.name === 'AbortError';
  }

  function logError(message, err) {
    if (window.console && console.error) console.error('section-map: ' + message, err);
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

  // -- geometry --
  // Data attributes and the Leaflet-era helpers speak "lat,lng"; the SDK
  // speaks [lng, lat]. Bounds are [[west, south], [east, north]].

  function lngLatOf(latlng) {
    return [latlng[1], latlng[0]];
  }

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

  // Bounds are [[west, south], [east, north]], which the SDK takes as is.
  function padBounds(bounds, ratio) {
    var dx = (bounds[1][0] - bounds[0][0]) * ratio;
    var dy = (bounds[1][1] - bounds[0][1]) * ratio;
    return [[bounds[0][0] - dx, bounds[0][1] - dy], [bounds[1][0] + dx, bounds[1][1] + dy]];
  }

  function boundsContains(outer, inner) {
    return inner[0][0] >= outer[0][0] && inner[0][1] >= outer[0][1] &&
      inner[1][0] <= outer[1][0] && inner[1][1] <= outer[1][1];
  }

  function boundsContainsPoint(bounds, lngLat) {
    return !!bounds && lngLat[0] >= bounds[0][0] && lngLat[0] <= bounds[1][0] &&
      lngLat[1] >= bounds[0][1] && lngLat[1] <= bounds[1][1];
  }

  function boundsIntersects(a, b) {
    return a[0][0] <= b[1][0] && a[1][0] >= b[0][0] && a[0][1] <= b[1][1] && a[1][1] >= b[0][1];
  }

  function boundsCenter(bounds) {
    return [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2];
  }

  function bboxParam(bounds) {
    return [bounds[0][0], bounds[0][1], bounds[1][0], bounds[1][1]].join(',');
  }

  // A feature's bounds, kept on its GeoJSON `bbox` member so each feature is
  // measured once; null for a feature without geometry.
  function featureBounds(feature) {
    if (!feature.bbox) {
      var bounds = geometryBounds(feature);
      if (!bounds) return null;
      feature.bbox = [bounds[0][0], bounds[0][1], bounds[1][0], bounds[1][1]];
    }
    return [[feature.bbox[0], feature.bbox[1]], [feature.bbox[2], feature.bbox[3]]];
  }

  // The popup HTML carries its centre the Leaflet way ({lat, lng}).
  function latLngOf(lngLat) {
    return { lat: lngLat[1], lng: lngLat[0] };
  }

  function findFeature(features, id) {
    for (var i = 0; i < features.length; i++) {
      if (features[i].properties.id === id) return features[i];
    }
    return null;
  }

  // A circle of `meters` around [lng, lat] as a polygon feature: the SDK has
  // no circle geometry, and a circle layer is sized in pixels, not metres.
  function circlePolygon(center, meters, id) {
    var latRadians = center[1] * Math.PI / 180;
    var dLat = meters / 111320;
    var dLng = meters / (111320 * Math.cos(latRadians));
    var ring = [];
    for (var i = 0; i <= RADIUS_CIRCLE_POINTS; i++) {
      var angle = (i % RADIUS_CIRCLE_POINTS) * 2 * Math.PI / RADIUS_CIRCLE_POINTS;
      ring.push([center[0] + dLng * Math.cos(angle), center[1] + dLat * Math.sin(angle)]);
    }
    return {
      type: 'Feature',
      properties: { id: id },
      geometry: { type: 'Polygon', coordinates: [ring] },
    };
  }

  // -- controls --
  // Locate and Reset as SDK controls: one bar each, stacked under the zoom
  // buttons, in the SDK's control idiom with the Leaflet markup inside
  // (an anchor acting as a button, an icon, a title and label).
  function BarControl(className, label, icon, onClick) {
    this.className = className;
    this.label = label;
    this.icon = icon;
    this.onClick = onClick;
  }

  BarControl.prototype.onAdd = function () {
    var self = this;
    var container = document.createElement('div');
    container.className = 'maplibregl-ctrl maplibregl-ctrl-group ' + this.className;
    var link = document.createElement('a');
    link.href = '#';
    link.setAttribute('role', 'button');
    link.setAttribute('title', this.label);
    link.setAttribute('aria-label', this.label);
    link.innerHTML = '<span class="' + this.icon + '" aria-hidden="true"></span>';
    link.addEventListener('click', function (event) {
      event.preventDefault();
      // A click on the control isn't a click on the map (it would switch
      // wheel-zoom on, see enableScrollZoom).
      event.stopPropagation();
      self.onClick();
    });
    container.appendChild(link);
    this.container = container;
    return container;
  };

  BarControl.prototype.onRemove = function () {
    if (this.container && this.container.parentNode) this.container.parentNode.removeChild(this.container);
    this.container = null;
  };

  function SectionMap(el) {
    this.el = el;
    this.data = el.dataset;
    this.reducedMotion = prefersReducedMotion();
    // ?metric=applications and ?notices=1|0 preselect a view, so a link can
    // share it; the toggles write them back (see syncViewParams).
    var metricMatch = /[?&]metric=(lbs_chemical|applications)/.exec(window.location.search || '');
    this.metric = metricMatch ? metricMatch[1] : 'lbs_chemical';
    // Notice markers are on by default only where notices are the subject of
    // the page; `data-show-notices` says which this is, a ?notices= param
    // overrides it, and the "Show notices" checkbox flips it from there.
    var noticesMatch = /[?&]notices=([01])/.exec(window.location.search || '');
    this.showNotices = noticesMatch ? noticesMatch[1] === '1' : this.data.showNotices !== '0';
    // School and child care markers work the same way: on by default only
    // where the schools are the subject of the page (a school district).
    var locationsMatch = /[?&]locations=([01])/.exec(window.location.search || '');
    this.showLocations = locationsMatch ? locationsMatch[1] === '1' : this.data.showLocations === '1';
    // "All sections": at the township zoom, draw every section in view
    // instead of the township grid (loaded in blocks, see loadAllSections).
    this.showAllSections = /[?&]sections=1/.test(window.location.search || '');
    // Only one grid is ever on the map at a time; `level` says which one.
    this.level = 'section';
    // The GeoJSON behind each of our sources, kept here so a style swap
    // (which empties the style of our layers) can put it all back.
    this.sourceData = {};
    this.counties = null;
    this.countyBounds = {};
    this.valleyBounds = null;
    // One controller per request family (see startRequest), and the
    // families seen, so destroy() can cut every one of them short.
    this.gridAbort = null;
    this.noticesAbort = null;
    this.locationsAbort = null;
    this.countiesAbort = null;
    this.outlineAbort = null;
    this.requestNames = [];
    // What the last successful fetch covers, so a pan inside it doesn't
    // refetch (and so doesn't rebuild a layer under an open popup).
    this.loadedBounds = null;
    this.loadedLevel = null;
    this.loadedNoticeBounds = null;
    this.loadedLocationBounds = null;
    this.lensCache = {};
    this.pendingLocate = null;
    // The grid on the map: its features (classed in place), by id, and the
    // classes the legend shows -- over the grid, or over the "all sections"
    // layer while that stands in for the township grid.
    this.gridFeatures = [];
    this.gridById = {};
    this.currentClasses = { breaks: [], colors: [], members: [] };
    this.currentClassesAreSections = false;
    // Township outlines don't change with the filters; after the first
    // load only the numbers are fetched (see loadTownships).
    this.townshipGeometry = null;
    this.townshipGeometryBounds = null;
    // Feature ids of the popups that are open, so a rebuild can put them
    // back, and the section whose popup is (or was) open.
    this.openGridId = null;
    this.openAllSectionsId = null;
    this.openLensId = null;
    this.selectedSectionId = null;
    // The one popup on the map, and whose it is (see openPopup).
    this.popup = null;
    this.popupKey = null;
    this.popupId = null;
    // The hovered feature id per source (a township and one of the lens
    // sections over it can both be hovered).
    this.hoverIds = {};
    // The lens: the hovered township (id and feature), its neighbourhood
    // (the hosts), the sections drawn and their classes, the rest and
    // clear timers, when it was last drawn, and whether a ring prefetch is
    // in flight (see showLens).
    this.lensId = null;
    this.lensHost = null;
    this.lensHosts = null;
    this.lensFeatures = [];
    this.lensClasses = { breaks: [], colors: [], members: [] };
    this.lensFetchTimer = null;
    this.lensClearTimer = null;
    this.lensDrawnAt = 0;
    this.prefetching = false;
    // "All sections": the run in progress, the reshade throttle, and what's
    // drawn (by township, and the features themselves).
    this.allSectionsRun = null;
    this.allSectionsDrawTimer = null;
    this.allSectionsAdded = null;
    this.allSectionsFeatures = [];
    this.allSectionsById = {};
    // The ramp and bins as loaded, so the URL keeps them (see syncViewParams).
    this.rampName = rampMatch && RAMPS[rampMatch[1]] ? rampMatch[1] : 'blues';
    this.bins = NUM_CLASSES;

    this.controlsEl = null;
    this.legendEl = null;
    this.levelEl = null;
    this.statusEl = null;

    this.init();
  }

  // The controls, legend, and level note live beside the map container, so
  // they are re-found (and re-wired) whenever the container gets a new home.
  SectionMap.prototype.attachControls = function () {
    var wrap = this.el.closest('.section-map-wrap') || this.el.parentNode;
    this.wrapEl = wrap;
    // Marks the wrap for the GL-specific styles (control sizes, the legend's
    // clearance of the SDK's logo) while both maps share one stylesheet.
    wrap.classList.add('is-gl');
    this.toolbarEl = wrap.querySelector('.section-map-toolbar');
    this.controlsEl = wrap.querySelector('.section-map-controls');
    this.legendPanelEl = wrap.querySelector('.section-map-legend-panel');
    this.legendEl = wrap.querySelector('.section-map-legend');
    this.levelEl = wrap.querySelector('.section-map-level');
    this.statusEl = this.controlsEl ? this.controlsEl.querySelector('.section-map-status') : null;

    if (this.toolbarEl) this.toolbarEl.hidden = false;
    if (this.legendPanelEl) this.legendPanelEl.hidden = false;

    if (this.controlsEl) {
      var radios = this.controlsEl.querySelectorAll('input[name="metric"]');
      for (var i = 0; i < radios.length; i++) {
        radios[i].checked = radios[i].value === this.metric;
        radios[i].addEventListener('change', this.onMetricChange.bind(this));
      }

      var noticesToggle = this.controlsEl.querySelector('input[name="notices"]');
      if (noticesToggle) {
        noticesToggle.checked = this.showNotices;
        noticesToggle.addEventListener('change', this.onNoticesToggle.bind(this));
      }

      var locationsToggle = this.controlsEl.querySelector('input[name="locations"]');
      if (locationsToggle) {
        locationsToggle.checked = this.showLocations;
        locationsToggle.addEventListener('change', this.onLocationsToggle.bind(this));
      }

      // Experiment controls: basemap style and colour ramp, applied live and
      // written to the URL (?tiles=, ?ramp=) so a combination can be linked.
      var tilesSelect = this.controlsEl.querySelector('select[name="tiles"]');
      if (tilesSelect) {
        TILE_STYLES.forEach(function (style) {
          var option = document.createElement('option');
          option.value = style;
          option.textContent = style;
          tilesSelect.appendChild(option);
        });
        tilesSelect.value = this.tileStyle;
        tilesSelect.addEventListener('change', this.onTilesChange.bind(this));
      }
      var rampSelect = this.controlsEl.querySelector('select[name="ramp"]');
      if (rampSelect) {
        Object.keys(RAMPS).forEach(function (name) {
          var option = document.createElement('option');
          option.value = name;
          option.textContent = name;
          rampSelect.appendChild(option);
        });
        rampSelect.value = rampMatch && RAMPS[rampMatch[1]] ? rampMatch[1] : 'blues';
        rampSelect.addEventListener('change', this.onRampChange.bind(this));
      }
      var binsSelect = this.controlsEl.querySelector('select[name="bins"]');
      if (binsSelect) {
        BIN_OPTIONS.forEach(function (pair) {
          var option = document.createElement('option');
          option.value = pair[0];
          option.textContent = pair[1] + ' (' + pair[0] + ')';
          binsSelect.appendChild(option);
        });
        binsSelect.value = NUM_CLASSES;
        binsSelect.addEventListener('change', this.onBinsChange.bind(this));
      }

      var sectionsToggle = this.controlsEl.querySelector('input[name="sections"]');
      if (sectionsToggle) {
        sectionsToggle.checked = this.showAllSections;
        sectionsToggle.addEventListener('change', this.onSectionsToggle.bind(this));
      }
    }
    var expand = wrap.querySelector('.section-map-expand');
    if (expand && !expand.getAttribute('data-bound')) {
      expand.setAttribute('data-bound', '1');
      expand.addEventListener('click', this.toggleExpanded.bind(this));
    }
    this.bindPanelToggles(wrap);
    this.bindToolbar(wrap);
    this.setExpanded(!!this.expanded);
  };

  // The filter toolbar's dropdowns: a click on a trigger opens its menu
  // (and focuses the picker's search box), a click anywhere else or Escape
  // closes them. The triggers are bound once per toolbar element (a
  // swapped-in toolbar is a new element and gets bound again); the
  // document-level closers are bound once per map and act on whichever
  // toolbar is current, so swaps don't pile up listeners.
  SectionMap.prototype.bindToolbar = function (wrap) {
    var self = this;
    if (!this.toolbarClickHandler) {
      this.toolbarClickHandler = function () { self.closeToolbarDropdowns(null); };
      this.toolbarKeyHandler = function (event) {
        if (event.key === 'Escape') self.closeToolbarDropdowns(null);
      };
      document.addEventListener('click', this.toolbarClickHandler);
      document.addEventListener('keydown', this.toolbarKeyHandler);
    }
    var toolbar = wrap.querySelector('.section-map-toolbar');
    if (!toolbar || toolbar.getAttribute('data-bound')) return;
    toolbar.setAttribute('data-bound', '1');
    var dropdowns = toolbar.querySelectorAll('.dropdown');

    // The filter form only knows its own fields; the map's view settings
    // (metric, notices, all sections) ride along so the URL it lands on
    // still says how the map is being viewed.
    var form = toolbar.querySelector('.section-map-toolbar-filters');
    if (form) {
      form.addEventListener('htmx:configRequest', function (event) {
        var params = event.detail.parameters;
        if (self.metric !== 'lbs_chemical') params.metric = self.metric;
        if (self.showNotices !== (self.data.showNotices !== '0')) params.notices = self.showNotices ? '1' : '0';
        if (self.showLocations !== (self.data.showLocations === '1')) params.locations = self.showLocations ? '1' : '0';
        if (self.showAllSections) params.sections = '1';
      });
    }

    for (var i = 0; i < dropdowns.length; i++) {
      (function (dropdown) {
        var trigger = dropdown.querySelector('.dropdown-trigger .button');
        if (!trigger) return;
        trigger.addEventListener('click', function (event) {
          event.stopPropagation();
          var open = !dropdown.classList.contains('is-active');
          self.closeToolbarDropdowns(dropdown);
          dropdown.classList.toggle('is-active', open);
          trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
          if (open) {
            var focusable = dropdown.querySelector('input[type="search"], select');
            if (focusable) focusable.focus();
          }
        });
        // Clicks inside the menu (typing, picking) shouldn't close it.
        var menu = dropdown.querySelector('.dropdown-menu');
        if (menu) menu.addEventListener('click', function (event) { event.stopPropagation(); });
      })(dropdowns[i]);
    }
  };

  // Closes the current toolbar's dropdowns, all but `except`.
  SectionMap.prototype.closeToolbarDropdowns = function (except) {
    if (!this.toolbarEl) return;
    var dropdowns = this.toolbarEl.querySelectorAll('.dropdown');
    for (var i = 0; i < dropdowns.length; i++) {
      if (dropdowns[i] === except) continue;
      dropdowns[i].classList.remove('is-active');
      var trigger = dropdowns[i].querySelector('.dropdown-trigger .button');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
    }
  };

  // The options and legend panels fold to their header. The fold is a
  // per-viewer convenience kept in localStorage, so it's wrapped: storage
  // can be absent or throw, and the panels must work regardless.
  var PANEL_STORAGE_PREFIX = 'pesticides:section-map:panel:';

  function readPanelState(name) {
    try {
      return window.localStorage.getItem(PANEL_STORAGE_PREFIX + name) === 'collapsed';
    } catch (err) {
      return false;
    }
  }

  function writePanelState(name, collapsed) {
    try {
      window.localStorage.setItem(PANEL_STORAGE_PREFIX + name, collapsed ? 'collapsed' : 'open');
    } catch (err) {
      // Nothing to do: the fold just won't be remembered.
    }
  }

  SectionMap.prototype.bindPanelToggles = function (wrap) {
    var panels = wrap.querySelectorAll('.section-map-panel[data-panel]');
    for (var i = 0; i < panels.length; i++) {
      this.setPanelCollapsed(panels[i], readPanelState(panels[i].getAttribute('data-panel')));
      var toggle = panels[i].querySelector('.section-map-panel-toggle');
      if (!toggle || toggle.getAttribute('data-bound')) continue;
      toggle.setAttribute('data-bound', '1');
      toggle.addEventListener('click', this.onPanelToggle.bind(this, panels[i]));
    }
  };

  SectionMap.prototype.onPanelToggle = function (panel) {
    var collapsed = !panel.classList.contains('is-collapsed');
    this.setPanelCollapsed(panel, collapsed);
    writePanelState(panel.getAttribute('data-panel'), collapsed);
  };

  SectionMap.prototype.setPanelCollapsed = function (panel, collapsed) {
    panel.classList.toggle('is-collapsed', collapsed);
    var toggle = panel.querySelector('.section-map-panel-toggle');
    if (toggle) toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  };

  // The expanded map starts exactly where the navbar ends, measured rather
  // than assumed: the navbar's height varies by a pixel with its contents,
  // and a guess a pixel short shows the hero through the gap.
  SectionMap.prototype.fitBelowNavbar = function () {
    if (!this.wrapEl) return;
    // The wrap carries a 1px border in the navbar's colour and starts 1px
    // above the navbar's measured bottom, so the two borders coincide:
    // whatever fraction of a pixel the navbar ends on, the reader sees one
    // grey line and never a sliver of the page beneath.
    var nav = document.querySelector('nav.navbar');
    var bottom = nav ? nav.getBoundingClientRect().bottom : 0;
    // The explorer's scope bar (year and county pickers) stays in view,
    // pinned under the navbar, so the scope can still be changed; the map
    // starts under it.
    var scopeBar = document.querySelector('.explorer-scope-bar');
    if (scopeBar) {
      scopeBar.style.top = Math.max(0, bottom) + 'px';
      bottom = scopeBar.getBoundingClientRect().bottom;
    }
    this.wrapEl.style.top = Math.max(0, bottom - 1) + 'px';
  };

  // Expanded, the map fills the viewport under the site navbar; the panels
  // over it are what keep it usable there. Escape brings the page back.
  SectionMap.prototype.toggleExpanded = function () {
    this.setExpanded(!this.expanded);
  };

  SectionMap.prototype.setExpanded = function (on) {
    var self = this;
    var was = !!this.expanded;
    this.expanded = on;
    // The site navbar isn't fixed, so the expanded map sits below it only
    // while the page is scrolled to the top: go there on the way in, and
    // come back to where the reader was on the way out.
    if (on && !was) {
      this.scrollBeforeExpand = window.scrollY || window.pageYOffset || 0;
      window.scrollTo(0, 0);
    }
    // The html class first: it pins the scope bar, and fitBelowNavbar
    // measures the pinned bar to place the map under it.
    document.documentElement.classList.toggle('section-map-expanded', on);
    if (this.wrapEl) {
      this.wrapEl.classList.toggle('is-expanded', on);
      if (on) {
        this.fitBelowNavbar();
      } else {
        this.wrapEl.style.top = '';
        var scopeBar = document.querySelector('.explorer-scope-bar');
        if (scopeBar) scopeBar.style.top = '';
      }
    }
    if (!on && was) {
      window.scrollTo(0, this.scrollBeforeExpand || 0);
    }
    if (!this.resizeHandler) {
      this.resizeHandler = function () {
        if (self.expanded) self.fitBelowNavbar();
      };
    }
    window.removeEventListener('resize', this.resizeHandler);
    if (on) window.addEventListener('resize', this.resizeHandler);
    var button = this.wrapEl ? this.wrapEl.querySelector('.section-map-expand') : null;
    if (button) {
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
      button.setAttribute('title', on ? 'Back to the page' : 'Expand the map');
      button.setAttribute('aria-label', on ? 'Back to the page' : 'Expand the map');
    }
    if (!this.escapeHandler) {
      this.escapeHandler = function (event) {
        if (event.key === 'Escape' && self.expanded) self.setExpanded(false);
      };
    }
    document.removeEventListener('keydown', this.escapeHandler);
    if (on) document.addEventListener('keydown', this.escapeHandler);
    // The container changed size. The SDK watches it, but resizing here,
    // once the new layout has applied, means the moveend that follows
    // measures the new size and fills in the wider grid straight away.
    setTimeout(function () { if (self.map) self.map.resize(); }, 0);
  };

  SectionMap.prototype.onSectionsToggle = function (event) {
    this.showAllSections = !!event.target.checked;
    this.syncViewParams();
    if (this.showAllSections) {
      this.clearLens();
      this.loadAllSections();
    } else {
      this.clearAllSections();
    }
  };

  SectionMap.prototype.onNoticesToggle = function (event) {
    this.showNotices = !!event.target.checked;
    this.syncViewParams();
    if (this.showNotices) {
      this.loadNotices();
    } else {
      this.loadedNoticeBounds = null;
      if (this.noticesAbort) this.noticesAbort.abort();
      this.clearNotices();
    }
  };

  SectionMap.prototype.onLocationsToggle = function (event) {
    this.showLocations = !!event.target.checked;
    this.syncViewParams();
    if (this.showLocations) {
      this.loadLocations();
    } else {
      this.loadedLocationBounds = null;
      if (this.locationsAbort) this.locationsAbort.abort();
      this.clearLocations();
    }
    this.updateLocationsNote();
  };

  SectionMap.prototype.init = function () {
    var self = this;
    // ?tiles=<style> swaps the basemap style while we pick one; known before
    // the controls bind so the select shows it.
    var tilesMatch = /[?&]tiles=([a-z0-9-]+)/.exec(window.location.search || '');
    this.defaultTileStyle = this.data.style || 'dataviz';
    this.tileStyle = tilesMatch ? tilesMatch[1] : this.defaultTileStyle;
    this.attachControls();

    var center = this.parseCenter(this.data.center) || [36.75, -119.80];
    var zoom = parseInt(this.data.zoom, 10) || 8;

    maptilersdk.config.apiKey = this.data.maptilerKey || '';
    this.map = new maptilersdk.Map({
      container: this.el,
      style: styleFor(this.tileStyle),
      center: lngLatOf(center),
      zoom: zoom,
      // The zoom buttons are added below, ahead of our own controls; the
      // SDK's other default furniture is either ours (locate) or unwanted.
      navigationControl: false,
      geolocateControl: false,
      terrainControl: false,
      // Wheel-zoom is off by default so the map doesn't hijack page scrolling
      // on long pages; enabled only while the map has focus/is being
      // interacted with directly (see enableScrollZoom).
      scrollZoom: false,
      // Flat and north-up, like the Leaflet map: no pitch, no rotation.
      pitchWithRotate: false,
      dragRotate: false,
      touchPitch: false,
      attributionControl: { compact: true },
    });
    this.map.touchZoomRotate.disableRotation();
    this.map.keyboard.disableRotation();
    // For debugging from the console: document.querySelector('.section-map').sectionMap
    this.el.sectionMap = this;

    this.el.addEventListener('click', this.enableScrollZoom.bind(this));
    this.el.addEventListener('focus', this.enableScrollZoom.bind(this), true);
    this.el.addEventListener('mouseleave', this.disableScrollZoom.bind(this));
    this.el.addEventListener('blur', this.disableScrollZoom.bind(this), true);
    // Escape closes the open popup, as Leaflet's did (closeOnEscapeKey);
    // the SDK's popup only closes from its button. Removing it is the
    // reader letting go (see the popup's close handler in openPopup).
    this.el.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && self.popup) self.popup.remove();
    });
    this.bindGridEvents();

    // Our sources and layers are part of the style, so a style swap (the
    // tiles select) starts from a style without them; they're put back from
    // the data kept on this instance whenever a style has loaded, the first
    // time included. Until then setSourceData just keeps the data, and the
    // camera takes fits and moves straight away, so nothing below waits.
    this.map.on('style.load', this.onStyleLoad.bind(this));
    this.map.once('load', function () { self.loaded = true; });

    // Zoom buttons first, then ours under them. The SDK adds its own
    // navigation control after the first render, which would have put it
    // below controls added here; adding it ourselves keeps the Leaflet
    // order, and leaves out the compass, which has nothing to do on a map
    // that can't rotate.
    this.map.addControl(new maptilersdk.NavigationControl({ showCompass: false }), 'top-left');
    this.addLocateControl();
    this.addResetControl();

    this.drawRadius(center);

    var debouncedLoad = debounce(this.loadGrid.bind(this), DEBOUNCE_MS);
    var debouncedNotices = debounce(this.loadNotices.bind(this), DEBOUNCE_MS);
    var debouncedLocations = debounce(this.loadLocations.bind(this), DEBOUNCE_MS);
    // moveend follows every camera change, a zoom included.
    this.map.on('moveend', debouncedLoad);
    this.map.on('moveend', debouncedNotices);
    this.map.on('moveend', debouncedLocations);
    this.map.on('zoomend', this.restyleCounties.bind(this));
    // Section strokes switch on/off across SECTION_LINES_MIN_ZOOM.
    this.map.on('zoomend', this.restyleSectionLines.bind(this));

    this.loadCounties();
    this.loadOutline();
    this.loadGrid();
    this.loadNotices();
    this.loadLocations();
  };

  SectionMap.prototype.onStyleLoad = function () {
    this.addBaseLayers();
  };

  // -- sources and layers --
  // Every data layer goes in below the basemap's first symbol layer, so the
  // place labels read over the choropleth. Serialises the style, so
  // addBaseLayers asks once and passes the answer to each ensureLayer.
  SectionMap.prototype.beforeLabels = function () {
    var layers = (this.map.getStyle() || {}).layers || [];
    for (var i = 0; i < layers.length; i++) {
      if (layers[i].type === 'symbol') return layers[i].id;
    }
    return undefined;
  };

  // GeoJSON sources are keyed on our own feature ids (`promoteId`), so
  // feature state (hover, selection) can address them by id.
  SectionMap.prototype.ensureSource = function (id) {
    if (this.map.getSource(id)) return;
    this.map.addSource(id, { type: 'geojson', data: this.sourceData[id] || EMPTY, promoteId: 'id' });
  };

  // `before` is the label layer id from beforeLabels(), asked for once by
  // the caller and passed to every layer it adds.
  SectionMap.prototype.ensureLayer = function (spec, before) {
    if (this.map.getLayer(spec.id)) return;
    this.map.addLayer(spec, before);
  };

  // Sets a source's data, remembering it for the next style load; before
  // the style is up the data just waits there for ensureSource. Nothing
  // to keep once the map is gone (a late response after destroy()).
  SectionMap.prototype.setSourceData = function (id, data) {
    if (!this.map) return;
    this.sourceData[id] = data;
    var source = this.map.getSource(id);
    if (source) source.setData(data);
  };

  // Our sources and their layers, bottom to top: the radius circle, the
  // grid, the sections drawn over it at the township zoom ("all sections",
  // then the lens and the hovered township's outline over it), the
  // selected and highlighted sections' outlines, the county lines, the
  // page's own outline, [locations and notices go here, under the located
  // position], and last the reader's located position
  // (`locate`/`locate-circle`), which stays on top of every marker.
  // Idempotent, so it can run on every style load.
  SectionMap.prototype.addBaseLayers = function () {
    var before = this.beforeLabels();
    this.ensureSource('radius');
    this.ensureSource('grid');
    this.ensureSource('all-sections');
    this.ensureSource('lens');
    this.ensureSource('lens-outline');
    this.ensureSource('selected');
    this.ensureSource('highlight');
    this.ensureSource('counties');
    this.ensureSource('outline');
    this.ensureSource('locate');

    this.ensureLayer({
      id: 'radius-fill', type: 'fill', source: 'radius',
      paint: { 'fill-color': RADIUS_COLOR, 'fill-opacity': 0.2 },
    }, before);
    this.ensureLayer({
      id: 'radius-line', type: 'line', source: 'radius',
      paint: { 'line-color': RADIUS_COLOR, 'line-width': 3 },
    }, before);
    // The grid: the fills carry the data, over a faint base grid that
    // darkens on hover. Its opacity and widths follow the level and step
    // aside under "all sections" (see applyGridPaint).
    this.ensureLayer({
      id: 'grid-fill', type: 'fill', source: 'grid',
      paint: { 'fill-color': ['get', 'fill'], 'fill-opacity': GRID_FILL_OPACITY },
    }, before);
    this.ensureLayer({
      id: 'grid-line', type: 'line', source: 'grid',
      paint: {
        'line-color': hoverCase(GRID_HOVER_COLOR, GRID_LINE.color),
        'line-opacity': hoverCase(1, GRID_LINE.opacity),
        'line-width': hoverCase(2, 0.5),
      },
    }, before);
    // Every section in view at the township zoom ("all sections"), and the
    // lens (the hovered township's neighbourhood, see showLens): the same
    // paint, see sectionsFillPaint/sectionsLinePaint.
    this.ensureLayer({ id: 'all-sections-fill', type: 'fill', source: 'all-sections', paint: sectionsFillPaint() }, before);
    this.ensureLayer({ id: 'all-sections-line', type: 'line', source: 'all-sections', paint: sectionsLinePaint() }, before);
    this.ensureLayer({ id: 'lens-fill', type: 'fill', source: 'lens', paint: sectionsFillPaint() }, before);
    this.ensureLayer({ id: 'lens-line', type: 'line', source: 'lens', paint: sectionsLinePaint() }, before);
    // The hovered township's own outline, over the lens sections (which
    // would otherwise paint over its hover border), in the township hover
    // stroke (see drawLensOutline).
    this.ensureLayer({
      id: 'lens-outline', type: 'line', source: 'lens-outline',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': GRID_HOVER_COLOR, 'line-opacity': 1, 'line-width': 2.5 },
    }, before);
    // The section whose popup is open, and the page's own section.
    this.ensureLayer({
      id: 'selected-line', type: 'line', source: 'selected',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': SELECTED_LINE.color, 'line-opacity': SELECTED_LINE.opacity, 'line-width': SELECTED_LINE.width },
    }, before);
    this.ensureLayer({
      id: 'highlight-line', type: 'line', source: 'highlight',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': HIGHLIGHT_LINE.color, 'line-opacity': HIGHLIGHT_LINE.opacity, 'line-width': HIGHLIGHT_LINE.width },
    }, before);
    this.ensureLayer({
      id: 'counties-line', type: 'line', source: 'counties',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': COUNTY_COLOR, 'line-width': 1.5, 'line-opacity': 0.8 },
    }, before);
    // The region this page is about, shaded faintly and outlined.
    this.ensureLayer({
      id: 'outline-fill', type: 'fill', source: 'outline',
      paint: { 'fill-color': OUTLINE_COLOR, 'fill-opacity': 0.08 },
    }, before);
    this.ensureLayer({
      id: 'outline-line', type: 'line', source: 'outline',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': OUTLINE_COLOR, 'line-width': 2.5, 'line-opacity': 0.9 },
    }, before);
    this.ensureLayer({
      id: 'locate-circle', type: 'circle', source: 'locate',
      paint: {
        'circle-radius': 6,
        'circle-color': LOCATE_COLOR,
        'circle-stroke-color': '#fff',
        'circle-stroke-width': 2,
      },
    }, before);
    this.restyleCounties();
    this.applyGridPaint();
    // Feature state (hover, the lens hosts) didn't survive a style swap:
    // forget the hovers (the next pointer move sets them again) and put
    // the lens hosts' state back if the lens is up.
    this.hoverIds = {};
    this.map.getCanvas().style.cursor = '';
    if (this.lensHosts) this.setHostFills(false);
  };

  // A locate button under the zoom buttons: zooms to the reader's square
  // mile and selects it (popup and outline), with a dot at their position.
  SectionMap.prototype.addLocateControl = function () {
    if (!navigator.geolocation) return;
    var self = this;
    this.locateControl = new BarControl('section-map-locate', 'Zoom to my location', 'fa-regular fa-location-crosshairs', function () {
      self.locate();
    });
    this.map.addControl(this.locateControl, 'top-left');
    this.locateEl = this.locateControl.container;
  };

  // A reset button under the locate button: back out to the map's home
  // framing (the whole valley, or the filtered county).
  SectionMap.prototype.addResetControl = function () {
    var self = this;
    this.resetControl = new BarControl('section-map-reset', 'Zoom out to the whole map', 'fa-regular fa-house', function () {
      self.resetView();
    });
    this.map.addControl(this.resetControl, 'top-left');
  };

  SectionMap.prototype.resetView = function () {
    var bounds = this.countyBounds[this.data.county] || this.valleyBounds;
    if (bounds) {
      this.map.fitBounds(bounds, { padding: 20, animate: !this.reducedMotion });
    } else {
      this.map.easeTo({
        center: lngLatOf(this.parseCenter(this.data.center) || [36.75, -119.80]),
        zoom: parseInt(this.data.zoom, 10) || 8,
        animate: !this.reducedMotion,
      });
    }
  };

  SectionMap.prototype.locate = function () {
    var self = this;
    if (this.locateEl) this.locateEl.classList.add('is-locating');
    this.setStatus('Finding your location…');
    navigator.geolocation.getCurrentPosition(function (position) {
      self.showLocation([position.coords.latitude, position.coords.longitude]);
    }, function () {
      if (self.locateEl) self.locateEl.classList.remove('is-locating');
      self.setStatus('Couldn\'t get your location');
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  };

  SectionMap.prototype.showLocation = function (latlng) {
    if (this.locateEl) this.locateEl.classList.remove('is-locating');
    this.setStatus('');
    this.setSourceData('locate', {
      type: 'Feature',
      properties: { id: 'me' },
      geometry: { type: 'Point', coordinates: lngLatOf(latlng) },
    });
    // Selecting the section has to wait for the section grid to be on the
    // map at this spot; the grid's render calls resolvePendingLocate when it is.
    this.pendingLocate = latlng;
    this.map.easeTo({ center: lngLatOf(latlng), zoom: this.sectionZoom(), animate: !this.reducedMotion });
    this.resolvePendingLocate();
  };

  SectionMap.prototype.drawRadius = function (center) {
    var radiusMiles = parseFloat(this.data.radius);
    if (!(radiusMiles > 0)) {
      this.setSourceData('radius', EMPTY);
      return;
    }
    var circle = circlePolygon(lngLatOf(center), milesToMeters(radiusMiles), 'radius');
    this.setSourceData('radius', circle);
    this.map.fitBounds(geometryBounds(circle), { animate: !this.reducedMotion });
  };

  // Keys whose change means the data on the map is different.
  var DATA_KEYS = ['year', 'chemical', 'product', 'commodity', 'county', 'concern'];

  // Take over a freshly rendered container (an htmx swap put a new page in
  // place): move this live map into its slot, read its data attributes, and
  // refetch only what changed. Keeping the map instance avoids the flash of
  // tearing the map down and reloading its basemap on every filter change.
  SectionMap.prototype.adopt = function (newEl) {
    var oldData = {};
    var key;
    for (key in this.el.dataset) oldData[key] = this.el.dataset[key];
    var newData = {};
    for (key in newEl.dataset) newData[key] = newEl.dataset[key];

    newEl.parentNode.replaceChild(this.el, newEl);
    for (key in oldData) {
      if (!(key in newData) && key !== 'rendered') delete this.el.dataset[key];
    }
    for (key in newData) this.el.dataset[key] = newData[key];
    this.el.dataset.rendered = '1';
    this.el.id = newEl.id;

    // A swap to a different page brings its own notices default with it;
    // adopt it so the checkbox and the layer agree with the page the reader
    // is now on. An unchanged attribute leaves their own toggle alone.
    var noticesDefaultChanged = (oldData.showNotices || '') !== (newData.showNotices || '');
    if (noticesDefaultChanged) {
      this.showNotices = newData.showNotices !== '0';
      this.loadedNoticeBounds = null;
      if (!this.showNotices) {
        // A request already in flight would otherwise land after the swap
        // and put the markers back on a page that doesn't want them.
        if (this.noticesAbort) this.noticesAbort.abort();
        this.clearNotices();
      }
    }

    var locationsDefaultChanged = (oldData.showLocations || '') !== (newData.showLocations || '');
    if (locationsDefaultChanged) {
      this.showLocations = newData.showLocations === '1';
      this.loadedLocationBounds = null;
      if (!this.showLocations) {
        if (this.locationsAbort) this.locationsAbort.abort();
        this.clearLocations();
      }
    }

    this.attachControls();
    this.map.resize();

    var dataChanged = DATA_KEYS.some(function (k) { return (oldData[k] || '') !== (newData[k] || ''); });
    var countyChanged = (oldData.county || '') !== (newData.county || '');
    var viewChanged = (oldData.center || '') !== (newData.center || '') || (oldData.zoom || '') !== (newData.zoom || '');
    var radiusChanged = (oldData.radius || '') !== (newData.radius || '');
    var outlineChanged = (oldData.outlineUrl || '') !== (newData.outlineUrl || '');

    if (outlineChanged) {
      this.clearOutline();
      this.loadOutline();
    }

    var center = this.parseCenter(this.data.center) || [36.75, -119.80];
    if (radiusChanged) {
      this.drawRadius(center);
    } else if (viewChanged) {
      this.map.easeTo({ center: lngLatOf(center), zoom: parseInt(this.data.zoom, 10) || 8, animate: !this.reducedMotion });
    }

    if (countyChanged) this.fitCounty();
    if (dataChanged) {
      this.loadedBounds = null;
      this.loadedNoticeBounds = null;
      // The cached lens/all-sections tiles were fetched under the old
      // filters; a fresh cache means in-flight fetches land in the old one
      // (fetchLensSections writes to the cache it started with) and any
      // all-sections run in progress stops scheduling work.
      this.lensCache = {};
      this.allSectionsRun = null;
      this.loadGrid();
      this.loadNotices();
      // The markers themselves don't change with the filters, but the block
      // totals in their popups do, so the layer is rebuilt either way.
      this.loadedLocationBounds = null;
      this.loadLocations();
    } else {
      if (noticesDefaultChanged && this.showNotices) this.loadNotices();
      if (locationsDefaultChanged && this.showLocations) this.loadLocations();
      // Same data; the legend/level notes are new elements and need filling.
      this.updateLegend();
      this.restyle();
    }
    this.updateLocationsNote();
  };

  // Releases the map (its WebGL context with it) once its page is gone:
  // requests in flight are cut short so nothing lands on a map that isn't
  // there, and the document-level listeners go with it.
  SectionMap.prototype.destroy = function () {
    this.abortRequests();
    this.allSectionsRun = null;
    this.cancelAllSectionsDraw();
    this.clearLens();
    this.closePopup();
    this.gridFeatures = [];
    this.gridById = {};
    if (this.resizeHandler) window.removeEventListener('resize', this.resizeHandler);
    if (this.escapeHandler) document.removeEventListener('keydown', this.escapeHandler);
    if (this.toolbarClickHandler) document.removeEventListener('click', this.toolbarClickHandler);
    if (this.toolbarKeyHandler) document.removeEventListener('keydown', this.toolbarKeyHandler);
    this.map.remove();
    this.map = null;
  };

  // County outlines never change with the filters, so they're fetched once.
  // Their bounds are what the reset button and the valley fit frame.
  SectionMap.prototype.loadCounties = function () {
    if (!this.data.countiesUrl) return;
    var self = this;
    var abort = this.startRequest('counties');
    fetchJson(this.data.countiesUrl, null, abort)
      .then(function (geojson) {
        if (self.countiesAbort !== abort) return;
        self.counties = geojson;
        self.countyBounds = {};
        self.valleyBounds = null;
        (geojson.features || []).forEach(function (feature) {
          var bounds = geometryBounds(feature);
          if (!bounds) return;
          var slug = feature.properties && feature.properties.slug;
          if (slug) self.countyBounds[slug] = bounds;
          self.valleyBounds = unionBounds(self.valleyBounds, bounds);
        });
        self.setSourceData('counties', geojson);
        self.fitCounty();
      })
      .catch(function (err) {
        if (isAbort(err) || self.countiesAbort !== abort) return;
        logError('failed to load counties', err);
      });
  };

  // With a county filter the map shows that county alone (the grid
  // endpoints leave the others out), so it also frames it: fit to the
  // county's outline, or back out to the whole valley when the filter goes.
  SectionMap.prototype.fitCounty = function () {
    if (!this.map || !this.counties) return;
    var target = this.countyBounds[this.data.county] || null;
    if (target) {
      this.map.fitBounds(target, { padding: 20, animate: !this.reducedMotion });
    } else if (this.data.fit === 'valley' && this.valleyBounds && (this.countyFitted || !this.valleyFitted)) {
      // Back out to the valley after a county filter, or frame it on first
      // load -- only on pages framed on the valley. A place or section page
      // frames itself (adopt() sets its view), and clearing the county
      // there must not zoom back out over it. The first-load fit snaps
      // rather than animating out from the placeholder view.
      var animate = !!this.valleyFitted && !this.reducedMotion;
      this.map.fitBounds(this.valleyBounds, { padding: 20, animate: animate });
      this.valleyFitted = true;
    }
    this.countyFitted = !!target;
  };

  // Draws the region this page is about (from the regions API) and fits the
  // map to it, so a city or ZIP page opens on the whole area, shaded.
  SectionMap.prototype.loadOutline = function () {
    if (!this.data.outlineUrl) return;
    var self = this;
    var abort = this.startRequest('outline');
    fetchJson(this.data.outlineUrl, null, abort)
      .then(function (payload) {
        if (self.outlineAbort !== abort) return;
        var region = payload && payload.data;
        var geometry = region && region.boundary && region.boundary.geometry;
        if (!geometry) return;
        var feature = { type: 'Feature', properties: { id: 'outline' }, geometry: geometry };
        self.setSourceData('outline', feature);
        self.map.fitBounds(geometryBounds(feature), { padding: 24, animate: !self.reducedMotion });
      })
      .catch(function (err) {
        if (isAbort(err) || self.outlineAbort !== abort) return;
        logError('failed to load the region outline', err);
      });
  };

  SectionMap.prototype.clearOutline = function () {
    this.setSourceData('outline', EMPTY);
  };

  // Dashed once the section grid is on, so the two don't compete.
  SectionMap.prototype.restyleCounties = function () {
    if (!this.map.getLayer('counties-line')) return;
    this.map.setPaintProperty('counties-line', 'line-dasharray', this.atSectionZoom() ? COUNTY_DASH : null);
  };

  SectionMap.prototype.enableScrollZoom = function () {
    this.map.scrollZoom.enable();
  };

  SectionMap.prototype.disableScrollZoom = function () {
    this.map.scrollZoom.disable();
  };

  SectionMap.prototype.parseCenter = function (value) {
    if (!value) return null;
    var parts = value.split(',');
    if (parts.length !== 2) return null;
    var lat = parseFloat(parts[0]);
    var lng = parseFloat(parts[1]);
    if (isNaN(lat) || isNaN(lng)) return null;
    return [lat, lng];
  };

  SectionMap.prototype.setStatus = function (message) {
    if (this.statusEl) this.statusEl.textContent = message || '';
  };

  SectionMap.prototype.onMetricChange = function (event) {
    this.metric = event.target.value;
    this.restyle();
    this.syncViewParams();
  };

  // The basemap style is part of the map's style, so swapping it rebuilds
  // the style outright (no diff, which would drop our layers without the
  // style.load that puts them back).
  SectionMap.prototype.onTilesChange = function (event) {
    this.tileStyle = event.target.value;
    this.map.setStyle(styleFor(this.tileStyle), { diff: false });
    this.syncViewParams();
  };

  SectionMap.prototype.onRampChange = function (event) {
    var name = event.target.value;
    if (!RAMPS[name]) return;
    RAMP = RAMPS[name];
    this.rampName = name;
    // The lens goes (restyle would otherwise redraw it first); the next
    // hover draws it with the new ramp.
    this.clearLens();
    this.restyle();
    this.syncViewParams();
  };

  SectionMap.prototype.onBinsChange = function (event) {
    NUM_CLASSES = +event.target.value;
    this.bins = NUM_CLASSES;
    this.clearLens();
    this.restyle();
    this.syncViewParams();
  };

  // Keep ?metric= and ?notices= in the address bar in step with the controls
  // so the current view can be linked to. Each is left off the URL while it
  // matches the page's default.
  SectionMap.prototype.syncViewParams = function () {
    if (!window.history || !window.history.replaceState || !window.URL) return;
    try {
      var url = new URL(window.location.href);
      if (this.metric === 'lbs_chemical') {
        url.searchParams.delete('metric');
      } else {
        url.searchParams.set('metric', this.metric);
      }
      var noticesDefault = this.data.showNotices !== '0';
      if (this.showNotices === noticesDefault) {
        url.searchParams.delete('notices');
      } else {
        url.searchParams.set('notices', this.showNotices ? '1' : '0');
      }
      var locationsDefault = this.data.showLocations === '1';
      if (this.showLocations === locationsDefault) {
        url.searchParams.delete('locations');
      } else {
        url.searchParams.set('locations', this.showLocations ? '1' : '0');
      }
      if (this.showAllSections) {
        url.searchParams.set('sections', '1');
      } else {
        url.searchParams.delete('sections');
      }
      // The experiment controls (basemap style, ramp) while a look is chosen.
      if (this.tileStyle && this.tileStyle !== this.defaultTileStyle) {
        url.searchParams.set('tiles', this.tileStyle);
      } else {
        url.searchParams.delete('tiles');
      }
      if (this.rampName && this.rampName !== 'blues') {
        url.searchParams.set('ramp', this.rampName);
      } else if (this.rampName) {
        url.searchParams.delete('ramp');
      }
      if (this.bins && this.bins !== DEFAULT_BINS) {
        url.searchParams.set('bins', this.bins);
      } else if (this.bins) {
        url.searchParams.delete('bins');
      }
      window.history.replaceState(window.history.state, '', url.toString());
    } catch (err) {
      // A malformed location is nothing to break the map over.
    }
  };

  SectionMap.prototype.commonParams = function () {
    return {
      year: this.data.year,
      chemical: this.data.chemical,
      product: this.data.product,
      commodity: this.data.commodity,
      county: this.data.county,
      concern: this.data.concern,
    };
  };

  // Aborts the request in flight under `name` (if any) and starts the
  // controller for the next one; the caller keeps the returned controller
  // to check it is still current when its response lands. One name covers
  // both grid levels: a pending section request is stale the moment we
  // decide to draw townships, and vice versa.
  SectionMap.prototype.startRequest = function (name) {
    var key = name + 'Abort';
    if (this[key]) this[key].abort();
    if (this.requestNames.indexOf(name) === -1) this.requestNames.push(name);
    var abort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    this[key] = abort;
    return abort;
  };

  // Cuts short every request in flight, whatever family it belongs to.
  SectionMap.prototype.abortRequests = function () {
    for (var i = 0; i < this.requestNames.length; i++) {
      var abort = this[this.requestNames[i] + 'Abort'];
      if (abort) abort.abort();
    }
  };

  // The zoom at which this viewport can show sections: SECTION_ZOOM, or
  // closer when the map is wide enough that zoom 11 would put more sections
  // in view than one request can return. Web Mercator: metres per pixel at
  // zoom z is 156543 * cos(lat) / 2^z.
  SectionMap.prototype.sectionZoom = function () {
    var canvas = this.map.getCanvas();
    var width = canvas.clientWidth;
    var height = canvas.clientHeight;
    var lat = this.map.getCenter().lat * Math.PI / 180;
    for (var zoom = SECTION_ZOOM; zoom < 18; zoom++) {
      var milesPerPx = 156543.03 * Math.cos(lat) / Math.pow(2, zoom) / METERS_PER_MILE;
      var squareMiles = width * height * milesPerPx * milesPerPx;
      if (squareMiles <= MAX_VIEWPORT_SECTIONS) return zoom;
    }
    return 18;
  };

  SectionMap.prototype.atSectionZoom = function () {
    return this.map.getZoom() >= this.sectionZoom();
  };

  // -- the grid --
  // Picks the grid for the current zoom: sections up close, townships
  // further out. Either way exactly one grid is in the `grid` source.
  SectionMap.prototype.loadGrid = function () {
    if (!this.map) return;
    // Mid-animation the viewport is nowhere yet: the moveend that ends the
    // animation loads the grid for where it lands. (A resize also fires
    // moveend, and its debounced load can fall inside a fit's animation.)
    if (this.map.isMoving()) return;
    var level = this.atSectionZoom() ? 'section' : 'township';
    // Crossing into section zoom with "all sections" on: stop loading more
    // blocks, but leave the layer up until the section grid replaces it
    // (renderGrid clears it), so the townships don't flash in between.
    if (level === 'section' && this.allSectionsRun) {
      this.allSectionsRun = null;
      this.cancelAllSectionsDraw();
      this.setStatus('');
    }
    // Crossing the section/township threshold always refetches; otherwise the
    // padded bbox we already hold may still cover the viewport.
    if (level === this.loadedLevel && this.covers(this.loadedBounds)) {
      // Same township grid, new viewport: "all sections" may need more blocks.
      if (level === 'township' && this.showAllSections) this.loadAllSections();
      return;
    }
    if (level === 'section') {
      this.loadSections();
    } else {
      this.loadTownships();
    }
  };

  // The viewport as [[west, south], [east, north]].
  SectionMap.prototype.mapBounds = function () {
    var bounds = this.map.getBounds();
    return [[bounds.getWest(), bounds.getSouth()], [bounds.getEast(), bounds.getNorth()]];
  };

  // True when `bounds` (from a previous padded fetch) still contains the
  // current viewport.
  SectionMap.prototype.covers = function (bounds) {
    return !!bounds && boundsContains(bounds, this.mapBounds());
  };

  SectionMap.prototype.fetchBounds = function (unpadded) {
    var bounds = this.mapBounds();
    return unpadded ? bounds : padBounds(bounds, BBOX_PAD);
  };

  SectionMap.prototype.loadSections = function (unpadded) {
    if (!this.data.sectionsUrl) return;
    var abort = this.startRequest('grid');
    var bounds = this.fetchBounds(unpadded);
    var params = this.commonParams();
    params.bbox = bboxParam(bounds);
    this.setStatus('Loading sections…');

    var self = this;
    fetchJson(this.data.sectionsUrl, params, abort)
      .then(function (geojson) {
        if (self.gridAbort !== abort) return; // stale response
        self.setStatus('');
        self.loadedBounds = bounds;
        self.loadedLevel = 'section';
        self.renderGrid(geojson, 'section');
      })
      .catch(function (err) {
        if (isAbort(err) || self.gridAbort !== abort) return;
        if (err.status === 400) {
          // The endpoint caps how many sections it will return, and the padded
          // bbox asks for more than the viewport needs. Try the bare viewport
          // once, then fall back to the township grid rather than leaving the
          // map bare.
          if (!unpadded) {
            self.loadSections(true);
          } else {
            self.loadTownships();
          }
          return;
        }
        if (err.status) {
          // The server answered, but not with a grid.
          self.clearGrid();
          if (self.legendEl) self.legendEl.innerHTML = '';
        } else {
          logError('failed to load sections', err);
        }
        self.loadedBounds = null;
        self.loadedLevel = null;
        self.setStatus('Couldn\'t load sections; try again');
      });
  };

  SectionMap.prototype.loadTownships = function () {
    if (!this.data.townshipsUrl) return;
    var abort = this.startRequest('grid');
    var bounds = this.fetchBounds();
    var params = this.commonParams();
    params.bbox = bboxParam(bounds);
    // Outlines don't change between years or filters, so after the first
    // load only the numbers are requested and the outlines are re-attached
    // from the cache (see attachTownshipGeometry). A township outside what
    // was cached (a wider bbox) falls back to a full request.
    var valuesOnly = !!this.townshipGeometry && this.townshipGeometryCovers(bounds);
    if (valuesOnly) params.geometry = '0';
    this.setStatus('Loading grid…');

    var self = this;
    fetchJson(this.data.townshipsUrl, params, abort)
      .then(function (geojson) {
        if (self.gridAbort !== abort) return; // stale response
        if (valuesOnly && !self.attachTownshipGeometry(geojson)) {
          // Something in view isn't in the outline cache: fetch it fully.
          self.townshipGeometry = null;
          self.loadTownships();
          return;
        }
        if (!valuesOnly) self.rememberTownshipGeometry(geojson, bounds);
        self.setStatus('');
        self.loadedBounds = bounds;
        self.loadedLevel = 'township';
        self.renderGrid(geojson, 'township');
        if (self.showAllSections) self.loadAllSections();
      })
      .catch(function (err) {
        if (isAbort(err) || self.gridAbort !== abort) return;
        logError('failed to load townships', err);
        self.clearGrid();
        self.loadedBounds = null;
        self.loadedLevel = null;
        if (self.legendEl) self.legendEl.innerHTML = '';
        self.setStatus('Couldn\'t load the grid; try again');
      });
  };

  SectionMap.prototype.rememberTownshipGeometry = function (geojson, bounds) {
    var cache = {};
    (geojson.features || []).forEach(function (feature) {
      cache[feature.id || feature.properties.id] = feature.geometry;
    });
    this.townshipGeometry = cache;
    this.townshipGeometryBounds = [[bounds[0][0], bounds[0][1]], [bounds[1][0], bounds[1][1]]];
  };

  SectionMap.prototype.townshipGeometryCovers = function (bounds) {
    return !!this.townshipGeometryBounds && boundsContains(this.townshipGeometryBounds, bounds);
  };

  // Puts cached outlines back onto a values-only response; false if any
  // feature has no cached outline.
  SectionMap.prototype.attachTownshipGeometry = function (geojson) {
    var cache = this.townshipGeometry || {};
    var features = geojson.features || [];
    for (var i = 0; i < features.length; i++) {
      var geometry = cache[features[i].id || features[i].properties.id];
      if (!geometry) return false;
      features[i].geometry = geometry;
    }
    return true;
  };

  SectionMap.prototype.allSectionsActive = function () {
    return this.showAllSections && this.level === 'township';
  };

  // Writes each feature's shade onto its properties for the paint to read:
  // `value` (the metric, 0 for none), `fill`, and `opacity` from
  // `opacities` ([with data, without]).
  SectionMap.prototype.classFeatures = function (features, classes, opacities) {
    var metric = this.metric;
    for (var i = 0; i < features.length; i++) {
      var props = features[i].properties;
      var value = Number(props[metric]) || 0;
      props.value = value;
      props.fill = colorFor(classes, value);
      props.opacity = value ? opacities[0] : opacities[1];
    }
  };

  SectionMap.prototype.renderGrid = function (geojson, level) {
    var self = this;
    var reopenId = this.openGridId;
    this.level = level;
    var features = (geojson && geojson.features) || [];
    this.currentClasses = quantileClasses(features.map(function (feature) { return feature.properties[self.metric]; }));
    this.currentClassesAreSections = false;

    // The lens and the "all sections" layer were drawn over the grid this
    // one replaces; the selected section's outline comes back with
    // whichever section layer next holds it (see reopenSelectedSection).
    this.clearLens();
    this.resetAllSections();
    this.showSelectedOutline(null);
    this.clearHover('grid');

    this.gridFeatures = features;
    this.gridById = {};
    for (var i = 0; i < features.length; i++) this.gridById[features[i].properties.id] = features[i];
    this.classFeatures(features, this.currentClasses, GRID_OPACITY);
    this.setSourceData('grid', { type: 'FeatureCollection', features: features });
    this.applyGridPaint();
    this.updateHighlight();
    this.updateLegend();
    this.reopenGridPopup(reopenId);
    if (level === 'section') {
      this.reopenSelectedSection(features, 'grid');
      this.resolvePendingLocate();
    }
  };

  SectionMap.prototype.clearGrid = function () {
    this.clearLens();
    this.resetAllSections();
    this.showSelectedOutline(null);
    this.clearHover('grid');
    // No grid cell is left for a popup to belong to (clearLens and
    // resetAllSections above keep theirs only for a grid about to load).
    if (this.popup && ['openGridId', 'openLensId', 'openAllSectionsId'].indexOf(this.popupKey) !== -1) this.closePopup();
    this.gridFeatures = [];
    this.gridById = {};
    this.setSourceData('grid', EMPTY);
    this.setSourceData('highlight', EMPTY);
  };

  // The grid's paint follows the level (township lines are a touch
  // heavier, and their hover stroke too) and, with every section drawn on
  // top ("all sections"), the township grid steps aside: no fill, no line,
  // just the interactive shape.
  SectionMap.prototype.applyGridPaint = function () {
    if (!this.map || !this.map.getLayer('grid-fill')) return;
    var hidden = this.allSectionsActive();
    var township = this.level === 'township';
    this.map.setPaintProperty('grid-fill', 'fill-opacity', hidden ? 0 : GRID_FILL_OPACITY);
    this.map.setPaintProperty('grid-line', 'line-opacity', hidden ? 0 : hoverCase(1, GRID_LINE.opacity));
    this.map.setPaintProperty('grid-line', 'line-width', hoverCase(township ? 2.5 : 2, township ? 0.75 : 0.5));
  };

  // The page's own section (a section page) wears an orange outline while
  // the section grid is up.
  SectionMap.prototype.updateHighlight = function () {
    var feature = this.level === 'section' && this.data.highlight ? this.gridById[this.data.highlight] : null;
    this.setSourceData('highlight', feature || EMPTY);
  };

  // Reclasses the grid (a metric, ramp, or bins change) and reshades it in
  // place; a township popup's headline follows the metric.
  SectionMap.prototype.restyle = function () {
    if (!this.map || !this.gridFeatures.length) return;
    var self = this;
    this.currentClasses = quantileClasses(this.gridFeatures.map(function (feature) { return feature.properties[self.metric]; }));
    this.currentClassesAreSections = false;
    this.classFeatures(this.gridFeatures, this.currentClasses, GRID_OPACITY);
    this.setSourceData('grid', { type: 'FeatureCollection', features: this.gridFeatures });
    this.applyGridPaint();
    this.updateHighlight();
    if (this.level === 'township' && this.popup && this.popupKey === 'openGridId') {
      var feature = this.gridById[this.popupId];
      if (feature) this.popup.setHTML(this.townshipPopupHtml(feature.properties, latLngOf(boundsCenter(featureBounds(feature)))));
    }
    // A lens that's up (a metric change under it, possibly pinned by one
    // of its popups) is reclassed in place rather than left in the old
    // metric's shades over townships that just got their fill back.
    if (this.lensId && this.lensFeatures.length) this.drawLens(this.lensId, this.lensFeatures);
    if (this.allSectionsActive() && this.allSectionsAdded) {
      this.restyleAllSections();
    } else {
      this.updateLegend();
    }
  };

  // Sections drawn at the township zoom (the lens, "all sections") switch
  // between fill-only and stroked across SECTION_LINES_MIN_ZOOM. The paint
  // does that by itself (a zoom step), so crossing it only drops the lens,
  // which is redrawn with the right strokes on the next hover.
  SectionMap.prototype.restyleSectionLines = function () {
    var lines = this.map.getZoom() >= SECTION_LINES_MIN_ZOOM;
    if (lines === this.sectionLinesShown) return;
    this.sectionLinesShown = lines;
    this.clearLens();
  };

  SectionMap.prototype.legendUnit = function () {
    var unit = METRIC_UNITS[this.metric] || '';
    return this.level === 'township' && !this.allSectionsActive() ? unit + ' per township' : unit;
  };

  SectionMap.prototype.updateLegend = function () {
    if (this.legendEl) {
      renderLegend(this.legendEl, this.currentClasses, this.legendUnit());
      this.appendMarkerLegend();
    }
    // "All sections" only means something at the township zoom.
    var sectionsToggle = this.controlsEl ? this.controlsEl.querySelector('input[name="sections"]') : null;
    if (sectionsToggle) sectionsToggle.disabled = this.level === 'section';
    if (this.levelEl) {
      this.levelEl.textContent = this.allSectionsActive() ? LEVEL_TEXT.allSections : (LEVEL_TEXT[this.level] || '');
    }
    this.updateLocationsNote();
  };

  // -- hover and click --
  // Bound once: the SDK keeps layer listeners across style swaps and skips
  // a layer that isn't in the style yet.
  SectionMap.prototype.bindGridEvents = function () {
    var self = this;
    var map = this.map;
    map.on('mousemove', 'grid-fill', function (event) {
      // Under "all sections" the townships are only click plumbing.
      if (self.allSectionsActive()) return;
      var id = event.features[0].id;
      if (self.level === 'township') {
        // Hovering a township brings up its lens; the pointer is still
        // over the township while it's over one of the lens sections, so
        // a scheduled clear is cancelled here as well as there.
        self.cancelLensClear();
        if (self.lensId !== id) {
          var feature = self.gridById[id];
          if (feature) self.showLens(feature);
        }
      }
      self.setHover('grid', id);
    });
    map.on('mouseleave', 'grid-fill', function () {
      self.clearHover('grid');
      // Off the grid: the lens goes after its grace, unless the pointer
      // comes back onto a township (or one of the lens sections) first.
      if (self.level === 'township' && self.lensId) self.scheduleLensClear();
    });
    // The lens sections cover the townships, so this is where a move into
    // a neighbouring township is noticed too: recentre the lens on it.
    map.on('mousemove', 'lens-fill', function (event) {
      self.cancelLensClear();
      var feature = findFeature(self.lensFeatures, event.features[0].id);
      if (!feature || self.recentreLens(feature)) return;
      self.setHover('lens', event.features[0].id);
    });
    map.on('mouseleave', 'lens-fill', function () {
      self.clearHover('lens');
      // Delegated listeners run in binding order within one event, so on
      // a move from a lens section straight onto a township outside the
      // block the grid handler above has already recentred the lens on it
      // (and hovered it) by the time this runs; scheduling a clear then
      // would drop the new lens once the pointer rests (nothing cancels
      // it). Leaving the grid altogether clears the township hover first
      // (its own mouseleave), so the clear is scheduled only then.
      if (self.hoverIds.grid != null && self.hoverIds.grid === self.lensId) return;
      self.scheduleLensClear();
    });
    map.on('mousemove', 'all-sections-fill', function (event) {
      self.setHover('all-sections', event.features[0].id);
    });
    map.on('mouseleave', 'all-sections-fill', function () { self.clearHover('all-sections'); });
    // Sections drawn over the townships take the click; a township is
    // reached where no section covers it. Layer listeners fire in the order
    // they're bound, so the section ones mark the event as taken.
    map.on('click', 'lens-fill', function (event) {
      var feature = findFeature(self.lensFeatures, event.features[0].id);
      if (!feature) return;
      event.originalEvent.sectionMapTaken = true;
      self.showSectionPopup(feature, 'lens');
    });
    map.on('click', 'all-sections-fill', function (event) {
      var feature = self.allSectionsById[event.features[0].id];
      if (!feature) return;
      event.originalEvent.sectionMapTaken = true;
      self.showSectionPopup(feature, 'all-sections');
    });
    map.on('click', 'grid-fill', function (event) {
      if (event.originalEvent.sectionMapTaken) return;
      var feature = self.gridById[event.features[0].id];
      if (!feature) return;
      if (self.level === 'township') {
        self.openTownshipPopup(feature);
      } else {
        self.showSectionPopup(feature, 'grid');
      }
    });
  };

  // Hover is a feature state, one cell per source (the township under the
  // pointer and the lens section over it are hovered together); the line
  // paint reads it (see addBaseLayers). The cursor is a pointer over any
  // hovered cell.
  SectionMap.prototype.setHover = function (source, id) {
    if (this.hoverIds[source] === id) return;
    this.clearHover(source);
    this.hoverIds[source] = id;
    this.map.setFeatureState({ source: source, id: id }, { hover: true });
    this.map.getCanvas().style.cursor = 'pointer';
  };

  SectionMap.prototype.clearHover = function (source) {
    if (!this.map || this.hoverIds[source] == null) return;
    if (this.map.getSource(source)) this.map.setFeatureState({ source: source, id: this.hoverIds[source] }, { hover: false });
    delete this.hoverIds[source];
    if (!Object.keys(this.hoverIds).length) this.map.getCanvas().style.cursor = '';
  };

  // -- popups --
  // One popup at a time, in the SDK's popup with the Leaflet popups' class
  // hooks, rising from the cell's centre. It stays until its close button
  // or another cell is clicked; clicking empty map (or a pan that ends on
  // it) doesn't dismiss it. `key` (openGridId, openAllSectionsId,
  // openLensId) records whose popup is up so a rebuilt layer can put it
  // back (see reopenGridPopup, reopenSelectedSection).
  SectionMap.prototype.openPopup = function (lngLat, html, key, id) {
    var self = this;
    if (this.popupKey && this[this.popupKey] === this.popupId) this[this.popupKey] = null;
    // Opening another feature's popup is letting go of this one: a
    // selected section loses its selection (a township popup replacing a
    // lens or all-sections section's; a section's own reopen keeps it).
    if (this.popupId && this.popupId !== id && this.selectedSectionId === this.popupId) this.clearSelection();
    this.popupKey = key;
    this.popupId = id;
    this[key] = id;
    if (this.popup) {
      // Moving the one popup rather than replacing it keeps a section's
      // popup from blinking when its grid is rebuilt under it.
      this.popup.setLngLat(lngLat).setHTML(html);
      return this.popup;
    }
    var popup = new maptilersdk.Popup({
      className: 'section-popup-wrap',
      maxWidth: POPUP_MAX_WIDTH,
      closeButton: true,
      closeOnClick: false,
      focusAfterOpen: false,
    });
    popup.setLngLat(lngLat).setHTML(html).addTo(this.map);
    popup.on('close', function () {
      // Only a close with the popup still current is the reader letting
      // go; closePopup() has already let go of the ones it removes.
      if (self.popup !== popup) return;
      self.popup = null;
      var closedKey = self.popupKey;
      var closedId = self.popupId;
      self.popupKey = null;
      self.popupId = null;
      if (closedKey && self[closedKey] === closedId) self[closedKey] = null;
      if (closedId && self.selectedSectionId === closedId) self.clearSelection();
      // A lens section's popup was pinning the lens; it's let go of too.
      if (closedKey === 'openLensId') self.scheduleLensClear();
    });
    this.popup = popup;
    this.bindPopupButtons(popup.getElement());
    return popup;
  };

  // Takes the popup down on the map's own account (a rebuilt layer, a
  // zoom), which is not the reader letting go: the selected section stays
  // selected and comes back with its popup wherever the section next
  // appears. The reader's own closes go through the popup's close event.
  SectionMap.prototype.closePopup = function () {
    var popup = this.popup;
    if (!popup) return;
    this.popup = null;
    if (this.popupKey && this[this.popupKey] === this.popupId) this[this.popupKey] = null;
    this.popupKey = null;
    this.popupId = null;
    popup.remove();
  };

  // The "Zoom in" buttons are served by one listener on the popup's outer
  // element, which survives setHTML replacing the content.
  SectionMap.prototype.bindPopupButtons = function (container) {
    var self = this;
    if (!container || container.getAttribute('data-zoom-bound')) return;
    container.setAttribute('data-zoom-bound', '1');
    container.addEventListener('click', function (click) {
      var button = click.target.closest ? click.target.closest('.section-map-zoom') : null;
      if (!button) return;
      var lat = parseFloat(button.getAttribute('data-lat'));
      var lng = parseFloat(button.getAttribute('data-lng'));
      if (!isFinite(lat) || !isFinite(lng)) return;
      // A section popup rides through the zoom: the section grid that
      // loads at the new zoom re-opens the popup for this id (see
      // reopenGridPopup). A township popup just closes.
      var sectionId = button.getAttribute('data-id');
      if (sectionId) {
        self.openGridId = sectionId;
      } else {
        self.closePopup();
      }
      self.map.easeTo({ center: [lng, lat], zoom: self.sectionZoom(), animate: !self.reducedMotion });
    });
  };

  // "in 2023", or "across 2014–2023" when the map sums every year.
  SectionMap.prototype.yearPhrase = function () {
    var label = this.data.yearLabel || this.data.year;
    if (!label) return '';
    return (this.data.year === 'all' ? ' across ' : ' in ') + escapeHtml(label);
  };

  // The headline figure of a grid popup: "5,966 lbs applied in 2023" or
  // "312 applications in 2023", following the metric toggle.
  SectionMap.prototype.metricLine = function (props) {
    var value = formatNumber(props[this.metric] || 0);
    var year = this.yearPhrase();
    var text = this.metric === 'applications'
      ? '<strong>' + value + '</strong> application' + (props.applications === 1 ? '' : 's') + year
      : '<strong>' + value + ' lbs</strong> applied' + year;
    return '<p class="section-popup-metric">' + text + '</p>';
  };

  SectionMap.prototype.townshipPopupHtml = function (props, center) {
    var sections = props.sections || 0;
    // The target is carried on the button so the popup's own listener (see
    // bindPopupButtons) can serve it after the content is replaced.
    return (
      '<div class="section-popup">' +
      '<h4>' + escapeHtml(props.name || props.id) + '</h4>' +
      '<p class="section-popup-sub">Township · ' + formatNumber(sections) + ' square-mile section' + (sections === 1 ? '' : 's') + '</p>' +
      this.metricLine(props) +
      '<div class="section-popup-actions"><button type="button" class="section-popup-action section-map-zoom" data-lat="' + center.lat + '" data-lng="' + center.lng + '">' +
      '<span class="fa-regular fa-fw fa-magnifying-glass-plus"></span> Zoom in to sections</button></div>' +
      '</div>'
    );
  };

  SectionMap.prototype.openTownshipPopup = function (feature) {
    var center = boundsCenter(featureBounds(feature));
    this.openPopup(center, this.townshipPopupHtml(feature.properties, latLngOf(center)), 'openGridId', feature.properties.id);
  };

  // `detailHtml` is the top-chemicals block: a list once loaded, a loading
  // or empty note otherwise.
  // `center` is passed when the popup was opened from the lens; the
  // township popup is unreachable there (the sections cover it),
  // so its "zoom in" action rides along on the section popup instead.
  SectionMap.prototype.sectionPopupHtml = function (props, detailHtml, center) {
    var sub = 'Square-mile section' + (props.county ? ' · ' + escapeHtml(shortCounty(props.county)) : '');
    var url = this.sectionUrl(props.id);
    var links = url
      ? '<a class="section-popup-action" href="' + escapeHtml(url) + '"><span class="fa-regular fa-fw fa-circle-info"></span> Section details</a>'
      : '';
    if (center && this.level === 'township') {
      links += '<button type="button" class="section-popup-action section-map-zoom" data-id="' + escapeHtml(props.id) + '" data-lat="' + center.lat + '" data-lng="' + center.lng + '">' +
        '<span class="fa-regular fa-fw fa-magnifying-glass-plus"></span> Zoom in</button>';
    }
    return (
      '<div class="section-popup">' +
      '<h4>' + escapeHtml(props.mtrs || props.id) + '</h4>' +
      '<p class="section-popup-sub">' + sub + '</p>' +
      this.metricLine(props) +
      '<p class="section-popup-label">Top chemicals</p>' +
      detailHtml +
      '<div class="section-popup-actions">' + links + '</div>' +
      '</div>'
    );
  };

  // The open popup's section wears SELECTED_LINE (the `selected` source's
  // outline) for as long as the popup is up.
  SectionMap.prototype.selectSection = function (id, feature) {
    this.selectedSectionId = id;
    this.showSelectedOutline(feature);
  };

  SectionMap.prototype.clearSelection = function () {
    this.selectedSectionId = null;
    this.showSelectedOutline(null);
  };

  // The outline is drawn only while a section layer holds the section (the
  // section grid, the lens, "all sections"); the selection itself outlives
  // the layer.
  SectionMap.prototype.showSelectedOutline = function (feature) {
    this.setSourceData('selected', feature || EMPTY);
  };

  // After a layer of sections is (re)built, put the selected section's
  // popup back on it if it's there.
  SectionMap.prototype.reopenSelectedSection = function (features, source) {
    var id = this.selectedSectionId;
    if (!id || !features) return;
    var feature = findFeature(features, id);
    if (!feature) return;
    if (this.popup && this.popupId === id) {
      this.showSelectedOutline(feature);
      return;
    }
    this.showSectionPopup(feature, source);
  };

  // A refetch rebuilds the grid; if the popup that was open belongs to a
  // feature that's still there, put it back rather than making the reader
  // click again. A popup whose feature is gone goes with it.
  SectionMap.prototype.reopenGridPopup = function (id) {
    var feature = id ? this.gridById[id] : null;
    if (feature) {
      if (this.level === 'township') {
        this.openTownshipPopup(feature);
      } else {
        this.showSectionPopup(feature, 'grid');
      }
    } else if (this.popup) {
      this.closePopup();
    }
  };

  // `source` says which layer the section was clicked on ('grid',
  // 'all-sections', or 'lens'), which is whose popup this is.
  SectionMap.prototype.showSectionPopup = function (feature, source) {
    var self = this;
    var props = feature.properties;
    var center = boundsCenter(featureBounds(feature));
    var latlng = latLngOf(center);
    var key = source === 'grid' ? 'openGridId' : (source === 'lens' ? 'openLensId' : 'openAllSectionsId');
    this.openPopup(center, this.sectionPopupHtml(props, '<p class="section-popup-note">Loading…</p>', latlng), key, props.id);
    this.selectSection(props.id, feature);

    if (!this.data.sectionUrlPattern) return;
    var url = this.data.sectionUrlPattern.replace('{id}', props.id) + '?year=' + encodeURIComponent(this.data.year || '');
    fetchJson(url)
      .then(function (detail) {
        if (!self.popup || self.popupId !== props.id) return; // popup was closed before this resolved
        var chemicals = (detail && detail.top_chemicals) || [];
        var detailHtml = '<p class="section-popup-note">No use reported' + (self.data.year === 'all' ? ' in any year.' : ' this year.') + '</p>';
        if (chemicals.length) {
          detailHtml = '<ul class="section-popup-chems">' + chemicals.slice(0, 3).map(function (c) {
            return '<li>' +
              '<span class="name' + (c.is_of_concern ? ' is-of-concern' : '') + '">' + linkHtml(self.chemicalUrl(c.id), c.display_name || c.name) + '</span>' +
              '<span class="amount">' + formatNumber(c.lbs) + ' lbs</span>' +
              '</li>';
          }).join('') + '</ul>';
        }
        self.popup.setHTML(self.sectionPopupHtml(props, detailHtml, latlng));
      })
      .catch(function (err) {
        logError('failed to load section detail', err);
        if (!self.popup || self.popupId !== props.id) return;
        self.popup.setHTML(self.sectionPopupHtml(props, '<p class="section-popup-note">Couldn\'t load the top chemicals.</p>', latlng));
      });
  };

  SectionMap.prototype.chemicalUrl = function (id) {
    return fillUrl(this.data.chemicalPageUrl, id);
  };

  SectionMap.prototype.sectionUrl = function (id) {
    return fillUrl(this.data.sectionPageUrl, id);
  };

  SectionMap.prototype.productUrl = function (id) {
    return fillUrl(this.data.productPageUrl, id);
  };

  SectionMap.prototype.noticeUrl = function (id) {
    return fillUrl(this.data.noticePageUrl, id);
  };

  // The located point is held until the section grid for its viewport is
  // on the map (renderGrid calls this after a section load); then the
  // section under it opens.
  SectionMap.prototype.resolvePendingLocate = function () {
    var latlng = this.pendingLocate;
    if (!latlng || this.level !== 'section' || !this.gridFeatures.length) return;
    var point = lngLatOf(latlng);
    if (!boundsContainsPoint(this.mapBounds(), point)) return;
    var hit = null;
    for (var i = 0; i < this.gridFeatures.length && !hit; i++) {
      if (boundsContainsPoint(featureBounds(this.gridFeatures[i]), point)) hit = this.gridFeatures[i];
    }
    if (!hit) {
      // Grid loaded but nothing under the point (outside the valley's
      // sections): nothing to select, and nothing more to wait for.
      if (this.loadedBounds && boundsContainsPoint(this.loadedBounds, point)) this.pendingLocate = null;
      return;
    }
    this.pendingLocate = null;
    this.showSectionPopup(hit, 'grid');
  };

  // -- "all sections" --
  // At the township zoom, every section in the padded viewport is drawn
  // instead of the township grid. Sections load in the same 5x5 township
  // blocks the lens prefetches, a few at a time, and go into the same
  // per-township cache, so the two modes share their work.
  SectionMap.prototype.visibleTownships = function () {
    if (this.level !== 'township') return [];
    var bounds = padBounds(this.mapBounds(), 0.15);
    return this.gridFeatures.filter(function (feature) {
      var featureBox = featureBounds(feature);
      return !!featureBox && boundsIntersects(featureBox, bounds);
    });
  };

  SectionMap.prototype.loadAllSections = function () {
    if (!this.showAllSections || this.level !== 'township' || !this.gridFeatures.length || !this.data.sectionsUrl) return;
    var self = this;
    // Uncached townships are tiled into a fixed 5x5-township grid of
    // blocks, so a valley-wide view is ~36 requests of ~25 townships each
    // (well under the endpoint's cap) rather than a request per hover-sized
    // neighbourhood.
    var tiles = {};
    var blocks = [];
    var tileLng = TOWNSHIP_DEGREES.lng * 5;
    var tileLat = TOWNSHIP_DEGREES.lat * 5;
    this.visibleTownships().forEach(function (host) {
      if (self.lensCache[host.properties.id]) return;
      var center = boundsCenter(featureBounds(host));
      var key = Math.floor(center[0] / tileLng) + ':' + Math.floor(center[1] / tileLat);
      if (!tiles[key]) {
        tiles[key] = [];
        blocks.push(tiles[key]);
      }
      tiles[key].push(host);
    });

    // Draw what's cached right away; the blocks fill in as they land.
    this.drawAllSections();
    if (!blocks.length) return;

    // A new run supersedes any in flight: its callbacks see a different
    // token and stop scheduling more work (fetches already started finish
    // and still land in the cache).
    var run = { total: blocks.length, done: 0 };
    this.allSectionsRun = run;
    var queue = blocks.slice();
    var active = 0;
    var next = function () {
      if (self.allSectionsRun !== run) return;
      while (active < ALL_SECTIONS_CONCURRENCY && queue.length) {
        active += 1;
        self.fetchLensSections(queue.shift(), function () {
          active -= 1;
          if (self.allSectionsRun !== run) return;
          run.done += 1;
          self.setStatus(run.done < run.total ? 'Loading sections… ' + run.done + ' of ' + run.total : '');
          // New sections join the layer at once, styled by the current
          // classes; the classes themselves (and so every section's shade)
          // are refreshed on a throttle while blocks land, and once more
          // when the last one has.
          self.drawAllSections();
          if (run.done < run.total) {
            self.scheduleAllSectionsDraw();
          } else {
            self.cancelAllSectionsDraw();
            self.restyleAllSections();
          }
          next();
        });
      }
    };
    this.setStatus('Loading sections… 0 of ' + run.total);
    next();
  };

  SectionMap.prototype.scheduleAllSectionsDraw = function () {
    if (this.allSectionsDrawTimer) return;
    var self = this;
    this.allSectionsDrawTimer = setTimeout(function () {
      self.allSectionsDrawTimer = null;
      self.restyleAllSections();
    }, ALL_SECTIONS_REDRAW_MS);
  };

  SectionMap.prototype.cancelAllSectionsDraw = function () {
    if (this.allSectionsDrawTimer) {
      clearTimeout(this.allSectionsDrawTimer);
      this.allSectionsDrawTimer = null;
    }
  };

  // One request for a set of townships: the bbox is the union of their
  // bounds, and the response is filed per township so any later hover over
  // one of them draws from cache. `done` runs after filing (also on
  // failure, so a draw can still proceed with whatever is cached). Not
  // abortable: a superseded fetch's result is either still-good cache, or
  // lands in a cache adopt() has already replaced (see below).
  SectionMap.prototype.fetchLensSections = function (hosts, done) {
    var ids = hosts.map(function (host) { return host.properties.id; });
    var union = null;
    hosts.forEach(function (host) { union = unionBounds(union, featureBounds(host)); });
    var params = this.commonParams();
    params.bbox = bboxParam(union);
    // Results go into the cache that was current when the fetch started:
    // if the filters change meanwhile, adopt() swaps in a fresh cache and
    // this one is simply dropped.
    var cache = this.lensCache;
    fetchJson(this.data.sectionsUrl, params)
      .then(function (body) {
        if (!body || !body.features) return;
        var byTownship = {};
        ids.forEach(function (townshipId) { byTownship[townshipId] = []; });
        body.features.forEach(function (section) {
          var mtrs = section.properties.mtrs || '';
          var townshipId = mtrs.slice(0, mtrs.lastIndexOf('-'));
          if (byTownship[townshipId]) byTownship[townshipId].push(section);
        });
        ids.forEach(function (townshipId) { cache[townshipId] = byTownship[townshipId]; });
      })
      .catch(function () {})
      .then(function () { if (done) done(); });
  };

  SectionMap.prototype.cachedLensSections = function (ids) {
    var self = this;
    return ids.reduce(function (all, townshipId) {
      return all.concat(self.lensCache[townshipId] || []);
    }, []);
  };

  // Adds any cached, visible sections that aren't drawn yet. The source is
  // grown, never rebuilt: the SDK applies the additions in its worker,
  // which costs less than re-sending every polygon each time a block lands.
  SectionMap.prototype.drawAllSections = function () {
    if (!this.showAllSections || this.level !== 'township' || !this.gridFeatures.length) return;
    var self = this;
    if (!this.allSectionsAdded) {
      this.allSectionsAdded = {};
      this.allSectionsFeatures = [];
      this.allSectionsById = {};
      // The township grid steps aside (see applyGridPaint) once the layer
      // is up; the legend follows in restyleAllSections.
      this.applyGridPaint();
    }

    var fresh = [];
    this.visibleTownships().forEach(function (host) {
      var id = host.properties.id;
      if (self.allSectionsAdded[id] || !self.lensCache[id]) return;
      self.allSectionsAdded[id] = true;
      fresh = fresh.concat(self.lensCache[id]);
    });
    if (!fresh.length) {
      if (!this.currentClassesAreSections) this.restyleAllSections();
      return;
    }
    this.allSectionsFeatures = this.allSectionsFeatures.concat(fresh);
    for (var i = 0; i < fresh.length; i++) this.allSectionsById[fresh[i].properties.id] = fresh[i];
    // First sections in: classes over them so they don't draw unshaded.
    if (!this.currentClassesAreSections) {
      this.currentClasses = quantileClasses(this.allSectionsFeatures.map(function (f) { return f.properties[self.metric]; }));
      this.currentClassesAreSections = true;
      this.updateLegend();
    }
    this.classFeatures(fresh, this.currentClasses, LENS_OPACITY);
    this.updateAllSectionsSource({ add: fresh });
    this.reopenSelectedSection(this.allSectionsFeatures, 'all-sections');
  };

  // Recomputes the classes over everything drawn and reshades it; also
  // what a metric change calls.
  SectionMap.prototype.restyleAllSections = function () {
    if (!this.allSectionsAdded) return;
    var self = this;
    this.currentClasses = quantileClasses(this.allSectionsFeatures.map(function (f) { return f.properties[self.metric]; }));
    this.currentClassesAreSections = true;
    this.classFeatures(this.allSectionsFeatures, this.currentClasses, LENS_OPACITY);
    this.updateAllSectionsSource({
      update: this.allSectionsFeatures.map(function (f) {
        var props = f.properties;
        return {
          id: props.id,
          addOrUpdateProperties: [
            { key: 'value', value: props.value },
            { key: 'fill', value: props.fill },
            { key: 'opacity', value: props.opacity },
          ],
        };
      }),
    });
    this.updateLegend();
  };

  // Applies a change to the "all sections" source as a diff the SDK works
  // through in its worker (added features, or new shades on the drawn
  // ones), keeping the whole collection on the instance for the next style
  // load. Falls back to resetting the source where diffs aren't supported.
  SectionMap.prototype.updateAllSectionsSource = function (diff) {
    var data = { type: 'FeatureCollection', features: this.allSectionsFeatures };
    this.sourceData['all-sections'] = data;
    var source = this.map ? this.map.getSource('all-sections') : null;
    if (!source) return;
    if (typeof source.updateData === 'function') {
      source.updateData(diff);
    } else {
      source.setData(data);
    }
  };

  // `keepFlag` leaves the toggle on (a zoom to section level, where the
  // mode is moot) rather than turning it off.
  SectionMap.prototype.clearAllSections = function (keepFlag) {
    this.allSectionsRun = null;
    this.cancelAllSectionsDraw();
    if (!keepFlag) this.showAllSections = false;
    if (this.allSectionsAdded) {
      // The mode is going, so a popup on one of its sections goes with it
      // (nothing is about to reopen it); the selection outlives the layer.
      if (this.popup && this.popupKey === 'openAllSectionsId') this.closePopup();
      this.resetAllSections();
      this.setStatus('');
      if (this.gridFeatures.length) this.restyle();
    }
  };

  // Drops the drawn sections and their state; the cache stays. A popup on
  // one of them goes too, unless what loads next is going to reopen it:
  // the section grid after its "Zoom in" button (openGridId), or the
  // section layer that next holds the selected section.
  SectionMap.prototype.resetAllSections = function () {
    this.clearHover('all-sections');
    if (this.popup && this.popupKey === 'openAllSectionsId' && this.openGridId !== this.popupId && this.selectedSectionId !== this.popupId) this.closePopup();
    this.allSectionsAdded = null;
    this.allSectionsFeatures = [];
    this.allSectionsById = {};
    this.currentClassesAreSections = false;
    this.setSourceData('all-sections', EMPTY);
    this.applyGridPaint();
  };

  // -- the lens --
  // Zoomed out, hovering a township shows the sections of that township
  // and its neighbours (its Moore neighborhood, a 3x3 block), shaded by the
  // same metric with quantile classes over the block, so the reader can
  // see where within the neighborhood the use concentrates. Each section
  // can be hovered and clicked like the zoomed-in grid. The sections come
  // from the same endpoint the zoomed-in grid uses and are kept per
  // township for the life of the map (lensCache, shared with "all
  // sections").

  // The townships whose bounds touch the hovered one (itself included): a
  // 3x3 block in the regular grid, fewer at the valley edge. `reach` is in
  // townships from the centre: 1.5 is the 3x3 block, 2.5 the 5x5 block
  // around it (used to prefetch the ring beyond the lens). Measured over
  // the township grid on the map (each feature's bounds are measured once,
  // see featureBounds); nothing at any other level.
  SectionMap.prototype.neighborhoodOf = function (hostId, reach) {
    var hosts = [];
    var host = this.level === 'township' ? this.gridById[hostId] : null;
    var bounds = host ? featureBounds(host) : null;
    if (!bounds) return hosts;
    reach = reach || 1.5;
    // Neighbours by centre distance rather than touching bounds: diagonal
    // townships meet the hovered one only at a corner, and survey offsets
    // between ranges leave small gaps, so an intersection test drops them.
    // Anything whose centre is within `reach` townships on both axes is in;
    // the next ring starts a whole township further out.
    var center = boundsCenter(bounds);
    // A partial township (county edge, survey gap) has small bounds, so the
    // reach is floored at a full township's size.
    var maxDx = Math.max(bounds[1][0] - bounds[0][0], TOWNSHIP_DEGREES.lng) * reach;
    var maxDy = Math.max(bounds[1][1] - bounds[0][1], TOWNSHIP_DEGREES.lat) * reach;
    for (var i = 0; i < this.gridFeatures.length; i++) {
      var other = this.gridFeatures[i];
      var otherBounds = featureBounds(other);
      if (!otherBounds) continue;
      var c = boundsCenter(otherBounds);
      if (Math.abs(c[0] - center[0]) <= maxDx && Math.abs(c[1] - center[1]) <= maxDy) hosts.push(other);
    }
    return hosts;
  };

  SectionMap.prototype.showLens = function (feature) {
    if (!this.data.sectionsUrl) return;
    var id = feature.properties.id;
    // While one of the lens sections has its popup open the lens is pinned:
    // hovering a neighbouring township mustn't pull it (and the popup) away.
    if (this.openLensId) return;
    this.clearLens();
    this.lensId = id;
    this.lensHost = feature;

    var self = this;
    var hosts = this.neighborhoodOf(id);
    this.lensHosts = hosts;
    var ids = hosts.map(function (host) { return host.properties.id; });
    var draw = function () {
      // The lens has moved on (or gone) meanwhile: nothing to draw, and the
      // ring to prefetch is the new centre's, not this one's.
      if (self.lensId !== id) return;
      self.drawLens(id, self.cachedLensSections(ids));
      self.prefetchRing(id);
    };
    if (!this.uncached(ids).length) {
      draw();
      return;
    }
    // A cursor sweeping across the map crosses many townships; fetch only
    // for the one it settles on. Cached blocks above draw at once.
    this.cancelLensFetch();
    this.lensFetchTimer = setTimeout(function () {
      self.lensFetchTimer = null;
      if (self.lensId !== id) return;
      self.fetchLensSections(hosts, draw);
    }, LENS_FETCH_DELAY_MS);
  };

  SectionMap.prototype.cancelLensFetch = function () {
    if (this.lensFetchTimer) {
      clearTimeout(this.lensFetchTimer);
      this.lensFetchTimer = null;
    }
  };

  SectionMap.prototype.uncached = function (ids) {
    var self = this;
    return ids.filter(function (townshipId) { return !self.lensCache[townshipId]; });
  };

  // Once the lens is drawn, warm the cache for the ring of townships one
  // step beyond it, in idle time, so recentring the lens in any direction
  // draws without waiting on the network. One prefetch at a time; a lens
  // that has moved on by the time it runs prefetches around its new centre
  // instead.
  SectionMap.prototype.prefetchRing = function (hostId) {
    if (this.prefetching || !this.data.sectionsUrl) return;
    var self = this;
    var run = function () {
      if (self.prefetching || !self.map) return;
      var inner = {};
      self.neighborhoodOf(hostId, 1.5).forEach(function (host) { inner[host.properties.id] = true; });
      var ring = self.neighborhoodOf(hostId, 2.5).filter(function (host) {
        var townshipId = host.properties.id;
        return !inner[townshipId] && !self.lensCache[townshipId];
      });
      if (!ring.length) return;
      self.prefetching = true;
      self.fetchLensSections(ring, function () { self.prefetching = false; });
    };
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(run, { timeout: 500 });
    } else {
      setTimeout(run, 150);
    }
  };

  // The nine townships under the lens lose their fill while it's up (the
  // `lensHost` feature state, which grid-fill's opacity reads), so the
  // section shades aren't stacked on the township shade beneath them; the
  // hovered one keeps its darker outline.
  SectionMap.prototype.setHostFills = function (visible) {
    var map = this.map;
    if (map && map.getSource('grid')) {
      (this.lensHosts || []).forEach(function (host) {
        map.setFeatureState({ source: 'grid', id: host.properties.id }, { lensHost: !visible });
      });
    }
    this.drawLensOutline(!visible);
  };

  // The hovered township's own outline, on its own layer above the lens
  // sections (which would otherwise paint over the township's border), in
  // the township hover stroke: dark when the township has data, lighter
  // when it hasn't, matching the hover rule elsewhere.
  SectionMap.prototype.drawLensOutline = function (show) {
    var data = show && this.lensHost ? this.lensHost : EMPTY;
    // Every clearLens and every redraw passes through here: the source is
    // only re-sent when it changes. The host feature is the same object
    // across a restyle, so its `value` (which the stroke colour reads) is
    // compared too: a metric change can turn data into no data.
    var value = data === EMPTY ? null : data.properties.value;
    if (this.sourceData['lens-outline'] === data && this.lensOutlineValue === value) return;
    this.lensOutlineValue = value;
    this.setSourceData('lens-outline', data);
  };

  // Keeps the township under the pointer at the centre of the lens. Returns
  // true when the lens was redrawn around a different township (the caller's
  // section is gone by then). A pinned lens (popup open) stays put.
  SectionMap.prototype.recentreLens = function (section) {
    var mtrs = section.properties.mtrs || '';
    var townshipId = mtrs.slice(0, mtrs.lastIndexOf('-'));
    if (!townshipId || townshipId === this.lensId || this.openLensId || this.level !== 'township') return false;
    var host = this.gridById[townshipId];
    if (!host) return false;
    this.showLens(host);
    return true;
  };

  // Also what a restyle calls with the lens's own features (a reclass in
  // place; a hovered section keeps its state, its id being the same).
  SectionMap.prototype.drawLens = function (id, features) {
    if (!this.map) return;
    var self = this;
    this.lensId = id;
    this.lensDrawnAt = Date.now();
    this.lensFeatures = features;
    if (!features.length) {
      this.setSourceData('lens', EMPTY);
      return;
    }
    // The township shade stays until the sections are here to replace it,
    // so the lens never shows an empty grid while the request is in flight.
    this.setHostFills(false);
    this.lensClasses = quantileClasses(features.map(function (section) { return section.properties[self.metric]; }));
    this.classFeatures(features, this.lensClasses, LENS_OPACITY);
    this.setSourceData('lens', { type: 'FeatureCollection', features: features });
    // The selected section wears its outline while a section layer holds it.
    var selected = this.selectedSectionId ? findFeature(features, this.selectedSectionId) : null;
    if (selected) this.showSelectedOutline(selected);
  };

  // A short grace period between leaving a township (or one of its
  // sections) and dropping the lens, so moving between the two doesn't
  // flicker it away.
  SectionMap.prototype.scheduleLensClear = function () {
    this.cancelLensClear();
    var self = this;
    var scheduledAt = Date.now();
    this.lensClearTimer = setTimeout(function () {
      self.lensClearTimer = null;
      // Keep the lens while one of its section popups is open, or when it
      // was redrawn (recentred) after this clear was scheduled: that
      // mouseleave came from a section the redraw removed.
      if (self.openLensId) return;
      if (self.lensDrawnAt && self.lensDrawnAt >= scheduledAt) return;
      self.clearLens();
    }, LENS_CLEAR_DELAY_MS);
  };

  SectionMap.prototype.cancelLensClear = function () {
    if (this.lensClearTimer) {
      clearTimeout(this.lensClearTimer);
      this.lensClearTimer = null;
    }
  };

  // Takes the lens down: timers, the pin, the hosts' fills, the sections.
  // A popup on one of its sections goes too, unless the section grid about
  // to load is going to reopen it (its "Zoom in" button set openGridId);
  // the selection outlives the lens either way, its outline hidden until a
  // section layer holds the section again. Unlike resetAllSections, a
  // popup on the selected section is not kept: resetAllSections only runs
  // where a section layer follows (renderGrid, or the mode switching off,
  // which closes the popup itself), while the lens clears from hover flows
  // (leaving the grid, a ramp change) where nothing would reopen it and
  // the popup would be left floating over the township grid.
  SectionMap.prototype.clearLens = function () {
    this.cancelLensClear();
    this.cancelLensFetch();
    this.lensId = null;
    this.openLensId = null;
    this.setHostFills(true);
    this.lensHosts = null;
    this.lensHost = null;
    this.clearHover('lens');
    if (this.popup && this.popupKey === 'openLensId' && this.openGridId !== this.popupId) this.closePopup();
    if (this.lensFeatures.length) {
      if (this.selectedSectionId && findFeature(this.lensFeatures, this.selectedSectionId)) this.showSelectedOutline(null);
      this.lensFeatures = [];
      this.setSourceData('lens', EMPTY);
    }
  };

  // -- not yet ported --
  // The notice and location layers and the marker legend rows are still to
  // come; the code above already calls into them, so each is a no-op until
  // its port lands.
  SectionMap.prototype.appendMarkerLegend = function () {};
  SectionMap.prototype.loadNotices = function () {};
  SectionMap.prototype.clearNotices = function () {};
  SectionMap.prototype.loadLocations = function () {};
  SectionMap.prototype.clearLocations = function () {};
  SectionMap.prototype.updateLocationsNote = function () {};

  // Collect the `.section-map` containers marked for this map at or under
  // `root`. `root` may be a document or an element (htmx hands us the element
  // it just swapped in, and that element can itself be a container).
  function containersUnder(root) {
    var found = [];
    if (root.matches && root.matches('.section-map')) found.push(root);
    var nested = root.querySelectorAll ? root.querySelectorAll('.section-map') : [];
    for (var i = 0; i < nested.length; i++) found.push(nested[i]);
    return found.filter(function (el) { return !!el.dataset.gl; });
  }

  // Idempotent: containers already initialised carry `data-rendered`, so this
  // is safe to call repeatedly (page load plus every htmx swap).
  // The one live map on the page, so a swap can hand its container over
  // rather than building a second map.
  var liveMap = null;

  function init(root) {
    if (typeof maptilersdk === 'undefined') return;
    var containers = containersUnder(root || document);
    // A swap to a page without a map drops the live one: undo the page-level
    // expanded state (html class, pinned scope bar), since no map remains to
    // do it, and release the map. Judged against the whole document, not
    // `root`: a swap fires htmx:load per swapped element, and the one for an
    // out-of-band fragment must not take the map from the page that has it.
    if (liveMap && !document.body.contains(liveMap.el) && !containersUnder(document).length) {
      if (liveMap.expanded) liveMap.setExpanded(false);
      liveMap.destroy();
      liveMap = null;
    }
    for (var i = 0; i < containers.length; i++) {
      var el = containers[i];
      if (el.dataset.rendered) continue;
      try {
        if (!webglAvailable()) {
          el.dataset.rendered = '1';
          showUnavailable(el);
          continue;
        }
        if (liveMap && !document.body.contains(liveMap.el)) {
          liveMap.adopt(el);
          continue;
        }
        el.dataset.rendered = '1';
        liveMap = new SectionMap(el);
      } catch (err) {
        logError('failed to initialize', err);
      }
    }
  }

  window.PesticidesSectionMapGL = {
    init: init,
    instances: function () { return liveMap ? [liveMap] : []; },
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
