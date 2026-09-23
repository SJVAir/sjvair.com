/*
 * Facility map for the Facility Emissions Explorer, a module on the map core
 * (assets/js/maps/), registered as 'facility'.
 *
 * One circle per permitted facility: its area scaled by the selected
 * pollutant (square root, so the largest emitter doesn't bury the rest) and
 * its colour by a fixed log-scale class; facilities that reported none are
 * small hollow grey rings. County and air district outlines sit under the
 * circles, and all of it draws over the whole basemap, labels included.
 * Config comes from the container's data-* attributes
 * (views.facility_map_config); the chrome is the core's.
 *
 * Modes: `full` (the map page, with the sector filter) and `compact`
 * (facility and sector pages; a facility page's own facility is highlighted
 * and the rest faded).
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M || !M.register) return;

  // ColorBrewer Blues, one colour per class below (the pesticides map's
  // default ramp, without its palest step, which vanishes on the basemap).
  var RAMP = ['#c6dbef', '#9ecae1', '#6baed6', '#3182bd', '#08519c'];
  // Fixed classes on a log scale, per display unit: stable across pollutants,
  // counties and years, and readable ("1-10 tons"). Quantiles bunched at the
  // bottom, since most facilities emit very little. Toxics are shown in lbs.
  var CLASS_BREAKS = { tons: [0.1, 1, 10, 100], lbs: [1, 10, 100, 1000] };
  var EMPTY_COLOR = '#8a94a3';
  var HIGHLIGHT_COLOR = '#d35400';
  var COUNTY_COLOR = '#1f2d3d';
  var DISTRICT_COLOR = '#6a3d9a';
  var MIN_RADIUS = 3;
  var MAX_RADIUS = 26;

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
    // Layer-bound listeners wait for their layer, so they're bound once here
    // rather than on every style load.
    this.map.on('click', 'facilities', function (evt) { self.openPopup(evt.features[0], evt.lngLat); });
    this.map.on('mouseenter', 'facilities', function () { self.map.getCanvas().style.cursor = 'pointer'; });
    this.map.on('mouseleave', 'facilities', function () { self.map.getCanvas().style.cursor = ''; });
    // For debugging from the console: document.querySelector('.facility-map').facilityMap
    this.el.facilityMap = this;
  }

  // On top of the whole basemap, labels included, as on the pesticides map:
  // the map exists to show the facilities, and a place name over a circle
  // competes with it. The outlines load straight from their URLs.
  FacilityMap.prototype.addLayers = function () {
    this.shell.ensureSource('counties', { data: this.data.countiesUrl || M.EMPTY });
    this.shell.ensureSource('districts', { data: this.data.districtsUrl || M.EMPTY });
    this.shell.ensureSource('facilities');
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
    this.applyHighlight();
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

  FacilityMap.prototype.url = function () {
    var query = this.data.query || '';
    return this.data.geojsonUrl + (query ? '?' + query : '');
  };

  FacilityMap.prototype.load = function () {
    var self = this;
    var ticket = this.shell.ticket();
    this.el.dataset.loaded = '';
    this.shell.setStatus('Loading facilities…');
    fetch(this.url(), { credentials: 'same-origin' })
      .then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      })
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
    this.shell.setStatus('');
    if (!this.fitted) {
      this.fit(prepared.collection);
      this.fitted = true;
    }
    this.el.dataset.loaded = '1';
  };

  // Frame the facilities, unless the page framed the map itself (a facility
  // page's centre, or the covered counties' bounds).
  FacilityMap.prototype.fit = function (collection) {
    if (M.parseCenter(this.data.center) || M.parseBounds(this.data.bounds)) return;
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
    var self = this;
    var p = feature.properties;
    var value = p._empty ? 'none reported' : amount(p.value) + ' ' + escapeHtml(this.data.unit) + '/yr';
    var html = '<div class="facility-popup">' +
      '<p class="facility-popup-name"><a href="' + escapeHtml(this.facilityUrl(p.id)) + '">' + escapeHtml(p.name) + '</a></p>' +
      '<p>' + escapeHtml(p.sector) + '</p>' +
      '<p>' + escapeHtml(this.data.label) + ': <strong>' + value + '</strong>' + (p.rank ? ' · #' + p.rank : '') + '</p>' +
      '</div>';
    if (this.popup) this.popup.remove();
    this.popup = new maptilersdk.Popup({ maxWidth: this.shell.popupMaxWidth() }).setLngLat(lngLat).setHTML(html).addTo(this.map);
    // Clear of the toolbar and legend card, as on the pesticides map.
    this.shell.panPopupIntoView(this.popup);
    this.popup.on('close', function () { self.popup = null; });
  };

  // The legend card stays hidden until there's something to put in it.
  FacilityMap.prototype.legend = function (body) {
    var legend = body.querySelector('.facility-map-legend');
    if (!legend || !this.legendData) return;
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

  // The sector filter's items (the core runs the dropdown itself). The
  // legend card is hidden until the first data lands (see legend).
  FacilityMap.prototype.onChrome = function (wrap) {
    var self = this;
    if (this.shell.legendPanelEl && !this.legendData) this.shell.legendPanelEl.hidden = true;
    Array.prototype.forEach.call(wrap.querySelectorAll('[data-sector]'), function (item) {
      if (item.getAttribute('data-bound')) return;
      item.setAttribute('data-bound', '1');
      item.addEventListener('click', function (event) {
        event.preventDefault();
        M.chrome.closeDropdowns(self.shell, null);
        self.setSector(item.getAttribute('data-sector'), item.textContent.trim());
      });
    });
  };

  FacilityMap.prototype.onDropdownOpen = function () {
    if (this.popup) this.popup.remove();
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
    var dropdown = this.shell.wrap && this.shell.wrap.querySelector('.facility-map-sector');
    if (dropdown) {
      dropdown.classList.toggle('is-set', !!sector);
      var text = dropdown.querySelector('.map-toolbar-label');
      if (text) text.textContent = label || 'All sectors';
      Array.prototype.forEach.call(dropdown.querySelectorAll('[data-sector]'), function (item) {
        item.classList.toggle('is-active', item.getAttribute('data-sector') === (sector || ''));
      });
    }
    this.load();
  };

  // A swap brought a new page: drop what belonged to the old one (its
  // popup, the located dot), frame the new page, and reload.
  FacilityMap.prototype.onAdopt = function () {
    if (this.popup) this.popup.remove();
    // The new page's legend card waits for its own data, as on a first build.
    this.legendData = null;
    if (this.shell.legendPanelEl) this.shell.legendPanelEl.hidden = true;
    this.shell.setSourceData('locate', M.EMPTY);
    this.shell.setStatus('');
    this.fitted = false;
    this.shell.frame();
    this.applyHighlight();
    this.load();
  };

  FacilityMap.prototype.destroy = function () {
    if (this.popup) this.popup.remove();
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
