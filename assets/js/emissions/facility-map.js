/*
 * Facility map for the Facility Emissions Explorer, on the MapTiler SDK
 * (MapLibre GL).
 *
 * Turns each `.facility-map` container into a map of permitted facilities:
 * one circle per facility, its area scaled by the selected pollutant (square
 * root, so the largest emitter doesn't bury the rest) and its colour by
 * quantile class; facilities that reported none are small hollow grey rings.
 * County and air district outlines sit underneath, and everything sits below
 * the basemap's labels. Config comes entirely from the container's data-*
 * attributes (emissions/includes/facility-map.html, views.facility_map_config).
 *
 * Modes: `full` (the map page: sector filter, locate, expand, legend) and
 * `compact` (facility and sector pages: no toolbar; a facility page's own
 * facility is highlighted and the rest faded).
 *
 * htmx: explorer.js calls EmissionsFacilityMap.init(root) after every swap. A
 * swap that brings a new container adopts the live map in place instead of
 * building another, so a page load uses one MapTiler session.
 *
 * Plain ES2017, no framework; one global, window.EmissionsFacilityMap.
 */
(function () {
  'use strict';

  // ColorBrewer Blues, 6 classes: the pesticides map's default ramp.
  var RAMP = ['#deebf7', '#c6dbef', '#9ecae1', '#6baed6', '#3182bd', '#08519c'];
  var EMPTY_COLOR = '#8a94a3';
  var HIGHLIGHT_COLOR = '#d35400';
  var COUNTY_COLOR = '#1f2d3d';
  var DISTRICT_COLOR = '#6a3d9a';
  var MIN_RADIUS = 3;
  var MAX_RADIUS = 26;
  var STYLE_PATHS = { dataviz: ['DATAVIZ'], 'dataviz-light': ['DATAVIZ', 'LIGHT'], streets: ['STREETS'] };
  var EMPTY_COLLECTION = { type: 'FeatureCollection', features: [] };

  var liveMap = null;
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

  function logError(message, err) {
    if (window.console && console.error) console.error('facility-map: ' + message, err);
  }

  function styleFor(id) {
    var path = STYLE_PATHS[id];
    var style = path ? maptilersdk.MapStyle : null;
    for (var i = 0; style && i < path.length; i++) style = style[path[i]];
    return style || id;
  }

  // "36.75,-119.80" -> [lng, lat]; null when blank or malformed.
  function parseCenter(value) {
    if (!value || !String(value).trim()) return null;
    var parts = String(value).split(',').map(Number);
    if (parts.length !== 2 || !isFinite(parts[0]) || !isFinite(parts[1])) return null;
    return [parts[1], parts[0]];
  }

  // "west,south,east,north" -> [[west, south], [east, north]]; null when blank or malformed.
  function parseBounds(value) {
    if (!value || !String(value).trim()) return null;
    var parts = String(value).split(',').map(Number);
    if (parts.length !== 4 || !parts.every(isFinite)) return null;
    return [[parts[0], parts[1]], [parts[2], parts[3]]];
  }

  function escapeHtml(text) {
    return String(text == null ? '' : text).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // The same rules as the `amount` template filter.
  function amount(value) {
    if (value === null || value === undefined) return '—';
    var size = Math.abs(value);
    if (size && size < 0.01) return '<0.01';
    var digits = size && size < 1 ? 2 : (size && size < 10 ? 1 : 0);
    return value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  // Upper bounds of the quantile classes over the positive values (at most RAMP.length - 1).
  function quantileBreaks(values) {
    var sorted = values.filter(function (v) { return v > 0; }).sort(function (a, b) { return a - b; });
    var breaks = [];
    for (var i = 1; i < RAMP.length && sorted.length; i++) {
      var value = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * i / RAMP.length))];
      if (!breaks.length || value > breaks[breaks.length - 1]) breaks.push(value);
    }
    return breaks;
  }

  // However many classes there are, spread them across the whole ramp.
  function classColor(index, breaks) {
    return RAMP[breaks.length ? Math.round(index * (RAMP.length - 1) / breaks.length) : RAMP.length - 1];
  }

  function colorFor(value, breaks) {
    var index = 0;
    while (index < breaks.length && value > breaks[index]) index++;
    return classColor(index, breaks);
  }

  function radiusFor(value, max) {
    return MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * Math.sqrt(value / max);
  }

  // Precompute each circle so the layer's paint is plain `get`s.
  function prepare(collection) {
    var features = collection.features || [];
    var values = features.map(function (f) { return f.properties.value; });
    var positive = values.filter(function (v) { return v > 0; });
    var max = positive.length ? Math.max.apply(null, positive) : 0;
    var breaks = quantileBreaks(values);
    features.forEach(function (feature) {
      var p = feature.properties;
      var reported = p.value > 0 && max > 0;
      p._radius = reported ? radiusFor(p.value, max) : MIN_RADIUS;
      p._color = reported ? colorFor(p.value, breaks) : EMPTY_COLOR;
      p._empty = reported ? 0 : 1;
      p._sort = reported ? p.value : 0;
    });
    return { collection: collection, breaks: breaks, max: max };
  }

  var LOCATE_COLOR = '#3388ff';
  var LOCATE_ZOOM = 12;
  var PHONE_QUERY = '(max-width: 768px)';
  // The legend's fold, per viewer, in localStorage (wrapped: storage can be
  // absent or throw, and the card must work regardless).
  var PANEL_STORAGE_PREFIX = 'emissions:facility-map:panel:';

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

  function readPanelState(name) {
    try {
      var stored = window.localStorage.getItem(PANEL_STORAGE_PREFIX + name);
      return stored === null ? null : stored === 'collapsed';
    } catch (err) {
      return null;
    }
  }

  function writePanelState(name, collapsed) {
    try {
      window.localStorage.setItem(PANEL_STORAGE_PREFIX + name, collapsed ? 'collapsed' : 'open');
    } catch (err) {
      // The fold just won't be remembered.
    }
  }

  function setPanelCollapsed(panel, collapsed) {
    panel.classList.toggle('is-collapsed', collapsed);
    var toggle = panel.querySelector('.section-map-panel-toggle');
    if (toggle) toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  }

  // Locate and home as SDK controls, one bar each under the zoom buttons,
  // with the pesticides map's markup and classes (section-map-locate,
  // section-map-reset) so they look the same.
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
      // A click on a control isn't a click on the map (that turns wheel-zoom on).
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

  function FacilityMap(el) {
    this.el = el;
    this.data = el.dataset;
    this.wrap = el.closest('.facility-map-wrap');
    this.popup = null;
    this.request = 0;
    this.fitted = false;
    this.legendData = null;
    this.expanded = false;
    this.init();
  }

  FacilityMap.prototype.init = function () {
    var self = this;
    maptilersdk.config.apiKey = this.data.maptilerKey || '';
    var center = parseCenter(this.data.center);
    // Without a page-given centre (a facility page), open on the covered
    // counties, never on the facilities: one bad geocode would drag it anywhere.
    var bounds = center ? null : parseBounds(this.data.bounds);
    this.map = new maptilersdk.Map({
      container: this.el,
      style: styleFor(this.data.style || 'dataviz'),
      center: center || [-119.80, 36.75],
      zoom: parseFloat(this.data.zoom) || 7,
      bounds: bounds || undefined,
      fitBoundsOptions: { padding: 20 },
      navigationControl: false,
      geolocateControl: false,
      terrainControl: false,
      // Off until the map is clicked, so it doesn't hijack page scrolling.
      scrollZoom: false,
      pitchWithRotate: false,
      dragRotate: false,
      touchPitch: false,
      attributionControl: { compact: 'auto' },
      logoPosition: 'bottom-right',
    });
    this.map.touchZoomRotate.disableRotation();
    this.map.keyboard.disableRotation();
    // Zoom, then locate, then home, stacked top-left as on the pesticides map.
    this.map.addControl(new maptilersdk.NavigationControl({ showCompass: false }), 'top-left');
    if (navigator.geolocation) {
      this.locateControl = new BarControl('section-map-locate', 'Zoom to my location', 'fa-regular fa-location-crosshairs', function () {
        self.locate();
      });
      this.map.addControl(this.locateControl, 'top-left');
    }
    this.map.addControl(new BarControl('section-map-reset', 'Zoom out to the whole map', 'fa-regular fa-house', function () {
      self.resetView();
    }), 'top-left');
    this.el.addEventListener('click', function () { self.map.scrollZoom.enable(); });
    this.el.addEventListener('mouseleave', function () { self.map.scrollZoom.disable(); });
    // For debugging from the console: document.querySelector('.facility-map').facilityMap
    this.el.facilityMap = this;
    this.bindDocument();
    this.bindChrome();
    this.map.on('load', function () {
      self.addLayers();
      self.load();
    });
  };

  // The first symbol layer: our layers go under the basemap's labels.
  FacilityMap.prototype.labelLayer = function () {
    var layers = this.map.getStyle().layers || [];
    for (var i = 0; i < layers.length; i++) {
      if (layers[i].type === 'symbol') return layers[i].id;
    }
    return undefined;
  };

  FacilityMap.prototype.addLayers = function () {
    var self = this;
    var before = this.labelLayer();
    this.map.addSource('counties', { type: 'geojson', data: this.data.countiesUrl || EMPTY_COLLECTION });
    this.map.addSource('districts', { type: 'geojson', data: this.data.districtsUrl || EMPTY_COLLECTION });
    this.map.addSource('facilities', { type: 'geojson', data: EMPTY_COLLECTION });
    this.map.addSource('locate', { type: 'geojson', data: EMPTY_COLLECTION });
    this.map.addLayer({
      id: 'counties', type: 'line', source: 'counties',
      paint: { 'line-color': COUNTY_COLOR, 'line-width': 1, 'line-opacity': 0.5 },
    }, before);
    this.map.addLayer({
      id: 'districts', type: 'line', source: 'districts',
      paint: { 'line-color': DISTRICT_COLOR, 'line-width': 2, 'line-dasharray': [3, 2] },
    }, before);
    this.map.addLayer({
      id: 'facilities', type: 'circle', source: 'facilities',
      // Larger values draw on top.
      layout: { 'circle-sort-key': ['get', '_sort'] },
      paint: { 'circle-radius': ['get', '_radius'], 'circle-color': ['get', '_color'] },
    }, before);
    this.map.addLayer({
      id: 'locate', type: 'circle', source: 'locate',
      paint: { 'circle-radius': 7, 'circle-color': LOCATE_COLOR, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2 },
    });
    this.applyHighlight();
    this.map.on('click', 'facilities', function (evt) { self.openPopup(evt.features[0], evt.lngLat); });
    this.map.on('mouseenter', 'facilities', function () { self.map.getCanvas().style.cursor = 'pointer'; });
    this.map.on('mouseleave', 'facilities', function () { self.map.getCanvas().style.cursor = ''; });
  };

  // Hollow rings for "none reported"; with a highlighted facility (a facility
  // page), it gets an orange ring and everything else fades.
  FacilityMap.prototype.applyHighlight = function () {
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

  FacilityMap.prototype.url = function () {
    var query = this.data.query || '';
    return this.data.geojsonUrl + (query ? '?' + query : '');
  };

  FacilityMap.prototype.load = function () {
    var self = this;
    var ticket = ++this.request;
    this.el.dataset.loaded = '';
    this.setStatus('Loading facilities…');
    fetch(this.url(), { credentials: 'same-origin' })
      .then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      })
      .then(function (collection) {
        // A newer request (a sector change, a swap) has superseded this one.
        if (ticket !== self.request) return;
        self.show(collection);
      })
      .catch(function (err) {
        if (ticket !== self.request) return;
        self.setStatus('Couldn\'t load the facilities');
        logError('failed to load facilities', err);
      });
  };

  FacilityMap.prototype.show = function (collection) {
    var prepared = prepare(collection);
    this.legendData = prepared;
    this.map.getSource('facilities').setData(prepared.collection);
    this.applyHighlight();
    this.updateLegend();
    this.setStatus('');
    if (!this.fitted) {
      this.fit(prepared.collection);
      this.fitted = true;
    }
    this.el.dataset.loaded = '1';
  };

  // Frame the facilities, unless the page framed the map itself (a facility
  // page's centre, or the covered counties' bounds).
  FacilityMap.prototype.fit = function (collection) {
    if (parseCenter(this.data.center) || parseBounds(this.data.bounds)) return;
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
    var value = p._empty ? 'none reported' : amount(p.value) + ' ' + escapeHtml(this.data.unit) + '/yr';
    var html = '<div class="facility-popup">' +
      '<p class="facility-popup-name"><a href="' + escapeHtml(this.facilityUrl(p.id)) + '">' + escapeHtml(p.name) + '</a></p>' +
      '<p>' + escapeHtml(p.sector) + '</p>' +
      '<p>' + escapeHtml(this.data.label) + ': <strong>' + value + '</strong>' + (p.rank ? ' · #' + p.rank : '') + '</p>' +
      '</div>';
    if (this.popup) this.popup.remove();
    this.popup = new maptilersdk.Popup({ maxWidth: '280px' }).setLngLat(lngLat).setHTML(html).addTo(this.map);
  };

  FacilityMap.prototype.updateLegend = function () {
    var legend = this.wrap && this.wrap.querySelector('.facility-map-legend');
    var panel = this.wrap && this.wrap.querySelector('.facility-map-legend-panel');
    if (!legend || !this.legendData) return;
    if (panel) panel.hidden = false;
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
    for (var i = 0; i <= breaks.length; i++) {
      var low = i ? breaks[i - 1] : 0;
      var high = i < breaks.length ? breaks[i] : max;
      bins += '<span class="legend-bin"><span class="legend-swatch" style="background:' + classColor(i, breaks) + '"></span>' +
        amount(low) + '–' + amount(high) + '</span>';
    }
    legend.innerHTML = '<p class="legend-title">' + label + '</p>' +
      '<div class="legend-sizes">' + sizes + '</div>' +
      '<div class="legend-bins">' + bins + '</div>' +
      '<p class="legend-empty"><span class="legend-ring"></span>None reported</p>';
  };

  FacilityMap.prototype.setStatus = function (message) {
    var status = this.wrap && this.wrap.querySelector('.section-map-status');
    if (status) status.textContent = message || '';
  };

  // Listeners on the document, bound once per map: a click elsewhere closes
  // the toolbar's dropdowns; Escape closes them, then leaves expanded mode.
  FacilityMap.prototype.bindDocument = function () {
    var self = this;
    this.documentClick = function () { self.closeDropdowns(null); };
    this.documentKey = function (event) {
      if (event.key !== 'Escape') return;
      self.closeDropdowns(null);
      if (self.expanded) self.setExpanded(false);
    };
    this.windowResize = function () {
      if (self.expanded) self.fitBelowNavbar();
    };
    document.addEventListener('click', this.documentClick);
    document.addEventListener('keydown', this.documentKey);
    window.addEventListener('resize', this.windowResize);
  };

  // The toolbar (sector filter, expand) and the legend card, bound once per
  // element: a swap brings new ones, which get bound again.
  FacilityMap.prototype.bindChrome = function () {
    var self = this;
    if (!this.wrap) return;
    var toolbar = this.wrap.querySelector('.facility-map-toolbar');
    if (toolbar && !toolbar.dataset.bound) {
      toolbar.dataset.bound = '1';
      toolbar.hidden = false;
      var dropdowns = toolbar.querySelectorAll('.dropdown');
      Array.prototype.forEach.call(dropdowns, function (dropdown) {
        var trigger = dropdown.querySelector('.dropdown-trigger .button');
        if (!trigger) return;
        trigger.addEventListener('click', function (event) {
          event.stopPropagation();
          var open = !dropdown.classList.contains('is-active');
          self.closeDropdowns(dropdown);
          dropdown.classList.toggle('is-active', open);
          trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
          if (open && self.popup) self.popup.remove();
        });
        var menu = dropdown.querySelector('.dropdown-menu');
        if (menu) menu.addEventListener('click', function (event) { event.stopPropagation(); });
      });
      Array.prototype.forEach.call(toolbar.querySelectorAll('[data-sector]'), function (item) {
        item.addEventListener('click', function (event) {
          event.preventDefault();
          self.closeDropdowns(null);
          self.setSector(item.getAttribute('data-sector'), item.textContent.trim());
        });
      });
      var expand = toolbar.querySelector('.section-map-expand');
      if (expand) expand.addEventListener('click', function () { self.setExpanded(!self.expanded); });
    }
    var panel = this.wrap.querySelector('.facility-map-legend-panel');
    if (panel && !panel.dataset.bound) {
      panel.dataset.bound = '1';
      // Until the reader folds it, the legend starts open on a desktop and
      // folded on a phone, where it would cover the map.
      var stored = readPanelState('legend');
      setPanelCollapsed(panel, stored === null ? isPhone() : stored);
      var toggle = panel.querySelector('.section-map-panel-toggle');
      if (toggle) {
        toggle.addEventListener('click', function () {
          var collapsed = !panel.classList.contains('is-collapsed');
          setPanelCollapsed(panel, collapsed);
          writePanelState('legend', collapsed);
        });
      }
    }
  };

  FacilityMap.prototype.closeDropdowns = function (except) {
    if (!this.wrap) return;
    Array.prototype.forEach.call(this.wrap.querySelectorAll('.facility-map-toolbar .dropdown'), function (dropdown) {
      if (dropdown === except) return;
      dropdown.classList.remove('is-active');
      var trigger = dropdown.querySelector('.dropdown-trigger .button');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
    });
  };

  // The sector filter narrows the map without a page swap; the address bar
  // follows so the view can be shared.
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
    var dropdown = this.wrap && this.wrap.querySelector('.facility-map-sector');
    if (dropdown) {
      dropdown.classList.toggle('is-set', !!sector);
      var text = dropdown.querySelector('.section-map-toolbar-label');
      if (text) text.textContent = label || 'All sectors';
      Array.prototype.forEach.call(dropdown.querySelectorAll('[data-sector]'), function (item) {
        item.classList.toggle('is-active', item.getAttribute('data-sector') === (sector || ''));
      });
    }
    this.load();
  };

  // Home goes back to what the page is about: its facility on a facility
  // page, otherwise the covered counties.
  FacilityMap.prototype.resetView = function () {
    var center = parseCenter(this.data.center);
    var bounds = parseBounds(this.data.bounds);
    if (center) {
      this.map.easeTo({ center: center, zoom: parseFloat(this.data.zoom) || 11, animate: !prefersReducedMotion() });
    } else if (bounds) {
      this.map.fitBounds(bounds, { padding: 20, animate: !prefersReducedMotion() });
    }
  };

  FacilityMap.prototype.locate = function () {
    var self = this;
    var control = this.locateControl && this.locateControl.container;
    if (control) control.classList.add('is-locating');
    this.setStatus('Finding your location…');
    navigator.geolocation.getCurrentPosition(function (position) {
      if (control) control.classList.remove('is-locating');
      self.setStatus('');
      var here = [position.coords.longitude, position.coords.latitude];
      var source = self.map.getSource('locate');
      if (source) source.setData({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: here } });
      self.map.easeTo({ center: here, zoom: LOCATE_ZOOM, animate: !prefersReducedMotion() });
    }, function () {
      if (control) control.classList.remove('is-locating');
      self.setStatus('Couldn\'t get your location');
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  };

  // Expanded, the map fills the viewport under the site navbar, with the
  // explorer's scope bar pinned above it (the pesticides map's expanded
  // mode and CSS). Escape or the button brings the page back.
  FacilityMap.prototype.setExpanded = function (on) {
    var was = this.expanded;
    this.expanded = on;
    if (on && !was) {
      this.scrollBeforeExpand = window.scrollY || window.pageYOffset || 0;
      window.scrollTo(0, 0);
    }
    document.documentElement.classList.toggle('section-map-expanded', on);
    if (this.wrap) {
      this.wrap.classList.toggle('is-expanded', on);
      if (on) {
        this.fitBelowNavbar();
      } else {
        this.wrap.style.top = '';
        var scopeBar = document.querySelector('.explorer-scope-bar');
        if (scopeBar) scopeBar.style.top = '';
      }
      var button = this.wrap.querySelector('.section-map-expand');
      if (button) {
        button.setAttribute('aria-pressed', on ? 'true' : 'false');
        button.setAttribute('title', on ? 'Back to the page' : 'Expand the map');
        button.setAttribute('aria-label', on ? 'Back to the page' : 'Expand the map');
      }
    }
    if (!on && was) window.scrollTo(0, this.scrollBeforeExpand || 0);
    this.map.resize();
  };

  // The expanded map starts where the navbar (and the pinned scope bar) end.
  FacilityMap.prototype.fitBelowNavbar = function () {
    if (!this.wrap) return;
    var nav = document.querySelector('nav.navbar');
    var bottom = nav ? nav.getBoundingClientRect().bottom : 0;
    var scopeBar = document.querySelector('.explorer-scope-bar');
    if (scopeBar) {
      scopeBar.style.top = Math.max(0, bottom) + 'px';
      bottom = scopeBar.getBoundingClientRect().bottom;
    }
    this.wrap.style.top = Math.max(0, bottom - 1) + 'px';
  };

  // A boosted swap brought a new container: put the live map's element in
  // its place, take its config, and reload the facilities.
  FacilityMap.prototype.adopt = function (el) {
    if (this.expanded) this.setExpanded(false);
    el.parentNode.replaceChild(this.el, el);
    var keys = Object.keys(el.dataset);
    for (var i = 0; i < keys.length; i++) this.el.dataset[keys[i]] = el.dataset[keys[i]];
    this.el.dataset.rendered = '1';
    this.data = this.el.dataset;
    this.wrap = this.el.closest('.facility-map-wrap');
    if (this.popup) {
      this.popup.remove();
      this.popup = null;
    }
    this.bindChrome();
    this.setStatus('');
    var located = this.map.getSource('locate');
    if (located) located.setData(EMPTY_COLLECTION);
    this.fitted = false;
    this.map.resize();
    var center = parseCenter(this.data.center);
    var bounds = parseBounds(this.data.bounds);
    if (center) this.map.jumpTo({ center: center, zoom: parseFloat(this.data.zoom) || this.map.getZoom() });
    else if (bounds) this.map.fitBounds(bounds, { padding: 20, duration: 0 });
    if (this.map.getSource('facilities')) this.load();
  };

  FacilityMap.prototype.destroy = function () {
    if (this.expanded) this.setExpanded(false);
    document.documentElement.classList.remove('section-map-expanded');
    document.removeEventListener('click', this.documentClick);
    document.removeEventListener('keydown', this.documentKey);
    window.removeEventListener('resize', this.windowResize);
    // A fetch still in flight must not draw on the removed map.
    this.request++;
    if (this.popup) this.popup.remove();
    this.map.remove();
  };

  function containersUnder(root) {
    var found = [];
    if (root.matches && root.matches('.facility-map')) found.push(root);
    var nested = root.querySelectorAll ? root.querySelectorAll('.facility-map') : [];
    for (var i = 0; i < nested.length; i++) found.push(nested[i]);
    return found;
  }

  // Idempotent: initialised containers carry data-rendered, so this is safe
  // to call on page load and after every htmx swap.
  function init(root) {
    if (typeof maptilersdk === 'undefined') return;
    var containers = containersUnder(root || document);
    // A swap to a page without a map releases the live one. Judged against
    // the whole document: htmx fires htmx:load per swapped element, and the
    // one for an out-of-band fragment must not take the map away.
    if (liveMap && !document.body.contains(liveMap.el) && !containersUnder(document).length) {
      liveMap.destroy();
      liveMap = null;
    }
    for (var i = 0; i < containers.length; i++) {
      var el = containers[i];
      if (el.dataset.rendered) continue;
      try {
        if (!webglAvailable()) {
          el.dataset.rendered = '1';
          el.classList.add('is-unavailable');
          el.innerHTML = '<p class="section-map-note">This map needs WebGL, which this browser has turned off or doesn\'t support.</p>';
          continue;
        }
        if (liveMap && !document.body.contains(liveMap.el)) {
          liveMap.adopt(el);
          continue;
        }
        el.dataset.rendered = '1';
        liveMap = new FacilityMap(el);
      } catch (err) {
        logError('failed to initialize', err);
      }
    }
  }

  window.EmissionsFacilityMap = {
    init: init,
    instances: function () { return liveMap ? [liveMap] : []; },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(document); });
  } else {
    init(document);
  }
})();
