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
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M || !M.register) return;

  // ColorBrewer Blues, one colour per class below (the pesticides map's
  // default ramp, without its palest step, which vanishes on the basemap).
  var RAMP = ['#c6dbef', '#9ecae1', '#6baed6', '#3182bd', '#08519c'];
  // Fixed classes on a log scale, per display unit: stable across pollutants,
  // counties and years, and readable ("1-10 tons"). Toxics are shown in lbs.
  var CLASS_BREAKS = { tons: [0.1, 1, 10, 100], lbs: [1, 10, 100, 1000] };
  // The Areas view's classes, per measure and unit.
  var AREA_BREAKS = {
    density: { tons: [0.01, 0.1, 1, 10], lbs: [0.1, 1, 10, 100] },
    total: { tons: [1, 10, 100, 1000], lbs: [10, 100, 1000, 10000] },
    per_resident: { tons: [0.1, 1, 10, 100], lbs: [1, 10, 100, 1000] },
  };
  var AREA_FIELDS = { density: 'per_sq_mi', total: 'total', per_resident: 'per_1k_residents' };
  var AREA_SUFFIX = { density: ' per sq mi', total: '', per_resident: ' per 1,000 people' };
  var LEVEL_NAMES = { county: '', zipcode: 'ZIP ', tract: 'Tract ' };
  var EMPTY_COLOR = '#8a94a3';
  var HIGHLIGHT_COLOR = '#d35400';
  var COUNTY_COLOR = '#1f2d3d';
  var DISTRICT_COLOR = '#6a3d9a';
  var MIN_RADIUS = 3;
  var MAX_RADIUS = 26;
  var WORLD_RING = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
  var CIRCLE_POINTS = 64;
  var METERS_PER_MILE = 1609.344;

  var escapeHtml = M.escapeHtml;
  var logError = M.logger('facility-map');

  // The same rules as the `amount` template filter.
  function amount(value) {
    if (value === null || value === undefined) return '—';
    var size = Math.abs(value);
    if (size && size < 0.01) return '<0.01';
    var digits = size && size < 1 ? 2 : (size && size < 10 ? 1 : 0);
    return value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function breaksFor(unit) {
    return CLASS_BREAKS[unit] || CLASS_BREAKS.tons;
  }

  function areaBreaksFor(measure, unit) {
    var set = AREA_BREAKS[measure] || AREA_BREAKS.density;
    return set[unit] || set.tons;
  }

  function classIndex(value, breaks) {
    var index = 0;
    while (index < breaks.length && value >= breaks[index]) index++;
    return index;
  }

  // "under 0.1", "0.1–1", ..., "100 and up"
  function classLabel(index, breaks) {
    if (index === 0) return 'under ' + amount(breaks[0]);
    if (index === breaks.length) return amount(breaks[index - 1]) + ' and up';
    return amount(breaks[index - 1]) + '–' + amount(breaks[index]);
  }

  function radiusFor(value, max) {
    return MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * Math.sqrt(value / max);
  }

  function getJson(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    });
  }

  // Precompute each circle so the layer's paint is plain `get`s.
  function prepare(collection, unit) {
    var features = collection.features || [];
    var positive = features.map(function (f) { return f.properties.value; }).filter(function (v) { return v > 0; });
    var max = positive.length ? Math.max.apply(null, positive) : 0;
    var breaks = breaksFor(unit);
    features.forEach(function (feature) {
      var p = feature.properties;
      var reported = p.value > 0 && max > 0;
      p._radius = reported ? radiusFor(p.value, max) : MIN_RADIUS;
      p._color = reported ? RAMP[classIndex(p.value, breaks)] : EMPTY_COLOR;
      p._empty = reported ? 0 : 1;
      p._sort = reported ? p.value : 0;
    });
    return { collection: collection, breaks: breaks, max: max };
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
    this.popup = null;
    this.fitted = false;
    this.legendData = null;
    // The Areas view: shapes per level (they never change with the scope),
    // the current values, and a request counter of its own (the shell's
    // ticket is the facilities fetch's).
    this.shapes = {};
    this.areaData = null;
    this.areaRequest = 0;
    this.outlineBounds = null;
    this.readViewState();
    // Layer-bound listeners wait for their layer, so they're bound once here
    // rather than on every style load.
    this.map.on('click', 'facilities', function (evt) { self.openPopup(evt.features[0], evt.lngLat); });
    this.map.on('click', 'areas-fill', function (evt) { self.openAreaPopup(evt.features[0], evt.lngLat); });
    ['facilities', 'areas-fill'].forEach(function (layer) {
      self.map.on('mouseenter', layer, function () { self.map.getCanvas().style.cursor = 'pointer'; });
      self.map.on('mouseleave', layer, function () { self.map.getCanvas().style.cursor = ''; });
    });
    // The scope bar's links (year, pollutant, toggles) were rendered before
    // the reader switched view or sector here; carry the map's state along on
    // the boosted request so the next page opens the same way.
    this.onConfigRequest = function (event) {
      var elt = event.detail && event.detail.elt;
      if (!elt || !elt.closest || !elt.closest('.explorer-scope')) return;
      var params = event.detail.parameters;
      var sector = new URLSearchParams(self.data.query || '').get('sector');
      if (sector) params.sector = sector;
      if (self.view !== 'areas') return;
      params.view = 'areas';
      params.level = self.level;
      params.measure = self.measure;
    };
    document.body.addEventListener('htmx:configRequest', this.onConfigRequest);
    // For debugging from the console: document.querySelector('.facility-map').facilityMap
    this.el.facilityMap = this;
  }

  FacilityMap.prototype.readViewState = function () {
    this.areasEnabled = this.data.areas === '1';
    this.view = this.areasEnabled && this.data.view === 'areas' ? 'areas' : 'facilities';
    this.level = this.data.level || 'zipcode';
    this.measure = this.data.measure || 'density';
  };

  // Bottom to top: the shaded areas, the wash outside the page's area, the
  // county and district lines, the facilities, the page's area outline. On
  // top of the whole basemap, labels included: the data is what the map is for.
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
      paint: { 'line-color': '#4a5568', 'line-width': 0.5, 'line-opacity': 0.5 },
    });
    this.shell.ensureLayer({
      id: 'outline-mask', type: 'fill', source: 'outline-mask',
      paint: { 'fill-color': '#ffffff', 'fill-opacity': 0.55 },
    });
    this.shell.ensureLayer({
      id: 'counties', type: 'line', source: 'counties',
      paint: { 'line-color': COUNTY_COLOR, 'line-width': 1, 'line-opacity': 0.5 },
    });
    this.shell.ensureLayer({
      id: 'districts', type: 'line', source: 'districts',
      paint: { 'line-color': DISTRICT_COLOR, 'line-width': 2, 'line-dasharray': [3, 2] },
    });
    this.shell.ensureLayer({
      id: 'facilities', type: 'circle', source: 'facilities',
      // Larger values draw on top.
      layout: { 'circle-sort-key': ['get', '_sort'] },
      paint: { 'circle-radius': ['get', '_radius'], 'circle-color': ['get', '_color'] },
    });
    this.shell.ensureLayer({
      id: 'outline-line', type: 'line', source: 'outline',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': HIGHLIGHT_COLOR, 'line-width': 2.5, 'line-opacity': 0.9 },
    });
    this.applyHighlight();
    this.applyView();
  };

  // Hollow rings for "none reported"; with a highlighted facility (a facility
  // page), it gets an orange ring and everything else fades.
  FacilityMap.prototype.applyHighlight = function () {
    if (!this.map || !this.map.getLayer('facilities')) return;
    var id = this.data.highlight || '';
    var isHighlight = ['==', ['get', 'id'], id];
    var isEmpty = ['==', ['get', '_empty'], 1];
    this.map.setPaintProperty('facilities', 'circle-opacity',
      ['case', isEmpty, 0, id ? ['case', isHighlight, 0.95, 0.35] : 0.85]);
    this.map.setPaintProperty('facilities', 'circle-stroke-color',
      ['case', isHighlight, HIGHLIGHT_COLOR, isEmpty, EMPTY_COLOR, '#ffffff']);
    this.map.setPaintProperty('facilities', 'circle-stroke-width',
      ['case', isHighlight, 3, isEmpty, 1.25, 0.75]);
  };

  // One view at a time: the layers, the toolbar's switch and its Areas-only
  // controls follow `this.view`.
  FacilityMap.prototype.applyView = function () {
    var areas = this.view === 'areas';
    if (this.map) {
      var set = function (map, id, visible) {
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none');
      };
      set(this.map, 'facilities', !areas);
      set(this.map, 'areas-fill', areas);
      set(this.map, 'areas-line', areas);
    }
    Array.prototype.forEach.call(this.controls('[data-view]'), function (button) {
      var on = button.getAttribute('data-view') === (areas ? 'areas' : 'facilities');
      button.classList.toggle('is-selected', on);
      button.classList.toggle('is-link', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    Array.prototype.forEach.call(this.controls('[data-areas-only]'), function (control) {
      control.hidden = !areas;
    });
  };

  // The toolbar's own controls matching `selector`. Not the whole wrap: the
  // map container carries data-view, data-level and data-measure too.
  FacilityMap.prototype.controls = function (selector) {
    var toolbar = this.shell.toolbarEl;
    return toolbar ? toolbar.querySelectorAll(selector) : [];
  };

  FacilityMap.prototype.url = function () {
    var query = this.data.query || '';
    return this.data.geojsonUrl + (query ? '?' + query : '');
  };

  // The facilities always load (switching back to them is then instant);
  // the areas load when they're the view.
  FacilityMap.prototype.load = function () {
    this.loadFacilities();
    if (this.view === 'areas') this.loadAreas();
    this.loadOutline();
  };

  FacilityMap.prototype.loadFacilities = function () {
    var self = this;
    var ticket = this.shell.ticket();
    this.el.dataset.loaded = '';
    this.shell.setStatus('Loading facilities…');
    getJson(this.url())
      .then(function (collection) {
        // A newer request (a sector change, a swap) or a destroy superseded this one.
        if (!self.shell.isCurrent(ticket)) return;
        self.show(collection);
      })
      .catch(function (err) {
        if (!self.shell.isCurrent(ticket)) return;
        self.shell.setStatus('Couldn\'t load the facilities');
        logError('failed to load facilities', err);
      });
  };

  FacilityMap.prototype.show = function (collection) {
    var prepared = prepare(collection, this.data.unit);
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
        self.shell.setStatus('Couldn\'t load the areas');
        logError('failed to load areas', err);
      });
  };

  // Joins the values to the shapes and colours them by the current measure
  // (a measure change re-runs this without fetching).
  FacilityMap.prototype.showAreas = function () {
    var data = this.areaData;
    if (!data) return;
    var byId = {};
    data.values.areas.forEach(function (area) { byId[area.id] = area; });
    var field = AREA_FIELDS[this.measure] || AREA_FIELDS.density;
    var breaks = areaBreaksFor(this.measure, data.values.unit);
    var features = (data.shapes.features || []).map(function (feature) {
      var area = byId[feature.id];
      var value = area ? area[field] : null;
      var shaded = value !== null && value !== undefined && value > 0;
      return {
        type: 'Feature',
        id: feature.id,
        geometry: feature.geometry,
        properties: Object.assign({}, feature.properties, {
          facilities: area ? area.facilities : 0,
          total: area ? area.total : null,
          per_sq_mi: area ? area.per_sq_mi : null,
          per_1k_residents: area ? area.per_1k_residents : null,
          _color: shaded ? RAMP[classIndex(value, breaks)] : EMPTY_COLOR,
          _empty: shaded ? 0 : 1,
        }),
      };
    });
    data.breaks = breaks;
    this.shell.setSourceData('areas', { type: 'FeatureCollection', features: features });
    this.shell.updateLegend();
    this.shell.setStatus('');
    this.el.dataset.areasLoaded = '1';
  };

  // The page's own area: a region's boundary (region pages) or the radius
  // (near-me), outlined, with everything outside washed out, and framed.
  FacilityMap.prototype.loadOutline = function () {
    var self = this;
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
        var boundary = json && json.data && json.data.boundary;
        if (self.map) self.showOutline(boundary ? boundary.geometry : null);
      })
      .catch(function (err) { logError('failed to load the outline', err); });
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

  // Home goes back to the page's area when it has one.
  FacilityMap.prototype.home = function () {
    return this.outlineBounds ? { bounds: this.outlineBounds, padding: 24 } : null;
  };

  // Frame the facilities, unless the page framed the map itself (a facility
  // page's centre, the covered counties' bounds, or the page's area).
  FacilityMap.prototype.fit = function (collection) {
    if (M.parseCenter(this.data.center) || M.parseBounds(this.data.bounds) || this.data.outlineUrl) return;
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

  FacilityMap.prototype.placePopup = function (html, lngLat) {
    var self = this;
    if (this.popup) this.popup.remove();
    this.popup = new maptilersdk.Popup({ maxWidth: this.shell.popupMaxWidth() }).setLngLat(lngLat).setHTML(html).addTo(this.map);
    // Clear of the toolbar and legend card, as on the pesticides map.
    this.shell.panPopupIntoView(this.popup);
    this.popup.on('close', function () { self.popup = null; });
    return this.popup;
  };

  FacilityMap.prototype.openPopup = function (feature, lngLat) {
    var p = feature.properties;
    var value = p._empty ? 'none reported' : amount(p.value) + ' ' + escapeHtml(this.data.unit) + '/yr';
    this.placePopup('<div class="facility-popup">' +
      '<p class="facility-popup-name"><a href="' + escapeHtml(this.facilityUrl(p.id)) + '">' + escapeHtml(p.name) + '</a></p>' +
      '<p>' + escapeHtml(p.sector) + '</p>' +
      '<p>' + escapeHtml(this.data.label) + ': <strong>' + value + '</strong>' + (p.rank ? ' · #' + p.rank : '') + '</p>' +
      '</div>', lngLat);
  };

  FacilityMap.prototype.openAreaPopup = function (feature, lngLat) {
    var self = this;
    var p = feature.properties;
    var unit = escapeHtml(this.data.unit);
    var name = (LEVEL_NAMES[this.level] || '') + p.name;
    var query = new URLSearchParams(this.data.query || '');
    query.delete('sector');
    var regionUrl = (this.data.regionUrl || '').replace('{id}', encodeURIComponent(p.id));
    var qs = query.toString();
    var line = function (label, value, suffix) {
      return '<p>' + label + ': <strong>' + (value === null || value === undefined ? '—' : amount(value) + ' ' + unit + '/yr' + suffix) + '</strong></p>';
    };
    var html = '<div class="facility-popup area-popup">' +
      '<p class="facility-popup-name">' + (regionUrl ? '<a href="' + escapeHtml(regionUrl + (qs ? '?' + qs : '')) + '">' + escapeHtml(name) + '</a>' : escapeHtml(name)) + '</p>' +
      '<p>' + p.facilities + ' facilit' + (p.facilities === 1 ? 'y' : 'ies') + ' · ' + escapeHtml(this.data.label) + '</p>' +
      line('Total', p.total, '') + line('Per square mile', p.per_sq_mi, '') + line('Per 1,000 residents', p.per_1k_residents, '') +
      (p.facilities ? '<p><button type="button" class="button is-small is-link is-light" data-show-facilities>Show facilities</button></p>' : '') +
      '</div>';
    var popup = this.placePopup(html, lngLat);
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
    if (this.view === 'areas') {
      this.areaLegend(legend);
      return;
    }
    if (!this.legendData) return;
    if (this.shell.legendPanelEl) this.shell.legendPanelEl.hidden = false;
    var max = this.legendData.max;
    var breaks = this.legendData.breaks;
    var label = escapeHtml(this.data.label) + ' (' + escapeHtml(this.data.unit) + '/yr)';
    if (!max) {
      legend.innerHTML = '<p>No facilities here reported ' + escapeHtml(this.data.label) + '.</p>';
      return;
    }
    var sizes = [max, max / 10, max / 100].map(function (value) {
      var r = radiusFor(value, max);
      return '<span class="legend-size"><svg width="' + (2 * MAX_RADIUS + 2) + '" height="' + (2 * r + 2) + '">' +
        '<circle cx="' + (MAX_RADIUS + 1) + '" cy="' + (r + 1) + '" r="' + r + '"/></svg>' + amount(value) + '</span>';
    }).join('');
    var bins = '';
    for (var i = breaks.length; i >= 0; i--) {
      bins += '<span class="legend-bin"><span class="legend-swatch" style="background:' + RAMP[i] + '"></span>' +
        classLabel(i, breaks) + '</span>';
    }
    legend.innerHTML = '<p class="legend-title">' + label + '</p>' +
      '<div class="legend-sizes">' + sizes + '</div>' +
      '<div class="legend-bins">' + bins + '</div>' +
      '<p class="legend-empty"><span class="legend-ring"></span>None reported</p>';
  };

  FacilityMap.prototype.areaLegend = function (legend) {
    var data = this.areaData;
    if (!data || !data.breaks) return;
    if (this.shell.legendPanelEl) this.shell.legendPanelEl.hidden = false;
    var breaks = data.breaks;
    var title = escapeHtml(this.data.label) + ' (' + escapeHtml(data.values.unit) + '/yr' + (AREA_SUFFIX[this.measure] || '') + ')';
    var bins = '';
    for (var i = breaks.length; i >= 0; i--) {
      bins += '<span class="legend-bin"><span class="legend-swatch is-area" style="background:' + RAMP[i] + '"></span>' +
        classLabel(i, breaks) + '</span>';
    }
    var missing = data.values.facilities_without_point;
    legend.innerHTML = '<p class="legend-title">' + title + '</p>' +
      '<div class="legend-bins">' + bins + '</div>' +
      '<p class="legend-empty"><span class="legend-swatch is-area is-none"></span>No facilities' +
      (this.measure === 'per_resident' ? ' or no population' : '') + '</p>' +
      (missing ? '<p class="legend-note">' + missing + ' facilit' + (missing === 1 ? 'y has' : 'ies have') +
        ' no location and ' + (missing === 1 ? 'isn\'t' : 'aren\'t') + ' counted here.</p>' : '');
  };

  // The toolbar's controls: the view switch, level and measure (Areas), and
  // the sector filter (full map). The core runs the dropdowns themselves.
  FacilityMap.prototype.onChrome = function (wrap) {
    var self = this;
    if (this.shell.legendPanelEl && !this.legendData && !this.areaData) this.shell.legendPanelEl.hidden = true;
    var bind = function (selector, handler) {
      Array.prototype.forEach.call(self.controls(selector), function (item) {
        if (item.getAttribute('data-bound')) return;
        item.setAttribute('data-bound', '1');
        item.addEventListener('click', function (event) {
          event.preventDefault();
          M.chrome.closeDropdowns(self.shell, null);
          handler(item);
        });
      });
    };
    bind('[data-sector]', function (item) { self.setSector(item.getAttribute('data-sector'), item.textContent.trim()); });
    bind('[data-view]', function (item) { self.setView(item.getAttribute('data-view')); });
    bind('[data-level]', function (item) { self.setLevel(item.getAttribute('data-level'), item.textContent.trim()); });
    bind('[data-measure]', function (item) { self.setMeasure(item.getAttribute('data-measure'), item.textContent.trim()); });
    this.applyView();
  };

  FacilityMap.prototype.onDropdownOpen = function () {
    if (this.popup) this.popup.remove();
  };

  // The address bar follows the view, level and measure (and the sector) so
  // a view can be shared; defaults are left out.
  FacilityMap.prototype.syncUrl = function () {
    var page = new URLSearchParams(window.location.search);
    if (this.view === 'areas') {
      page.set('view', 'areas');
      page.set('level', this.level);
      page.set('measure', this.measure);
    } else {
      page.delete('view');
      page.delete('level');
      page.delete('measure');
    }
    var search = page.toString();
    window.history.replaceState(window.history.state, '', window.location.pathname + (search ? '?' + search : ''));
  };

  FacilityMap.prototype.setView = function (view) {
    if (!this.areasEnabled) return;
    this.view = view === 'areas' ? 'areas' : 'facilities';
    this.applyView();
    this.syncUrl();
    if (this.view === 'areas' && (!this.areaData || this.areaData.level !== this.level)) {
      this.loadAreas();
    } else {
      this.shell.updateLegend();
    }
  };

  FacilityMap.prototype.setLevel = function (level, label) {
    this.level = level;
    this.markDropdown('.facility-map-level', '[data-level]', level, label);
    this.syncUrl();
    this.loadAreas();
  };

  FacilityMap.prototype.setMeasure = function (measure, label) {
    this.measure = measure;
    this.markDropdown('.facility-map-measure', '[data-measure]', measure, label);
    this.syncUrl();
    this.showAreas();
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
    var page = new URLSearchParams(window.location.search);
    if (sector) {
      params.set('sector', sector);
      page.set('sector', sector);
    } else {
      params.delete('sector');
      page.delete('sector');
    }
    this.data.query = params.toString();
    var search = page.toString();
    window.history.replaceState(window.history.state, '', window.location.pathname + (search ? '?' + search : ''));
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
    if (this.view === 'areas') this.loadAreas();
  };

  // A swap brought a new page: drop what belonged to the old one (its
  // popup, the located dot, its area values and outline), take the new
  // page's view, frame it, and reload.
  FacilityMap.prototype.onAdopt = function () {
    if (this.popup) this.popup.remove();
    // The new page's legend card waits for its own data, as on a first build.
    this.legendData = null;
    this.areaData = null;
    if (this.shell.legendPanelEl) this.shell.legendPanelEl.hidden = true;
    this.shell.setSourceData('locate', M.EMPTY);
    this.shell.setSourceData('areas', M.EMPTY);
    this.shell.setStatus('');
    this.readViewState();
    this.applyView();
    this.fitted = false;
    this.shell.frame();
    this.applyHighlight();
    this.load();
  };

  FacilityMap.prototype.destroy = function () {
    if (this.popup) this.popup.remove();
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
