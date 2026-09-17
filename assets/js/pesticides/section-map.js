/*
 * Interactive pesticide section map for the Pesticides Explorer.
 *
 * Turns each `.section-map` container into a live Leaflet map: square-mile
 * (MTRS) sections shaded by a metric (pounds or application count), plus
 * SprayDays notice-of-intent markers. Config comes entirely from the
 * container's `data-*` attributes (see `pesticides/includes/section-map.html`
 * and `views.section_map_config`), so this script has no server-rendered
 * state baked in beyond that.
 *
 * Plain ES2017, no framework/bundler, single global side effect: none (IIFE).
 */
(function () {
  'use strict';

  // At this zoom and closer the map draws square-mile (MTRS) sections; further
  // out it draws the 6x6 mile township grid instead, so there's always a grid.
  var SECTION_ZOOM = 11;
  var DEBOUNCE_MS = 300;
  var RAMP = ['#deebf7', '#9ecae1', '#6baed6', '#3182bd', '#08519c'];
  var NO_DATA_COLOR = '#f0f0f0';
  var NUM_CLASSES = RAMP.length;
  var NOTICE_COLOR = '#d35400';
  var SPRAYDAYS_URL = 'https://spraydays.cdpr.ca.gov/';

  var METRIC_UNITS = {
    lbs_chemical: 'lbs',
    applications: 'applications',
  };

  var LEVEL_TEXT = {
    section: 'Each square is one square-mile section.',
    township: 'Each square is a 6 × 6 mile township; zoom in for square-mile sections.',
  };

  var COUNTY_COLOR = '#1f2d3d';

  function prefersReducedMotion() {
    try {
      return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (err) {
      return false;
    }
  }

  function milesToMeters(miles) {
    return miles * 1609.34;
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

  function formatNumber(value) {
    try {
      return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
    } catch (err) {
      return String(value);
    }
  }

  function formatDateTime(iso) {
    if (!iso) return '';
    var date = new Date(iso);
    if (isNaN(date.getTime())) return iso;
    try {
      return date.toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      });
    } catch (err) {
      return date.toLocaleString();
    }
  }

  function formatDate(iso) {
    if (!iso) return '';
    var date = new Date(iso);
    if (isNaN(date.getTime())) return iso;
    try {
      return date.toLocaleDateString(undefined, { dateStyle: 'medium' });
    } catch (err) {
      return date.toLocaleDateString();
    }
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
    var colors;
    if (count === 1) {
      colors = [RAMP[RAMP.length - 1]];
    } else {
      colors = [];
      for (var c = 0; c < count; c++) {
        colors.push(RAMP[Math.round((c * (RAMP.length - 1)) / (count - 1))]);
      }
    }
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

  function buildQuery(params) {
    var pairs = [];
    Object.keys(params).forEach(function (key) {
      var value = params[key];
      if (value === '' || value === null || value === undefined) return;
      pairs.push(encodeURIComponent(key) + '=' + encodeURIComponent(value));
    });
    return pairs.join('&');
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

  function SectionMap(el) {
    this.el = el;
    this.data = el.dataset;
    this.reducedMotion = prefersReducedMotion();
    this.metric = 'lbs_chemical';
    // Only one grid is ever on the map at a time; `level` says which one.
    this.level = 'section';
    this.gridLayer = null;
    this.countiesLayer = null;
    this.noticesLayer = null;
    this.currentClasses = { breaks: [], colors: [], members: [] };
    this.gridAbort = null;
    this.noticesAbort = null;

    this.controlsEl = null;
    this.legendEl = null;
    this.levelEl = null;
    this.statusEl = null;

    this.init();
  }

  SectionMap.prototype.init = function () {
    var wrap = this.el.closest('.section-map-wrap') || this.el.parentNode;
    this.controlsEl = wrap.querySelector('.section-map-controls');
    this.legendEl = wrap.querySelector('.section-map-legend');
    this.levelEl = wrap.querySelector('.section-map-level');
    if (this.controlsEl) this.statusEl = this.controlsEl.querySelector('.section-map-status');

    var center = this.parseCenter(this.data.center) || [36.75, -119.80];
    var zoom = parseInt(this.data.zoom, 10) || 8;

    this.map = L.map(this.el, { zoomControl: true, scrollWheelZoom: false });

    // Wheel-zoom is off by default so the map doesn't hijack page scrolling
    // on long pages; enable it only while the map has focus/is being
    // interacted with directly.
    this.el.addEventListener('click', this.enableScrollZoom.bind(this));
    this.el.addEventListener('focus', this.enableScrollZoom.bind(this), true);
    this.el.addEventListener('mouseleave', this.disableScrollZoom.bind(this));
    this.el.addEventListener('blur', this.disableScrollZoom.bind(this), true);

    var tileUrl = this.data.tiles;
    if (tileUrl) {
      L.tileLayer(tileUrl, {
        attribution: this.data.attribution || '',
        maxZoom: 21,
      }).addTo(this.map);
    }

    this.map.setView(center, zoom, { animate: !this.reducedMotion });

    // County outlines sit above the grid fills (overlayPane, 400) but below
    // the notice markers (450) so nothing hides a notice.
    var countiesPane = this.map.createPane('pesticide-counties');
    countiesPane.style.zIndex = 420;

    var noticesPane = this.map.createPane('pesticide-notices');
    noticesPane.style.zIndex = 450;

    if (this.data.radius) {
      var radiusMiles = parseFloat(this.data.radius);
      if (radiusMiles > 0) {
        var circle = L.circle(center, { radius: milesToMeters(radiusMiles) }).addTo(this.map);
        this.map.fitBounds(circle.getBounds(), { animate: !this.reducedMotion });
      }
    }

    if (this.controlsEl) this.controlsEl.hidden = false;
    if (this.legendEl) this.legendEl.hidden = false;
    if (this.levelEl) this.levelEl.hidden = false;

    if (this.controlsEl) {
      var radios = this.controlsEl.querySelectorAll('input[name="metric"]');
      for (var i = 0; i < radios.length; i++) {
        radios[i].addEventListener('change', this.onMetricChange.bind(this));
      }
    }

    var debouncedLoad = debounce(this.loadGrid.bind(this), DEBOUNCE_MS);
    var debouncedNotices = debounce(this.loadNotices.bind(this), DEBOUNCE_MS);
    this.map.on('moveend zoomend', debouncedLoad);
    this.map.on('moveend zoomend', debouncedNotices);
    this.map.on('zoomend', this.restyleCounties.bind(this));
    this.bindZoomButtons();

    this.loadCounties();
    this.loadGrid();
    this.loadNotices();
  };

  SectionMap.prototype.countyStyle = function () {
    return {
      color: COUNTY_COLOR,
      weight: 1.5,
      fill: false,
      opacity: 0.8,
      // Dashed once the section grid is on, so the two don't compete.
      dashArray: this.map.getZoom() >= SECTION_ZOOM ? '4 3' : null,
    };
  };

  // County outlines never change with the filters, so they're fetched once.
  SectionMap.prototype.loadCounties = function () {
    if (!this.data.countiesUrl) return;
    var self = this;
    fetch(this.data.countiesUrl)
      .then(function (response) {
        if (!response.ok) throw new Error('bad response');
        return response.json();
      })
      .then(function (geojson) {
        self.countiesLayer = L.geoJSON(geojson, {
          pane: 'pesticide-counties',
          interactive: false,
          style: self.countyStyle(),
        }).addTo(self.map);
      })
      .catch(function (err) {
        window.console && console.error && console.error('section-map: failed to load counties', err);
      });
  };

  SectionMap.prototype.restyleCounties = function () {
    if (this.countiesLayer) this.countiesLayer.setStyle(this.countyStyle());
  };

  SectionMap.prototype.enableScrollZoom = function () {
    this.map.scrollWheelZoom.enable();
  };

  SectionMap.prototype.disableScrollZoom = function () {
    this.map.scrollWheelZoom.disable();
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

  SectionMap.prototype.chemicalUrl = function (id) {
    return fillUrl(this.data.chemicalPageUrl, id);
  };

  SectionMap.prototype.sectionUrl = function (id) {
    return fillUrl(this.data.sectionPageUrl, id);
  };

  SectionMap.prototype.setStatus = function (message) {
    if (this.statusEl) this.statusEl.textContent = message || '';
  };

  SectionMap.prototype.onMetricChange = function (event) {
    this.metric = event.target.value;
    this.restyle();
  };

  SectionMap.prototype.commonParams = function () {
    return {
      year: this.data.year,
      chemical: this.data.chemical,
      product: this.data.product,
      commodity: this.data.commodity,
      county: this.data.county,
    };
  };

  // Picks the grid for the current zoom: sections up close, townships further
  // out. Either way exactly one grid layer is on the map.
  SectionMap.prototype.loadGrid = function () {
    if (this.map.getZoom() >= SECTION_ZOOM) {
      this.loadSections();
    } else {
      this.loadTownships();
    }
  };

  SectionMap.prototype.clearGrid = function () {
    if (this.gridLayer) {
      this.map.removeLayer(this.gridLayer);
      this.gridLayer = null;
    }
  };

  SectionMap.prototype.viewportBbox = function () {
    var bounds = this.map.getBounds();
    return [
      bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth(),
    ].join(',');
  };

  // One AbortController covers both grid levels: a pending section request is
  // stale the moment we decide to draw townships, and vice versa.
  SectionMap.prototype.startGridRequest = function () {
    if (this.gridAbort) this.gridAbort.abort();
    var abort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    this.gridAbort = abort;
    return abort;
  };

  SectionMap.prototype.loadSections = function () {
    if (!this.data.sectionsUrl) return;

    var abort = this.startGridRequest();
    var params = this.commonParams();
    params.bbox = this.viewportBbox();
    var query = buildQuery(params);
    var url = this.data.sectionsUrl + (query ? '?' + query : '');

    this.setStatus('Loading sections…');

    var self = this;
    fetch(url, abort ? { signal: abort.signal } : undefined)
      .then(function (response) {
        return response.json().then(function (body) {
          return { response: response, body: body };
        });
      })
      .then(function (result) {
        if (self.gridAbort !== abort) return; // stale response
        if (!result.response.ok) {
          // The endpoint caps how many sections it will return, and a very
          // wide viewport at this zoom can still trip that cap. Fall back to
          // the township grid rather than leaving the map bare.
          if (result.response.status === 400) {
            self.loadTownships();
            return;
          }
          self.clearGrid();
          if (self.legendEl) self.legendEl.innerHTML = '';
          self.setStatus('Couldn\'t load sections; try again');
          return;
        }
        self.setStatus('');
        self.renderGrid(result.body, 'section');
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (self.gridAbort !== abort) return;
        window.console && console.error && console.error('section-map: failed to load sections', err);
        self.setStatus('Couldn\'t load sections; try again');
      });
  };

  SectionMap.prototype.loadTownships = function () {
    if (!this.data.townshipsUrl) return;

    var abort = this.startGridRequest();
    var params = this.commonParams();
    params.bbox = this.viewportBbox();
    var query = buildQuery(params);
    var url = this.data.townshipsUrl + (query ? '?' + query : '');

    this.setStatus('Loading grid…');

    var self = this;
    fetch(url, abort ? { signal: abort.signal } : undefined)
      .then(function (response) {
        if (!response.ok) throw new Error('bad response');
        return response.json();
      })
      .then(function (geojson) {
        if (self.gridAbort !== abort) return; // stale response
        self.setStatus('');
        self.renderGrid(geojson, 'township');
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (self.gridAbort !== abort) return;
        window.console && console.error && console.error('section-map: failed to load townships', err);
        self.clearGrid();
        if (self.legendEl) self.legendEl.innerHTML = '';
        self.setStatus('Couldn\'t load the grid; try again');
      });
  };

  SectionMap.prototype.isHighlighted = function (feature) {
    return this.level === 'section' && !!this.data.highlight && feature.id === this.data.highlight;
  };

  SectionMap.prototype.featureStyle = function (feature) {
    var value = feature.properties[this.metric];
    var style = {
      fillColor: colorFor(this.currentClasses, value),
      fillOpacity: value ? 0.7 : 0.25,
      color: this.level === 'township' ? '#7a869a' : '#555',
      weight: this.level === 'township' ? 1 : 0.5,
    };
    if (this.isHighlighted(feature)) {
      style.color = '#d35400';
      style.weight = 3;
    }
    return style;
  };

  SectionMap.prototype.legendUnit = function () {
    var unit = METRIC_UNITS[this.metric] || '';
    return this.level === 'township' ? unit + ' per township' : unit;
  };

  SectionMap.prototype.updateLegend = function () {
    if (this.legendEl) renderLegend(this.legendEl, this.currentClasses, this.legendUnit());
    if (this.levelEl) this.levelEl.textContent = LEVEL_TEXT[this.level] || '';
  };

  SectionMap.prototype.bringHighlightToFront = function () {
    if (!this.data.highlight || !this.gridLayer) return;
    var self = this;
    this.gridLayer.eachLayer(function (layer) {
      if (layer.feature && self.isHighlighted(layer.feature) && layer.bringToFront) {
        layer.bringToFront();
      }
    });
  };

  SectionMap.prototype.renderGrid = function (geojson, level) {
    var self = this;
    this.level = level;
    var features = (geojson && geojson.features) || [];
    var values = [];
    features.forEach(function (feature) {
      var value = feature.properties[self.metric];
      if (value) values.push(value);
    });
    this.currentClasses = quantileClasses(values);

    this.clearGrid();

    this.gridLayer = L.geoJSON(geojson, {
      style: function (feature) {
        return self.featureStyle(feature);
      },
      onEachFeature: function (feature, layer) {
        if (level === 'township') {
          self.bindTownshipPopup(feature, layer);
          return;
        }
        layer.on('click', function () {
          self.showSectionPopup(feature, layer);
        });
      },
    }).addTo(this.map);

    this.bringHighlightToFront();
    this.updateLegend();
  };

  SectionMap.prototype.restyle = function () {
    if (!this.gridLayer) return;
    var self = this;
    var values = [];
    this.gridLayer.eachLayer(function (layer) {
      var value = layer.feature.properties[self.metric];
      if (value) values.push(value);
    });
    this.currentClasses = quantileClasses(values);
    this.gridLayer.eachLayer(function (layer) {
      layer.setStyle(self.featureStyle(layer.feature));
      if (self.level === 'township' && layer.getPopup()) {
        layer.setPopupContent(self.townshipPopupHtml(layer.feature.properties, layer.getBounds().getCenter()));
      }
    });
    this.bringHighlightToFront();
    this.updateLegend();
  };

  SectionMap.prototype.townshipPopupHtml = function (props, center) {
    var unit = METRIC_UNITS[this.metric] || '';
    var sections = props.sections || 0;
    // The target is carried on the button so a delegated listener (see init)
    // can serve it; per-popup listeners would be lost when restyle() swaps
    // the popup content.
    return (
      '<div class="section-popup">' +
      '<h4>' + escapeHtml(props.name || props.id) + '</h4>' +
      '<p>' + formatNumber(sections) + (sections === 1 ? ' section' : ' sections') + '</p>' +
      '<p class="section-popup-totals">' + formatNumber(props[this.metric]) + ' ' + escapeHtml(unit) + '</p>' +
      '<p><button type="button" class="section-map-zoom" data-lat="' + center.lat + '" data-lng="' + center.lng + '">Zoom in</button></p>' +
      '</div>'
    );
  };

  SectionMap.prototype.bindTownshipPopup = function (feature, layer) {
    layer.bindPopup(this.townshipPopupHtml(feature.properties, layer.getBounds().getCenter()), { className: 'section-popup-wrap' });
  };

  // The "Zoom in" handler is delegated on each popup's outer element, which
  // survives restyle() replacing the popup's inner content (Leaflet stops
  // click propagation at that element, so it can't live any higher up).
  SectionMap.prototype.bindZoomButtons = function () {
    var self = this;
    this.map.on('popupopen', function (event) {
      var container = event.popup.getElement();
      if (!container || container.getAttribute('data-zoom-bound')) return;
      container.setAttribute('data-zoom-bound', '1');
      container.addEventListener('click', function (click) {
        var button = click.target.closest ? click.target.closest('.section-map-zoom') : null;
        if (!button) return;
        var lat = parseFloat(button.getAttribute('data-lat'));
        var lng = parseFloat(button.getAttribute('data-lng'));
        if (!isFinite(lat) || !isFinite(lng)) return;
        self.map.closePopup();
        self.map.setView([lat, lng], SECTION_ZOOM, { animate: !self.reducedMotion });
      });
    });
  };

  SectionMap.prototype.sectionPopupHtml = function (props, detailHtml) {
    var unit = METRIC_UNITS[this.metric] || '';
    var totalValue = props[this.metric];
    return (
      '<div class="section-popup">' +
      '<h4>MTRS ' + escapeHtml(props.mtrs) + '</h4>' +
      '<p>' + escapeHtml(props.county || '') + '</p>' +
      '<p class="section-popup-totals">' + formatNumber(totalValue) + ' ' + escapeHtml(unit) + '</p>' +
      '<div class="section-popup-detail">' + detailHtml + '</div>' +
      '<p><a href="' + this.sectionUrl(props.id) + '">This section</a></p>' +
      '</div>'
    );
  };

  SectionMap.prototype.showSectionPopup = function (feature, layer) {
    var props = feature.properties;
    var html = this.sectionPopupHtml(props, 'Loading…');
    layer.bindPopup(html, { className: 'section-popup-wrap' }).openPopup();

    if (!this.data.sectionUrlPattern) return;
    var year = this.data.year;
    var url = this.data.sectionUrlPattern.replace('{id}', props.id) + '?year=' + encodeURIComponent(year || '');

    var self = this;
    fetch(url)
      .then(function (response) { return response.json(); })
      .then(function (detail) {
        if (!layer.getPopup() || !layer.isPopupOpen()) return; // popup was closed before this resolved
        var chemicals = (detail && detail.top_chemicals) || [];
        var detailHtml = '';
        if (chemicals.length) {
          var items = chemicals.slice(0, 3).map(function (c) {
            var concernClass = c.is_of_concern ? ' is-of-concern' : '';
            return '<li class="' + concernClass.trim() + '"><a href="' + self.chemicalUrl(c.id) + '">' +
              escapeHtml(c.name) + '</a> — ' + formatNumber(c.lbs) + ' lbs</li>';
          }).join('');
          detailHtml = '<ul>' + items + '</ul>';
        }
        layer.getPopup().setContent(self.sectionPopupHtml(props, detailHtml));
      })
      .catch(function (err) {
        window.console && console.error && console.error('section-map: failed to load section detail', err);
        if (!layer.getPopup() || !layer.isPopupOpen()) return;
        layer.getPopup().setContent(self.sectionPopupHtml(props, ''));
      });
  };

  SectionMap.prototype.loadNotices = function () {
    if (!this.data.noticesUrl) return;

    if (this.noticesAbort) this.noticesAbort.abort();
    var abort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    this.noticesAbort = abort;

    var bounds = this.map.getBounds();
    var bbox = [
      bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth(),
    ].join(',');

    var params = {
      bbox: bbox,
      chemical: this.data.chemical,
      product: this.data.product,
      county: this.data.county,
    };
    var query = buildQuery(params);
    var url = this.data.noticesUrl + (query ? '?' + query : '');

    var self = this;
    fetch(url, abort ? { signal: abort.signal } : undefined)
      .then(function (response) {
        if (!response.ok) throw new Error('bad response');
        return response.json();
      })
      .then(function (geojson) {
        if (self.noticesAbort !== abort) return; // stale response
        self.renderNotices(geojson);
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (self.noticesAbort !== abort) return;
        // Zoomed way out the bbox can cover more notices than the endpoint
        // will return (it 400s past its cap); drop the markers and move on.
        window.console && console.error && console.error('section-map: failed to load notices', err);
        self.clearNotices();
      });
  };

  SectionMap.prototype.clearNotices = function () {
    if (this.noticesLayer) {
      this.map.removeLayer(this.noticesLayer);
      this.noticesLayer = null;
    }
  };

  SectionMap.prototype.renderNotices = function (geojson) {
    var self = this;
    this.clearNotices();
    var features = ((geojson && geojson.features) || []).filter(function (f) { return f.geometry; });
    this.noticesLayer = L.geoJSON({ type: 'FeatureCollection', features: features }, {
      pointToLayer: function (feature, latlng) {
        return L.circleMarker(latlng, {
          pane: 'pesticide-notices',
          radius: 7,
          fillColor: NOTICE_COLOR,
          fillOpacity: 0.9,
          color: '#fff',
          weight: 1.5,
        });
      },
      onEachFeature: function (feature, layer) {
        layer.bindPopup(self.noticePopupHtml(feature.properties), { className: 'notice-popup-wrap' });
      },
    }).addTo(this.map);
  };

  SectionMap.prototype.noticePopupHtml = function (props) {
    var self = this;
    var chemicals = (props.chemicals || []).map(function (c) {
      var concernClass = c.is_of_concern ? ' is-of-concern' : '';
      return '<li class="' + concernClass.trim() + '"><a href="' + self.chemicalUrl(c.id) + '">' + escapeHtml(c.name) + '</a></li>';
    }).join('');
    var products = (props.products || []).map(function (p) {
      return '<li>' + escapeHtml(p.name) + '</li>';
    }).join('');

    return (
      '<div class="notice-popup">' +
      '<h4>Notice of intent</h4>' +
      '<p class="notice-popup-meta">' + escapeHtml(formatDateTime(props.scheduled_application)) +
      ', may begin through ' + escapeHtml(formatDate(props.scheduled_end)) + '</p>' +
      '<p class="notice-popup-meta">' + escapeHtml(props.county || '') + '</p>' +
      (props.application_method ? '<p class="notice-popup-meta">' + escapeHtml(props.application_method) + '</p>' : '') +
      (props.treated_amount ? '<p class="notice-popup-meta">' + formatNumber(props.treated_amount) + ' ' + escapeHtml(props.treated_units || '') + '</p>' : '') +
      (products ? '<p>Products</p><ul>' + products + '</ul>' : '') +
      (chemicals ? '<p>Chemicals</p><ul>' + chemicals + '</ul>' : '') +
      '<a class="spraydays-link" href="' + SPRAYDAYS_URL + '" target="_blank" rel="noopener">Sign up with SprayDays</a>' +
      '</div>'
    );
  };

  function init() {
    if (typeof L === 'undefined') return;
    var containers = document.querySelectorAll('.section-map');
    for (var i = 0; i < containers.length; i++) {
      var el = containers[i];
      if (el.dataset.rendered) continue;
      el.dataset.rendered = '1';
      try {
        new SectionMap(el);
      } catch (err) {
        window.console && console.error && console.error('section-map: failed to initialize', err);
      }
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
