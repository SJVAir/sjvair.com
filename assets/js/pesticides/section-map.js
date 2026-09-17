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

  var MIN_SECTION_ZOOM = 9;
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

  function chemicalUrl(id) {
    // /chemicals/<sqid>/ 301s to the slugged detail URL, so the slug isn't needed here.
    return '/tools/pesticides/chemicals/' + encodeURIComponent(id) + '/';
  }

  function sectionUrl(id) {
    // Sub-project 3 (per-section pages) hasn't landed yet; this 404s until it does.
    return '/tools/pesticides/sections/' + encodeURIComponent(id) + '/';
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
    this.sectionsLayer = null;
    this.noticesLayer = null;
    this.currentClasses = { breaks: [], colors: [], members: [] };
    this.sectionsAbort = null;
    this.noticesAbort = null;

    this.controlsEl = null;
    this.legendEl = null;
    this.statusEl = null;

    this.init();
  }

  SectionMap.prototype.init = function () {
    var wrap = this.el.closest('.section-map-wrap') || this.el.parentNode;
    this.controlsEl = wrap.querySelector('.section-map-controls');
    this.legendEl = wrap.querySelector('.section-map-legend');
    if (this.controlsEl) this.statusEl = this.controlsEl.querySelector('.section-map-status');

    var center = this.parseCenter(this.data.center) || [36.75, -119.80];
    var zoom = parseInt(this.data.zoom, 10) || 8;

    this.map = L.map(this.el, { zoomControl: true, scrollWheelZoom: true });

    var tileUrl = this.data.tiles;
    if (tileUrl) {
      L.tileLayer(tileUrl, {
        attribution: this.data.attribution || '',
        maxZoom: 21,
      }).addTo(this.map);
    }

    this.map.setView(center, zoom, { animate: !this.reducedMotion });

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

    if (this.controlsEl) {
      var radios = this.controlsEl.querySelectorAll('input[name="metric"]');
      for (var i = 0; i < radios.length; i++) {
        radios[i].addEventListener('change', this.onMetricChange.bind(this));
      }
    }

    var debouncedLoad = debounce(this.loadSections.bind(this), DEBOUNCE_MS);
    var debouncedNotices = debounce(this.loadNotices.bind(this), DEBOUNCE_MS);
    this.map.on('moveend zoomend', debouncedLoad);
    this.map.on('moveend zoomend', debouncedNotices);

    this.loadSections();
    this.loadNotices();
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

  SectionMap.prototype.loadSections = function () {
    if (!this.data.sectionsUrl) return;
    var zoom = this.map.getZoom();
    if (zoom < MIN_SECTION_ZOOM) {
      if (this.sectionsLayer) {
        this.map.removeLayer(this.sectionsLayer);
        this.sectionsLayer = null;
      }
      this.setStatus('Zoom in to see square-mile sections');
      return;
    }

    if (this.sectionsAbort) this.sectionsAbort.abort();
    var abort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    this.sectionsAbort = abort;

    var bounds = this.map.getBounds();
    var bbox = [
      bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth(),
    ].join(',');

    var params = this.commonParams();
    params.bbox = bbox;
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
        if (self.sectionsAbort !== abort) return; // stale response
        if (!result.response.ok) {
          if (self.sectionsLayer) {
            self.map.removeLayer(self.sectionsLayer);
            self.sectionsLayer = null;
          }
          if (self.legendEl) self.legendEl.innerHTML = '';
          if (result.response.status === 400) {
            self.setStatus('Zoom in to see square-mile sections');
          } else {
            self.setStatus('Couldn\'t load sections; try again');
          }
          return;
        }
        self.setStatus('');
        self.renderSections(result.body);
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (self.sectionsAbort !== abort) return;
        window.console && console.error && console.error('section-map: failed to load sections', err);
        self.setStatus('Couldn\'t load sections; try again');
      });
  };

  SectionMap.prototype.renderSections = function (geojson) {
    var self = this;
    var features = (geojson && geojson.features) || [];
    var values = [];
    features.forEach(function (feature) {
      var value = feature.properties[self.metric];
      if (value) values.push(value);
    });
    this.currentClasses = quantileClasses(values);

    if (this.sectionsLayer) {
      this.map.removeLayer(this.sectionsLayer);
      this.sectionsLayer = null;
    }

    this.sectionsLayer = L.geoJSON(geojson, {
      style: function (feature) {
        var value = feature.properties[self.metric];
        var style = {
          fillColor: colorFor(self.currentClasses, value),
          fillOpacity: value ? 0.7 : 0.25,
          color: '#555',
          weight: 0.5,
        };
        if (self.data.highlight && feature.id === self.data.highlight) {
          style.color = '#d35400';
          style.weight = 3;
        }
        return style;
      },
      onEachFeature: function (feature, layer) {
        layer.on('click', function () {
          self.showSectionPopup(feature, layer);
        });
      },
    }).addTo(this.map);

    if (this.data.highlight) {
      this.sectionsLayer.eachLayer(function (layer) {
        if (layer.feature && layer.feature.id === self.data.highlight && layer.bringToFront) {
          layer.bringToFront();
        }
      });
    }

    if (this.legendEl) {
      renderLegend(this.legendEl, this.currentClasses, METRIC_UNITS[this.metric] || '');
    }
  };

  SectionMap.prototype.restyle = function () {
    if (!this.sectionsLayer) return;
    var self = this;
    var values = [];
    this.sectionsLayer.eachLayer(function (layer) {
      var value = layer.feature.properties[self.metric];
      if (value) values.push(value);
    });
    this.currentClasses = quantileClasses(values);
    this.sectionsLayer.eachLayer(function (layer) {
      var value = layer.feature.properties[self.metric];
      var style = {
        fillColor: colorFor(self.currentClasses, value),
        fillOpacity: value ? 0.7 : 0.25,
        color: '#555',
        weight: 0.5,
      };
      if (self.data.highlight && layer.feature.id === self.data.highlight) {
        style.color = '#d35400';
        style.weight = 3;
      }
      layer.setStyle(style);
    });
    if (this.data.highlight) {
      this.sectionsLayer.eachLayer(function (layer) {
        if (layer.feature && layer.feature.id === self.data.highlight && layer.bringToFront) {
          layer.bringToFront();
        }
      });
    }
    if (this.legendEl) {
      renderLegend(this.legendEl, this.currentClasses, METRIC_UNITS[this.metric] || '');
    }
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
      '<p><a href="' + sectionUrl(props.id) + '">This section</a></p>' +
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
            return '<li class="' + concernClass.trim() + '"><a href="' + chemicalUrl(c.id) + '">' +
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
        window.console && console.error && console.error('section-map: failed to load notices', err);
      });
  };

  SectionMap.prototype.renderNotices = function (geojson) {
    var self = this;
    if (this.noticesLayer) {
      this.map.removeLayer(this.noticesLayer);
      this.noticesLayer = null;
    }
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
    var chemicals = (props.chemicals || []).map(function (c) {
      var concernClass = c.is_of_concern ? ' is-of-concern' : '';
      return '<li class="' + concernClass.trim() + '"><a href="' + chemicalUrl(c.id) + '">' + escapeHtml(c.name) + '</a></li>';
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
