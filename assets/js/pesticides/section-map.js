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

  var METRIC_LABELS = {
    lbs_chemical: 'Pounds applied',
    applications: 'Applications',
  };

  // Fetch a bbox padded by half a viewport on each side, then skip the next
  // fetch while the viewport is still inside what we already have. Without
  // this, opening a popup near the edge auto-pans the map, which refetched and
  // rebuilt the layers out from under the popup.
  var BBOX_PAD = 0.5;

  // Shared popup options: wide enough for the table, padded enough that
  // auto-pan doesn't tuck the popup against the map edge.
  var POPUP_OPTIONS = {
    maxWidth: 320,
    autoPanPadding: [24, 24],
    closeButton: true,
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

  // Popups are laid out as a two-column table (label / value) so a notice and
  // a section read the same way. `valueHtml` is already-escaped markup.
  function popupRow(label, valueHtml) {
    if (valueHtml === '' || valueHtml === null || valueHtml === undefined) return '';
    return '<tr><th scope="row">' + escapeHtml(label) + '</th><td>' + valueHtml + '</td></tr>';
  }

  function popupTable(rows) {
    var body = rows.join('');
    if (!body) return '';
    return '<table class="table is-narrow section-popup-table"><tbody>' + body + '</tbody></table>';
  }

  function popupList(items) {
    if (!items.length) return '';
    return '<ul class="section-popup-list">' + items.join('') + '</ul>';
  }

  function linkHtml(url, text, extraClass) {
    if (!url) return escapeHtml(text);
    return '<a' + (extraClass ? ' class="' + extraClass + '"' : '') +
      ' href="' + escapeHtml(url) + '">' + escapeHtml(text) + '</a>';
  }

  // Leaflet's bindPopup opens the popup wherever the cell was clicked; a
  // grid cell reads better with the popup rising from its centre.
  function openPopupAtCenter(layer) {
    if (layer._openPopup) layer.off('click', layer._openPopup, layer);
    if (layer._centerPopupBound) return;
    layer._centerPopupBound = true;
    layer.on('click', function () {
      layer.openPopup(layer.getBounds().getCenter());
    });
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
    // What the last successful fetch covers, so a pan inside it doesn't
    // refetch (and so doesn't rebuild a layer under an open popup).
    this.loadedBounds = null;
    this.loadedLevel = null;
    this.loadedNoticeBounds = null;
    // Feature ids of the popups that are open, so a rebuild can put them back.
    this.openGridId = null;
    this.openNoticeId = null;

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

    // The page's own region (a city, ZIP, or place) sits between the
    // county lines and the notices.
    var outlinePane = this.map.createPane('pesticide-outline');
    outlinePane.style.zIndex = 430;

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
    this.loadOutline();
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

  // Draws the region this page is about (from the regions API) and fits the
  // map to it, so a city or ZIP page opens on the whole area, shaded.
  SectionMap.prototype.loadOutline = function () {
    if (!this.data.outlineUrl) return;
    var self = this;
    fetch(this.data.outlineUrl)
      .then(function (response) {
        if (!response.ok) throw new Error('bad response');
        return response.json();
      })
      .then(function (payload) {
        var region = payload && payload.data;
        var geometry = region && region.boundary && region.boundary.geometry;
        if (!geometry) return;
        self.outlineLayer = L.geoJSON(geometry, {
          pane: 'pesticide-outline',
          interactive: false,
          style: { color: '#d35400', weight: 2.5, opacity: 0.9, fillColor: '#d35400', fillOpacity: 0.08 },
        }).addTo(self.map);
        self.map.fitBounds(self.outlineLayer.getBounds(), { padding: [24, 24], animate: !self.reducedMotion });
      })
      .catch(function (err) {
        window.console && console.error && console.error('section-map: failed to load the region outline', err);
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

  SectionMap.prototype.productUrl = function (id) {
    return fillUrl(this.data.productPageUrl, id);
  };

  SectionMap.prototype.noticeUrl = function (id) {
    return fillUrl(this.data.noticePageUrl, id);
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
    var level = this.map.getZoom() >= SECTION_ZOOM ? 'section' : 'township';
    // Crossing the section/township threshold always refetches; otherwise the
    // padded bbox we already hold may still cover the viewport.
    if (level === this.loadedLevel && this.covers(this.loadedBounds)) return;
    if (level === 'section') {
      this.loadSections();
    } else {
      this.loadTownships();
    }
  };

  // True when `bounds` (from a previous padded fetch) still contains the
  // current viewport.
  SectionMap.prototype.covers = function (bounds) {
    return !!bounds && bounds.contains(this.map.getBounds());
  };

  SectionMap.prototype.clearGrid = function () {
    if (this.gridLayer) {
      this.map.removeLayer(this.gridLayer);
      this.gridLayer = null;
    }
  };

  SectionMap.prototype.fetchBounds = function (unpadded) {
    var bounds = this.map.getBounds();
    return unpadded ? bounds : bounds.pad(BBOX_PAD);
  };

  function bboxParam(bounds) {
    return [
      bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth(),
    ].join(',');
  }

  // One AbortController covers both grid levels: a pending section request is
  // stale the moment we decide to draw townships, and vice versa.
  SectionMap.prototype.startGridRequest = function () {
    if (this.gridAbort) this.gridAbort.abort();
    var abort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    this.gridAbort = abort;
    return abort;
  };

  SectionMap.prototype.loadSections = function (unpadded) {
    if (!this.data.sectionsUrl) return;

    var abort = this.startGridRequest();
    var bounds = this.fetchBounds(unpadded);
    var params = this.commonParams();
    params.bbox = bboxParam(bounds);
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
          // The endpoint caps how many sections it will return, and the padded
          // bbox asks for more than the viewport needs. Try the bare viewport
          // once, then fall back to the township grid rather than leaving the
          // map bare.
          if (result.response.status === 400) {
            if (!unpadded) {
              self.loadSections(true);
            } else {
              self.loadTownships();
            }
            return;
          }
          self.clearGrid();
          self.loadedBounds = null;
          self.loadedLevel = null;
          if (self.legendEl) self.legendEl.innerHTML = '';
          self.setStatus('Couldn\'t load sections; try again');
          return;
        }
        self.setStatus('');
        self.loadedBounds = bounds;
        self.loadedLevel = 'section';
        self.renderGrid(result.body, 'section');
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (self.gridAbort !== abort) return;
        window.console && console.error && console.error('section-map: failed to load sections', err);
        self.loadedBounds = null;
        self.loadedLevel = null;
        self.setStatus('Couldn\'t load sections; try again');
      });
  };

  SectionMap.prototype.loadTownships = function () {
    if (!this.data.townshipsUrl) return;

    var abort = this.startGridRequest();
    var bounds = this.fetchBounds();
    var params = this.commonParams();
    params.bbox = bboxParam(bounds);
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
        self.loadedBounds = bounds;
        self.loadedLevel = 'township';
        self.renderGrid(geojson, 'township');
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (self.gridAbort !== abort) return;
        window.console && console.error && console.error('section-map: failed to load townships', err);
        self.clearGrid();
        self.loadedBounds = null;
        self.loadedLevel = null;
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

  // Remembers which feature's popup is open so a rebuilt layer can re-open it.
  // Removing a layer closes its popup, so the id has to be captured before the
  // old layer goes away (see renderGrid/renderNotices).
  SectionMap.prototype.trackPopup = function (layer, id, key) {
    var self = this;
    layer.on('popupopen', function () { self[key] = id; });
    layer.on('popupclose', function () {
      if (self[key] === id) self[key] = null;
    });
  };

  SectionMap.prototype.renderGrid = function (geojson, level) {
    var self = this;
    var reopenId = this.openGridId;
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
        self.trackPopup(layer, feature.properties.id, 'openGridId');
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
    this.reopenGridPopup(reopenId);
  };

  // A refetch rebuilds the grid; if the popup that was open belongs to a
  // feature that's still there, put it back rather than making the reader
  // click again.
  SectionMap.prototype.reopenGridPopup = function (id) {
    if (!id || !this.gridLayer) return;
    var self = this;
    this.gridLayer.eachLayer(function (layer) {
      if (!layer.feature || layer.feature.properties.id !== id) return;
      if (self.level === 'township') {
        layer.openPopup(layer.getBounds().getCenter());
      } else {
        self.showSectionPopup(layer.feature, layer);
      }
    });
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
      popupTable([
        popupRow('Sections', formatNumber(sections)),
        popupRow(METRIC_LABELS[this.metric] || 'Total', formatNumber(props[this.metric]) + ' ' + escapeHtml(unit)),
      ]) +
      '<p><button type="button" class="section-map-zoom" data-lat="' + center.lat + '" data-lng="' + center.lng + '">Zoom in</button></p>' +
      '</div>'
    );
  };

  SectionMap.prototype.popupOptions = function (className) {
    return Object.assign({ className: className }, POPUP_OPTIONS);
  };

  SectionMap.prototype.bindTownshipPopup = function (feature, layer) {
    layer.bindPopup(
      this.townshipPopupHtml(feature.properties, layer.getBounds().getCenter()),
      this.popupOptions('section-popup-wrap'),
    );
    openPopupAtCenter(layer);
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
      '<h4>Section</h4>' +
      popupTable([
        popupRow('MTRS', escapeHtml(props.mtrs)),
        popupRow('County', escapeHtml(props.county || '')),
        popupRow(METRIC_LABELS[this.metric] || 'Total', formatNumber(totalValue) + ' ' + escapeHtml(unit)),
        popupRow('Top chemicals', detailHtml),
      ]) +
      '<p class="section-popup-links">' + linkHtml(this.sectionUrl(props.id), 'This section') + '</p>' +
      '</div>'
    );
  };

  SectionMap.prototype.showSectionPopup = function (feature, layer) {
    var props = feature.properties;
    var html = this.sectionPopupHtml(props, 'Loading…');
    layer.bindPopup(html, this.popupOptions('section-popup-wrap'));
    openPopupAtCenter(layer);
    layer.openPopup(layer.getBounds().getCenter());

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
          detailHtml = popupList(chemicals.slice(0, 3).map(function (c) {
            return '<li class="' + (c.is_of_concern ? 'is-of-concern' : '') + '">' +
              linkHtml(self.chemicalUrl(c.id), c.name) +
              ' — ' + formatNumber(c.lbs) + ' lbs</li>';
          }));
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
    // Same padded-fetch/skip deal as the grid: don't rebuild the markers (and
    // drop an open popup) for a pan we already have data for.
    if (this.covers(this.loadedNoticeBounds)) return;

    if (this.noticesAbort) this.noticesAbort.abort();
    var abort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    this.noticesAbort = abort;

    var bounds = this.fetchBounds();

    var params = {
      bbox: bboxParam(bounds),
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
        self.loadedNoticeBounds = bounds;
        self.renderNotices(geojson);
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (self.noticesAbort !== abort) return;
        // Zoomed way out the bbox can cover more notices than the endpoint
        // will return (it 400s past its cap); drop the markers and move on.
        window.console && console.error && console.error('section-map: failed to load notices', err);
        self.loadedNoticeBounds = null;
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
    var reopenId = this.openNoticeId;
    this.clearNotices();
    var features = ((geojson && geojson.features) || []).filter(function (f) { return f.geometry; });
    this.noticesLayer = L.geoJSON({ type: 'FeatureCollection', features: features }, {
      pointToLayer: function (feature, latlng) {
        return L.circleMarker(latlng, {
          pane: 'pesticide-notices',
          radius: 8,
          fillColor: NOTICE_COLOR,
          fillOpacity: 0.9,
          color: '#fff',
          weight: 1.5,
        });
      },
      onEachFeature: function (feature, layer) {
        self.trackPopup(layer, feature.properties.id, 'openNoticeId');
        layer.bindPopup(self.noticePopupHtml(feature.properties), self.popupOptions('notice-popup-wrap'));
      },
    }).addTo(this.map);

    if (reopenId) {
      this.noticesLayer.eachLayer(function (layer) {
        if (layer.feature && layer.feature.properties.id === reopenId) layer.openPopup();
      });
    }
  };

  SectionMap.prototype.noticePopupHtml = function (props) {
    var self = this;
    var chemicals = popupList((props.chemicals || []).map(function (c) {
      return '<li class="' + (c.is_of_concern ? 'is-of-concern' : '') + '">' +
        linkHtml(self.chemicalUrl(c.id), c.name) + '</li>';
    }));
    var products = popupList((props.products || []).map(function (p) {
      return '<li>' + linkHtml(self.productUrl(p.id), p.name) + '</li>';
    }));
    var section = props.section
      ? linkHtml(props.section_id ? this.sectionUrl(props.section_id) : '', props.section)
      : '';
    var noticeUrl = props.id ? this.noticeUrl(props.id) : '';

    return (
      '<div class="notice-popup">' +
      '<h4>Notice of intent <span class="tag is-warning is-light">Active</span></h4>' +
      popupTable([
        popupRow('Scheduled', escapeHtml(formatDateTime(props.scheduled_application))),
        popupRow('May begin through', escapeHtml(formatDate(props.scheduled_end))),
        popupRow('County', escapeHtml(props.county || '')),
        popupRow('Section', section),
        popupRow('Method', escapeHtml(props.application_method || '')),
        popupRow('Treated', props.treated_amount
          ? formatNumber(props.treated_amount) + ' ' + escapeHtml(props.treated_units || '')
          : ''),
        popupRow('Products', products),
        popupRow('Chemicals', chemicals),
      ]) +
      '<p class="notice-popup-links">' +
      (noticeUrl ? linkHtml(noticeUrl, 'Full notice') + ' · ' : '') +
      '<a class="spraydays-link" href="' + SPRAYDAYS_URL + '" target="_blank" rel="noopener">Sign up with SprayDays</a>' +
      '</p>' +
      '</div>'
    );
  };

  // Collect the `.section-map` containers at or under `root`. `root` may be a
  // document or an element (htmx hands us the element it just swapped in, and
  // that element can itself be a container).
  function containersUnder(root) {
    var found = [];
    if (root.matches && root.matches('.section-map')) found.push(root);
    var nested = root.querySelectorAll ? root.querySelectorAll('.section-map') : [];
    for (var i = 0; i < nested.length; i++) found.push(nested[i]);
    return found;
  }

  // Idempotent: containers already initialised carry `data-rendered`, so this
  // is safe to call repeatedly (page load plus every htmx swap).
  function init(root) {
    if (typeof L === 'undefined') return;
    var containers = containersUnder(root || document);
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

  window.PesticidesSectionMap = { init: init };

  function initDocument() {
    init(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDocument);
  } else {
    initDocument();
  }
})();
