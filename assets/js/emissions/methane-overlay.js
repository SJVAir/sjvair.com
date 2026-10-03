/*
 * The "Methane sources (Carbon Mapper)" overlay, shared by facility-map.js
 * and dairy-map.js: each Carbon Mapper CH4 source from data-methane-url
 * (/api/2.0/emissions/methane/geojson/) drawn as its newest plume image, all
 * of them painted onto one canvas that spans the view (a single MapLibre
 * canvas source, redrawn after each pan or zoom, rather than hundreds of
 * image layers). A plume is a few hundred metres across, so zoomed out each
 * is drawn at least PLUME_MIN_PX wide, centred on its box, and at its true
 * footprint once that's bigger. An invisible circle per source takes the
 * clicks; a source with no stored image is a small dot. A legend checkbox
 * row toggles it and ?methane= carries it. The source carries a MapLibre
 * attribution, so the map's attribution control shows "Data by Carbon
 * Mapper®" whenever the layer is on; the popup repeats it with the
 * non-commercial terms. Nothing here is ours: every rate is labelled a
 * Carbon Mapper estimate.
 *
 * Opening a source's popup also fetches its plumes (data-methane-plumes-url,
 * /api/2.0/emissions/methane/sources/<id>/plumes/) and drapes the newest
 * one's image on the map as a MapLibre image source + raster layer, below
 * the source circles; small "< date >" controls in the popup step through
 * the source's other plumes. The image layer is removed when the popup
 * closes or the overlay is turned off.
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M) return;

  var COLORS = { livestock: '#7c3aed', 'oil-gas': '#0f766e', waste: '#b45309', other: '#6b7280' };
  var PLUME_SOURCE = 'methane-plume-image';
  var PLUME_LAYER = 'methane-plume-image';
  var PLUMES_SOURCE = 'methane-plumes';
  var PLUMES_LAYER = 'methane-plumes';
  var PLUME_MIN_PX = 18;

  var escapeHtml = M.escapeHtml;
  var getJson = M.getJson;
  var logError = M.logger('methane-overlay');

  function Overlay(host, opts) {
    this.host = host;
    this.before = (opts || {}).before || null;
    this.collection = null;
    this.request = 0;
    this.plumes = null;
    this.plumeIndex = 0;
    this.plumeRequest = 0;
    this.activePopup = null;
    this.activeSource = null;
    this.canvas = document.createElement('canvas');
    this.images = {};
    this.read();
    var self = this;
    host.map.on('moveend', function () { self.redraw(); });
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

  // The click targets go under the host's own points (`before`), so a dairy
  // or facility circle over a source still takes its own clicks; the plume
  // images go on top. Carbon Mapper is credited on the About, data providers
  // and integrations pages, not on the map.
  Overlay.prototype.addLayers = function () {
    var d = this.host.data;
    this.host.shell.ensureSource('methane');
    var map = this.host.map;
    var before = this.before && map.getLayer(this.before) ? this.before : undefined;
    // The plume images go on top of the map's own points: they're the point
    // of turning the overlay on, mostly transparent, and a raster layer
    // doesn't take clicks, so a dairy or facility under one stays clickable.
    if (!map.getSource(PLUMES_SOURCE)) {
      map.addSource(PLUMES_SOURCE, { type: 'canvas', canvas: this.canvas, coordinates: this.viewCorners(), animate: false });
    }
    if (!map.getLayer(PLUMES_LAYER)) {
      map.addLayer({ id: PLUMES_LAYER, type: 'raster', source: PLUMES_SOURCE, paint: { 'raster-opacity': 0.9, 'raster-fade-duration': 0 } });
    }
    // The click target: invisible over a plume image, a small dot for a
    // source with no stored image (so it isn't lost).
    if (!map.getLayer('methane')) {
      map.addLayer({
        id: 'methane', type: 'circle', source: 'methane',
        paint: {
          'circle-radius': ['case', ['to-boolean', ['get', 'plume']], 11, 4],
          'circle-color': ['match', ['get', 'group'], 'livestock', COLORS.livestock, 'oil-gas', COLORS['oil-gas'], 'waste', COLORS.waste, COLORS.other],
          'circle-opacity': ['case', ['to-boolean', ['get', 'plume']], 0, 0.8],
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': ['case', ['to-boolean', ['get', 'plume']], 0, 1],
        },
      }, before);
    }
    this.apply();
    this.redraw();
  };

  Overlay.prototype.apply = function () {
    var map = this.host.map;
    var visibility = this.enabled && this.on ? 'visible' : 'none';
    if (map && map.getLayer('methane')) map.setLayoutProperty('methane', 'visibility', visibility);
    if (map && map.getLayer(PLUMES_LAYER)) map.setLayoutProperty(PLUMES_LAYER, 'visibility', visibility);
    if (!this.enabled || !this.on) this.removePlumeLayer();
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
        self.redraw();
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

  // The view's corners, top-left first, as a canvas source wants them. The
  // maps are flat and north-up, so the view is a lng/lat rectangle.
  Overlay.prototype.viewCorners = function () {
    var b = this.host.map.getBounds();
    return [[b.getWest(), b.getNorth()], [b.getEast(), b.getNorth()], [b.getEast(), b.getSouth()], [b.getWest(), b.getSouth()]];
  };

  // A plume's image once it has loaded, else null and its download queued.
  // At the Valley's zoom every source is in view: started all at once, the
  // ~700 downloads can exhaust the browser (ERR_INSUFFICIENT_RESOURCES), so
  // at most IMAGE_LOADS run at a time and the rest wait their turn.
  var IMAGE_LOADS = 8;

  Overlay.prototype.image = function (url) {
    var img = this.images[url];
    if (!img) {
      img = this.images[url] = new Image();
      img.crossOrigin = 'anonymous'; // drawn to a canvas WebGL reads back
      this.queue = this.queue || [];
      this.queue.push([img, url]);
      this.pump();
    }
    return img.complete && img.naturalWidth && !img.failed ? img : null;
  };

  Overlay.prototype.pump = function () {
    var self = this;
    this.loading = this.loading || 0;
    while (this.loading < IMAGE_LOADS && this.queue && this.queue.length) {
      var next = this.queue.shift();
      var img = next[0];
      this.loading += 1;
      img.onload = function () { self.loading -= 1; self.scheduleRedraw(); self.pump(); };
      img.onerror = (function (failed) {
        return function () { failed.failed = true; self.loading -= 1; self.pump(); };
      })(img);
      img.src = next[1];
    }
  };

  // Images arrive one by one; draw them in a batch on the next frame.
  Overlay.prototype.scheduleRedraw = function () {
    var self = this;
    if (this.redrawQueued) return;
    this.redrawQueued = true;
    window.requestAnimationFrame(function () { self.redrawQueued = false; self.redraw(); });
  };

  // Paints every plume in view onto the canvas, then points the canvas
  // source at the view. A static canvas source only re-reads its pixels
  // while playing, so it plays for the one frame that picks them up.
  Overlay.prototype.redraw = function () {
    var map = this.host.map;
    var source = map && map.getSource(PLUMES_SOURCE);
    if (!source || !this.collection || !this.enabled || !this.on) return;
    var view = map.getCanvas();
    var ratio = window.devicePixelRatio || 1;
    var width = view.clientWidth, height = view.clientHeight;
    this.canvas.width = Math.max(1, Math.round(width * ratio));
    this.canvas.height = Math.max(1, Math.round(height * ratio));
    var ctx = this.canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    var bounds = map.getBounds();
    var self = this;
    this.collection.features.forEach(function (feature) {
      var plume = feature.properties.plume;
      if (!plume || !plume.bbox || feature.id === self.activeSource) return;
      var west = plume.bbox[0], south = plume.bbox[1], east = plume.bbox[2], north = plume.bbox[3];
      if (east < bounds.getWest() || west > bounds.getEast() || north < bounds.getSouth() || south > bounds.getNorth()) return;
      var img = self.image(plume.image_url);
      if (!img) return;
      var topLeft = map.project([west, north]);
      var bottomRight = map.project([east, south]);
      var w = bottomRight.x - topLeft.x, h = bottomRight.y - topLeft.y;
      var scale = Math.max(1, PLUME_MIN_PX / Math.max(w, h, 0.01));
      var cx = topLeft.x + w / 2, cy = topLeft.y + h / 2;
      ctx.drawImage(img, cx - (w * scale) / 2, cy - (h * scale) / 2, w * scale, h * scale);
    });
    source.setCoordinates(this.viewCorners());
    source.play();
    map.once('render', function () { if (map.getSource(PLUMES_SOURCE) === source) source.pause(); });
    map.triggerRepaint();
  };

  Overlay.prototype.legendHtml = function () {
    if (!this.enabled) return '';
    var html = '<div class="legend-overlay"><label class="legend-toggle"><input type="checkbox" data-methane' + (this.on ? ' checked' : '') + '> Methane sources</label>';
    if (this.on) {
      html += '<p class="legend-note">Each source\'s newest observed plume, shaded by methane concentration and drawn larger than life when zoomed out. Snapshots from overflights, not annual totals. Click one for its rate and other passes.</p>';
    }
    return html + '</div>';
  };

  Overlay.prototype.openPopup = function (feature, lngLat) {
    var self = this;
    var p = feature.properties;
    // Nested objects arrive as JSON strings in MapLibre feature properties.
    var link = p.facility ? JSON.parse(p.facility) : null;
    var dairy = p.dairy ? JSON.parse(p.dairy) : null;
    // The source (what it is, what's near it, its typical rate and how often
    // it's been seen), then the plume on the map with a stepper through its
    // passes.
    var html = '<div class="facility-popup methane-popup">' +
      '<p class="facility-popup-name">' + escapeHtml(p.sector) + ' methane source</p>' +
      (dairy ? '<p class="methane-near">Near ' + escapeHtml(dairy.name) + '</p>' : '') +
      (link ? '<p class="methane-near">Near <a href="' + escapeHtml(link.url) + '">' + escapeHtml(link.name) + '</a></p>' : '') +
      '<dl class="methane-facts">' +
        '<dt>Rate</dt><dd>' + escapeHtml(p.rate_text) + '</dd>' +
        '<dt>Seen</dt><dd>' + p.det + ' of ' + p.obs + ' pass' + (p.obs === 1 ? '' : 'es') + '</dd>' +
      '</dl>' +
      '<div class="methane-plume-panel" data-plume-panel><p class="has-text-grey">Loading plumes…</p></div>' +
      '<p class="methane-record"><a href="' + escapeHtml(p.viewer_url) + '">Source record →</a></p></div>';
    var popup = this.host.shell.placePopup(html, lngLat);
    this.plumes = null;
    this.plumeIndex = 0;
    this.activePopup = popup;
    // The popup drapes this source's plumes itself; its newest plume steps
    // aside from the canvas so a stepped-to older pass isn't drawn over it.
    this.activeSource = p.id;
    this.redraw();
    popup.on('close', function () { self.closePlumePanel(popup); });
    this.loadPlumes(p.id, popup);
  };

  // Fetched fresh per popup open (a source's plumes rarely change): the
  // stepper starts at the newest and drapes its image.
  Overlay.prototype.loadPlumes = function (sourceId, popup) {
    var self = this;
    var url = this.host.data.methanePlumesUrl;
    if (!url) return;
    var request = ++this.plumeRequest;
    getJson(url.replace('{id}', encodeURIComponent(sourceId)))
      .then(function (data) {
        if (request !== self.plumeRequest || self.activePopup !== popup) return;
        self.plumes = (data && data.plumes) || [];
        self.plumeIndex = 0;
        self.renderPlumePanel(popup);
      })
      .catch(function (err) {
        if (request !== self.plumeRequest || self.activePopup !== popup) return;
        logError('failed to load the source\'s plumes', err);
        var panel = self.plumePanel(popup);
        if (panel) panel.innerHTML = '';
      });
  };

  Overlay.prototype.plumePanel = function (popup) {
    var el = popup && popup.getElement && popup.getElement();
    return el ? el.querySelector('[data-plume-panel]') : null;
  };

  Overlay.prototype.formatPlumeDate = function (iso) {
    try {
      return new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
    } catch (err) {
      return iso || '';
    }
  };

  Overlay.prototype.renderPlumePanel = function (popup) {
    var panel = this.plumePanel(popup);
    if (!panel) return;
    if (!this.plumes || !this.plumes.length) {
      panel.innerHTML = '<p class="has-text-grey">No plume images on file.</p>';
      this.removePlumeLayer();
      return;
    }
    var self = this;
    // Newest first: index 0 is the latest pass, so "earlier" is +1.
    var plume = this.plumes[this.plumeIndex];
    var count = this.plumes.length;
    var hasRate = plume.rate !== null && plume.rate !== undefined;
    var hasWind = plume.wind_speed !== null && plume.wind_speed !== undefined;
    var details = [];
    if (count > 1) details.push('pass ' + (count - this.plumeIndex) + ' of ' + count);
    if (plume.platform) details.push(escapeHtml(plume.platform));
    if (hasRate) details.push(escapeHtml(plume.rate_text));
    if (hasWind) details.push('wind ' + Number(plume.wind_speed).toFixed(1) + ' m/s');
    panel.innerHTML =
      '<div class="methane-plume-head">' +
        '<span class="methane-plume-label">Plume</span>' +
        '<span class="buttons has-addons methane-plume-stepper">' +
          '<button type="button" class="button is-small methane-plume-prev" aria-label="Earlier pass"' + (this.plumeIndex < count - 1 ? '' : ' disabled') + '><span class="fa-regular fa-chevron-left" aria-hidden="true"></span></button>' +
          '<span class="button is-small is-static methane-plume-date">' + escapeHtml(this.formatPlumeDate(plume.observed_at)) + '</span>' +
          '<button type="button" class="button is-small methane-plume-next" aria-label="Later pass"' + (this.plumeIndex > 0 ? '' : ' disabled') + '><span class="fa-regular fa-chevron-right" aria-hidden="true"></span></button>' +
        '</span>' +
      '</div>' +
      (details.length ? '<p class="methane-plume-details">' + details.join(' · ') + '</p>' : '') +
      (!plume.image_url ? '<p class="has-text-grey">No image for this pass.</p>' : '');
    var prevBtn = panel.querySelector('.methane-plume-prev');
    var nextBtn = panel.querySelector('.methane-plume-next');
    if (prevBtn) prevBtn.addEventListener('click', function () { self.stepPlume(1, popup); });
    if (nextBtn) nextBtn.addEventListener('click', function () { self.stepPlume(-1, popup); });
    this.drapePlume(plume);
  };

  Overlay.prototype.stepPlume = function (delta, popup) {
    if (!this.plumes) return;
    var index = this.plumeIndex + delta;
    if (index < 0 || index >= this.plumes.length) return;
    this.plumeIndex = index;
    this.renderPlumePanel(popup);
  };

  // The image source + raster layer, below the source circles (`before`
  // 'methane' when it's on the map yet).
  Overlay.prototype.drapePlume = function (plume) {
    this.removePlumeLayer();
    var map = this.host.map;
    if (!map || !plume || !plume.image_url || !plume.bounds) return;
    try {
      map.addSource(PLUME_SOURCE, { type: 'image', url: plume.image_url, coordinates: plume.bounds });
      map.addLayer(
        { id: PLUME_LAYER, type: 'raster', source: PLUME_SOURCE, paint: { 'raster-opacity': 0.85 } },
        map.getLayer('methane') ? 'methane' : undefined
      );
    } catch (err) {
      logError('failed to drape the plume image', err);
    }
  };

  Overlay.prototype.removePlumeLayer = function () {
    var map = this.host.map;
    if (!map) return;
    if (map.getLayer(PLUME_LAYER)) map.removeLayer(PLUME_LAYER);
    if (map.getSource(PLUME_SOURCE)) map.removeSource(PLUME_SOURCE);
  };

  Overlay.prototype.closePlumePanel = function (popup) {
    if (this.activePopup !== popup) return;
    this.activePopup = null;
    this.activeSource = null;
    this.plumes = null;
    this.plumeIndex = 0;
    this.plumeRequest += 1;
    this.removePlumeLayer();
    this.redraw();
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

  Overlay.prototype.onAdopt = function () {
    this.activePopup = null;
    this.plumes = null;
    this.plumeIndex = 0;
    this.plumeRequest += 1;
    this.read();
    this.apply();
    this.load();
  };
  Overlay.prototype.destroy = function () {
    this.collection = null;
    this.activePopup = null;
    this.plumes = null;
    this.plumeRequest += 1;
    this.removePlumeLayer();
  };

  window.EmissionsMethaneOverlay = Overlay;
})();
