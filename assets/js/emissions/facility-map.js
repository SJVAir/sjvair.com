/*
 * Facility map for the Facility Emissions Explorer, a module on the map core
 * (assets/js/maps/), registered as 'facility'.
 *
 * Two views, one at a time:
 *   Facilities  one circle per permitted facility: area scaled by the
 *               selected pollutant (square root, so the largest emitter
 *               doesn't bury the rest), colour by a fixed log-scale class;
 *               facilities that reported none are small hollow grey rings.
 *   Areas       counties, ZIP areas or 2020 census tracts shaded by the
 *               facilities inside them: per square mile, total, or per
 *               1,000 residents (fixed log-scale classes). Shapes come from
 *               the regions GeoJSON (simplified together, so shared borders
 *               stay shared), numbers from /api/2.0/emissions/areas/.
 *
 * County and air district outlines sit under the data, and everything draws
 * over the whole basemap, labels included. On a region or near-me page the
 * page's own area is outlined and everything outside it washed out.
 * Config comes from the container's data-* attributes
 * (views.facility_map_config); the chrome is the core's.
 *
 * Modes: `full` (the map page, with the sector filter) and `compact`
 * (facility, sector and region pages; a facility page's own facility is
 * highlighted and the rest faded).
 * On a facility page the schools and child care within 1/4 mile are drawn
 * as dots inside a dashed ring (data-nearby).
 *
 * Overlays: Oil & gas wells (CalGEM), clustered, from data-wells-url; on
 * where data-wells is 1; the legend's checkbox toggles it and ?wells=
 * carries it. Methane sources (Carbon Mapper), from data-methane-url,
 * shared with the dairy map (methane-overlay.js).
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M || !M.register) return;

  // The ramps live on the map core (assets/js/maps/core.js), shared with
  // the pesticides section map's Options menu. RAMP and CHANGE_RAMP are
  // reassigned by onRampChange (below) when the reader picks a different
  // one from the Options menu's Ramp select; every function that shades by
  // them reads the variable at call time, so a change takes effect at once.
  // 'steelblue'/'rdbu7' are this map's original defaults (ColorBrewer Blues
  // without its palest step, which vanishes on the basemap; ColorBrewer
  // RdBu at this map's own 7-class fixed breaks) -- sampling either at its
  // native length reproduces the exact original colours.
  var DEFAULT_RAMP = 'steelblue';
  var DEFAULT_DRAMP = 'rdbu7';
  var sampleRamp = M.sampleRamp;
  var RAMP = sampleRamp(M.ramps.sequential[DEFAULT_RAMP], 5);
  // Fixed classes on a log scale, per display unit: stable across pollutants,
  // counties and years, and readable ("1-10 tons"). Toxics are shown in lbs.
  // A weighted toxics measure has no unit: it's shown as a share of the
  // Valley total, on fixed percent classes (0.01%, 0.1%, 1%, 5% and up).
  var SHARE_BREAKS = [0.0001, 0.001, 0.01, 0.05];
  var CLASS_BREAKS = { tons: [0.1, 1, 10, 100], lbs: [1, 10, 100, 1000], share: SHARE_BREAKS };
  // The Areas view's classes, per measure and unit.
  var AREA_BREAKS = {
    density: { tons: [0.01, 0.1, 1, 10], lbs: [0.1, 1, 10, 100] },
    total: { tons: [1, 10, 100, 1000], lbs: [10, 100, 1000, 10000], share: SHARE_BREAKS },
    per_resident: { tons: [0.1, 1, 10, 100], lbs: [1, 10, 100, 1000] },
  };
  var AREA_FIELDS = { density: 'per_sq_mi', total: 'total', per_resident: 'per_1k_residents' };
  var AREA_SUFFIX = { density: ' per sq mi', total: '', per_resident: ' per 1,000 people' };
  // Compare mode: the Areas view shades the selected measure's percent
  // change instead of its value, on a fixed diverging scale (ColorBrewer
  // RdBu) -- blue for a fall, red for a rise, pale grey near zero. Fixed
  // rather than data-driven, like CLASS_BREAKS/AREA_BREAKS: stable classes
  // across a measure, county or year change, at the cost of an outlier
  // pinning the top bucket.
  var CHANGE_BREAKS = [-0.5, -0.25, -0.1, 0.1, 0.25, 0.5];
  var CHANGE_RAMP = sampleRamp(M.ramps.diverging[DEFAULT_DRAMP], CHANGE_BREAKS.length + 1);
  var LEVEL_NAMES = { county: '', zipcode: 'ZIP ', tract: 'Tract ' };
  var EMPTY_COLOR = '#8a94a3';
  // A facility circle with nothing to colour it by: grey, outlined darker.
  var EMPTY_FILL = '#c9ced6';
  var EMPTY_STROKE = '#6b7480';
  var HIGHLIGHT_COLOR = '#d35400';
  var COUNTY_COLOR = '#1f2d3d';
  var DISTRICT_COLOR = '#6a3d9a';
  var AREA_LINE_COLOR = '#4a5568';
  var AREA_LINE_WIDTH = 0.5;
  var NEARBY_COLOR = '#2f6f4e';
  var MIN_RADIUS = 4;
  var MAX_RADIUS = 34;
  var WORLD_RING = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
  var CIRCLE_POINTS = 64;
  var METERS_PER_MILE = 1609.344;

  // The Oil & gas wells overlay (CalGEM WellSTAR, /api/2.0/emissions/wells/geojson/):
  // one point per well, clustered by the GeoJSON source until CLUSTER_MAX_ZOOM.
  // Status colours; a red ring marks a verified health protection zone.
  var WELL_COLORS = { Active: '#b45309', Idle: '#6b7280', New: '#2563eb' };
  var WELL_HPZ_COLOR = '#dc2626';
  var CLUSTER_COLOR = '#7c2d12';
  var CLUSTER_MAX_ZOOM = 11;
  var CLUSTER_RADIUS = 40;
  var WELL_STATUSES = ['Active', 'Idle', 'New'];

  var escapeHtml = M.escapeHtml;
  var logError = M.logger('facility-map');
  var getJson = M.getJson;
  var quantity = M.format.quantity;
  var roundLabel = M.format.round;
  var classIndex = M.classes.index;

  function breaksFor(unit) {
    return CLASS_BREAKS[unit] || CLASS_BREAKS.tons;
  }

  function areaBreaksFor(measure, unit) {
    var set = AREA_BREAKS[measure] || AREA_BREAKS.density;
    return set[unit] || set.tons;
  }

  function radiusFor(value, max) {
    return MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * Math.sqrt(value / max);
  }

  // A size key's sample circle, its own square viewBox (2*MAX_RADIUS+2 on a
  // side, however small `r` is) so a phone's narrower CSS width scales the
  // whole drawing down rather than clipping it -- the map's own circles
  // (paint's `_radius`, from this same radiusFor) are untouched either way.
  function sizeCircle(r, value, color, round) {
    var box = 2 * MAX_RADIUS + 2;
    return '<span class="legend-size"><svg viewBox="0 0 ' + box + ' ' + box + '" width="' + box + '" height="' + box + '">' +
      '<circle cx="' + (box / 2) + '" cy="' + (box - r - 1) + '" r="' + r + '"' +
      (color ? ' style="stroke: ' + color + '"' : '') + '/></svg>' +
      (round || roundLabel)(value >= 1 ? Math.round(value) : value) + '</span>';
  }

  // The Compare legend's size key (three sample circles at max/10/100 of
  // it). Empty when there's nothing to scale. `color` is the circles'
  // stroke, the stylesheet's grey when unset: under Compare the circles'
  // colour means change rather than size.
  function sizeKeyHtml(max, color, round) {
    if (!max) return '';
    return '<div class="legend-sizes">' + [max, max / 10, max / 100].map(function (value) {
      return sizeCircle(radiusFor(value, max), value, color, round);
    }).join('') + '</div>';
  }

  // The plain Facilities legend's one key: size and colour both follow the
  // value there, so each colour class shows as a circle in its colour at
  // the size of the class's top (the largest facility's for the top class).
  // Classes above the largest facility have no circles on the map and are
  // left out. Under Compare the two part ways (size is this year's value,
  // colour the change), so that legend keeps a size key and colour classes.
  function valueKeyHtml(max, breaks, round) {
    var box = 2 * MAX_RADIUS + 2;
    var top = classIndex(max, breaks);
    var rows = '';
    for (var i = top; i >= 0; i--) {
      var value = i === top ? max : breaks[i];
      var r = radiusFor(value, max);
      rows += '<span class="legend-key-row"><svg viewBox="0 0 ' + box + ' ' + (2 * r + 2) + '" width="' + box + '" height="' + (2 * r + 2) + '">' +
        '<circle cx="' + (box / 2) + '" cy="' + (r + 1) + '" r="' + r + '" style="fill: ' + RAMP[i] + '; stroke: ' + darken(RAMP[i], 0.35) + '"/></svg>' +
        '<span>' + M.classes.label(i, breaks, round) + '</span></span>';
    }
    return '<div class="legend-key">' + rows + '</div>';
  }

  // A legend's classes on the blue ramp, largest first.
  function facilityBins(breaks, swatchClass, round) {
    return M.classes.bins(breaks, RAMP, swatchClass, round);
  }

  // A fraction (0.234) as the change legend and popup write it: '+23%',
  // '-8%', '0%'.
  function pctRound(value) {
    var pct = Math.round(value * 100);
    return (pct > 0 ? '+' : '') + pct + '%';
  }

  // A share of the Valley total (0-1) as a percent: '0.01%', '0.1%', '1%',
  // '5%', '24%' -- two significant digits, no trailing zeros.
  function sharePct(value) {
    if (value === null || value === undefined) return '—';
    return String(Number((value * 100).toPrecision(2))) + '%';
  }

  // A data value with its unit as the popups and legends write it.
  function valueText(value, unit) {
    if (unit === 'share') return sharePct(value) + ' of Valley total';
    return quantity(value) + ' ' + escapeHtml(unit) + '/yr';
  }

  // The change legend's classes on the diverging ramp, largest fall first.
  function changeBins(swatchClass) {
    return M.classes.bins(CHANGE_BREAKS, CHANGE_RAMP, swatchClass, pctRound);
  }

  // A value and its compared-year counterpart (either may be null/undefined)
  // as a fraction change, or null when there's nothing to compare (either
  // year's missing, or the compared year was zero -- no percentage of zero).
  // Shared by the Areas view (per-region totals) and the Facilities view
  // (per-facility values, below).
  function changeFraction(value, prevValue) {
    if (value === null || value === undefined || !(prevValue > 0)) return null;
    return (value - prevValue) / prevValue;
  }

  // Precompute each circle so the layer's paint is plain `get`s. `compare`
  // (a loaded year, from the geojson's own properties.compare) keeps the
  // circle's size by this year's value -- still a useful scale -- but
  // colours it by the percent change from that year instead, on the same
  // diverging ramp as the Areas view.
  function prepare(collection, unit, compare) {
    var features = collection.features || [];
    var positive = features.map(function (f) { return f.properties.value; }).filter(function (v) { return v > 0; });
    var max = positive.length ? Math.max.apply(null, positive) : 0;
    var breaks = compare ? CHANGE_BREAKS : breaksFor(unit);
    var ramp = compare ? CHANGE_RAMP : RAMP;
    features.forEach(function (feature) {
      var p = feature.properties;
      var sized = p.value > 0 && max > 0;
      var change = compare ? changeFraction(p.value, p.value_prev) : null;
      var coloured = compare ? change !== null : sized;
      p._radius = sized ? radiusFor(p.value, max) : MIN_RADIUS;
      p._color = coloured ? ramp[classIndex(compare ? change : p.value, breaks)] : EMPTY_FILL;
      // Each circle's outline is a darker shade of its own fill, so two
      // overlapping circles read as two rather than one half-bordered one.
      p._stroke = coloured ? darken(p._color, 0.35) : EMPTY_STROKE;
      p._empty = coloured ? 0 : 1;
      p._sort = sized ? p.value : 0;
      p._change = change;
    });
    return { collection: collection, breaks: breaks, max: max, compare: compare || '' };
  }

  // `hex` (#rrggbb) moved `amount` of the way to black.
  function darken(hex, amount) {
    return '#' + [1, 3, 5].map(function (i) {
      var v = Math.round(parseInt(hex.slice(i, i + 2), 16) * (1 - amount));
      return ('0' + v.toString(16)).slice(-2);
    }).join('');
  }

  // Everything outside `geometry` (a Polygon or MultiPolygon), as one polygon
  // with the geometry's outer rings as holes: the page's area stays clear,
  // the rest is washed out.
  function maskFor(geometry) {
    var rings = [];
    if (geometry.type === 'Polygon') rings = [geometry.coordinates[0]];
    if (geometry.type === 'MultiPolygon') rings = geometry.coordinates.map(function (part) { return part[0]; });
    if (!rings.length) return M.EMPTY;
    return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [WORLD_RING].concat(rings) } };
  }

  // A `miles` circle around [lng, lat] as a polygon (the SDK has no circles in metres).
  function circle(center, miles) {
    var meters = miles * METERS_PER_MILE;
    var dLat = meters / 111320;
    var dLng = meters / (111320 * Math.cos(center[1] * Math.PI / 180));
    var ring = [];
    for (var i = 0; i <= CIRCLE_POINTS; i++) {
      var angle = (i % CIRCLE_POINTS) * 2 * Math.PI / CIRCLE_POINTS;
      ring.push([center[0] + dLng * Math.cos(angle), center[1] + dLat * Math.sin(angle)]);
    }
    return { type: 'Polygon', coordinates: [ring] };
  }

  function FacilityMap(shell) {
    var self = this;
    this.shell = shell;
    this.el = shell.el;
    // The container's live dataset (an adopt rewrites this same element's).
    this.data = shell.data;
    this.map = shell.map;
    this.fitted = false;
    this.legendData = null;
    // The Areas view: shapes per level (they never change with the scope),
    // the current values, and a request counter of its own (the shell's
    // ticket is the facilities fetch's).
    this.shapes = {};
    this.areaData = null;
    this.areaRequest = 0;
    // The page's outline (region JSON) has its own counter too.
    this.outlineRequest = 0;
    this.outlineBounds = null;
    // Areas view: the hovered area's outline (feature-state, shared with the
    // fill's click and the scope outline's own line width). Highlight only --
    // the click popup already carries the values (M.hover.controller, shared
    // with the dairy map's counties).
    this.areaHover = M.hover.controller(this.map, 'areas');
    // The Options menu's experiment controls: basemap style and colour
    // ramp, applied live and written to the URL (?tiles=, ?ramp=, ?dramp=).
    // Not page scope (readViewState), so they survive a scope swap
    // untouched. The shell already resolved the basemap style from
    // ?tiles=/data-style; the ramp names are read the same way pesticides'
    // section map reads ?ramp=, but kept as two names (sequential and
    // diverging) so switching Compare on and off doesn't forget either.
    this.defaultTileStyle = this.data.style || 'dataviz';
    this.tileStyle = shell.tileStyle;
    var rampMatch = /[?&]ramp=([a-z0-9]+)/.exec(window.location.search || '');
    this.rampName = rampMatch && M.ramps.sequential[rampMatch[1]] ? rampMatch[1] : DEFAULT_RAMP;
    var dRampMatch = /[?&]dramp=([a-z0-9]+)/.exec(window.location.search || '');
    this.dRampName = dRampMatch && M.ramps.diverging[dRampMatch[1]] ? dRampMatch[1] : DEFAULT_DRAMP;
    RAMP = sampleRamp(M.ramps.sequential[this.rampName], 5);
    CHANGE_RAMP = sampleRamp(M.ramps.diverging[this.dRampName], CHANGE_BREAKS.length + 1);
    this.readViewState();
    // Layer-bound listeners wait for their layer, so they're bound once here
    // rather than on every style load.
    this.map.on('click', 'facilities', function (evt) { self.openPopup(evt.features[0], evt.lngLat); });
    this.map.on('click', 'areas-fill', function (evt) { self.openAreaPopup(evt.features[0], evt.lngLat); });
    this.map.on('mousemove', 'areas-fill', function (evt) { self.areaHover.set(evt.features[0], evt.lngLat); });
    this.map.on('mouseleave', 'areas-fill', function () { self.areaHover.clear(); });
    this.map.on('click', 'nearby', function (evt) { self.openNearbyPopup(evt.features[0], evt.lngLat); });
    this.wellsData = null;
    this.wellsRequest = 0;
    this.map.on('click', 'wells-clusters', function (evt) { self.zoomToCluster(evt.features[0]); });
    this.map.on('click', 'wells', function (evt) { self.openWellPopup(evt.features[0], evt.lngLat); });
    ['facilities', 'areas-fill', 'nearby', 'wells-clusters', 'wells'].forEach(function (layer) {
      self.map.on('mouseenter', layer, function () { self.map.getCanvas().style.cursor = 'pointer'; });
      self.map.on('mouseleave', layer, function () { self.map.getCanvas().style.cursor = ''; });
    });
    // The legend's own-layer checkbox; a page can start it off (data-main-layer="0"),
    // or leave the facilities off the map altogether ("none": an Oil & gas map, wells and methane only).
    this.noFacilities = this.data.mainLayer === 'none';
    this.mainLayer = !this.noFacilities && this.data.mainLayer !== '0';
    this.methane = window.EmissionsMethaneOverlay ? new window.EmissionsMethaneOverlay(this, { before: 'facilities' }) : null;
    // The scope bar's links (year, pollutant, toggles) and the near-me radius
    // buttons were rendered before
    // the reader switched view, level, measure or sector here, and carry the
    // page's original values. Rewrite the boosted request's URL (htmx reads
    // detail.path back after this event) so the next page opens the way the
    // map is now; defaults are left out.
    this.onConfigRequest = function (event) {
      var detail = event.detail;
      var elt = detail && detail.elt;
      if (!elt || !elt.closest || !elt.closest('.explorer-scope, .radius-switcher') || typeof detail.path !== 'string') return;
      if (!self.areasEnabled && self.data.mode !== 'full') return;
      var path = M.rewriteQuery(detail.path, self.writeState.bind(self));
      if (path !== null) detail.path = path;
    };
    document.body.addEventListener('htmx:configRequest', this.onConfigRequest);
    // For debugging from the console: document.querySelector('.facility-map').facilityMap
    this.el.facilityMap = this;
  }

  FacilityMap.prototype.readViewState = function () {
    this.areasEnabled = this.data.areas === '1';
    this.view = this.areasEnabled && this.data.view === 'areas' ? 'areas' : 'facilities';
    // The page's default level (the server's), left out of the URLs we write.
    this.defaultLevel = this.data.defaultLevel || 'tract';
    this.level = this.data.level || this.defaultLevel;
    this.measure = this.data.measure || 'density';
    // A weighted toxics measure is a share: only Total means anything (the
    // server renders density and per-resident disabled).
    if (this.data.unit === 'share') this.measure = 'total';
    // The year Compare shades the change against, in both views, or ''
    // for plain values; a toolbar control, not part of the page's scope.
    this.compare = this.data.compare || '';
    // A shared link asking for density (or per-resident) on a share opens as
    // Total; the address bar says so too.
    if (this.areasEnabled && this.data.unit === 'share' && /[?&]measure=(?!total(&|$))/.test(window.location.search)) this.syncUrl();
    // The wells overlay: offered where the page gave a URL; its default is the
    // page's (Kern County, the oil-gas sector), the URL may override it.
    this.wellsEnabled = !!this.data.wellsUrl;
    this.wellsDefault = this.data.wellsDefault === '1';
    this.wells = this.wellsEnabled && this.data.wells === '1';
  };

  // Bottom to top: the shaded areas, the county and district lines, the
  // facilities, the wash outside the page's area, its outline. On top of the
  // whole basemap, labels included: the data is what the map is for.
  FacilityMap.prototype.addLayers = function () {
    this.shell.ensureSource('areas');
    this.shell.ensureSource('outline');
    this.shell.ensureSource('outline-mask');
    this.shell.ensureSource('counties', { data: this.data.countiesUrl || M.EMPTY });
    this.shell.ensureSource('districts', { data: this.data.districtsUrl || M.EMPTY });
    this.shell.ensureSource('facilities');
    this.shell.ensureLayer({
      id: 'areas-fill', type: 'fill', source: 'areas',
      paint: { 'fill-color': ['get', '_color'], 'fill-opacity': ['case', ['==', ['get', '_empty'], 1], 0, 0.72] },
    });
    this.shell.ensureLayer({
      id: 'areas-line', type: 'line', source: 'areas',
      // The hovered area's outline: dark and thicker, the same as the dairy
      // map's counties (M.hover). max() so hovering never draws thinner than
      // the area's own normal outline (X4's deferred minor). The page's own
      // outline (region-page highlight, county scope) is on separate layers
      // and sources, so it's unaffected either way.
      paint: {
        'line-color': M.hover.paint(M.hover.COLOR, AREA_LINE_COLOR),
        'line-width': M.hover.paint(Math.max(M.hover.WIDTH, AREA_LINE_WIDTH), AREA_LINE_WIDTH),
        'line-opacity': 0.5,
      },
    });
    this.shell.ensureLayer({
      id: 'counties', type: 'line', source: 'counties',
      paint: { 'line-color': COUNTY_COLOR, 'line-width': 1, 'line-opacity': 0.5 },
    });
    this.shell.ensureLayer({
      id: 'districts', type: 'line', source: 'districts',
      paint: { 'line-color': DISTRICT_COLOR, 'line-width': 2, 'line-dasharray': [3, 2] },
    });
    // Wells: clustered until CLUSTER_MAX_ZOOM; cluster size by count, colour
    // by its active share; single wells by status, ringed when in a verified HPZ.
    this.shell.ensureSource('wells', {
      cluster: true, clusterMaxZoom: CLUSTER_MAX_ZOOM, clusterRadius: CLUSTER_RADIUS,
      clusterProperties: {
        active: ['+', ['case', ['==', ['get', 's'], 'Active'], 1, 0]],
        hpz: ['+', ['get', 'h']],
      },
    });
    this.shell.ensureLayer({
      id: 'wells-clusters', type: 'circle', source: 'wells', filter: ['has', 'point_count'],
      paint: {
        'circle-radius': ['step', ['get', 'point_count'], 10, 50, 14, 500, 19, 5000, 26],
        'circle-color': CLUSTER_COLOR,
        'circle-opacity': ['interpolate', ['linear'], ['/', ['get', 'active'], ['get', 'point_count']], 0, 0.35, 1, 0.8],
        'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.5,
      },
    });
    this.shell.ensureLayer({
      id: 'wells', type: 'circle', source: 'wells', filter: ['!', ['has', 'point_count']],
      paint: {
        'circle-radius': 4,
        'circle-color': ['match', ['get', 's'], 'Active', WELL_COLORS.Active, 'Idle', WELL_COLORS.Idle, 'New', WELL_COLORS.New, WELL_COLORS.Idle],
        'circle-opacity': 0.85,
        'circle-stroke-color': ['case', ['==', ['get', 'h'], 1], WELL_HPZ_COLOR, '#ffffff'],
        'circle-stroke-width': ['case', ['==', ['get', 'h'], 1], 2, 0.5],
      },
    });
    this.shell.ensureLayer({
      id: 'facilities', type: 'circle', source: 'facilities',
      // Larger values draw on top.
      layout: { 'circle-sort-key': ['get', '_sort'] },
      paint: { 'circle-radius': ['get', '_radius'], 'circle-color': ['get', '_color'] },
    });
    // The facility page's schools and child care within 1/4 mile: the ring,
    // then the dots (data-nearby / data-ring-miles; camp.apps.emissions.schools).
    this.shell.ensureSource('nearby-ring');
    this.shell.ensureSource('nearby');
    this.shell.ensureLayer({
      id: 'nearby-ring', type: 'line', source: 'nearby-ring',
      paint: { 'line-color': NEARBY_COLOR, 'line-width': 1.5, 'line-dasharray': [2, 2], 'line-opacity': 0.8 },
    });
    this.shell.ensureLayer({
      id: 'nearby', type: 'circle', source: 'nearby',
      paint: { 'circle-radius': 5, 'circle-color': NEARBY_COLOR, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.5 },
    });
    this.shell.ensureLayer({
      id: 'outline-mask', type: 'fill', source: 'outline-mask',
      paint: { 'fill-color': '#ffffff', 'fill-opacity': 0.55 },
    });
    this.shell.ensureLayer({
      id: 'outline-line', type: 'line', source: 'outline',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': HIGHLIGHT_COLOR, 'line-width': 2.5, 'line-opacity': 0.9 },
    });
    // A facility page's own facility: a fixed-size ring at its point, on
    // top of everything, so a small emitter is as easy to find as a large one.
    this.shell.ensureSource('highlight-pin');
    this.shell.ensureLayer({
      id: 'highlight-pin', type: 'circle', source: 'highlight-pin',
      paint: {
        'circle-radius': 13, 'circle-color': 'rgba(0, 0, 0, 0)',
        'circle-stroke-color': HIGHLIGHT_COLOR, 'circle-stroke-width': 3,
      },
    });
    this.showHighlightPin();
    this.applyHighlight();
    this.applyView();
    this.showNearby();
    this.applyWells();
    if (this.methane) this.methane.addLayers();
  };

  // Every circle outlined in a darker shade of its fill (grey for "none
  // reported"); with a highlighted facility (a facility page), it gets an
  // orange ring and everything else fades.
  FacilityMap.prototype.applyHighlight = function () {
    if (!this.map || !this.map.getLayer('facilities')) return;
    var id = this.data.highlight || '';
    var isHighlight = ['==', ['get', 'id'], id];
    this.map.setPaintProperty('facilities', 'circle-opacity',
      id ? ['case', isHighlight, 0.95, 0.35] : 0.85);
    this.map.setPaintProperty('facilities', 'circle-stroke-opacity',
      id ? ['case', isHighlight, 1, 0.5] : 1);
    this.map.setPaintProperty('facilities', 'circle-stroke-color',
      ['case', isHighlight, HIGHLIGHT_COLOR, ['get', '_stroke']]);
    this.map.setPaintProperty('facilities', 'circle-stroke-width',
      ['case', isHighlight, 3, 1]);
  };

  FacilityMap.prototype.showHighlightPin = function () {
    var parts = (this.data.highlightPoint || '').split(',').map(Number);
    var features = parts.length === 2 && isFinite(parts[0]) && isFinite(parts[1])
      ? [{ type: 'Feature', geometry: { type: 'Point', coordinates: parts }, properties: {} }]
      : [];
    this.shell.setSourceData('highlight-pin', { type: 'FeatureCollection', features: features });
  };

  // One view at a time: the layers, the toolbar's switch and its Areas-only
  // controls follow `this.view`.
  FacilityMap.prototype.applyView = function () {
    var areas = this.view === 'areas';
    var compareActive = !!this.compare;
    if (this.map) {
      var set = function (map, id, visible) {
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none');
      };
      // mainLayer: the legend's checkbox for the pollutant's own layer, off
      // to see an overlay (plumes, wells) alone.
      set(this.map, 'facilities', !areas && this.mainLayer);
      set(this.map, 'areas-fill', areas && this.mainLayer);
      set(this.map, 'areas-line', areas && this.mainLayer);
    }
    Array.prototype.forEach.call(this.shell.controls('[data-view]'), function (button) {
      var on = button.getAttribute('data-view') === (areas ? 'areas' : 'facilities');
      button.classList.toggle('is-selected', on);
      button.classList.toggle('is-link', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    Array.prototype.forEach.call(this.shell.controls('[data-areas-only]'), function (control) {
      control.hidden = !areas;
    });
    // The Measure dropdown picks which per-area value is shaded, but
    // Compare always shades the percent change regardless of measure, so
    // its choice is inert while Compare is on -- hide it rather than let
    // it look like a live control. Its value (and the dropdown's own
    // selected state) is untouched, so turning Compare off restores it.
    Array.prototype.forEach.call(this.shell.controls('[data-measure-only]'), function (control) {
      control.hidden = !areas || compareActive;
    });
  };

  FacilityMap.prototype.url = function () {
    var params = new URLSearchParams(this.data.query || '');
    if (this.compare) params.set('compare', this.compare); else params.delete('compare');
    var query = params.toString();
    return this.data.geojsonUrl + (query ? '?' + query : '');
  };

  // The facilities always load (switching back to them is then instant);
  // the areas load when they're the view.
  FacilityMap.prototype.load = function () {
    if (this.noFacilities) {
      this.el.dataset.loaded = '1';
      this.shell.updateLegend();
    } else {
      this.loadFacilities();
    }
    if (this.view === 'areas') this.loadAreas();
    this.loadOutline();
    this.showNearby();
    if (this.wells) this.loadWells();
    if (this.methane) this.methane.load();
  };

  FacilityMap.prototype.loadFacilities = function () {
    var self = this;
    var ticket = this.shell.ticket();
    this.el.dataset.loaded = '';
    if (this.view === 'facilities') this.shell.setStatus('Loading facilities…');
    getJson(this.url())
      .then(function (collection) {
        // A newer request (a sector change, a swap) or a destroy superseded this one.
        if (!self.shell.isCurrent(ticket)) return;
        self.show(collection);
      })
      .catch(function (err) {
        if (!self.shell.isCurrent(ticket)) return;
        if (self.view === 'facilities') self.shell.setStatus('Couldn\'t load the facilities');
        logError('failed to load facilities', err);
      });
  };

  FacilityMap.prototype.show = function (collection) {
    // The geojson's own `compare` (its properties, not `this.compare`)
    // confirms the fetch actually paired a compared year -- e.g. it's
    // absent if the request raced a Compare toggle-off.
    var compare = this.compare && (collection.properties || {}).compare;
    var prepared = prepare(collection, this.data.unit, compare);
    this.legendData = prepared;
    this.shell.setSourceData('facilities', prepared.collection);
    this.applyHighlight();
    this.shell.updateLegend();
    if (this.view === 'facilities') this.shell.setStatus('');
    if (!this.fitted) {
      this.fit(prepared.collection);
      this.fitted = true;
    }
    this.el.dataset.loaded = '1';
  };

  FacilityMap.prototype.areasUrl = function () {
    var params = new URLSearchParams(this.data.query || '');
    params.set('level', this.level);
    if (this.compare) params.set('compare', this.compare); else params.delete('compare');
    return this.data.areasUrl + '?' + params.toString();
  };

  FacilityMap.prototype.shapesFor = function (level) {
    var self = this;
    if (this.shapes[level]) return Promise.resolve(this.shapes[level]);
    return getJson(this.data.shapesUrl + '?type=' + encodeURIComponent(level) + '&simplify=1').then(function (shapes) {
      self.shapes[level] = shapes;
      return shapes;
    });
  };

  FacilityMap.prototype.loadAreas = function () {
    var self = this;
    var request = ++this.areaRequest;
    var level = this.level;
    this.el.dataset.areasLoaded = '';
    this.shell.setStatus('Loading areas…');
    Promise.all([this.shapesFor(level), getJson(this.areasUrl())])
      .then(function (results) {
        if (request !== self.areaRequest || !self.map) return;
        self.areaData = { level: level, shapes: results[0], values: results[1] };
        self.showAreas();
      })
      .catch(function (err) {
        if (request !== self.areaRequest || !self.map) return;
        if (self.view === 'areas') self.shell.setStatus('Couldn\'t load the areas');
        logError('failed to load areas', err);
      });
  };

  // Joins the values to the shapes and colours them by the current measure
  // (a measure change re-runs this without fetching) -- or, in Compare mode,
  // by that measure's percent change from the compared year (both years came
  // with the fetch, so switching the measure or clearing Compare still needs
  // no refetch; only picking a different compared year does, since the
  // server computes the pair).
  FacilityMap.prototype.showAreas = function () {
    var data = this.areaData;
    if (!data) return;
    var compare = this.compare && data.values.compare;
    var byId = {};
    data.values.areas.forEach(function (area) { byId[area.id] = area; });
    var field = AREA_FIELDS[this.measure] || AREA_FIELDS.density;
    var breaks = compare ? CHANGE_BREAKS : areaBreaksFor(this.measure, data.values.unit);
    var ramp = compare ? CHANGE_RAMP : RAMP;
    var features = (data.shapes.features || []).map(function (feature) {
      var area = byId[feature.id];
      var value = area ? area[field] : null;
      var change = compare && area ? changeFraction(value, area[field + '_prev']) : null;
      var shaded = compare ? change !== null : (value !== null && value !== undefined && value > 0);
      return {
        type: 'Feature',
        id: feature.id,
        geometry: feature.geometry,
        properties: Object.assign({}, feature.properties, {
          facilities: area ? area.facilities : 0,
          total: area ? area.total : null,
          per_sq_mi: area ? area.per_sq_mi : null,
          per_1k_residents: area ? area.per_1k_residents : null,
          total_prev: area ? area.total_prev : null,
          per_sq_mi_prev: area ? area.per_sq_mi_prev : null,
          per_1k_residents_prev: area ? area.per_1k_residents_prev : null,
          _change: change,
          _color: shaded ? ramp[classIndex(compare ? change : value, breaks)] : EMPTY_COLOR,
          _empty: shaded ? 0 : 1,
        }),
      };
    });
    data.breaks = breaks;
    data.compareActive = compare;
    this.shell.setSourceData('areas', { type: 'FeatureCollection', features: features });
    this.shell.updateLegend();
    if (this.view === 'areas') this.shell.setStatus('');
    this.el.dataset.areasLoaded = '1';
  };

  // The page's own area: a region's boundary (region pages) or the radius
  // (near-me), outlined, with everything outside washed out, and framed.
  FacilityMap.prototype.loadOutline = function () {
    var self = this;
    var request = ++this.outlineRequest;
    var center = M.parseCenter(this.data.center);
    var radius = parseFloat(this.data.radius);
    if (center && radius > 0) {
      this.showOutline(circle(center, radius));
      return;
    }
    if (!this.data.outlineUrl) {
      this.showOutline(null);
      return;
    }
    getJson(this.data.outlineUrl)
      .then(function (json) {
        if (request !== self.outlineRequest || !self.map) return;
        var boundary = json && json.data && json.data.boundary;
        self.showOutline(boundary ? boundary.geometry : null);
      })
      .catch(function (err) {
        if (request !== self.outlineRequest || !self.map) return;
        logError('failed to load the outline', err);
      });
  };

  FacilityMap.prototype.showOutline = function (geometry) {
    if (!geometry) {
      this.outlineBounds = null;
      this.shell.setSourceData('outline', M.EMPTY);
      this.shell.setSourceData('outline-mask', M.EMPTY);
      return;
    }
    this.shell.setSourceData('outline', { type: 'Feature', properties: {}, geometry: geometry });
    this.shell.setSourceData('outline-mask', maskFor(geometry));
    this.outlineBounds = M.geometryBounds(geometry);
    if (this.outlineBounds) this.map.fitBounds(this.outlineBounds, { padding: 24, duration: 0 });
  };

  // The overlay's layers follow `this.wells`; the legend's checkbox too.
  FacilityMap.prototype.applyWells = function () {
    var on = this.wellsEnabled && this.wells;
    if (this.map) {
      ['wells-clusters', 'wells'].forEach(function (id) {
        if (this.map.getLayer(id)) this.map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
      }, this);
    }
  };

  // Every Valley well, fetched once per page load (about 66,000 points, a
  // day's cache server-side) and only when the overlay is on.
  FacilityMap.prototype.loadWells = function () {
    var self = this;
    if (!this.wellsEnabled) return;
    if (this.wellsData) {
      this.shell.setSourceData('wells', this.wellsData);
      this.el.dataset.wellsLoaded = '1';
      return;
    }
    var request = ++this.wellsRequest;
    this.el.dataset.wellsLoaded = '';
    getJson(this.data.wellsUrl)
      .then(function (packed) {
        if (request !== self.wellsRequest || !self.map) return;
        var collection = wellsCollection(packed);
        self.wellsData = collection;
        self.shell.setSourceData('wells', collection);
        self.shell.updateLegend();
        self.el.dataset.wellsLoaded = '1';
      })
      .catch(function (err) {
        if (request !== self.wellsRequest || !self.map) return;
        logError('failed to load the wells', err);
      });
  };

  // The wells endpoint's compact rows ([id, lng, lat, status, hpz]) as the
  // GeoJSON the clustered source takes; `imported` rides along on properties.
  function wellsCollection(packed) {
    var statuses = packed.statuses || [];
    return {
      type: 'FeatureCollection',
      properties: { imported: packed.imported },
      features: (packed.wells || []).map(function (row) {
        return {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [row[1], row[2]] },
          properties: { id: row[0], s: statuses[row[3]], h: row[4] },
        };
      }),
    };
  }

  FacilityMap.prototype.setWells = function (on) {
    if (!this.wellsEnabled) return;
    this.wells = !!on;
    this.applyWells();
    this.syncUrl();
    this.shell.updateLegend();
    if (this.wells) this.loadWells();
  };

  // A cluster click zooms to where it breaks apart (MapLibre's expansion
  // zoom: a Promise on current SDKs, a callback on older ones).
  FacilityMap.prototype.zoomToCluster = function (feature) {
    var self = this;
    var source = this.map.getSource('wells');
    var center = feature.geometry.coordinates;
    var go = function (zoom) {
      if (typeof zoom !== 'number') return;
      self.map.easeTo({ center: center, zoom: zoom + 0.5, duration: self.shell.reducedMotion ? 0 : 400 });
    };
    var result = source.getClusterExpansionZoom(feature.properties.cluster_id, function (err, zoom) { if (!err) go(zoom); });
    if (result && typeof result.then === 'function') result.then(go).catch(function (err) { logError('cluster zoom', err); });
  };

  FacilityMap.prototype.openWellPopup = function (feature, lngLat) {
    var self = this;
    var id = feature.properties.id;
    var popup = this.shell.placePopup('<div class="facility-popup well-popup"><p>Loading…</p></div>', lngLat);
    getJson((this.data.wellUrl || '').replace('{id}', encodeURIComponent(id)))
      .then(function (well) {
        if (self.shell.popup !== popup) return;
        popup.setHTML('<div class="facility-popup well-popup">' +
          '<p class="facility-popup-name">' + escapeHtml(well.label) + '</p>' +
          '<p>' + escapeHtml(well.status) + (well.well_type ? ' · ' + escapeHtml(well.well_type) : '') + '</p>' +
          (well.operator ? '<p>' + escapeHtml(well.operator) + (well.field ? ', ' + escapeHtml(well.field) + ' field' : '') + '</p>' : '') +
          '<p>' + (well.spud_year ? 'Drilled ' + escapeHtml(String(well.spud_year)) + ' · ' : '') + escapeHtml(well.in_hpz || 'HPZ status unknown') + '</p>' +
          '<p class="is-size-7 has-text-grey">' + escapeHtml(self.wellsAsOf('Current status')) + '</p>' +
          '<p><a href="' + escapeHtml(well.url) + '">CalGEM record →</a></p>' +
          '</div>');
        if (self.shell.panPopupIntoView) self.shell.panPopupIntoView(popup);
      })
      .catch(function (err) {
        if (self.shell.popup !== popup) return;
        popup.setHTML('<div class="facility-popup well-popup"><p>Couldn\'t load this well.</p></div>');
        logError('failed to load a well', err);
      });
  };

  // "Today's wells, as of Sep 29, 2026": the import date the wells GeoJSON
  // carries. Wells are CalGEM's current snapshot, whatever the page's year.
  FacilityMap.prototype.wellsAsOf = function (lead) {
    var imported = this.wellsData && this.wellsData.properties && this.wellsData.properties.imported;
    if (!imported) return lead;
    var date = new Date(imported + 'T12:00:00');
    return lead + ', as of ' + date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  // The legend's overlay row: the checkbox, and while it's on the key.
  FacilityMap.prototype.wellsLegendHtml = function () {
    if (!this.wellsEnabled) return '';
    var html = '<div class="legend-overlay"><label class="legend-toggle"><input type="checkbox" data-wells' +
      (this.wells ? ' checked' : '') + '> Oil &amp; gas wells</label>';
    if (this.wells) {
      html += '<p class="legend-wells">' + WELL_STATUSES.map(function (status) {
        return '<span class="legend-well"><span class="legend-swatch is-well" style="background: ' + WELL_COLORS[status] + '"></span>' + status + '</span>';
      }).join('') + '<span class="legend-well"><span class="legend-swatch is-well is-hpz"></span>Verified health-protection zone</span></p>' +
        '<p class="legend-note">' + this.wellsAsOf('Today\'s wells') + ', not by year: CalGEM records, not emissions. Zoom in to split the clusters; click a well for its record.</p>';
    }
    return html + '</div>';
  };

  // The Methane sources (Carbon Mapper) overlay's own legend row (methane-overlay.js).
  FacilityMap.prototype.methaneLegendHtml = function () {
    return this.methane ? this.methane.legendHtml() : '';
  };

  // The schools and child care listed on a facility page, from the
  // container's own attributes (no fetch): the dots and the 1/4-mile ring
  // around the page's centre. Empty on every other page.
  FacilityMap.prototype.showNearby = function () {
    var collection = M.EMPTY;
    if (this.data.nearby) {
      try { collection = JSON.parse(this.data.nearby); } catch (err) { logError('bad nearby JSON', err); }
    }
    var center = M.parseCenter(this.data.center);
    var miles = parseFloat(this.data.ringMiles);
    this.shell.setSourceData('nearby', collection);
    this.shell.setSourceData('nearby-ring', center && miles > 0
      ? { type: 'Feature', properties: {}, geometry: circle(center, miles) }
      : M.EMPTY);
  };

  FacilityMap.prototype.openNearbyPopup = function (feature, lngLat) {
    var p = feature.properties;
    this.shell.placePopup('<div class="facility-popup">' +
      '<p class="facility-popup-name">' + escapeHtml(p.name) + '</p>' +
      // A facility page's sites say how far; an area's Schools tab's say what's near them.
      '<p>' + escapeHtml(p.type_label) + ' · ' + (p.summary ? escapeHtml(p.summary) : Number(p.feet).toLocaleString('en-US') + ' ft away') + '</p>' +
      '</div>', lngLat);
  };

  // Home goes back to the page's area when it has one.
  FacilityMap.prototype.home = function () {
    return this.outlineBounds ? { bounds: this.outlineBounds, padding: 24 } : null;
  };

  // Frame the facilities, unless the page framed the map itself (a facility
  // page's centre, the covered counties' bounds, or the page's area). A page
  // that asks (data-fit, a sector page) frames its facilities over the bounds.
  FacilityMap.prototype.fit = function (collection) {
    if (M.parseCenter(this.data.center) || this.data.outlineUrl) return;
    if (M.parseBounds(this.data.bounds) && this.data.fit !== '1') return;
    var features = collection.features || [];
    if (!features.length) return;
    var bounds = new maptilersdk.LngLatBounds();
    features.forEach(function (f) { bounds.extend(f.geometry.coordinates); });
    this.map.fitBounds(bounds, { padding: 40, maxZoom: 12, duration: 0 });
  };

  FacilityMap.prototype.facilityUrl = function (id) {
    var url = (this.data.facilityUrl || '').replace('{id}', encodeURIComponent(id));
    var query = this.data.query || '';
    if (this.data.mode === 'compact') {
      var params = new URLSearchParams(query);
      params.delete('minor');
      query = params.toString();
    }
    return url + (query ? '?' + query : '');
  };

  FacilityMap.prototype.openPopup = function (feature, lngLat) {
    var p = feature.properties;
    // p._empty means something different in Compare mode (not comparable,
    // regardless of whether this year has a value), so a null or 0 current
    // value is checked directly rather than through it.
    var noneReported = p.value === null || p.value === undefined || !(p.value > 0);
    var value = noneReported ? 'none reported' : valueText(p.value, this.data.unit);
    var compare = this.legendData && this.legendData.compare;
    var changeLine = '';
    if (compare) {
      changeLine = '<p>Change, ' + escapeHtml(String(compare)) + ' to ' + escapeHtml(this.data.year || '') + ': <strong>' +
        (p._change === null || p._change === undefined ? 'not comparable' : pctRound(p._change)) + '</strong></p>' +
        (p.value_prev === null || p.value_prev === undefined ? '' :
          '<p>' + escapeHtml(this.data.label) + ', ' + escapeHtml(String(compare)) + ': ' +
          valueText(p.value_prev, this.data.unit) + '</p>');
    }
    this.shell.placePopup('<div class="facility-popup">' +
      '<p class="facility-popup-name"><a href="' + escapeHtml(this.facilityUrl(p.id)) + '">' + escapeHtml(p.name) + '</a></p>' +
      '<p>' + escapeHtml(p.sector) + '</p>' +
      '<p>' + escapeHtml(this.data.label) + ': <strong>' + value + '</strong>' + (p.rank ? ' · #' + p.rank : '') + '</p>' +
      changeLine +
      '</div>', lngLat);
  };

  FacilityMap.prototype.openAreaPopup = function (feature, lngLat) {
    var self = this;
    var p = feature.properties;
    var count = Number(p.facilities) || 0;
    var share = this.data.unit === 'share';
    var name = (LEVEL_NAMES[this.level] || '') + p.name;
    var query = new URLSearchParams(this.data.query || '');
    query.delete('sector');
    var regionUrl = (this.data.regionUrl || '').replace('{id}', encodeURIComponent(p.id));
    var qs = query.toString();
    var line = function (label, value, suffix) {
      return '<p>' + label + ': <strong>' + (value === null || value === undefined ? '—' : valueText(value, self.data.unit) + suffix) + '</strong></p>';
    };
    var compare = this.areaData && this.areaData.compareActive;
    var changeLine = '';
    if (compare) {
      changeLine = '<p>Change, ' + escapeHtml(String(compare)) + ' to ' + escapeHtml(this.data.year || '') + ': <strong>' +
        (p._change === null || p._change === undefined ? 'not comparable' : pctRound(p._change)) + '</strong></p>';
    }
    var html = '<div class="facility-popup area-popup">' +
      '<p class="facility-popup-name">' + (regionUrl ? '<a href="' + escapeHtml(regionUrl + (qs ? '?' + qs : '')) + '">' + escapeHtml(name) + '</a>' : escapeHtml(name)) + '</p>' +
      '<p>' + count.toLocaleString('en-US') + ' facilit' + (count === 1 ? 'y' : 'ies') + ' · ' + escapeHtml(this.data.label) + '</p>' +
      changeLine +
      line(share ? 'Share' : 'Total', p.total, '') + (share ? '' : line('Per square mile', p.per_sq_mi, '') + line('Per 1,000 residents', p.per_1k_residents, '')) +
      (compare ? line('Total, ' + escapeHtml(String(compare)), p.total_prev, '') : '') +
      (count ? '<p><button type="button" class="button is-small is-link is-light" data-show-facilities>Show facilities</button></p>' : '') +
      '</div>';
    var popup = this.shell.placePopup(html, lngLat);
    var button = popup.getElement().querySelector('[data-show-facilities]');
    if (button) {
      button.addEventListener('click', function () {
        var shape = (self.areaData && self.areaData.shapes.features || []).filter(function (f) { return f.id === p.id; })[0];
        popup.remove();
        self.setView('facilities');
        var bounds = shape && M.geometryBounds(shape.geometry);
        if (bounds) self.map.fitBounds(bounds, { padding: 24, animate: !self.shell.reducedMotion });
      });
    }
  };

  // The legend card follows the view. It stays hidden until there's
  // something to put in it.
  FacilityMap.prototype.legend = function (body) {
    var legend = body.querySelector('.facility-map-legend');
    if (!legend) return;
    if (this.noFacilities) {
      // Only the overlays: their own checkboxes and keys, no facility key.
      if (this.shell.legendPanelEl) this.shell.legendPanelEl.hidden = false;
      legend.innerHTML = this.wellsLegendHtml() + this.methaneLegendHtml();
      return;
    }
    this.renderLegend(body, legend);
    legend.innerHTML = M.mainLayerToggle(legend.innerHTML, this.mainLayer);
  };

  FacilityMap.prototype.renderLegend = function (body, legend) {
    if (this.view === 'areas') {
      this.areaLegend(legend);
      return;
    }
    if (!this.legendData) return;
    if (this.shell.legendPanelEl) this.shell.legendPanelEl.hidden = false;
    var share = this.data.unit === 'share';
    var round = share ? sharePct : undefined;
    var max = this.legendData.max;
    if (this.legendData.compare) {
      // Circles still size by this year's value, a useful scale on its own,
      // so the key stays; the colour classes swap to the change ramp instead.
      var changeTitle = escapeHtml(this.data.label) + ', change ' + escapeHtml(String(this.legendData.compare)) +
        ' to ' + escapeHtml(this.data.year || '');
      legend.innerHTML = '<p class="legend-title">' + changeTitle + '</p>' + sizeKeyHtml(max, undefined, round) +
        changeBins() + '<p class="legend-empty"><span class="legend-ring"></span>' +
        'New, too small to compare, or none reported in ' + escapeHtml(String(this.legendData.compare)) + '</p>' +
        '<p class="legend-note">Facilities that closed before ' + escapeHtml(this.data.year || '') +
        ' aren\'t shown.</p>' + this.wellsLegendHtml() + this.methaneLegendHtml();
      return;
    }
    var breaks = this.legendData.breaks;
    var label = share
      ? 'Share of Valley ' + escapeHtml(this.data.label).toLowerCase() + ' toxics, ' + escapeHtml(String(this.data.year || ''))
      : escapeHtml(this.data.label) + ' (' + escapeHtml(this.data.unit) + '/yr)';
    if (!max) {
      legend.innerHTML = '<p>No facilities here reported ' + escapeHtml(this.data.label) + '.</p>' + this.wellsLegendHtml() + this.methaneLegendHtml();
      return;
    }
    legend.innerHTML = '<p class="legend-title">' + label + '</p>' +
      valueKeyHtml(max, breaks, round) +
      '<p class="legend-empty"><span class="legend-ring"></span>None reported</p>' +
      (share ? '<p class="legend-note">Pounds × OEHHA toxicity, relative to the Valley total. Not a health risk: stack height, weather and distance are ignored.</p>' : '') +
      (this.data.nearby ? '<p class="legend-note">Green dots: schools and child care within ¼ mile (dashed ring).</p>' : '') +
      this.wellsLegendHtml() + this.methaneLegendHtml();
  };

  // Before a view, level, measure, sector or page change swaps the data: no
  // hover (an area's) outlives it.
  FacilityMap.prototype.clearHover = function () {
    this.areaHover.clear();
  };

  FacilityMap.prototype.areaLegend = function (legend) {
    var data = this.areaData;
    if (!data || !data.breaks) return;
    if (this.shell.legendPanelEl) this.shell.legendPanelEl.hidden = false;
    var share = data.values.unit === 'share';
    var breaks = data.breaks;
    var missing = Number(data.values.facilities_without_point) || 0;
    if (data.compareActive) {
      var title = escapeHtml(this.data.label) + (share ? '' : (AREA_SUFFIX[this.measure] || '')) + ', change ' +
        escapeHtml(String(data.compareActive)) + ' to ' + escapeHtml(this.data.year || '');
      legend.innerHTML = '<p class="legend-title">' + title + '</p>' +
        changeBins('is-area') +
        '<p class="legend-empty"><span class="legend-swatch is-area is-none"></span>New, too small to compare, or none reported in ' +
        escapeHtml(String(data.compareActive)) + (this.measure === 'per_resident' ? ', or no population' : '') + '</p>' +
        '<p class="legend-note">Areas whose only facilities closed before ' + escapeHtml(this.data.year || '') +
        ' aren\'t shown.</p>' + this.wellsLegendHtml() + this.methaneLegendHtml();
      return;
    }
    var plainTitle = share
      ? 'Share of Valley ' + escapeHtml(this.data.label).toLowerCase() + ' toxics, ' + escapeHtml(String(this.data.year || ''))
      : escapeHtml(this.data.label) + ' (' + escapeHtml(data.values.unit) + '/yr' + (AREA_SUFFIX[this.measure] || '') + ')';
    legend.innerHTML = '<p class="legend-title">' + plainTitle + '</p>' +
      facilityBins(breaks, 'is-area', share ? sharePct : undefined) +
      '<p class="legend-empty"><span class="legend-swatch is-area is-none"></span>No facilities' +
      (this.measure === 'per_resident' ? ' or no population' : '') + '</p>' +
      (missing ? '<p class="legend-note">' + missing.toLocaleString('en-US') + ' facilit' + (missing === 1 ? 'y has' : 'ies have') +
        ' no location and ' + (missing === 1 ? 'isn\'t' : 'aren\'t') + ' counted here.</p>' : '') +
      this.wellsLegendHtml() + this.methaneLegendHtml();
  };

  // The toolbar's controls: the view switch, level and measure (Areas), and
  // the sector filter (full map). The core runs the dropdowns themselves.
  FacilityMap.prototype.onChrome = function (wrap) {
    var self = this;
    if (this.shell.legendPanelEl && !this.legendData && !this.areaData) this.shell.legendPanelEl.hidden = true;
    var shell = this.shell;
    shell.bindControls('[data-sector]', function (item) { self.setSector(item.getAttribute('data-sector'), item.textContent.trim()); });
    shell.bindControls('[data-view]', function (item) { self.setView(item.getAttribute('data-view')); });
    shell.bindControls('[data-level]', function (item) { self.setLevel(item.getAttribute('data-level'), item.textContent.trim()); });
    shell.bindControls('[data-measure]', function (item) { self.setMeasure(item.getAttribute('data-measure'), item.textContent.trim()); });
    shell.bindControls('[data-compare]', function (item) { self.setCompare(item.getAttribute('data-compare')); });
    this.applyView();

    // The legend's wells checkbox is re-rendered with the legend, so the
    // handler is delegated to the legend body, bound once.
    var legendBody = this.shell.legendBodyEl;
    if (legendBody && !legendBody.getAttribute('data-wells-bound')) {
      legendBody.setAttribute('data-wells-bound', '1');
      legendBody.addEventListener('change', function (event) {
        if (event.target && event.target.hasAttribute('data-wells')) self.setWells(event.target.checked);
        if (event.target && event.target.hasAttribute('data-main-layer')) { self.mainLayer = event.target.checked; self.applyView(); }
      });
    }
    if (this.methane) this.methane.bind(legendBody);

    // The Options menu's experiment controls (basemap style, colour ramp),
    // same pattern as the pesticides section map: fill the selects, apply
    // a change live and write it to the URL.
    this.optionsEl = wrap.querySelector('.facility-map-options');
    if (this.optionsEl) {
      var options = this.optionsEl;
      var fill = function (select, pairs) {
        pairs.forEach(function (pair) {
          var option = document.createElement('option');
          option.value = pair[0];
          option.textContent = pair[1];
          select.appendChild(option);
        });
      };
      var bindChange = function (selector, handler) {
        var input = options.querySelector(selector);
        if (input) input.addEventListener('change', handler.bind(self));
        return input;
      };
      // The tiles select is the shell's: it fills, applies and writes its
      // own style, and only tells us to catch up (this.tileStyle, syncUrl).
      shell.bindTiles('select[name="tiles"]', function () {
        self.tileStyle = shell.tileStyle;
        self.syncUrl();
      });
      this.rampSelect = bindChange('select[name="ramp"]', this.onRampChange);
      // Diverging names while Compare is on: a sequential ramp can't grade
      // signed data, and vice versa.
      this.fillRampOptions = function () {
        if (!self.rampSelect) return;
        self.rampSelect.innerHTML = '';
        fill(self.rampSelect, Object.keys(self.compare ? M.ramps.diverging : M.ramps.sequential)
          .map(function (name) { return [name, name]; }));
        self.rampSelect.value = self.compare ? self.dRampName : self.rampName;
      };
      this.fillRampOptions();
    }
    this.syncOptionsControls();
  };

  // Puts the Options controls in line with this map's view: after a bind
  // (onChrome, including an adopt) and after a Compare toggle.
  FacilityMap.prototype.syncOptionsControls = function () {
    if (!this.optionsEl) return;
    var set = function (selector, prop, value) {
      var input = this.optionsEl.querySelector(selector);
      if (input) input[prop] = value;
    }.bind(this);
    set('select[name="tiles"]', 'value', this.tileStyle);
    set('select[name="ramp"]', 'value', this.compare ? this.dRampName : this.rampName);
  };

  FacilityMap.prototype.onDropdownOpen = function () {
    this.shell.closePopup();
  };

  // Sets the map's state on `params` (a URLSearchParams), defaults left out:
  // view `facilities`, the page's default level, measure `density`, and no
  // sector. The sector is only the map's to write on the full map, where the
  // reader picks it (a sector page's own sector is the page, not a filter).
  FacilityMap.prototype.writeState = function (params) {
    if (this.areasEnabled) {
      var areas = this.view === 'areas';
      if (areas) params.set('view', 'areas'); else params.delete('view');
      if (areas && this.level !== this.defaultLevel) params.set('level', this.level); else params.delete('level');
      if (areas && this.measure !== 'density') params.set('measure', this.measure); else params.delete('measure');
      // Compare applies to both views (a facility's own circle too), so it's
      // written whenever it's set, not only in Areas.
      if (this.compare) params.set('compare', this.compare); else params.delete('compare');
    }
    if (this.data.mode === 'full') {
      var sector = new URLSearchParams(this.data.query || '').get('sector');
      if (sector) params.set('sector', sector); else params.delete('sector');
    }
    // The Options menu's experiment controls (basemap style, colour ramp);
    // not page scope, so every map with a toolbar writes these regardless
    // of mode. `dramp` is kept apart from `ramp` (rather than one name
    // reused across both tables) so toggling Compare on and off never
    // loses the other one's pick.
    if (this.tileStyle && this.tileStyle !== this.defaultTileStyle) params.set('tiles', this.tileStyle); else params.delete('tiles');
    if (this.rampName !== DEFAULT_RAMP) params.set('ramp', this.rampName); else params.delete('ramp');
    if (this.dRampName !== DEFAULT_DRAMP) params.set('dramp', this.dRampName); else params.delete('dramp');
    // The wells overlay: written only when it differs from the page's default.
    if (this.wellsEnabled && this.wells !== this.wellsDefault) params.set('wells', this.wells ? '1' : '0'); else params.delete('wells');
    if (this.methane) this.methane.writeState(params);
  };

  // The address bar follows the view, level and measure (and the sector) so
  // a view can be shared.
  FacilityMap.prototype.syncUrl = function () {
    M.syncUrl(this.writeState.bind(this));
  };

  FacilityMap.prototype.setView = function (view) {
    if (!this.areasEnabled) return;
    this.view = view === 'areas' ? 'areas' : 'facilities';
    this.clearHover();
    this.applyView();
    this.syncUrl();
    if (this.view === 'areas' && (!this.areaData || this.areaData.level !== this.level)) {
      this.loadAreas();
      return;
    }
    this.shell.updateLegend();
    // The status pill speaks for the view on screen.
    if (this.view === 'facilities') {
      this.shell.setStatus(this.el.dataset.loaded === '1' ? '' : 'Loading facilities…');
    } else {
      this.shell.setStatus('');
    }
  };

  FacilityMap.prototype.setLevel = function (level, label) {
    this.level = level;
    this.clearHover();
    this.markDropdown('.facility-map-level', '[data-level]', level, label);
    this.syncUrl();
    this.loadAreas();
  };

  FacilityMap.prototype.setMeasure = function (measure, label) {
    if (this.data.unit === 'share' && measure !== 'total') return;
    this.measure = measure;
    this.clearHover();
    this.markDropdown('.facility-map-measure', '[data-measure]', measure, label);
    this.syncUrl();
    this.showAreas();
  };

  // The compared year: unlike a measure switch, this needs a refetch (the
  // server pairs both years' totals; the client never fetches a bare year on
  // its own).
  FacilityMap.prototype.setCompare = function (compare) {
    this.compare = compare || '';
    this.clearHover();
    var dropdown = this.shell.wrap && this.shell.wrap.querySelector('.facility-map-compare');
    if (dropdown) {
      dropdown.classList.toggle('is-set', !!this.compare);
      var text = dropdown.querySelector('.map-toolbar-label');
      if (text) text.textContent = this.compare ? 'vs ' + this.compare : 'Compare';
      Array.prototype.forEach.call(dropdown.querySelectorAll('[data-compare]'), function (item) {
        item.classList.toggle('is-active', item.getAttribute('data-compare') === (compare || ''));
      });
    }
    this.syncUrl();
    this.applyView();
    // The Ramp select swaps tables (sequential <-> diverging) with Compare;
    // refill it so it offers the right names and shows the one already
    // chosen for whichever table is live now.
    if (this.fillRampOptions) this.fillRampOptions();
    // Facilities always shade by the change when it's on; areas only need
    // the refetch while that view is up (same pattern as setSector) --
    // otherwise leave a stale areaData behind for setView('areas') to
    // reuse and refetch itself.
    this.loadFacilities();
    if (this.view === 'areas') {
      this.loadAreas();
    } else {
      this.areaData = null;
      this.areaRequest++;
    }
  };

  // The basemap style is part of the map's style, so swapping it (shell.
  // bindTiles) rebuilds it outright (no diff, which would drop our layers
  // without the style.load that puts them back). The shell's onStyleLoad
  // calls addLayers() on load, which re-adds every source and layer from
  // the data this map already has cached (facilities, areas, outline), so
  // nothing here needs to refetch.

  // Recolours the facilities layer (Facilities view) and/or the areas
  // choropleth (Areas view) after RAMP or CHANGE_RAMP changes, from data
  // already on hand -- no refetch. The change ramp also recolours the
  // Facilities circles while Compare is on (prepare() colours them by the
  // change too, see `compare` there).
  FacilityMap.prototype.recolor = function () {
    if (this.legendData) {
      this.legendData = prepare(this.legendData.collection, this.data.unit, this.legendData.compare);
      this.shell.setSourceData('facilities', this.legendData.collection);
      this.applyHighlight();
    }
    if (this.areaData) this.showAreas();
    this.shell.updateLegend();
  };

  // Picks a candidate ramp from the shared table (assets/js/maps/core.js):
  // the sequential table normally, the diverging one while Compare is on
  // (see fillRampOptions). Each is sampled to the class count its view
  // uses, so the fixed breaks (CLASS_BREAKS/AREA_BREAKS, CHANGE_BREAKS)
  // are unaffected -- only the colours change.
  FacilityMap.prototype.onRampChange = function (event) {
    var name = event.target.value;
    if (this.compare) {
      if (!M.ramps.diverging[name]) return;
      this.dRampName = name;
      CHANGE_RAMP = sampleRamp(M.ramps.diverging[name], CHANGE_BREAKS.length + 1);
    } else {
      if (!M.ramps.sequential[name]) return;
      this.rampName = name;
      RAMP = sampleRamp(M.ramps.sequential[name], 5);
    }
    this.recolor();
    this.syncUrl();
  };

  FacilityMap.prototype.markDropdown = function (selector, itemSelector, value, label) {
    var dropdown = this.shell.wrap && this.shell.wrap.querySelector(selector);
    if (!dropdown) return;
    var text = dropdown.querySelector('.map-toolbar-label');
    if (text && label) text.textContent = label;
    var attribute = itemSelector.slice(1, -1);
    Array.prototype.forEach.call(dropdown.querySelectorAll(itemSelector), function (item) {
      item.classList.toggle('is-active', item.getAttribute(attribute) === value);
    });
  };

  // The sector filter narrows both views without a page swap; the address
  // bar follows so the view can be shared.
  FacilityMap.prototype.setSector = function (sector, label) {
    var params = new URLSearchParams(this.data.query || '');
    if (sector) params.set('sector', sector); else params.delete('sector');
    this.data.query = params.toString();
    this.clearHover();
    this.syncUrl();
    var dropdown = this.shell.wrap && this.shell.wrap.querySelector('.facility-map-sector');
    if (dropdown) {
      dropdown.classList.toggle('is-set', !!sector);
      var text = dropdown.querySelector('.map-toolbar-label');
      if (text) text.textContent = label || 'All sectors';
      Array.prototype.forEach.call(dropdown.querySelectorAll('[data-sector]'), function (item) {
        item.classList.toggle('is-active', item.getAttribute('data-sector') === (sector || ''));
      });
    }
    this.loadFacilities();
    if (this.view === 'areas') {
      this.loadAreas();
    } else {
      // A sector change made while off the areas view must not leave a
      // stale areaData behind: setView('areas') would otherwise reuse it
      // because the level still matches.
      this.areaData = null;
      this.areaRequest++;
    }
  };

  // A swap brought a new page: drop what belonged to the old one (its
  // popup, the located dot, its area values and outline), take the new
  // page's view, frame it, and reload.
  FacilityMap.prototype.onAdopt = function () {
    this.shell.closePopup();
    // The new page's legend card waits for its own data, as on a first build.
    this.legendData = null;
    this.areaData = null;
    // An old page's areas or outline still in flight must not land here.
    this.areaRequest++;
    this.outlineRequest++;
    if (this.shell.legendPanelEl) this.shell.legendPanelEl.hidden = true;
    // Before the areas source is replaced: a stale hover feature-state on
    // the new page's data would otherwise point at the wrong feature.
    this.clearHover();
    this.shell.setSourceData('locate', M.EMPTY);
    this.shell.setSourceData('areas', M.EMPTY);
    this.shell.setStatus('');
    this.readViewState();
    this.noFacilities = this.data.mainLayer === 'none';
    this.mainLayer = !this.noFacilities && this.data.mainLayer !== '0';
    this.applyView();
    this.applyWells();
    if (this.wells) this.loadWells();
    if (this.methane) this.methane.onAdopt();
    this.fitted = false;
    this.shell.frame();
    this.showHighlightPin();
    this.applyHighlight();
    this.load();
  };

  FacilityMap.prototype.destroy = function () {
    this.shell.closePopup();
    this.clearHover();
    if (this.methane) this.methane.destroy();
    document.body.removeEventListener('htmx:configRequest', this.onConfigRequest);
    this.map = null;
  };

  M.register('facility', {
    selector: '.facility-map',
    lifecycle: 'adopt',
    features: { controls: ['zoom', 'locate', 'home'], toolbar: true, legend: true, status: true, expand: true },
    // The key readers' folded legends were saved under before the core.
    panelStoragePrefix: 'emissions:facility-map:panel:',
    create: function (shell) { return new FacilityMap(shell); },
  });

  window.EmissionsFacilityMap = {
    init: M.init,
    instances: function () { return M.instances('facility'); },
  };
})();
