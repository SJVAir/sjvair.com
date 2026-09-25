/*
 * The Dairies tab's map, a module on the map core (assets/js/maps/)
 * registered as 'dairy', and the dairy pieces the facility map borrows for
 * region pages (SJVAirMaps.dairies: the amber ramp and its classes, the popup).
 *
 * Two views, one at a time:
 *   Dairies   one circle per dairy in CARB's dairy database (CADD) with a
 *             counted herd that year: area by EPA animal units (square root,
 *             on a fixed scale so years and counties compare), amber by
 *             fixed animal-unit classes; a green ring when a digester ran.
 *   Counties  the covered counties shaded by a measure: CARB's county dairy
 *             cattle emissions (tons/yr) or the herd (animal units), each
 *             also per square mile.
 *
 * Its own module rather than a view of the facility map: its data, views,
 * legend and URL state are its own, and as a separate registry module a tab
 * switch between the two maps is a clean release and build. Config comes
 * from the container's data-* attributes (dairy_views.dairy_map_config); the
 * chrome is the core's.
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M || !M.register) return;

  // ColorBrewer YlOrBr: one amber per animal-unit class below.
  var RAMP = ['#fee391', '#fec44f', '#fe9929', '#d95f0e', '#993404'];
  // Fixed classes in EPA animal units, set against CADD's 2023 Valley herds
  // (about 170 / 300 / 260 / 230 / 170 counted dairies in each).
  var BREAKS = [500, 1500, 3000, 6000];
  var EMPTY_COLOR = '#8a94a3';
  var COUNTY_COLOR = '#1f2d3d';
  var DIGESTER_COLOR = '#2e7d32';
  var MIN_RADIUS = 3;
  var MAX_RADIUS = 22;
  // Circle areas are scaled to this herd, the same in every year and county,
  // so sizes compare; the few larger herds are drawn at the largest size.
  var SCALE_UNITS = 40000;
  var SIZE_KEY = [20000, 5000, 1000];
  var ZOOM_TO = 12;

  var escapeHtml = M.escapeHtml;
  var logError = M.logger('dairy-map');

  var getJson = M.getJson;
  var quantity = M.format.quantity;
  var classIndex = M.classes.index;

  // A head count or an animal-unit total: whole, with commas; '—' for none.
  function whole(value) {
    if (value === null || value === undefined) return '—';
    return Math.round(value).toLocaleString('en-US');
  }

  // The counties' classes can fall under 0.01 (per square mile): written to
  // two significant digits rather than '<0.01', so neighbouring classes differ.
  function roundLabel(value) {
    return M.format.round(value, true);
  }

  function colorFor(units) {
    return RAMP[classIndex(units || 0, BREAKS)];
  }

  function radiusFor(units) {
    var capped = Math.min(Math.max(units || 0, 0), SCALE_UNITS);
    return MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * Math.sqrt(capped / SCALE_UNITS);
  }

  // Five classes up to `max` on round steps (1, 2, 2.5 or 5 times a power of
  // ten): the counties' values change with the measure, pollutant and year.
  function niceBreaks(max) {
    if (!(max > 0)) return [];
    var step = max / 5;
    var magnitude = Math.pow(10, Math.floor(Math.log10(step)));
    var nice = [1, 2, 2.5, 5, 10].map(function (m) { return m * magnitude; }).filter(function (v) { return v >= step; })[0];
    return [1, 2, 3, 4].map(function (i) { return Number((i * nice).toPrecision(6)); });
  }

  // A legend's classes, largest first.
  function rampBins(breaks, swatchClass) {
    return M.classes.bins(breaks, RAMP, swatchClass, roundLabel);
  }

  function digesterText(digester) {
    var span = digester.shutdown_year
      ? digester.operational_year + '–' + digester.shutdown_year + ', shut down'
      : 'since ' + digester.operational_year;
    return escapeHtml(span) + (digester.source ? ' (' + escapeHtml(digester.source) + ')' : '');
  }

  // A dairy's popup from /api/2.0/emissions/dairies/<id>/: name, address,
  // animal units and the herd by class (CARB's estimates starred), its
  // digesters, and the region pages it counts in (`qs`, the scope, rides along).
  function popupHtml(data, qs) {
    var address = data.address || {};
    var parts = [
      '<div class="facility-popup dairy-popup">',
      '<p class="facility-popup-name">' + escapeHtml(data.name) + '</p>',
      '<p>' + escapeHtml([address.street, address.city].filter(Boolean).join(', ')) + '</p>',
    ];
    var herd = data.herd;
    if (herd) {
      var estimated = false;
      var rows = herd.classes.map(function (row) {
        var starred = row.estimated && row.count !== null;
        if (starred) estimated = true;
        return '<tr><td>' + escapeHtml(row.label) + '</td><td class="has-text-right">' + whole(row.count) + (starred ? '*' : '') + '</td></tr>';
      }).join('');
      parts.push('<p>Animal units (EPA), ' + escapeHtml(data.year) + ': <strong>' + whole(herd.animal_units) + '</strong></p>');
      parts.push('<table class="dairy-popup-herd"><tbody>' + rows + '</tbody></table>');
      if (estimated) parts.push('<p class="is-size-7">* CARB\'s estimate, not a reported count</p>');
    } else {
      parts.push('<p>No herd count for ' + escapeHtml(data.year) + '.</p>');
    }
    if (data.digesters && data.digesters.length) {
      parts.push('<p>Digester' + (data.digesters.length > 1 ? 's' : '') + ': ' + data.digesters.map(digesterText).join('; ') + '</p>');
    }
    if (data.areas && data.areas.length) {
      parts.push('<p>Counted in ' + data.areas.map(function (area) {
        return '<a href="' + escapeHtml(area.url + (qs || '')) + '">' + escapeHtml(area.label) + '</a>';
      }).join(', ') + '</p>');
    }
    parts.push('</div>');
    return parts.join('');
  }

  var LOADING = '<div class="facility-popup dairy-popup"><p>Loading…</p></div>';
  var FAILED = '<div class="facility-popup dairy-popup"><p>Couldn\'t load this dairy.</p></div>';

  // What the facility map borrows for region and near-me pages.
  M.dairies = {
    RAMP: RAMP,
    BREAKS: BREAKS,
    colorFor: colorFor,
    rampBins: function () { return rampBins(BREAKS); },
    popupHtml: popupHtml,
    LOADING: LOADING,
    FAILED: FAILED,
  };

  function DairyMap(shell) {
    var self = this;
    this.shell = shell;
    this.el = shell.el;
    // The container's live dataset (an adopt rewrites this same element's).
    this.data = shell.data;
    this.map = shell.map;
    this.popupRequest = 0;
    this.dairies = null;
    this.counties = null;
    this.shapes = null;
    this.countyBreaks = [];
    this.readState();
    this.map.on('click', 'dairies', function (evt) {
      var feature = evt.features[0];
      self.openPopup(feature.properties.id, feature.geometry.coordinates.slice());
    });
    this.map.on('click', 'counties-fill', function (evt) { self.openCountyPopup(evt.features[0], evt.lngLat); });
    ['dairies', 'counties-fill'].forEach(function (layer) {
      self.map.on('mouseenter', layer, function () { self.map.getCanvas().style.cursor = 'pointer'; });
      self.map.on('mouseleave', layer, function () { self.map.getCanvas().style.cursor = ''; });
    });
    // A dairy's name in the table moves the map to it and opens its popup.
    this.onZoomClick = function (event) {
      var link = event.target && event.target.closest && event.target.closest('.dairy-zoom');
      if (!link) return;
      event.preventDefault();
      self.zoomTo(link.getAttribute('data-dairy'), [parseFloat(link.getAttribute('data-lng')), parseFloat(link.getAttribute('data-lat'))]);
    };
    document.body.addEventListener('click', this.onZoomClick);
    // The page's links (the scope bar, the table's sorts and pages, the
    // filter form) were rendered before the reader switched view or measure
    // here. Rewrite a boosted request back to this page (htmx reads
    // detail.path back after this event) so it opens the way the map is now.
    this.onConfigRequest = function (event) {
      var detail = event.detail;
      if (!detail || typeof detail.path !== 'string') return;
      var path = M.rewriteQuery(detail.path, self.writeState.bind(self), true);
      if (path !== null) detail.path = path;
    };
    document.body.addEventListener('htmx:configRequest', this.onConfigRequest);
    // For debugging from the console: document.querySelector('.dairy-map').dairyMap
    this.el.dairyMap = this;
  }

  DairyMap.prototype.readState = function () {
    this.view = this.data.view === 'counties' ? 'counties' : 'dairies';
    this.measure = this.data.measure || 'emissions';
  };

  // Bottom to top: the shaded counties, their outlines, the dairies. Smaller
  // herds draw on top of larger ones, so none hides under a neighbour.
  DairyMap.prototype.addLayers = function () {
    this.shell.ensureSource('counties');
    this.shell.ensureSource('dairies');
    this.shell.ensureLayer({
      id: 'counties-fill', type: 'fill', source: 'counties',
      paint: { 'fill-color': ['get', '_color'], 'fill-opacity': ['case', ['==', ['get', '_empty'], 1], 0, 0.72] },
    });
    this.shell.ensureLayer({
      id: 'counties-line', type: 'line', source: 'counties',
      paint: { 'line-color': COUNTY_COLOR, 'line-width': 1, 'line-opacity': 0.6 },
    });
    this.shell.ensureLayer({
      id: 'dairies', type: 'circle', source: 'dairies',
      layout: { 'circle-sort-key': ['*', -1, ['get', 'animal_units']] },
      paint: {
        'circle-radius': ['get', '_radius'],
        'circle-color': ['get', '_color'],
        'circle-opacity': 0.85,
        'circle-stroke-color': ['case', ['get', 'digester'], DIGESTER_COLOR, '#ffffff'],
        'circle-stroke-width': ['case', ['get', 'digester'], 2.5, 0.75],
      },
    });
    this.applyView();
    this.applyCounty();
  };

  // One view at a time: the layers, the switch and the Counties-only measure follow `this.view`.
  DairyMap.prototype.applyView = function () {
    var counties = this.view === 'counties';
    if (this.map) {
      var set = function (map, id, visible) {
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none');
      };
      set(this.map, 'dairies', !counties);
      set(this.map, 'counties-fill', counties);
    }
    Array.prototype.forEach.call(this.shell.controls('[data-view]'), function (button) {
      var on = button.getAttribute('data-view') === (counties ? 'counties' : 'dairies');
      button.classList.toggle('is-selected', on);
      button.classList.toggle('is-link', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    Array.prototype.forEach.call(this.shell.controls('[data-counties-only]'), function (control) {
      control.hidden = !counties;
    });
  };

  // The scope's county: only its dairies, and its outline drawn heavier.
  DairyMap.prototype.applyCounty = function () {
    if (!this.map || !this.map.getLayer('dairies')) return;
    var county = this.data.county || '';
    this.map.setFilter('dairies', county ? ['==', ['get', 'county'], county] : null);
    this.map.setPaintProperty('counties-line', 'line-width', county ? ['case', ['==', ['get', 'slug'], county], 3, 1] : 1);
  };

  DairyMap.prototype.load = function () {
    var self = this;
    var ticket = this.shell.ticket();
    this.el.dataset.loaded = '';
    this.shell.setStatus('Loading dairies…');
    var shapes = this.shapes ? Promise.resolve(this.shapes) : getJson(this.data.shapesUrl);
    Promise.all([getJson(this.data.geojsonUrl), shapes, getJson(this.data.countiesUrl)])
      .then(function (results) {
        // A newer load (a swap) or a destroy superseded this one.
        if (!self.shell.isCurrent(ticket)) return;
        self.shapes = results[1];
        self.counties = results[2];
        self.showDairies(results[0]);
        self.showCounties();
        self.frame();
        self.shell.setStatus('');
        self.el.dataset.loaded = '1';
      })
      .catch(function (err) {
        if (!self.shell.isCurrent(ticket)) return;
        self.shell.setStatus('Couldn\'t load the dairies');
        logError('failed to load the dairies', err);
      });
  };

  DairyMap.prototype.showDairies = function (collection) {
    (collection.features || []).forEach(function (feature) {
      var p = feature.properties;
      p._radius = radiusFor(p.animal_units);
      p._color = colorFor(p.animal_units);
    });
    this.dairies = collection;
    this.shell.setSourceData('dairies', collection);
    this.shell.updateLegend();
  };

  // Joins the county values to the shapes and colours them by the measure (a
  // measure change re-runs this without fetching).
  DairyMap.prototype.showCounties = function () {
    if (!this.shapes || !this.counties) return;
    var rows = this.counties.counties || [];
    var byId = {};
    rows.forEach(function (row) { byId[row.id] = row; });
    var field = this.measure;
    var values = rows.map(function (row) { return row[field]; }).filter(function (value) { return value > 0; });
    var breaks = niceBreaks(values.length ? Math.max.apply(null, values) : 0);
    var features = (this.shapes.features || []).map(function (feature) {
      var row = byId[feature.id] || {};
      var value = row[field];
      var shaded = breaks.length > 0 && value !== null && value !== undefined && value > 0;
      return {
        type: 'Feature',
        id: feature.id,
        geometry: feature.geometry,
        properties: Object.assign({}, feature.properties, {
          emissions: row.emissions,
          emissions_per_sq_mi: row.emissions_per_sq_mi,
          animal_units: row.animal_units,
          animal_units_per_sq_mi: row.animal_units_per_sq_mi,
          _color: shaded ? RAMP[classIndex(value, breaks)] : EMPTY_COLOR,
          _empty: shaded ? 0 : 1,
        }),
      };
    });
    this.countyBreaks = breaks;
    this.shell.setSourceData('counties', { type: 'FeatureCollection', features: features });
    this.shell.updateLegend();
  };

  DairyMap.prototype.countyBounds = function () {
    var county = this.data.county;
    if (!county || !this.shapes) return null;
    return M.counties.bounds(this.shapes).bySlug[county] || null;
  };

  // A county in scope frames the map on it; otherwise the page's bounds do.
  DairyMap.prototype.frame = function () {
    var bounds = this.countyBounds();
    if (bounds) this.map.fitBounds(bounds, { padding: 24, duration: 0 });
  };

  DairyMap.prototype.home = function () {
    var bounds = this.countyBounds();
    return bounds ? { bounds: bounds, padding: 24 } : null;
  };

  DairyMap.prototype.regionQuery = function () {
    return this.data.query ? '?' + this.data.query : '';
  };

  // Fetched on click: the herd by class, digesters and "Counted in".
  DairyMap.prototype.openPopup = function (id, lngLat) {
    var self = this;
    var request = ++this.popupRequest;
    var popup = this.shell.placePopup(LOADING, lngLat);
    getJson((this.data.popupUrl || '').replace('{id}', encodeURIComponent(id)))
      .then(function (data) {
        if (request !== self.popupRequest || self.shell.popup !== popup) return;
        popup.setHTML(popupHtml(data, self.regionQuery()));
        self.shell.panPopupIntoView(popup);
      })
      .catch(function (err) {
        if (request !== self.popupRequest || self.shell.popup !== popup) return;
        popup.setHTML(FAILED);
        logError('failed to load a dairy', err);
      });
  };

  DairyMap.prototype.openCountyPopup = function (feature, lngLat) {
    var p = feature.properties;
    var unit = escapeHtml(this.data.unit);
    var url = (this.data.regionUrl || '').replace('{id}', encodeURIComponent(p.id)) + this.regionQuery();
    var line = function (label, value) { return '<p>' + label + ': <strong>' + value + '</strong></p>'; };
    this.shell.placePopup('<div class="facility-popup dairy-popup">' +
      '<p class="facility-popup-name"><a href="' + escapeHtml(url) + '">' + escapeHtml(p.name) + '</a></p>' +
      line('Dairy emissions, ' + escapeHtml(this.data.label), quantity(p.emissions) + ' ' + unit + '/yr') +
      line('Per square mile', quantity(p.emissions_per_sq_mi) + ' ' + unit + '/yr') +
      line('Animal units (EPA)', whole(p.animal_units)) +
      line('Per square mile', quantity(p.animal_units_per_sq_mi)) +
      '<p class="is-size-7">' + escapeHtml(this.data.sourceNote) + '</p></div>', lngLat);
  };

  DairyMap.prototype.zoomTo = function (id, lngLat) {
    if (!this.map || !isFinite(lngLat[0]) || !isFinite(lngLat[1])) return;
    if (this.view !== 'dairies') this.setView('dairies');
    if (!this.shell.expanded && this.shell.wrap) {
      this.shell.wrap.scrollIntoView({ behavior: this.shell.reducedMotion ? 'auto' : 'smooth', block: 'center' });
    }
    this.map.jumpTo({ center: lngLat, zoom: Math.max(this.map.getZoom(), ZOOM_TO) });
    this.openPopup(id, lngLat);
  };

  DairyMap.prototype.measureTitle = function () {
    var label = this.data.label;
    var unit = this.data.unit;
    return {
      emissions: 'Dairy emissions, ' + label + ' (' + unit + '/yr)',
      emissions_per_sq_mi: 'Dairy emissions, ' + label + ' (' + unit + '/yr per sq mi)',
      animal_units: 'Animal units (EPA)',
      animal_units_per_sq_mi: 'Animal units (EPA) per sq mi',
    }[this.measure] || '';
  };

  DairyMap.prototype.dairyLegend = function () {
    var sizes = SIZE_KEY.map(function (units) {
      var r = radiusFor(units);
      return '<span class="legend-size"><svg width="' + (2 * MAX_RADIUS + 2) + '" height="' + (2 * r + 2) + '">' +
        '<circle class="is-dairy" cx="' + (MAX_RADIUS + 1) + '" cy="' + (r + 1) + '" r="' + r + '"/></svg>' +
        units.toLocaleString('en-US') + '</span>';
    }).join('');
    return '<p class="legend-title">Animal units (EPA)</p>' +
      '<div class="legend-sizes">' + sizes + '</div>' + rampBins(BREAKS) +
      '<p class="legend-empty"><span class="legend-ring is-digester"></span>Digester operating in ' + escapeHtml(this.data.year) + '</p>' +
      '<p class="legend-note">(Milk + dry cows) × 1.4 + other cattle × 1.0</p>';
  };

  DairyMap.prototype.countyLegend = function () {
    var title = '<p class="legend-title">' + escapeHtml(this.measureTitle()) + '</p>';
    var note = this.measure.indexOf('emissions') === 0
      ? '<p class="legend-note">' + escapeHtml(this.data.sourceNote) + '</p>'
      : '<p class="legend-note">CARB\'s dairy database (CADD), ' + escapeHtml(this.data.year) + '</p>';
    if (!this.countyBreaks.length) return title + '<p>No county figures for ' + escapeHtml(this.data.year) + '.</p>' + note;
    return title + rampBins(this.countyBreaks, 'is-area') + note;
  };

  // The legend card follows the view; it stays hidden until there's data.
  DairyMap.prototype.legend = function (body) {
    var legend = body.querySelector('.dairy-map-legend');
    if (!legend) return;
    if (this.view === 'counties' ? !this.counties : !this.dairies) return;
    if (this.shell.legendPanelEl) this.shell.legendPanelEl.hidden = false;
    legend.innerHTML = this.view === 'counties' ? this.countyLegend() : this.dairyLegend();
  };

  DairyMap.prototype.onChrome = function () {
    var self = this;
    if (this.shell.legendPanelEl && !this.dairies) this.shell.legendPanelEl.hidden = true;
    this.shell.bindControls('[data-view]', function (item) { self.setView(item.getAttribute('data-view')); });
    this.shell.bindControls('[data-measure]', function (item) { self.setMeasure(item.getAttribute('data-measure'), item.textContent.trim()); });
    this.applyView();
  };

  DairyMap.prototype.onDropdownOpen = function () {
    this.shell.closePopup();
  };

  // The map's state on `params` (a URLSearchParams), defaults left out: view
  // `dairies`, and measure `emissions` (written only in Counties).
  DairyMap.prototype.writeState = function (params) {
    var counties = this.view === 'counties';
    if (counties) params.set('view', 'counties'); else params.delete('view');
    if (counties && this.measure !== 'emissions') params.set('measure', this.measure); else params.delete('measure');
  };

  DairyMap.prototype.syncUrl = function () {
    M.syncUrl(this.writeState.bind(this));
  };

  DairyMap.prototype.setView = function (view) {
    this.view = view === 'counties' ? 'counties' : 'dairies';
    this.shell.closePopup();
    this.applyView();
    this.syncUrl();
    this.shell.updateLegend();
  };

  DairyMap.prototype.setMeasure = function (measure, label) {
    this.measure = measure;
    var dropdown = this.shell.wrap && this.shell.wrap.querySelector('.dairy-map-measure');
    if (dropdown) {
      var text = dropdown.querySelector('.map-toolbar-label');
      if (text && label) text.textContent = label;
      Array.prototype.forEach.call(dropdown.querySelectorAll('[data-measure]'), function (item) {
        item.classList.toggle('is-active', item.getAttribute('data-measure') === measure);
      });
    }
    this.syncUrl();
    this.showCounties();
  };

  // A swap brought a new page. Only the table changed (a sort, a page, a
  // filter): keep the map as it is and refill the new page's legend card. A
  // new year, pollutant or county: drop the old data, frame, and reload.
  DairyMap.prototype.onAdopt = function (changed) {
    var reloads = ['geojsonUrl', 'countiesUrl', 'county', 'year', 'label', 'unit'];
    var reload = changed.some(function (key) { return reloads.indexOf(key) !== -1; });
    this.readState();
    this.applyView();
    if (!reload) {
      if (changed.indexOf('measure') !== -1) this.showCounties();
      this.shell.updateLegend();
      // The new container came without data-loaded (adopt drops what it
      // lacks); the map is still drawn, so say so again.
      if (this.dairies) this.el.dataset.loaded = '1';
      return;
    }
    this.shell.closePopup();
    this.dairies = null;
    this.counties = null;
    if (this.shell.legendPanelEl) this.shell.legendPanelEl.hidden = true;
    this.shell.setSourceData('locate', M.EMPTY);
    this.shell.setSourceData('dairies', M.EMPTY);
    this.applyCounty();
    if (!this.data.county) this.shell.frame();
    this.load();
  };

  DairyMap.prototype.destroy = function () {
    this.shell.closePopup();
    document.body.removeEventListener('htmx:configRequest', this.onConfigRequest);
    document.body.removeEventListener('click', this.onZoomClick);
    this.map = null;
  };

  M.register('dairy', {
    selector: '.dairy-map',
    lifecycle: 'adopt',
    features: { controls: ['zoom', 'locate', 'home'], toolbar: true, legend: true, status: true, expand: true },
    create: function (shell) { return new DairyMap(shell); },
  });

  window.EmissionsDairyMap = {
    instances: function () { return M.instances('dairy'); },
  };
})();
