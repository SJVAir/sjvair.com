/*
 * SPIKE -- throwaway. The explorer's section map on the MapTiler SDK
 * (MapLibre GL) instead of Leaflet, enough to judge the port: the
 * township/section grid with quantile classes, hover, the 3x3 lens, a
 * popup, and the htmx swap lifecycle. Loaded only under `?gl=1` (see
 * pesticides/base.html); the Leaflet map skips containers marked data-gl.
 * Timings and MapTiler request stats are logged to the console and kept
 * on window.__glStats.
 */
(function () {
  'use strict';

  if (typeof window.maptilersdk === 'undefined') return;

  var SECTION_ZOOM = 11;
  var NUM_CLASSES = 6;
  var RAMP = ['#deebf7', '#9ecae1', '#6baed6', '#3182bd', '#08519c'];
  var NO_DATA_COLOR = '#f0f0f0';
  var TOWNSHIP_DEGREES = { lat: 0.087, lng: 0.108 };
  // The eight counties, roughly.
  var VALLEY = [[-121.65, 34.75], [-117.6, 38.35]];
  var METRIC_LABELS = { lbs_chemical: 'lbs', applications: 'applications' };

  var instances = [];
  window.__glStats = window.__glStats || [];

  // -- classing, as in section-map.js --
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
  function quantileClasses(values) {
    var positive = values.filter(function (v) { return v; }).sort(function (a, b) { return a - b; });
    var distinct = positive.filter(function (v, i) { return i === 0 || v !== positive[i - 1]; });
    if (!distinct.length) return { breaks: [], colors: [] };
    var count = Math.min(NUM_CLASSES, distinct.length);
    var breaks = [];
    for (var k = 1; k <= count; k++) breaks.push(distinct[Math.ceil((k * distinct.length) / count) - 1]);
    return { breaks: breaks, colors: sampleRamp(RAMP, count) };
  }
  function indexFor(breaks, value) {
    for (var i = 0; i < breaks.length; i++) if (value <= breaks[i]) return i;
    return breaks.length - 1;
  }
  function colorFor(classes, value) {
    if (!value || !classes.breaks.length) return NO_DATA_COLOR;
    return classes.colors[indexFor(classes.breaks, value)];
  }

  // -- helpers --
  function buildQuery(params) {
    return Object.keys(params).filter(function (k) { return params[k] !== undefined && params[k] !== null && params[k] !== ''; })
      .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); }).join('&');
  }
  function bboxOf(geometry) {
    var w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
    var rings = geometry.type === 'Polygon' ? geometry.coordinates : [].concat.apply([], geometry.coordinates);
    rings.forEach(function (ring) {
      ring.forEach(function (c) { if (c[0] < w) w = c[0]; if (c[0] > e) e = c[0]; if (c[1] < s) s = c[1]; if (c[1] > n) n = c[1]; });
    });
    return [w, s, e, n];
  }
  function bboxPolygon(b) {
    return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]] } };
  }
  function formatNumber(n) { return Math.round(n || 0).toLocaleString('en-US'); }
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

  function GLMap(el) {
    var self = this;
    this.el = el;
    this.data = el.dataset;
    this.metric = 'lbs_chemical';
    this.bboxes = {};
    this.lensCache = {};
    this.hoverId = null;
    this.lensId = null;
    this.stats = { created: performance.now(), requests: 0 };
    window.__glStats.push(this.stats);

    var keyMatch = /[?&]key=([^&]+)/.exec(this.data.tiles || '');
    maptilersdk.config.apiKey = keyMatch ? keyMatch[1] : '';
    var center = (this.data.center || '').split(',').map(parseFloat);
    var hasCenter = center.length === 2 && !center.some(isNaN);

    this.map = new maptilersdk.Map({
      container: el,
      style: maptilersdk.MapStyle.DATAVIZ,
      center: hasCenter ? [center[1], center[0]] : [-119.8, 36.75],
      zoom: parseInt(this.data.zoom, 10) || 8,
      navigationControl: 'top-left',
      geolocateControl: false,
      scrollZoom: false,
      terrainControl: false,
    });
    el.glMap = this;

    this.map.once('load', function () {
      self.stats.styleLoaded = performance.now() - self.stats.created;
      console.log('[gl] style loaded in ' + Math.round(self.stats.styleLoaded) + ' ms');
      if (self.data.fit === 'valley') self.map.fitBounds(VALLEY, { padding: 20, animate: false });
      self.addLayers();
      self.loadGrid();
      self.map.on('moveend', function () { self.loadGrid(); });
      self.bindHover();
      self.bindClick();
    });
    this.map.once('idle', function () {
      self.stats.firstIdle = performance.now() - self.stats.created;
      console.log('[gl] first idle at ' + Math.round(self.stats.firstIdle) + ' ms');
      self.reportRequests();
    });
  }

  GLMap.prototype.firstSymbolLayer = function () {
    var layers = this.map.getStyle().layers || [];
    for (var i = 0; i < layers.length; i++) if (layers[i].type === 'symbol') return layers[i].id;
    return undefined;
  };

  GLMap.prototype.addLayers = function () {
    var map = this.map;
    var before = this.firstSymbolLayer();
    var empty = { type: 'FeatureCollection', features: [] };
    var hovered = ['boolean', ['feature-state', 'hover'], false];
    map.addSource('grid', { type: 'geojson', data: empty, promoteId: 'id' });
    map.addSource('lens', { type: 'geojson', data: empty, promoteId: 'id' });
    map.addSource('lens-outline', { type: 'geojson', data: empty });
    map.addLayer({
      id: 'grid-fill', type: 'fill', source: 'grid',
      paint: {
        'fill-color': ['coalesce', ['get', 'fill'], NO_DATA_COLOR],
        'fill-opacity': ['coalesce', ['get', 'opacity'], 0.25],
      },
    }, before);
    map.addLayer({
      id: 'grid-line', type: 'line', source: 'grid',
      paint: {
        'line-color': ['case', hovered, '#222', '#999'],
        'line-width': ['case', hovered, 2.5, 0.75],
        'line-opacity': ['case', hovered, 1, 0.6],
      },
    }, before);
    map.addLayer({
      id: 'lens-fill', type: 'fill', source: 'lens',
      paint: { 'fill-color': ['coalesce', ['get', 'fill'], NO_DATA_COLOR], 'fill-opacity': ['coalesce', ['get', 'opacity'], 0.25] },
    }, before);
    map.addLayer({
      id: 'lens-line', type: 'line', source: 'lens',
      paint: { 'line-color': '#999', 'line-width': 0.5, 'line-opacity': 0.8 },
    }, before);
    map.addLayer({
      id: 'lens-outline', type: 'line', source: 'lens-outline',
      paint: { 'line-color': '#222', 'line-width': 2 },
    }, before);
  };

  GLMap.prototype.commonParams = function () {
    return { year: this.data.year, chemical: this.data.chemical, product: this.data.product, commodity: this.data.commodity, county: this.data.county, concern: this.data.concern };
  };

  GLMap.prototype.viewBbox = function (pad) {
    var b = this.map.getBounds();
    var w = b.getWest(), s = b.getSouth(), e = b.getEast(), n = b.getNorth();
    var dx = (e - w) * (pad || 0), dy = (n - s) * (pad || 0);
    return [w - dx, s - dy, e + dx, n + dy].map(function (v) { return v.toFixed(4); }).join(',');
  };

  GLMap.prototype.loadGrid = function () {
    var self = this;
    var level = this.map.getZoom() >= SECTION_ZOOM ? 'section' : 'township';
    var url = level === 'township' ? this.data.townshipsUrl : this.data.sectionsUrl;
    if (!url) return;
    var params = this.commonParams();
    params.bbox = this.viewBbox(0.2);
    var started = performance.now();
    var request = ++this.stats.requests;
    fetch(url + '?' + buildQuery(params))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (geojson) {
        if (!geojson || request !== self.stats.requests) return;
        var fetched = performance.now() - started;
        self.level = level;
        var classes = quantileClasses(geojson.features.map(function (f) { return f.properties[self.metric]; }));
        self.classes = classes;
        geojson.features.forEach(function (f) {
          var value = f.properties[self.metric];
          f.properties.fill = colorFor(classes, value);
          f.properties.opacity = value ? 0.7 : 0.25;
          if (level === 'township') self.bboxes[f.properties.id] = bboxOf(f.geometry);
        });
        self.map.getSource('grid').setData(geojson);
        self.map.once('idle', function () {
          var total = performance.now() - started;
          console.log('[gl] ' + level + ' grid: ' + geojson.features.length + ' features, fetch ' + Math.round(fetched) + ' ms, drawn at ' + Math.round(total) + ' ms');
          self.stats.lastGrid = { level: level, features: geojson.features.length, fetch: fetched, total: total };
        });
      })
      .catch(function (err) { console.error('[gl] grid failed', err); });
  };

  GLMap.prototype.setHover = function (id) {
    if (this.hoverId === id) return;
    if (this.hoverId != null) this.map.setFeatureState({ source: 'grid', id: this.hoverId }, { hover: false });
    this.hoverId = id;
    if (id != null) this.map.setFeatureState({ source: 'grid', id: id }, { hover: true });
  };

  GLMap.prototype.bindHover = function () {
    var self = this;
    var lensTimer = null, clearTimer = null;
    this.map.on('mousemove', 'grid-fill', function (e) {
      var feature = e.features && e.features[0];
      if (!feature) return;
      self.map.getCanvas().style.cursor = 'pointer';
      self.setHover(feature.id);
      clearTimeout(clearTimer);
      if (self.level === 'township' && self.lensId !== feature.id) {
        clearTimeout(lensTimer);
        lensTimer = setTimeout(function () { self.showLens(feature.id); }, 50);
      }
    });
    this.map.on('mouseleave', 'grid-fill', function () {
      self.map.getCanvas().style.cursor = '';
      self.setHover(null);
      clearTimeout(lensTimer);
      clearTimer = setTimeout(function () { self.clearLens(); }, 150);
    });
  };

  GLMap.prototype.neighbourhood = function (id) {
    var host = this.bboxes[id];
    if (!host) return [id];
    var cx = (host[0] + host[2]) / 2, cy = (host[1] + host[3]) / 2;
    var maxDx = Math.max(host[2] - host[0], TOWNSHIP_DEGREES.lng) * 1.5;
    var maxDy = Math.max(host[3] - host[1], TOWNSHIP_DEGREES.lat) * 1.5;
    var ids = [];
    for (var other in this.bboxes) {
      var b = this.bboxes[other];
      if (Math.abs((b[0] + b[2]) / 2 - cx) <= maxDx && Math.abs((b[1] + b[3]) / 2 - cy) <= maxDy) ids.push(other);
    }
    return ids;
  };

  GLMap.prototype.showLens = function (id) {
    var self = this;
    this.lensId = id;
    var ids = this.neighbourhood(id);
    var union = [Infinity, Infinity, -Infinity, -Infinity];
    ids.forEach(function (other) {
      var b = self.bboxes[other];
      union = [Math.min(union[0], b[0]), Math.min(union[1], b[1]), Math.max(union[2], b[2]), Math.max(union[3], b[3])];
    });
    var draw = function (sections) {
      if (self.lensId !== id) return;
      var classes = quantileClasses(sections.map(function (f) { return f.properties[self.metric]; }));
      sections.forEach(function (f) {
        var value = f.properties[self.metric];
        f.properties.fill = colorFor(classes, value);
        f.properties.opacity = value ? 0.75 : 0.15;
      });
      self.map.getSource('lens').setData({ type: 'FeatureCollection', features: sections });
      self.map.getSource('lens-outline').setData(bboxPolygon(union));
    };
    var key = ids.slice().sort().join('|');
    if (this.lensCache[key]) { draw(this.lensCache[key]); return; }
    var params = this.commonParams();
    params.bbox = union.map(function (v) { return v.toFixed(4); }).join(',');
    var started = performance.now();
    fetch(this.data.sectionsUrl + '?' + buildQuery(params))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (body) {
        if (!body) return;
        self.lensCache[key] = body.features;
        console.log('[gl] lens ' + id + ': ' + body.features.length + ' sections in ' + Math.round(performance.now() - started) + ' ms');
        draw(body.features);
      })
      .catch(function () {});
  };

  GLMap.prototype.clearLens = function () {
    if (this.lensId == null) return;
    this.lensId = null;
    var empty = { type: 'FeatureCollection', features: [] };
    this.map.getSource('lens').setData(empty);
    this.map.getSource('lens-outline').setData(empty);
  };

  GLMap.prototype.bindClick = function () {
    var self = this;
    this.map.on('click', 'grid-fill', function (e) {
      var feature = e.features && e.features[0];
      if (!feature) return;
      var p = feature.properties;
      var value = p[self.metric];
      var html =
        '<div class="section-popup"><h4>' + escapeHtml(p.name || p.mtrs || p.id) + '</h4>' +
        (self.level === 'township' ? '<p class="section-popup-sub">Township · ' + formatNumber(p.sections) + ' square-mile sections</p>' : '<p class="section-popup-sub">Section</p>') +
        '<p><strong>' + formatNumber(value) + '</strong> ' + METRIC_LABELS[self.metric] + (self.data.yearLabel ? ' in ' + escapeHtml(self.data.yearLabel) : '') + '</p>' +
        (self.level === 'township' ? '<div class="section-popup-actions"><button type="button" class="section-popup-action gl-zoom">Zoom in to sections</button></div>' : '') +
        '</div>';
      if (self.popup) self.popup.remove();
      self.popup = new maptilersdk.Popup({ maxWidth: '300px' }).setLngLat(e.lngLat).setHTML(html).addTo(self.map);
      var button = self.popup.getElement().querySelector('.gl-zoom');
      if (button) button.addEventListener('click', function () {
        self.popup.remove();
        self.map.easeTo({ center: e.lngLat, zoom: SECTION_ZOOM });
      });
    });
  };

  GLMap.prototype.reportRequests = function () {
    var entries = performance.getEntriesByType('resource').filter(function (r) { return r.name.indexOf('api.maptiler.com') !== -1; });
    var keys = {};
    var sessions = {};
    entries.forEach(function (r) {
      var q = r.name.split('?')[1] || '';
      q.split('&').forEach(function (pair) {
        var k = pair.split('=')[0];
        keys[k] = (keys[k] || 0) + 1;
        if (k === 'mtsid') sessions[pair.split('=')[1]] = true;
      });
    });
    this.stats.maptilerRequests = entries.length;
    this.stats.queryKeys = keys;
    this.stats.sessionIds = Object.keys(sessions);
    console.log('[gl] MapTiler requests so far: ' + entries.length + '; query keys: ' + JSON.stringify(keys) + '; session ids: ' + JSON.stringify(this.stats.sessionIds));
  };

  GLMap.prototype.destroy = function () {
    if (this.popup) this.popup.remove();
    this.map.remove();
  };

  function init(root) {
    root = root || document;
    instances = instances.filter(function (item) {
      if (document.body.contains(item.el)) return true;
      item.destroy();
      console.log('[gl] destroyed a swapped-out map');
      return false;
    });
    var els = root.querySelectorAll ? root.querySelectorAll('.section-map[data-gl]') : [];
    Array.prototype.forEach.call(els, function (el) {
      if (!el.dataset.gl || el.dataset.rendered) return;
      el.dataset.rendered = '1';
      instances.push(new GLMap(el));
    });
  }

  window.PesticidesSectionMapGL = { init: init, instances: function () { return instances; } };
})();
