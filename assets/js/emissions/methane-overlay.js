/*
 * The "Methane sources (Carbon Mapper)" overlay, shared by facility-map.js
 * and dairy-map.js: one circle per Carbon Mapper CH4 source from
 * data-methane-url (/tools/emissions/methane/geojson/, our pages only),
 * sized by the square root of its rate and coloured by sector group; a
 * legend checkbox row toggles it and ?methane= carries it. The source
 * carries a MapLibre attribution, so the map's attribution control shows
 * "Data by Carbon Mapper®" whenever the layer is on; the popup repeats it
 * with the non-commercial terms. Nothing here is ours: every rate is
 * labelled a Carbon Mapper estimate.
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M) return;

  var COLORS = { livestock: '#7c3aed', 'oil-gas': '#0f766e', waste: '#b45309', other: '#6b7280' };
  var GROUPS = [['livestock', 'Livestock'], ['oil-gas', 'Oil & gas'], ['waste', 'Waste & wastewater'], ['other', 'Other']];
  var TERMS_URL = 'https://carbonmapper.org/terms';

  var escapeHtml = M.escapeHtml;
  var getJson = M.getJson;
  var logError = M.logger('methane-overlay');

  function Overlay(host, opts) {
    this.host = host;
    this.before = (opts || {}).before || null;
    this.collection = null;
    this.request = 0;
    this.read();
    var self = this;
    host.map.on('click', 'methane', function (evt) { self.openPopup(evt.features[0], evt.lngLat); });
    host.map.on('mouseenter', 'methane', function () { host.map.getCanvas().style.cursor = 'pointer'; });
    host.map.on('mouseleave', 'methane', function () { host.map.getCanvas().style.cursor = ''; });
  }

  Overlay.prototype.read = function () {
    var d = this.host.data;
    this.enabled = !!d.methaneUrl;
    this.default = d.methaneDefault === '1';
    this.on = this.enabled && d.methane === '1';
  };

  // Under the host's own points (`before`), so a dairy or facility circle on
  // top of a plume stays clickable. The attribution is the licence's.
  Overlay.prototype.addLayers = function () {
    var d = this.host.data;
    this.host.shell.ensureSource('methane', {
      attribution: '<a href="' + escapeHtml(d.methaneHome || 'https://carbonmapper.org') + '">' + escapeHtml(d.methaneAttribution || 'Data by Carbon Mapper®') + '</a>',
    });
    if (!this.host.map.getLayer('methane')) {
      this.host.map.addLayer({
        id: 'methane', type: 'circle', source: 'methane',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['sqrt', ['coalesce', ['get', 'rate'], 0]], 0, 4, 5, 6, 15, 10, 30, 16, 60, 22],
          'circle-color': ['match', ['get', 'group'], 'livestock', COLORS.livestock, 'oil-gas', COLORS['oil-gas'], 'waste', COLORS.waste, COLORS.other],
          'circle-opacity': 0.55,
          'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1,
        },
      }, this.before && this.host.map.getLayer(this.before) ? this.before : undefined);
    }
    this.apply();
  };

  Overlay.prototype.apply = function () {
    var map = this.host.map;
    if (map && map.getLayer('methane')) map.setLayoutProperty('methane', 'visibility', this.enabled && this.on ? 'visible' : 'none');
  };

  // Fetched once per page (the whole Valley, cached an hour server-side), only when on.
  Overlay.prototype.load = function () {
    var self = this;
    if (!this.enabled || !this.on) return;
    if (this.collection) { this.host.shell.setSourceData('methane', this.collection); this.host.el.dataset.methaneLoaded = '1'; return; }
    var request = ++this.request;
    this.host.el.dataset.methaneLoaded = '';
    getJson(this.host.data.methaneUrl)
      .then(function (collection) {
        if (request !== self.request || !self.host.map) return;
        self.collection = collection;
        self.host.shell.setSourceData('methane', collection);
        self.host.shell.updateLegend();
        self.host.el.dataset.methaneLoaded = '1';
      })
      .catch(function (err) { if (request === self.request && self.host.map) logError('failed to load the methane sources', err); });
  };

  Overlay.prototype.set = function (on) {
    if (!this.enabled) return;
    this.on = !!on;
    this.apply();
    this.host.syncUrl();
    this.host.shell.updateLegend();
    this.load();
  };

  Overlay.prototype.legendHtml = function () {
    if (!this.enabled) return '';
    var html = '<div class="legend-overlay"><label class="legend-toggle"><input type="checkbox" data-methane' + (this.on ? ' checked' : '') + '> Methane sources (Carbon Mapper)</label>';
    if (this.on) {
      html += '<p class="legend-wells">' + GROUPS.map(function (g) {
        return '<span class="legend-well"><span class="legend-swatch is-well is-methane" style="background: ' + COLORS[g[0]] + '"></span>' + g[1] + '</span>';
      }).join('') + '</p><p class="legend-note">Circle area by Carbon Mapper\'s estimated rate (kg/h). Snapshots from overflights, not annual totals. <a href="' + escapeHtml(this.host.data.methaneHome || 'https://carbonmapper.org') + '">' + escapeHtml(this.host.data.methaneAttribution || 'Data by Carbon Mapper®') + '</a>, non-commercial use.</p>';
    }
    return html + '</div>';
  };

  Overlay.prototype.openPopup = function (feature, lngLat) {
    var p = feature.properties;
    // Nested objects arrive as JSON strings in MapLibre feature properties.
    var link = p.facility ? JSON.parse(p.facility) : null;
    var dairy = p.dairy ? JSON.parse(p.dairy) : null;
    var hasRate = p.rate !== null && p.rate !== undefined && p.rate !== '';
    var html = '<div class="facility-popup methane-popup">' +
      '<p class="facility-popup-name">' + escapeHtml(p.sector) + ' methane source</p>' +
      '<p>' + escapeHtml(p.rate_text) + (hasRate ? ' <span class="has-text-grey">(Carbon Mapper estimate)</span>' : '') + '</p>' +
      '<p>' + p.det + ' detection' + (p.det === 1 ? '' : 's') + ' of ' + p.obs + ' pass' + (p.obs === 1 ? '' : 'es') + (p.persistence !== null && p.persistence !== undefined ? ' · persistence ' + Number(p.persistence).toFixed(2) : '') + '</p>' +
      (dairy ? '<p>Nearest dairy: ' + escapeHtml(dairy.name) + '</p>' : '') +
      (link ? '<p>Nearest facility: <a href="' + escapeHtml(link.url) + '">' + escapeHtml(link.name) + '</a></p>' : '') +
      '<p><a href="' + escapeHtml(p.viewer_url) + '">View at Carbon Mapper →</a></p>' +
      '<p class="is-size-7 has-text-grey"><a href="' + escapeHtml(this.host.data.methaneHome || 'https://carbonmapper.org') + '">' + escapeHtml(this.host.data.methaneAttribution || 'Data by Carbon Mapper®') + '</a>, for <a href="' + TERMS_URL + '">non-commercial use</a>.</p></div>';
    this.host.shell.placePopup(html, lngLat);
  };

  Overlay.prototype.writeState = function (params) {
    if (this.enabled && this.on !== this.default) params.set('methane', this.on ? '1' : '0'); else params.delete('methane');
  };

  // The legend re-renders with the map, so the checkbox handler is delegated to the legend body, bound once.
  Overlay.prototype.bind = function (legendBody) {
    var self = this;
    if (!legendBody || legendBody.getAttribute('data-methane-bound')) return;
    legendBody.setAttribute('data-methane-bound', '1');
    legendBody.addEventListener('change', function (event) {
      if (event.target && event.target.hasAttribute('data-methane')) self.set(event.target.checked);
    });
  };

  Overlay.prototype.onAdopt = function () { this.read(); this.apply(); this.load(); };
  Overlay.prototype.destroy = function () { this.collection = null; };

  window.EmissionsMethaneOverlay = Overlay;
})();
