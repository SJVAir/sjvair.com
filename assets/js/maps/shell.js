/*
 * The Shell: one map on the page. It builds the SDK map from the container's
 * data-* attributes (key, style, center/zoom, bounds), adds the controls and
 * chrome the module's spec asks for, and runs the module's hooks. A module
 * (registered with SJVAirMaps.register, see registry.js) supplies only what
 * its map draws: create(shell) returns an object whose optional hooks are
 *
 *   load()                      fetch and draw its data (right after create)
 *   addLayers()                 sources and layers, after every style load
 *   onChrome(wrap)              bind its own toolbar/Options controls
 *   onDropdownOpen()            a toolbar dropdown opened (close a popup)
 *   onAdopt(changedKeys, old)   an htmx swap handed it a new container
 *   onLocate(lngLat)            the reader's position, once located
 *   home()                      {bounds, padding} or {center, zoom}, or null
 *   legend(bodyEl)              fill the legend card (shell.updateLegend())
 *   destroy()                   let go of anything it holds
 *
 * and which it builds on with the shell's helpers: its toolbar controls
 * (controls, bindControls), one popup at a time (placePopup, closePopup,
 * shell.popup), sources and layers (ensureSource, ensureLayer,
 * setSourceData), fetch tickets, the status pill and the legend.
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M || M.Shell) return;

  var DEFAULT_CENTER = [-119.80, 36.75];
  var DEFAULT_ZOOM = 8;
  var LOCATE_ZOOM = 12;
  var LOCATE_COLOR = '#3273dc';
  // A figure, not a map to move: every handler off.
  var NOT_INTERACTIVE = {
    dragPan: false,
    scrollZoom: false,
    doubleClickZoom: false,
    boxZoom: false,
    keyboard: false,
    touchZoomRotate: false,
    dragRotate: false,
    pitchWithRotate: false,
    touchPitch: false,
  };

  // Which chrome this map has. The server renders the chrome
  // (camp/utils/mapconfig.py, templates/maps/includes/map.html) and says so
  // in data-features, so when the container carries it that set wins for the
  // chrome booleans -- otherwise a spec that says `toolbar: false` would
  // leave a rendered toolbar hidden forever, since attach() is the only thing
  // that unhides it. A map the server doesn't render the chrome for (a
  // figure) has no data-features, and falls back to its spec. `controls` and
  // `interactive` always come from the spec: they're the module's business,
  // not the page's.
  var CHROME_FEATURES = ['toolbar', 'legend', 'status', 'expand'];

  function featuresFor(el, spec) {
    var features = Object.assign({}, spec.features || {});
    var declared = el.dataset.features;
    if (declared == null) return features;
    var rendered = declared.split(/\s+/);
    CHROME_FEATURES.forEach(function (feature) {
      features[feature] = rendered.indexOf(feature) !== -1;
    });
    return features;
  }

  function Shell(el, name, spec) {
    var self = this;
    this.el = el;
    this.name = name;
    this.spec = spec;
    this.features = featuresFor(el, spec);
    this.data = el.dataset;
    // The GeoJSON behind each source, kept so a style swap (which empties the
    // style of our layers) can put it all back.
    this.sourceData = {};
    this.expanded = false;
    this.loaded = false;
    this.tickets = 0;
    this.popup = null;
    this.reducedMotion = M.prefersReducedMotion();
    this.tileStyle = M.tileStyle(el);

    var center = M.parseCenter(this.data.center);
    var bounds = center ? null : M.parseBounds(this.data.bounds);
    var options = {
      container: el,
      style: M.styleFor(this.tileStyle),
      center: center || DEFAULT_CENTER,
      zoom: parseFloat(this.data.zoom) || DEFAULT_ZOOM,
      // Controls are added below in a fixed order; the SDK's defaults are
      // either ours (locate) or unwanted.
      navigationControl: false,
      geolocateControl: false,
      terrainControl: false,
      // Wheel-zoom is off until the cursor is deliberately moved onto the
      // map (bindWheelZoom), so it doesn't hijack page scrolling.
      scrollZoom: false,
      // Flat and north-up: no pitch, no rotation.
      pitchWithRotate: false,
      dragRotate: false,
      touchPitch: false,
      attributionControl: { compact: 'auto' },
      logoPosition: 'bottom-right',
    };
    if (bounds) {
      options.bounds = bounds;
      options.fitBoundsOptions = { padding: 20 };
    }
    if (this.features.interactive === false) Object.assign(options, NOT_INTERACTIVE);
    if (spec.mapOptions) Object.assign(options, spec.mapOptions(el) || {});

    maptilersdk.config.apiKey = this.data.maptilerKey || '';
    this.map = new maptilersdk.Map(options);
    // For debugging from the console: document.querySelector('.map-canvas').sjvairMap
    el.sjvairMap = this;

    if (this.features.interactive !== false) {
      this.map.touchZoomRotate.disableRotation();
      this.map.keyboard.disableRotation();
    }

    M.addControls(this, this.features.controls);
    // The document-level closers are only for chrome that opens something:
    // a map with neither a toolbar nor Expand has nothing for them to close.
    if (this.features.toolbar || this.features.expand) M.chrome.bindDocument(this);
    M.chrome.attach(this);
    // After attach(): the region it arms over is shell.wrap.
    this.bindWheelZoom();

    this.module = (spec.create && spec.create(this)) || {};
    if (this.module.onChrome) this.module.onChrome(this.wrap);

    // Sources and layers are part of the style, so they're (re)added on
    // every style load, the first time included.
    this.map.on('style.load', function () { self.onStyleLoad(); });
    this.map.once('load', function () {
      self.loaded = true;
      M.chrome.collapseAttribution(self);
    });
    if (this.module.load) this.module.load();
  }

  // -- wheel zoom --
  //
  // The wheel zooms while the cursor is deliberately over the map, and the
  // page scrolls otherwise. The region is the whole .map-wrap, not just the
  // canvas, so reaching for the toolbar, Options or the Legend doesn't
  // disarm it -- that was the old click-to-arm rule's worst habit.
  //
  // "Deliberately" is the point: a page scroll can slide the map under a
  // still cursor, and grabbing the wheel then would trap the scroll. The two
  // are told apart by where the pointer was: a scroll moves the map to the
  // cursor without changing clientX/clientY (only the page coordinates
  // move), so an entry at the same viewport position the pointer already
  // held is the map arriving, not the reader crossing into it. Tracking the
  // pointer on the document, rather than reading the scroll gesture, keeps
  // this independent of event order -- the scroll-induced mouseenter is
  // dispatched *before* the scroll event that caused it.
  //
  //   entering somewhere the pointer wasn't  -> deliberate, arm
  //   entering where the pointer already was -> the map came to them, wait
  //   any mousemove inside the region        -> deliberate, arm
  //
  // On top of that the wheel stays disarmed for as long as a scroll gesture
  // is running, whatever the hover says, so a jittery hand mid-scroll can't
  // grab it.

  // How long after the last scroll event a page-scroll gesture is still
  // considered in flight. Covers a jittery hand mid-scroll: small cursor
  // movement over the map during a scroll must not arm the wheel.
  var SCROLL_SETTLE_MS = 200;

  Shell.prototype.bindWheelZoom = function () {
    if (this.features.interactive === false) return;
    var region = this.wrap || this.el;
    if (this.wheelRegion === region) return;
    this.unbindWheelZoom();

    var self = this;
    this.wheelRegion = region;
    this.wheelHover = false;  // the cursor was deliberately moved in here
    this.wheelFocus = false;  // something in here has keyboard focus
    this.wheelAt = null;      // where the pointer last was, anywhere on the page
    this.wheelScrolling = 0;  // timer id while a page scroll is in flight
    this.wheelArmed = false;  // what the handler was last set to (map option: off)
    this.wheelHandlers = {
      mouseenter: function (event) {
        // Somewhere the pointer wasn't: they crossed into the map. The same
        // spot it already held: the map scrolled to them, so wait for a move.
        var at = event.clientX + ',' + event.clientY;
        self.wheelHover = self.wheelAt !== null && self.wheelAt !== at;
        self.syncWheelZoom();
      },
      mousemove: function () {
        self.wheelHover = true;
        self.syncWheelZoom();
      },
      mouseleave: function () {
        self.wheelHover = false;
        self.syncWheelZoom();
      },
      focusin: function () { self.wheelFocus = true; self.syncWheelZoom(); },
      focusout: function () { self.wheelFocus = false; self.syncWheelZoom(); },
    };
    Object.keys(this.wheelHandlers).forEach(function (type) {
      region.addEventListener(type, self.wheelHandlers[type]);
    });

    // Where the pointer is, tracked page-wide: mouseenter needs the position
    // it held *before* the entry, which a listener on the region can't see.
    // Capture and passive: this only ever reads.
    this.wheelPointerHandler = function (event) {
      self.wheelAt = event.clientX + ',' + event.clientY;
    };
    document.addEventListener('mousemove', this.wheelPointerHandler, { capture: true, passive: true });

    this.wheelScrollHandler = function () {
      if (self.wheelScrolling) clearTimeout(self.wheelScrolling);
      self.wheelScrolling = setTimeout(function () {
        self.wheelScrolling = 0;
        self.syncWheelZoom();
      }, SCROLL_SETTLE_MS);
      self.syncWheelZoom();
    };
    // Capture: a scroll doesn't bubble, and this must see the page's as well
    // as any scrolling ancestor's.
    document.addEventListener('scroll', this.wheelScrollHandler, true);
  };

  Shell.prototype.unbindWheelZoom = function () {
    var self = this;
    if (this.wheelRegion && this.wheelHandlers) {
      Object.keys(this.wheelHandlers).forEach(function (type) {
        self.wheelRegion.removeEventListener(type, self.wheelHandlers[type]);
      });
    }
    if (this.wheelScrollHandler) document.removeEventListener('scroll', this.wheelScrollHandler, true);
    if (this.wheelPointerHandler) document.removeEventListener('mousemove', this.wheelPointerHandler, { capture: true });
    if (this.wheelScrolling) clearTimeout(this.wheelScrolling);
    this.wheelRegion = null;
    this.wheelHandlers = null;
    this.wheelScrollHandler = null;
    this.wheelPointerHandler = null;
    this.wheelScrolling = 0;
    this.wheelHover = false;
    this.wheelFocus = false;
    this.wheelAt = null;
    this.setWheelZoom(false);
  };

  // Armed while the map has the cursor or the keyboard, and no page-scroll
  // gesture is in flight.
  Shell.prototype.syncWheelZoom = function () {
    this.setWheelZoom((this.wheelHover || this.wheelFocus) && !this.wheelScrolling);
  };

  // syncWheelZoom runs on every mousemove over the map, so this only reaches
  // the handler when the answer actually changed.
  Shell.prototype.setWheelZoom = function (on) {
    if (!this.map || this.wheelArmed === on) return;
    this.wheelArmed = on;
    if (on) this.map.scrollZoom.enable();
    else this.map.scrollZoom.disable();
  };

  Shell.prototype.onStyleLoad = function () {
    if (this.module.addLayers) this.module.addLayers();
    if ((this.features.controls || []).indexOf('locate') === -1) return;
    // The reader's located position, on top of everything the module drew.
    this.ensureSource('locate');
    this.ensureLayer({
      id: 'locate-circle', type: 'circle', source: 'locate',
      paint: {
        'circle-radius': 6,
        'circle-color': LOCATE_COLOR,
        'circle-stroke-color': '#fff',
        'circle-stroke-width': 2,
      },
    });
  };

  // GeoJSON sources are keyed on our own feature ids (`promoteId`), so
  // feature state (hover, selection) can address them by id.
  Shell.prototype.ensureSource = function (id, extra) {
    if (!this.map || this.map.getSource(id)) return;
    this.map.addSource(id, Object.assign({ type: 'geojson', data: this.sourceData[id] || M.EMPTY, promoteId: 'id' }, extra || {}));
  };

  Shell.prototype.ensureLayer = function (spec) {
    if (!this.map || this.map.getLayer(spec.id)) return;
    this.map.addLayer(spec);
  };

  // Sets a source's data, remembering it for the next style load; before the
  // style is up the data waits for ensureSource. Nothing to keep once the map
  // is gone (a late response after destroy()).
  Shell.prototype.setSourceData = function (id, data) {
    if (!this.map) return;
    this.sourceData[id] = data;
    var source = this.map.getSource(id);
    if (source) source.setData(data);
  };

  // A number for a fetch about to start; isCurrent(ticket) says whether it's
  // still the newest one (and the map is still here) when it lands. One
  // family per shell: a new ticket supersedes every earlier one, whatever
  // fetch it came from.
  Shell.prototype.ticket = function () {
    this.tickets += 1;
    return this.tickets;
  };

  Shell.prototype.isCurrent = function (ticket) {
    return !!this.map && ticket === this.tickets;
  };

  Shell.prototype.setStatus = function (message) {
    M.chrome.setStatus(this, message);
  };

  Shell.prototype.updateLegend = function () {
    if (this.module.legend && this.legendBodyEl) this.module.legend(this.legendBodyEl);
  };

  // The toolbar's own controls matching `selector`. Not the whole wrap: the
  // map container carries data-view, data-measure and the like too.
  Shell.prototype.controls = function (selector) {
    return this.toolbarEl ? this.toolbarEl.querySelectorAll(selector) : [];
  };

  // Binds a click on each toolbar control matching `selector` to
  // handler(control), once per control (an adopt re-runs onChrome over the
  // new page's chrome): it closes any open dropdown first.
  Shell.prototype.bindControls = function (selector, handler) {
    var self = this;
    Array.prototype.forEach.call(this.controls(selector), function (item) {
      if (item.getAttribute('data-bound')) return;
      item.setAttribute('data-bound', '1');
      item.addEventListener('click', function (event) {
        event.preventDefault();
        M.chrome.closeDropdowns(self, null);
        handler(item);
      });
    });
  };

  // Opens the map's one popup at `lngLat` (closing any other), clear of the
  // toolbar and legend card; shell.popup is it until it closes.
  Shell.prototype.placePopup = function (html, lngLat) {
    var self = this;
    this.closePopup();
    var popup = new maptilersdk.Popup({ maxWidth: this.popupMaxWidth() }).setLngLat(lngLat).setHTML(html).addTo(this.map);
    this.popup = popup;
    this.panPopupIntoView(popup);
    popup.on('close', function () { if (self.popup === popup) self.popup = null; });
    return popup;
  };

  Shell.prototype.closePopup = function () {
    if (this.popup) this.popup.remove();
  };

  Shell.prototype.popupMaxWidth = function () {
    return M.chrome.popupMaxWidth(this);
  };

  Shell.prototype.panPopupIntoView = function (popup, again) {
    M.chrome.panPopupIntoView(this, popup, again);
  };

  Shell.prototype.setExpanded = function (on) {
    M.chrome.setExpanded(this, on);
  };

  // Home goes back to what the page is about: the module's own framing when
  // it has one, else the page's centre, else its bounds, else the default view.
  Shell.prototype.home = function () {
    var animate = !this.reducedMotion;
    var target = this.module.home ? this.module.home() : null;
    if (target && target.bounds) {
      this.map.fitBounds(target.bounds, { padding: target.padding == null ? 20 : target.padding, animate: animate });
      return;
    }
    if (target && target.center) {
      this.map.easeTo({ center: target.center, zoom: target.zoom || DEFAULT_ZOOM, animate: animate });
      return;
    }
    var center = M.parseCenter(this.data.center);
    var bounds = M.parseBounds(this.data.bounds);
    if (center) {
      this.map.easeTo({ center: center, zoom: parseFloat(this.data.zoom) || DEFAULT_ZOOM, animate: animate });
    } else if (bounds) {
      this.map.fitBounds(bounds, { padding: 20, animate: animate });
    } else {
      this.map.easeTo({ center: DEFAULT_CENTER, zoom: DEFAULT_ZOOM, animate: animate });
    }
  };

  // Snap to the page's framing (after an adopt, for a module with no onAdopt).
  Shell.prototype.frame = function () {
    var center = M.parseCenter(this.data.center);
    var bounds = M.parseBounds(this.data.bounds);
    if (center) {
      this.map.jumpTo({ center: center, zoom: parseFloat(this.data.zoom) || this.map.getZoom() });
    } else if (bounds) {
      this.map.fitBounds(bounds, { padding: 20, duration: 0 });
    }
  };

  // Finds the reader, drops the dot on their position, and hands it to the
  // module (onLocate: it decides where the camera goes) or eases there.
  Shell.prototype.locate = function () {
    var self = this;
    var control = this.locateControl && this.locateControl.container;
    if (control) control.classList.add('is-locating');
    this.setStatus('Finding your location…');
    navigator.geolocation.getCurrentPosition(function (position) {
      if (!self.map) return;
      if (control) control.classList.remove('is-locating');
      self.setStatus('');
      var here = [position.coords.longitude, position.coords.latitude];
      self.setSourceData('locate', {
        type: 'Feature',
        properties: { id: 'me' },
        geometry: { type: 'Point', coordinates: here },
      });
      if (self.module.onLocate) {
        self.module.onLocate(here);
      } else {
        self.map.easeTo({ center: here, zoom: LOCATE_ZOOM, animate: !self.reducedMotion });
      }
    }, function () {
      if (control) control.classList.remove('is-locating');
      self.setStatus('Couldn\'t get your location');
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  };

  // An htmx swap put a new page in place: move this live map into the new
  // container's slot, take its data attributes, re-bind the new chrome, and
  // tell the module what changed. Keeping the map avoids tearing it down and
  // reloading its basemap on every scope change.
  Shell.prototype.adopt = function (newEl) {
    var oldData = {};
    var newData = {};
    var key;
    for (key in this.el.dataset) oldData[key] = this.el.dataset[key];
    for (key in newEl.dataset) newData[key] = newEl.dataset[key];

    newEl.parentNode.replaceChild(this.el, newEl);
    for (key in oldData) {
      if (!(key in newData) && key !== 'rendered') delete this.el.dataset[key];
    }
    for (key in newData) this.el.dataset[key] = newData[key];
    this.el.dataset.rendered = '1';
    this.el.id = newEl.id;
    this.data = this.el.dataset;

    var changed = Object.keys(Object.assign({}, oldData, newData)).filter(function (k) {
      return k !== 'rendered' && (oldData[k] || '') !== (newData[k] || '');
    });

    // The new page rendered its own chrome, so re-read what it has.
    this.features = featuresFor(this.el, this.spec);
    if (this.features.toolbar || this.features.expand) M.chrome.bindDocument(this);
    M.chrome.attach(this);
    // The wrapper is the new page's, so the wheel region moves with it.
    this.bindWheelZoom();
    if (this.module.onChrome) this.module.onChrome(this.wrap);
    this.map.resize();
    if (this.module.onAdopt) {
      this.module.onAdopt(changed, oldData);
    } else {
      this.frame();
      if (this.module.load) this.module.load();
    }
  };

  // Releases the map (its WebGL context with it) once its page is gone. A
  // fetch still in flight is let go of (its ticket is no longer current).
  Shell.prototype.destroy = function () {
    if (this.expanded) M.chrome.setExpanded(this, false);
    M.chrome.unbindDocument(this);
    this.unbindWheelZoom();
    this.tickets += 1;
    if (this.module.destroy) this.module.destroy();
    this.map.remove();
    this.map = null;
  };

  M.Shell = Shell;
})();
