/*
 * Interactive pesticide section map for the Pesticides Explorer, on the
 * MapTiler SDK (MapLibre GL).
 *
 * Turns each `.section-map` container into a live map: square-mile (MTRS)
 * sections shaded by a metric (pounds or application count), plus SprayDays
 * notice-of-intent markers and, where the page asks for them, school and
 * child care markers. Config comes entirely from the container's `data-*`
 * attributes (see `pesticides/includes/section-map.html` and
 * `views.section_map_config`), so this script has no server-rendered state
 * baked in beyond that.
 *
 * While the port from Leaflet is in progress this module loads beside the
 * Leaflet one under `?gl=1` and claims only the containers marked `data-gl`
 * (the Leaflet script skips those). The behaviour it is held to is the
 * parity checklist, docs/superpowers/specs/2026-09-21-section-map-inventory.md.
 *
 * Plain ES2017, no framework/bundler, single global side effect: none (IIFE).
 */
(function () {
  'use strict';

  // At this zoom and closer the map draws square-mile (MTRS) sections; further
  // out it draws the 6x6 mile township grid instead, so there's always a grid.
  // It's a floor: a wide viewport needs to be closer still, or the sections
  // in view would exceed what the endpoint returns (see sectionZoom()).
  var SECTION_ZOOM = 11;
  // The most sections a viewport should ask for at once, under the API's
  // 2,500 cap with room for the padded bbox fetch to fall back unpadded.
  var MAX_VIEWPORT_SECTIONS = 2000;
  var METERS_PER_MILE = 1609.34;
  var DEBOUNCE_MS = 300;
  // Candidate ramps, selectable with ?ramp=<name> while we pick one.
  var RAMPS = {
    blues: ['#deebf7', '#9ecae1', '#6baed6', '#3182bd', '#08519c'],
    purd: ['#f1eef6', '#d7b5d8', '#df65b0', '#dd1c77', '#980043'],
    bupu: ['#edf8fb', '#b3cde3', '#8c96c6', '#8856a7', '#810f7c'],
    ylorbr: ['#ffffd4', '#fed98e', '#fe9929', '#d95f0e', '#993404'],
    putrid: ['#eef2b8', '#cfd96e', '#a3b53c', '#72871f', '#3f4f12'],
    bile: ['#f5f2a4', '#d9d95a', '#a9b62e', '#6b7615', '#3a400c'],
    // Putrid with a paler, greyer light end and the middle steps spread apart.
    putrid2: ['#eceedc', '#c9d18c', '#98ab3f', '#5f7a1c', '#2f3f0e'],
    // Multi-hue sequential: yellow-green through teal to navy (ColorBrewer YlGnBu).
    ylgnbu: ['#ffffcc', '#a1dab4', '#41b6c4', '#2c7fb8', '#253494'],
    // Cool teal-to-green (ColorBrewer PuBuGn).
    pubugn: ['#f6eff7', '#bdc9e1', '#67a9cf', '#1c9099', '#016c59'],
    // Perceptually uniform (matplotlib): mako and cividis.
    mako: ['#def5e5', '#60ceac', '#3497a9', '#3e5ba9', '#382a54'],
    cividis: ['#fde725', '#c7b76e', '#7f7c75', '#4b5a6a', '#00224e'],
  };
  var rampMatch = /[?&]ramp=([a-z]+)/.exec(window.location.search || '');
  var RAMP = RAMPS[rampMatch && rampMatch[1]] || RAMPS.blues;
  // How many quantile classes: ?bins=4|5|6|8|10 (quartiles ... deciles).
  var BIN_OPTIONS = [[4, 'Quartiles'], [5, 'Quintiles'], [6, 'Sextiles'], [8, 'Octiles'], [10, 'Deciles']];
  var binsMatch = /[?&]bins=(\d+)/.exec(window.location.search || '');
  var DEFAULT_BINS = 6;
  var NUM_CLASSES = binsMatch && BIN_OPTIONS.some(function (o) { return o[0] === +binsMatch[1]; }) ? +binsMatch[1] : DEFAULT_BINS;

  // The basemap styles the experiment control offers (?tiles=<id>), each
  // mapped to its entry in the SDK's style catalogue (a path under
  // maptilersdk.MapStyle). An id the table doesn't know is handed to the SDK
  // as is, which reads it as a MapTiler style id.
  var TILE_STYLES = ['streets', 'basic-v2', 'bright-v2', 'dataviz', 'dataviz-light', 'topo-v2', 'outdoor-v2', 'toner-v2', 'hybrid'];
  var TILE_STYLE_PATHS = {
    streets: ['STREETS'],
    'basic-v2': ['BASIC'],
    'bright-v2': ['BRIGHT'],
    dataviz: ['DATAVIZ'],
    'dataviz-light': ['DATAVIZ', 'LIGHT'],
    'topo-v2': ['TOPO'],
    'outdoor-v2': ['OUTDOOR'],
    'toner-v2': ['TONER'],
    hybrid: ['HYBRID'],
  };
  function styleFor(id) {
    var path = TILE_STYLE_PATHS[id];
    var style = path ? maptilersdk.MapStyle : null;
    for (var i = 0; style && i < path.length; i++) style = style[path[i]];
    return style || id;
  }

  var COUNTY_COLOR = '#1f2d3d';
  // Dashed county lines once the section grid is on (see restyleCounties);
  // dash lengths are in line widths, so this is Leaflet's "4 3" at 1.5px.
  var COUNTY_DASH = [2.5, 2];
  // The page's own region (a city, ZIP, or place), in the notices orange.
  var OUTLINE_COLOR = '#d35400';
  // The locate radius circle, in Leaflet's default path style.
  var RADIUS_COLOR = '#3388ff';
  // How many vertices approximate the radius circle.
  var RADIUS_CIRCLE_POINTS = 64;
  // The reader's own position after a locate: a small blue dot ringed white.
  var LOCATE_COLOR = '#3273dc';

  var EMPTY = { type: 'FeatureCollection', features: [] };

  function prefersReducedMotion() {
    try {
      return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (err) {
      return false;
    }
  }

  // The SDK draws on WebGL; without it there's no map to make, and the page
  // says so in the container instead (see showUnavailable). Checked once:
  // the probe makes a throwaway GL context, and init() runs on every swap.
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

  function showUnavailable(el) {
    el.classList.add('is-unavailable');
    el.innerHTML = '<p class="section-map-note">This map needs WebGL, which this browser has turned off or doesn\'t support.</p>';
  }

  function milesToMeters(miles) {
    return miles * METERS_PER_MILE;
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

  // One fetch shape for every endpoint: `params` (empty values dropped) go on
  // the query string, a non-OK response rejects with its status on the error
  // (a 400 from the grid endpoints means "bbox too large", which callers
  // handle), and an AbortController can cut the request short.
  function fetchJson(url, params, abort) {
    var query = params ? buildQuery(params) : '';
    if (query) url += (url.indexOf('?') === -1 ? '?' : '&') + query;
    return fetch(url, abort ? { signal: abort.signal } : {})
      .then(function (response) {
        if (!response.ok) {
          var err = new Error('bad response');
          err.status = response.status;
          throw err;
        }
        return response.json();
      });
  }

  function isAbort(err) {
    return !!err && err.name === 'AbortError';
  }

  function logError(message, err) {
    if (window.console && console.error) console.error('section-map: ' + message, err);
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

  // -- geometry --
  // Data attributes and the Leaflet-era helpers speak "lat,lng"; the SDK
  // speaks [lng, lat]. Bounds are [[west, south], [east, north]].

  function lngLatOf(latlng) {
    return [latlng[1], latlng[0]];
  }

  function extendBounds(bounds, coordinates) {
    if (typeof coordinates[0] === 'number') {
      if (coordinates[0] < bounds[0][0]) bounds[0][0] = coordinates[0];
      if (coordinates[0] > bounds[1][0]) bounds[1][0] = coordinates[0];
      if (coordinates[1] < bounds[0][1]) bounds[0][1] = coordinates[1];
      if (coordinates[1] > bounds[1][1]) bounds[1][1] = coordinates[1];
      return;
    }
    for (var i = 0; i < coordinates.length; i++) extendBounds(bounds, coordinates[i]);
  }

  // The bounding box of a GeoJSON geometry, feature, or feature collection;
  // null for nothing (an empty collection, a null geometry).
  function geometryBounds(geojson) {
    if (!geojson) return null;
    var bounds = [[Infinity, Infinity], [-Infinity, -Infinity]];
    var items = geojson.type === 'FeatureCollection' ? geojson.features : [geojson];
    for (var i = 0; i < items.length; i++) {
      var geometry = items[i].type === 'Feature' ? items[i].geometry : items[i];
      if (!geometry) continue;
      var parts = geometry.type === 'GeometryCollection' ? geometry.geometries : [geometry];
      for (var j = 0; j < parts.length; j++) {
        if (parts[j] && parts[j].coordinates) extendBounds(bounds, parts[j].coordinates);
      }
    }
    return bounds[0][0] === Infinity ? null : bounds;
  }

  function unionBounds(a, b) {
    if (!a) return b;
    if (!b) return a;
    return [
      [Math.min(a[0][0], b[0][0]), Math.min(a[0][1], b[0][1])],
      [Math.max(a[1][0], b[1][0]), Math.max(a[1][1], b[1][1])],
    ];
  }

  // A circle of `meters` around [lng, lat] as a polygon feature: the SDK has
  // no circle geometry, and a circle layer is sized in pixels, not metres.
  function circlePolygon(center, meters, id) {
    var latRadians = center[1] * Math.PI / 180;
    var dLat = meters / 111320;
    var dLng = meters / (111320 * Math.cos(latRadians));
    var ring = [];
    for (var i = 0; i <= RADIUS_CIRCLE_POINTS; i++) {
      var angle = (i % RADIUS_CIRCLE_POINTS) * 2 * Math.PI / RADIUS_CIRCLE_POINTS;
      ring.push([center[0] + dLng * Math.cos(angle), center[1] + dLat * Math.sin(angle)]);
    }
    return {
      type: 'Feature',
      properties: { id: id },
      geometry: { type: 'Polygon', coordinates: [ring] },
    };
  }

  // -- controls --
  // Locate and Reset as SDK controls: one bar each, stacked under the zoom
  // buttons, in the SDK's control idiom with the Leaflet markup inside
  // (an anchor acting as a button, an icon, a title and label).
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
      // A click on the control isn't a click on the map (it would switch
      // wheel-zoom on, see enableScrollZoom).
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

  function SectionMap(el) {
    this.el = el;
    this.data = el.dataset;
    this.reducedMotion = prefersReducedMotion();
    // ?metric=applications and ?notices=1|0 preselect a view, so a link can
    // share it; the toggles write them back (see syncViewParams).
    var metricMatch = /[?&]metric=(lbs_chemical|applications)/.exec(window.location.search || '');
    this.metric = metricMatch ? metricMatch[1] : 'lbs_chemical';
    // Notice markers are on by default only where notices are the subject of
    // the page; `data-show-notices` says which this is, a ?notices= param
    // overrides it, and the "Show notices" checkbox flips it from there.
    var noticesMatch = /[?&]notices=([01])/.exec(window.location.search || '');
    this.showNotices = noticesMatch ? noticesMatch[1] === '1' : this.data.showNotices !== '0';
    // School and child care markers work the same way: on by default only
    // where the schools are the subject of the page (a school district).
    var locationsMatch = /[?&]locations=([01])/.exec(window.location.search || '');
    this.showLocations = locationsMatch ? locationsMatch[1] === '1' : this.data.showLocations === '1';
    // "All sections": at the township zoom, draw every section in view
    // instead of the township grid (loaded in blocks, see loadAllSections).
    this.showAllSections = /[?&]sections=1/.test(window.location.search || '');
    // Only one grid is ever on the map at a time; `level` says which one.
    this.level = 'section';
    // The GeoJSON behind each of our sources, kept here so a style swap
    // (which empties the style of our layers) can put it all back.
    this.sourceData = {};
    this.counties = null;
    this.countyBounds = {};
    this.valleyBounds = null;
    // One controller per request family (see startRequest), and the
    // families seen, so destroy() can cut every one of them short.
    this.gridAbort = null;
    this.noticesAbort = null;
    this.locationsAbort = null;
    this.countiesAbort = null;
    this.outlineAbort = null;
    this.requestNames = [];
    // What the last successful fetch covers, so a pan inside it doesn't
    // refetch (and so doesn't rebuild a layer under an open popup).
    this.loadedBounds = null;
    this.loadedLevel = null;
    this.loadedNoticeBounds = null;
    this.loadedLocationBounds = null;
    this.lensCache = {};
    this.pendingLocate = null;

    this.controlsEl = null;
    this.legendEl = null;
    this.levelEl = null;
    this.statusEl = null;

    this.init();
  }

  // The controls, legend, and level note live beside the map container, so
  // they are re-found (and re-wired) whenever the container gets a new home.
  SectionMap.prototype.attachControls = function () {
    var wrap = this.el.closest('.section-map-wrap') || this.el.parentNode;
    this.wrapEl = wrap;
    // Marks the wrap for the GL-specific styles (control sizes, the legend's
    // clearance of the SDK's logo) while both maps share one stylesheet.
    wrap.classList.add('is-gl');
    this.toolbarEl = wrap.querySelector('.section-map-toolbar');
    this.controlsEl = wrap.querySelector('.section-map-controls');
    this.legendPanelEl = wrap.querySelector('.section-map-legend-panel');
    this.legendEl = wrap.querySelector('.section-map-legend');
    this.levelEl = wrap.querySelector('.section-map-level');
    this.statusEl = this.controlsEl ? this.controlsEl.querySelector('.section-map-status') : null;

    if (this.toolbarEl) this.toolbarEl.hidden = false;
    if (this.legendPanelEl) this.legendPanelEl.hidden = false;

    if (this.controlsEl) {
      var radios = this.controlsEl.querySelectorAll('input[name="metric"]');
      for (var i = 0; i < radios.length; i++) {
        radios[i].checked = radios[i].value === this.metric;
        radios[i].addEventListener('change', this.onMetricChange.bind(this));
      }

      var noticesToggle = this.controlsEl.querySelector('input[name="notices"]');
      if (noticesToggle) {
        noticesToggle.checked = this.showNotices;
        noticesToggle.addEventListener('change', this.onNoticesToggle.bind(this));
      }

      var locationsToggle = this.controlsEl.querySelector('input[name="locations"]');
      if (locationsToggle) {
        locationsToggle.checked = this.showLocations;
        locationsToggle.addEventListener('change', this.onLocationsToggle.bind(this));
      }

      // Experiment controls: basemap style and colour ramp, applied live and
      // written to the URL (?tiles=, ?ramp=) so a combination can be linked.
      var tilesSelect = this.controlsEl.querySelector('select[name="tiles"]');
      if (tilesSelect) {
        TILE_STYLES.forEach(function (style) {
          var option = document.createElement('option');
          option.value = style;
          option.textContent = style;
          tilesSelect.appendChild(option);
        });
        tilesSelect.value = this.tileStyle;
        tilesSelect.addEventListener('change', this.onTilesChange.bind(this));
      }
      var rampSelect = this.controlsEl.querySelector('select[name="ramp"]');
      if (rampSelect) {
        Object.keys(RAMPS).forEach(function (name) {
          var option = document.createElement('option');
          option.value = name;
          option.textContent = name;
          rampSelect.appendChild(option);
        });
        rampSelect.value = rampMatch && RAMPS[rampMatch[1]] ? rampMatch[1] : 'blues';
        rampSelect.addEventListener('change', this.onRampChange.bind(this));
      }
      var binsSelect = this.controlsEl.querySelector('select[name="bins"]');
      if (binsSelect) {
        BIN_OPTIONS.forEach(function (pair) {
          var option = document.createElement('option');
          option.value = pair[0];
          option.textContent = pair[1] + ' (' + pair[0] + ')';
          binsSelect.appendChild(option);
        });
        binsSelect.value = NUM_CLASSES;
        binsSelect.addEventListener('change', this.onBinsChange.bind(this));
      }

      var sectionsToggle = this.controlsEl.querySelector('input[name="sections"]');
      if (sectionsToggle) {
        sectionsToggle.checked = this.showAllSections;
        sectionsToggle.addEventListener('change', this.onSectionsToggle.bind(this));
      }
    }
    var expand = wrap.querySelector('.section-map-expand');
    if (expand && !expand.getAttribute('data-bound')) {
      expand.setAttribute('data-bound', '1');
      expand.addEventListener('click', this.toggleExpanded.bind(this));
    }
    this.bindPanelToggles(wrap);
    this.bindToolbar(wrap);
    this.setExpanded(!!this.expanded);
  };

  // The filter toolbar's dropdowns: a click on a trigger opens its menu
  // (and focuses the picker's search box), a click anywhere else or Escape
  // closes them. The triggers are bound once per toolbar element (a
  // swapped-in toolbar is a new element and gets bound again); the
  // document-level closers are bound once per map and act on whichever
  // toolbar is current, so swaps don't pile up listeners.
  SectionMap.prototype.bindToolbar = function (wrap) {
    var self = this;
    if (!this.toolbarClickHandler) {
      this.toolbarClickHandler = function () { self.closeToolbarDropdowns(null); };
      this.toolbarKeyHandler = function (event) {
        if (event.key === 'Escape') self.closeToolbarDropdowns(null);
      };
      document.addEventListener('click', this.toolbarClickHandler);
      document.addEventListener('keydown', this.toolbarKeyHandler);
    }
    var toolbar = wrap.querySelector('.section-map-toolbar');
    if (!toolbar || toolbar.getAttribute('data-bound')) return;
    toolbar.setAttribute('data-bound', '1');
    var dropdowns = toolbar.querySelectorAll('.dropdown');

    // The filter form only knows its own fields; the map's view settings
    // (metric, notices, all sections) ride along so the URL it lands on
    // still says how the map is being viewed.
    var form = toolbar.querySelector('.section-map-toolbar-filters');
    if (form) {
      form.addEventListener('htmx:configRequest', function (event) {
        var params = event.detail.parameters;
        if (self.metric !== 'lbs_chemical') params.metric = self.metric;
        if (self.showNotices !== (self.data.showNotices !== '0')) params.notices = self.showNotices ? '1' : '0';
        if (self.showLocations !== (self.data.showLocations === '1')) params.locations = self.showLocations ? '1' : '0';
        if (self.showAllSections) params.sections = '1';
      });
    }

    for (var i = 0; i < dropdowns.length; i++) {
      (function (dropdown) {
        var trigger = dropdown.querySelector('.dropdown-trigger .button');
        if (!trigger) return;
        trigger.addEventListener('click', function (event) {
          event.stopPropagation();
          var open = !dropdown.classList.contains('is-active');
          self.closeToolbarDropdowns(dropdown);
          dropdown.classList.toggle('is-active', open);
          trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
          if (open) {
            var focusable = dropdown.querySelector('input[type="search"], select');
            if (focusable) focusable.focus();
          }
        });
        // Clicks inside the menu (typing, picking) shouldn't close it.
        var menu = dropdown.querySelector('.dropdown-menu');
        if (menu) menu.addEventListener('click', function (event) { event.stopPropagation(); });
      })(dropdowns[i]);
    }
  };

  // Closes the current toolbar's dropdowns, all but `except`.
  SectionMap.prototype.closeToolbarDropdowns = function (except) {
    if (!this.toolbarEl) return;
    var dropdowns = this.toolbarEl.querySelectorAll('.dropdown');
    for (var i = 0; i < dropdowns.length; i++) {
      if (dropdowns[i] === except) continue;
      dropdowns[i].classList.remove('is-active');
      var trigger = dropdowns[i].querySelector('.dropdown-trigger .button');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
    }
  };

  // The options and legend panels fold to their header. The fold is a
  // per-viewer convenience kept in localStorage, so it's wrapped: storage
  // can be absent or throw, and the panels must work regardless.
  var PANEL_STORAGE_PREFIX = 'pesticides:section-map:panel:';

  function readPanelState(name) {
    try {
      return window.localStorage.getItem(PANEL_STORAGE_PREFIX + name) === 'collapsed';
    } catch (err) {
      return false;
    }
  }

  function writePanelState(name, collapsed) {
    try {
      window.localStorage.setItem(PANEL_STORAGE_PREFIX + name, collapsed ? 'collapsed' : 'open');
    } catch (err) {
      // Nothing to do: the fold just won't be remembered.
    }
  }

  SectionMap.prototype.bindPanelToggles = function (wrap) {
    var panels = wrap.querySelectorAll('.section-map-panel[data-panel]');
    for (var i = 0; i < panels.length; i++) {
      this.setPanelCollapsed(panels[i], readPanelState(panels[i].getAttribute('data-panel')));
      var toggle = panels[i].querySelector('.section-map-panel-toggle');
      if (!toggle || toggle.getAttribute('data-bound')) continue;
      toggle.setAttribute('data-bound', '1');
      toggle.addEventListener('click', this.onPanelToggle.bind(this, panels[i]));
    }
  };

  SectionMap.prototype.onPanelToggle = function (panel) {
    var collapsed = !panel.classList.contains('is-collapsed');
    this.setPanelCollapsed(panel, collapsed);
    writePanelState(panel.getAttribute('data-panel'), collapsed);
  };

  SectionMap.prototype.setPanelCollapsed = function (panel, collapsed) {
    panel.classList.toggle('is-collapsed', collapsed);
    var toggle = panel.querySelector('.section-map-panel-toggle');
    if (toggle) toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  };

  // The expanded map starts exactly where the navbar ends, measured rather
  // than assumed: the navbar's height varies by a pixel with its contents,
  // and a guess a pixel short shows the hero through the gap.
  SectionMap.prototype.fitBelowNavbar = function () {
    if (!this.wrapEl) return;
    // The wrap carries a 1px border in the navbar's colour and starts 1px
    // above the navbar's measured bottom, so the two borders coincide:
    // whatever fraction of a pixel the navbar ends on, the reader sees one
    // grey line and never a sliver of the page beneath.
    var nav = document.querySelector('nav.navbar');
    var bottom = nav ? nav.getBoundingClientRect().bottom : 0;
    // The explorer's scope bar (year and county pickers) stays in view,
    // pinned under the navbar, so the scope can still be changed; the map
    // starts under it.
    var scopeBar = document.querySelector('.explorer-scope-bar');
    if (scopeBar) {
      scopeBar.style.top = Math.max(0, bottom) + 'px';
      bottom = scopeBar.getBoundingClientRect().bottom;
    }
    this.wrapEl.style.top = Math.max(0, bottom - 1) + 'px';
  };

  // Expanded, the map fills the viewport under the site navbar; the panels
  // over it are what keep it usable there. Escape brings the page back.
  SectionMap.prototype.toggleExpanded = function () {
    this.setExpanded(!this.expanded);
  };

  SectionMap.prototype.setExpanded = function (on) {
    var self = this;
    var was = !!this.expanded;
    this.expanded = on;
    // The site navbar isn't fixed, so the expanded map sits below it only
    // while the page is scrolled to the top: go there on the way in, and
    // come back to where the reader was on the way out.
    if (on && !was) {
      this.scrollBeforeExpand = window.scrollY || window.pageYOffset || 0;
      window.scrollTo(0, 0);
    }
    // The html class first: it pins the scope bar, and fitBelowNavbar
    // measures the pinned bar to place the map under it.
    document.documentElement.classList.toggle('section-map-expanded', on);
    if (this.wrapEl) {
      this.wrapEl.classList.toggle('is-expanded', on);
      if (on) {
        this.fitBelowNavbar();
      } else {
        this.wrapEl.style.top = '';
        var scopeBar = document.querySelector('.explorer-scope-bar');
        if (scopeBar) scopeBar.style.top = '';
      }
    }
    if (!on && was) {
      window.scrollTo(0, this.scrollBeforeExpand || 0);
    }
    if (!this.resizeHandler) {
      this.resizeHandler = function () {
        if (self.expanded) self.fitBelowNavbar();
      };
    }
    window.removeEventListener('resize', this.resizeHandler);
    if (on) window.addEventListener('resize', this.resizeHandler);
    var button = this.wrapEl ? this.wrapEl.querySelector('.section-map-expand') : null;
    if (button) {
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
      button.setAttribute('title', on ? 'Back to the page' : 'Expand the map');
      button.setAttribute('aria-label', on ? 'Back to the page' : 'Expand the map');
    }
    if (!this.escapeHandler) {
      this.escapeHandler = function (event) {
        if (event.key === 'Escape' && self.expanded) self.setExpanded(false);
      };
    }
    document.removeEventListener('keydown', this.escapeHandler);
    if (on) document.addEventListener('keydown', this.escapeHandler);
    // The container changed size. The SDK watches it, but resizing here,
    // once the new layout has applied, means the moveend that follows
    // measures the new size and fills in the wider grid straight away.
    setTimeout(function () { if (self.map) self.map.resize(); }, 0);
  };

  SectionMap.prototype.onSectionsToggle = function (event) {
    this.showAllSections = !!event.target.checked;
    this.syncViewParams();
    if (this.showAllSections) {
      this.clearLens();
      this.loadAllSections();
    } else {
      this.clearAllSections();
    }
  };

  SectionMap.prototype.onNoticesToggle = function (event) {
    this.showNotices = !!event.target.checked;
    this.syncViewParams();
    if (this.showNotices) {
      this.loadNotices();
    } else {
      this.loadedNoticeBounds = null;
      if (this.noticesAbort) this.noticesAbort.abort();
      this.clearNotices();
    }
  };

  SectionMap.prototype.onLocationsToggle = function (event) {
    this.showLocations = !!event.target.checked;
    this.syncViewParams();
    if (this.showLocations) {
      this.loadLocations();
    } else {
      this.loadedLocationBounds = null;
      if (this.locationsAbort) this.locationsAbort.abort();
      this.clearLocations();
    }
    this.updateLocationsNote();
  };

  SectionMap.prototype.init = function () {
    var self = this;
    // ?tiles=<style> swaps the basemap style while we pick one; known before
    // the controls bind so the select shows it.
    var tilesMatch = /[?&]tiles=([a-z0-9-]+)/.exec(window.location.search || '');
    this.defaultTileStyle = this.data.style || 'dataviz';
    this.tileStyle = tilesMatch ? tilesMatch[1] : this.defaultTileStyle;
    this.attachControls();

    var center = this.parseCenter(this.data.center) || [36.75, -119.80];
    var zoom = parseInt(this.data.zoom, 10) || 8;

    maptilersdk.config.apiKey = this.data.maptilerKey || '';
    this.map = new maptilersdk.Map({
      container: this.el,
      style: styleFor(this.tileStyle),
      center: lngLatOf(center),
      zoom: zoom,
      // The zoom buttons are added below, ahead of our own controls; the
      // SDK's other default furniture is either ours (locate) or unwanted.
      navigationControl: false,
      geolocateControl: false,
      terrainControl: false,
      // Wheel-zoom is off by default so the map doesn't hijack page scrolling
      // on long pages; enabled only while the map has focus/is being
      // interacted with directly (see enableScrollZoom).
      scrollZoom: false,
      // Flat and north-up, like the Leaflet map: no pitch, no rotation.
      pitchWithRotate: false,
      dragRotate: false,
      touchPitch: false,
      attributionControl: { compact: true },
    });
    this.map.touchZoomRotate.disableRotation();
    this.map.keyboard.disableRotation();
    // For debugging from the console: document.querySelector('.section-map').sectionMap
    this.el.sectionMap = this;

    this.el.addEventListener('click', this.enableScrollZoom.bind(this));
    this.el.addEventListener('focus', this.enableScrollZoom.bind(this), true);
    this.el.addEventListener('mouseleave', this.disableScrollZoom.bind(this));
    this.el.addEventListener('blur', this.disableScrollZoom.bind(this), true);

    // Our sources and layers are part of the style, so a style swap (the
    // tiles select) starts from a style without them; they're put back from
    // the data kept on this instance whenever a style has loaded, the first
    // time included. Until then setSourceData just keeps the data, and the
    // camera takes fits and moves straight away, so nothing below waits.
    this.map.on('style.load', this.onStyleLoad.bind(this));
    this.map.once('load', function () { self.loaded = true; });

    // Zoom buttons first, then ours under them. The SDK adds its own
    // navigation control after the first render, which would have put it
    // below controls added here; adding it ourselves keeps the Leaflet
    // order, and leaves out the compass, which has nothing to do on a map
    // that can't rotate.
    this.map.addControl(new maptilersdk.NavigationControl({ showCompass: false }), 'top-left');
    this.addLocateControl();
    this.addResetControl();

    this.drawRadius(center);

    var debouncedLoad = debounce(this.loadGrid.bind(this), DEBOUNCE_MS);
    var debouncedNotices = debounce(this.loadNotices.bind(this), DEBOUNCE_MS);
    var debouncedLocations = debounce(this.loadLocations.bind(this), DEBOUNCE_MS);
    // moveend follows every camera change, a zoom included.
    this.map.on('moveend', debouncedLoad);
    this.map.on('moveend', debouncedNotices);
    this.map.on('moveend', debouncedLocations);
    this.map.on('zoomend', this.restyleCounties.bind(this));
    // Section strokes switch on/off across SECTION_LINES_MIN_ZOOM.
    this.map.on('zoomend', this.restyleSectionLines.bind(this));

    this.loadCounties();
    this.loadOutline();
    this.loadGrid();
    this.loadNotices();
    this.loadLocations();
  };

  SectionMap.prototype.onStyleLoad = function () {
    this.addBaseLayers();
  };

  // -- sources and layers --
  // Every data layer goes in below the basemap's first symbol layer, so the
  // place labels read over the choropleth. Serialises the style, so
  // addBaseLayers asks once and passes the answer to each ensureLayer.
  SectionMap.prototype.beforeLabels = function () {
    var layers = (this.map.getStyle() || {}).layers || [];
    for (var i = 0; i < layers.length; i++) {
      if (layers[i].type === 'symbol') return layers[i].id;
    }
    return undefined;
  };

  // GeoJSON sources are keyed on our own feature ids (`promoteId`), so
  // feature state (hover, selection) can address them by id.
  SectionMap.prototype.ensureSource = function (id) {
    if (this.map.getSource(id)) return;
    this.map.addSource(id, { type: 'geojson', data: this.sourceData[id] || EMPTY, promoteId: 'id' });
  };

  // `before` is the label layer id from beforeLabels(), asked for once by
  // the caller and passed to every layer it adds.
  SectionMap.prototype.ensureLayer = function (spec, before) {
    if (this.map.getLayer(spec.id)) return;
    this.map.addLayer(spec, before);
  };

  // Sets a source's data, remembering it for the next style load; before
  // the style is up the data just waits there for ensureSource. Nothing
  // to keep once the map is gone (a late response after destroy()).
  SectionMap.prototype.setSourceData = function (id, data) {
    if (!this.map) return;
    this.sourceData[id] = data;
    var source = this.map.getSource(id);
    if (source) source.setData(data);
  };

  // Our sources and their layers, bottom to top: the radius circle, [the
  // grid and the lens go here], the county lines, the page's own outline,
  // [locations and notices go here, under the located position], and last
  // the reader's located position (`locate`/`locate-circle`), which stays
  // on top of every marker. Idempotent, so it can run on every style load.
  SectionMap.prototype.addBaseLayers = function () {
    var before = this.beforeLabels();
    this.ensureSource('radius');
    this.ensureSource('counties');
    this.ensureSource('outline');
    this.ensureSource('locate');

    this.ensureLayer({
      id: 'radius-fill', type: 'fill', source: 'radius',
      paint: { 'fill-color': RADIUS_COLOR, 'fill-opacity': 0.2 },
    }, before);
    this.ensureLayer({
      id: 'radius-line', type: 'line', source: 'radius',
      paint: { 'line-color': RADIUS_COLOR, 'line-width': 3 },
    }, before);
    this.ensureLayer({
      id: 'counties-line', type: 'line', source: 'counties',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': COUNTY_COLOR, 'line-width': 1.5, 'line-opacity': 0.8 },
    }, before);
    // The region this page is about, shaded faintly and outlined.
    this.ensureLayer({
      id: 'outline-fill', type: 'fill', source: 'outline',
      paint: { 'fill-color': OUTLINE_COLOR, 'fill-opacity': 0.08 },
    }, before);
    this.ensureLayer({
      id: 'outline-line', type: 'line', source: 'outline',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': OUTLINE_COLOR, 'line-width': 2.5, 'line-opacity': 0.9 },
    }, before);
    this.ensureLayer({
      id: 'locate-circle', type: 'circle', source: 'locate',
      paint: {
        'circle-radius': 6,
        'circle-color': LOCATE_COLOR,
        'circle-stroke-color': '#fff',
        'circle-stroke-width': 2,
      },
    }, before);
    this.restyleCounties();
  };

  // A locate button under the zoom buttons: zooms to the reader's square
  // mile and selects it (popup and outline), with a dot at their position.
  SectionMap.prototype.addLocateControl = function () {
    if (!navigator.geolocation) return;
    var self = this;
    this.locateControl = new BarControl('section-map-locate', 'Zoom to my location', 'fa-regular fa-location-crosshairs', function () {
      self.locate();
    });
    this.map.addControl(this.locateControl, 'top-left');
    this.locateEl = this.locateControl.container;
  };

  // A reset button under the locate button: back out to the map's home
  // framing (the whole valley, or the filtered county).
  SectionMap.prototype.addResetControl = function () {
    var self = this;
    this.resetControl = new BarControl('section-map-reset', 'Zoom out to the whole map', 'fa-regular fa-house', function () {
      self.resetView();
    });
    this.map.addControl(this.resetControl, 'top-left');
  };

  SectionMap.prototype.resetView = function () {
    var bounds = this.countyBounds[this.data.county] || this.valleyBounds;
    if (bounds) {
      this.map.fitBounds(bounds, { padding: 20, animate: !this.reducedMotion });
    } else {
      this.map.easeTo({
        center: lngLatOf(this.parseCenter(this.data.center) || [36.75, -119.80]),
        zoom: parseInt(this.data.zoom, 10) || 8,
        animate: !this.reducedMotion,
      });
    }
  };

  SectionMap.prototype.locate = function () {
    var self = this;
    if (this.locateEl) this.locateEl.classList.add('is-locating');
    this.setStatus('Finding your location…');
    navigator.geolocation.getCurrentPosition(function (position) {
      self.showLocation([position.coords.latitude, position.coords.longitude]);
    }, function () {
      if (self.locateEl) self.locateEl.classList.remove('is-locating');
      self.setStatus('Couldn\'t get your location');
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  };

  SectionMap.prototype.showLocation = function (latlng) {
    if (this.locateEl) this.locateEl.classList.remove('is-locating');
    this.setStatus('');
    this.setSourceData('locate', {
      type: 'Feature',
      properties: { id: 'me' },
      geometry: { type: 'Point', coordinates: lngLatOf(latlng) },
    });
    // Selecting the section has to wait for the section grid to be on the
    // map at this spot; the grid's render calls resolvePendingLocate when it is.
    this.pendingLocate = latlng;
    this.map.easeTo({ center: lngLatOf(latlng), zoom: this.sectionZoom(), animate: !this.reducedMotion });
    this.resolvePendingLocate();
  };

  SectionMap.prototype.drawRadius = function (center) {
    var radiusMiles = parseFloat(this.data.radius);
    if (!(radiusMiles > 0)) {
      this.setSourceData('radius', EMPTY);
      return;
    }
    var circle = circlePolygon(lngLatOf(center), milesToMeters(radiusMiles), 'radius');
    this.setSourceData('radius', circle);
    this.map.fitBounds(geometryBounds(circle), { animate: !this.reducedMotion });
  };

  // Keys whose change means the data on the map is different.
  var DATA_KEYS = ['year', 'chemical', 'product', 'commodity', 'county', 'concern'];

  // Take over a freshly rendered container (an htmx swap put a new page in
  // place): move this live map into its slot, read its data attributes, and
  // refetch only what changed. Keeping the map instance avoids the flash of
  // tearing the map down and reloading its basemap on every filter change.
  SectionMap.prototype.adopt = function (newEl) {
    var oldData = {};
    var key;
    for (key in this.el.dataset) oldData[key] = this.el.dataset[key];
    var newData = {};
    for (key in newEl.dataset) newData[key] = newEl.dataset[key];

    newEl.parentNode.replaceChild(this.el, newEl);
    for (key in oldData) {
      if (!(key in newData) && key !== 'rendered') delete this.el.dataset[key];
    }
    for (key in newData) this.el.dataset[key] = newData[key];
    this.el.dataset.rendered = '1';
    this.el.id = newEl.id;

    // A swap to a different page brings its own notices default with it;
    // adopt it so the checkbox and the layer agree with the page the reader
    // is now on. An unchanged attribute leaves their own toggle alone.
    var noticesDefaultChanged = (oldData.showNotices || '') !== (newData.showNotices || '');
    if (noticesDefaultChanged) {
      this.showNotices = newData.showNotices !== '0';
      this.loadedNoticeBounds = null;
      if (!this.showNotices) {
        // A request already in flight would otherwise land after the swap
        // and put the markers back on a page that doesn't want them.
        if (this.noticesAbort) this.noticesAbort.abort();
        this.clearNotices();
      }
    }

    var locationsDefaultChanged = (oldData.showLocations || '') !== (newData.showLocations || '');
    if (locationsDefaultChanged) {
      this.showLocations = newData.showLocations === '1';
      this.loadedLocationBounds = null;
      if (!this.showLocations) {
        if (this.locationsAbort) this.locationsAbort.abort();
        this.clearLocations();
      }
    }

    this.attachControls();
    this.map.resize();

    var dataChanged = DATA_KEYS.some(function (k) { return (oldData[k] || '') !== (newData[k] || ''); });
    var countyChanged = (oldData.county || '') !== (newData.county || '');
    var viewChanged = (oldData.center || '') !== (newData.center || '') || (oldData.zoom || '') !== (newData.zoom || '');
    var radiusChanged = (oldData.radius || '') !== (newData.radius || '');
    var outlineChanged = (oldData.outlineUrl || '') !== (newData.outlineUrl || '');

    if (outlineChanged) {
      this.clearOutline();
      this.loadOutline();
    }

    var center = this.parseCenter(this.data.center) || [36.75, -119.80];
    if (radiusChanged) {
      this.drawRadius(center);
    } else if (viewChanged) {
      this.map.easeTo({ center: lngLatOf(center), zoom: parseInt(this.data.zoom, 10) || 8, animate: !this.reducedMotion });
    }

    if (countyChanged) this.fitCounty();
    if (dataChanged) {
      this.loadedBounds = null;
      this.loadedNoticeBounds = null;
      // The cached lens/all-sections tiles were fetched under the old
      // filters; a fresh cache means in-flight fetches land in the old one
      // (fetchLensSections writes to the cache it started with) and any
      // all-sections run in progress stops scheduling work.
      this.lensCache = {};
      this.allSectionsRun = null;
      this.loadGrid();
      this.loadNotices();
      // The markers themselves don't change with the filters, but the block
      // totals in their popups do, so the layer is rebuilt either way.
      this.loadedLocationBounds = null;
      this.loadLocations();
    } else {
      if (noticesDefaultChanged && this.showNotices) this.loadNotices();
      if (locationsDefaultChanged && this.showLocations) this.loadLocations();
      // Same data; the legend/level notes are new elements and need filling.
      this.updateLegend();
      this.restyle();
    }
    this.updateLocationsNote();
  };

  // Releases the map (its WebGL context with it) once its page is gone:
  // requests in flight are cut short so nothing lands on a map that isn't
  // there, and the document-level listeners go with it.
  SectionMap.prototype.destroy = function () {
    this.abortRequests();
    if (this.resizeHandler) window.removeEventListener('resize', this.resizeHandler);
    if (this.escapeHandler) document.removeEventListener('keydown', this.escapeHandler);
    if (this.toolbarClickHandler) document.removeEventListener('click', this.toolbarClickHandler);
    if (this.toolbarKeyHandler) document.removeEventListener('keydown', this.toolbarKeyHandler);
    this.map.remove();
    this.map = null;
  };

  // County outlines never change with the filters, so they're fetched once.
  // Their bounds are what the reset button and the valley fit frame.
  SectionMap.prototype.loadCounties = function () {
    if (!this.data.countiesUrl) return;
    var self = this;
    var abort = this.startRequest('counties');
    fetchJson(this.data.countiesUrl, null, abort)
      .then(function (geojson) {
        if (self.countiesAbort !== abort) return;
        self.counties = geojson;
        self.countyBounds = {};
        self.valleyBounds = null;
        (geojson.features || []).forEach(function (feature) {
          var bounds = geometryBounds(feature);
          if (!bounds) return;
          var slug = feature.properties && feature.properties.slug;
          if (slug) self.countyBounds[slug] = bounds;
          self.valleyBounds = unionBounds(self.valleyBounds, bounds);
        });
        self.setSourceData('counties', geojson);
        self.fitCounty();
      })
      .catch(function (err) {
        if (isAbort(err) || self.countiesAbort !== abort) return;
        logError('failed to load counties', err);
      });
  };

  // With a county filter the map shows that county alone (the grid
  // endpoints leave the others out), so it also frames it: fit to the
  // county's outline, or back out to the whole valley when the filter goes.
  SectionMap.prototype.fitCounty = function () {
    if (!this.map || !this.counties) return;
    var target = this.countyBounds[this.data.county] || null;
    if (target) {
      this.map.fitBounds(target, { padding: 20, animate: !this.reducedMotion });
    } else if (this.data.fit === 'valley' && this.valleyBounds && (this.countyFitted || !this.valleyFitted)) {
      // Back out to the valley after a county filter, or frame it on first
      // load -- only on pages framed on the valley. A place or section page
      // frames itself (adopt() sets its view), and clearing the county
      // there must not zoom back out over it. The first-load fit snaps
      // rather than animating out from the placeholder view.
      var animate = !!this.valleyFitted && !this.reducedMotion;
      this.map.fitBounds(this.valleyBounds, { padding: 20, animate: animate });
      this.valleyFitted = true;
    }
    this.countyFitted = !!target;
  };

  // Draws the region this page is about (from the regions API) and fits the
  // map to it, so a city or ZIP page opens on the whole area, shaded.
  SectionMap.prototype.loadOutline = function () {
    if (!this.data.outlineUrl) return;
    var self = this;
    var abort = this.startRequest('outline');
    fetchJson(this.data.outlineUrl, null, abort)
      .then(function (payload) {
        if (self.outlineAbort !== abort) return;
        var region = payload && payload.data;
        var geometry = region && region.boundary && region.boundary.geometry;
        if (!geometry) return;
        var feature = { type: 'Feature', properties: { id: 'outline' }, geometry: geometry };
        self.setSourceData('outline', feature);
        self.map.fitBounds(geometryBounds(feature), { padding: 24, animate: !self.reducedMotion });
      })
      .catch(function (err) {
        if (isAbort(err) || self.outlineAbort !== abort) return;
        logError('failed to load the region outline', err);
      });
  };

  SectionMap.prototype.clearOutline = function () {
    this.setSourceData('outline', EMPTY);
  };

  // Dashed once the section grid is on, so the two don't compete.
  SectionMap.prototype.restyleCounties = function () {
    if (!this.map.getLayer('counties-line')) return;
    this.map.setPaintProperty('counties-line', 'line-dasharray', this.atSectionZoom() ? COUNTY_DASH : null);
  };

  SectionMap.prototype.enableScrollZoom = function () {
    this.map.scrollZoom.enable();
  };

  SectionMap.prototype.disableScrollZoom = function () {
    this.map.scrollZoom.disable();
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
    this.syncViewParams();
  };

  // The basemap style is part of the map's style, so swapping it rebuilds
  // the style outright (no diff, which would drop our layers without the
  // style.load that puts them back).
  SectionMap.prototype.onTilesChange = function (event) {
    this.tileStyle = event.target.value;
    this.map.setStyle(styleFor(this.tileStyle), { diff: false });
    this.syncViewParams();
  };

  SectionMap.prototype.onRampChange = function (event) {
    var name = event.target.value;
    if (!RAMPS[name]) return;
    RAMP = RAMPS[name];
    this.rampName = name;
    this.restyle();
    this.clearLens();
    this.syncViewParams();
  };

  SectionMap.prototype.onBinsChange = function (event) {
    NUM_CLASSES = +event.target.value;
    this.bins = NUM_CLASSES;
    this.restyle();
    this.clearLens();
    this.syncViewParams();
  };

  // Keep ?metric= and ?notices= in the address bar in step with the controls
  // so the current view can be linked to. Each is left off the URL while it
  // matches the page's default.
  SectionMap.prototype.syncViewParams = function () {
    if (!window.history || !window.history.replaceState || !window.URL) return;
    try {
      var url = new URL(window.location.href);
      if (this.metric === 'lbs_chemical') {
        url.searchParams.delete('metric');
      } else {
        url.searchParams.set('metric', this.metric);
      }
      var noticesDefault = this.data.showNotices !== '0';
      if (this.showNotices === noticesDefault) {
        url.searchParams.delete('notices');
      } else {
        url.searchParams.set('notices', this.showNotices ? '1' : '0');
      }
      var locationsDefault = this.data.showLocations === '1';
      if (this.showLocations === locationsDefault) {
        url.searchParams.delete('locations');
      } else {
        url.searchParams.set('locations', this.showLocations ? '1' : '0');
      }
      if (this.showAllSections) {
        url.searchParams.set('sections', '1');
      } else {
        url.searchParams.delete('sections');
      }
      // The experiment controls (basemap style, ramp) while a look is chosen.
      if (this.tileStyle && this.tileStyle !== this.defaultTileStyle) {
        url.searchParams.set('tiles', this.tileStyle);
      } else {
        url.searchParams.delete('tiles');
      }
      if (this.rampName && this.rampName !== 'blues') {
        url.searchParams.set('ramp', this.rampName);
      } else if (this.rampName) {
        url.searchParams.delete('ramp');
      }
      if (this.bins && this.bins !== DEFAULT_BINS) {
        url.searchParams.set('bins', this.bins);
      } else if (this.bins) {
        url.searchParams.delete('bins');
      }
      window.history.replaceState(window.history.state, '', url.toString());
    } catch (err) {
      // A malformed location is nothing to break the map over.
    }
  };

  SectionMap.prototype.commonParams = function () {
    return {
      year: this.data.year,
      chemical: this.data.chemical,
      product: this.data.product,
      commodity: this.data.commodity,
      county: this.data.county,
      concern: this.data.concern,
    };
  };

  // Aborts the request in flight under `name` (if any) and starts the
  // controller for the next one; the caller keeps the returned controller
  // to check it is still current when its response lands. One name covers
  // both grid levels: a pending section request is stale the moment we
  // decide to draw townships, and vice versa.
  SectionMap.prototype.startRequest = function (name) {
    var key = name + 'Abort';
    if (this[key]) this[key].abort();
    if (this.requestNames.indexOf(name) === -1) this.requestNames.push(name);
    var abort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    this[key] = abort;
    return abort;
  };

  // Cuts short every request in flight, whatever family it belongs to.
  SectionMap.prototype.abortRequests = function () {
    for (var i = 0; i < this.requestNames.length; i++) {
      var abort = this[this.requestNames[i] + 'Abort'];
      if (abort) abort.abort();
    }
  };

  // The zoom at which this viewport can show sections: SECTION_ZOOM, or
  // closer when the map is wide enough that zoom 11 would put more sections
  // in view than one request can return. Web Mercator: metres per pixel at
  // zoom z is 156543 * cos(lat) / 2^z.
  SectionMap.prototype.sectionZoom = function () {
    var canvas = this.map.getCanvas();
    var width = canvas.clientWidth;
    var height = canvas.clientHeight;
    var lat = this.map.getCenter().lat * Math.PI / 180;
    for (var zoom = SECTION_ZOOM; zoom < 18; zoom++) {
      var milesPerPx = 156543.03 * Math.cos(lat) / Math.pow(2, zoom) / METERS_PER_MILE;
      var squareMiles = width * height * milesPerPx * milesPerPx;
      if (squareMiles <= MAX_VIEWPORT_SECTIONS) return zoom;
    }
    return 18;
  };

  SectionMap.prototype.atSectionZoom = function () {
    return this.map.getZoom() >= this.sectionZoom();
  };

  // -- not yet ported --
  // The grid, its classing and legend, the lens, the notice and location
  // layers, and the popups are still to come; the lifecycle above already
  // calls into them, so each is a no-op until its port lands.
  SectionMap.prototype.loadGrid = function () {};
  SectionMap.prototype.restyle = function () {};
  SectionMap.prototype.restyleSectionLines = function () {};
  SectionMap.prototype.updateLegend = function () {};
  SectionMap.prototype.resolvePendingLocate = function () {};
  SectionMap.prototype.clearLens = function () {};
  SectionMap.prototype.loadAllSections = function () {};
  SectionMap.prototype.clearAllSections = function () {};
  SectionMap.prototype.loadNotices = function () {};
  SectionMap.prototype.clearNotices = function () {};
  SectionMap.prototype.loadLocations = function () {};
  SectionMap.prototype.clearLocations = function () {};
  SectionMap.prototype.updateLocationsNote = function () {};

  // Collect the `.section-map` containers marked for this map at or under
  // `root`. `root` may be a document or an element (htmx hands us the element
  // it just swapped in, and that element can itself be a container).
  function containersUnder(root) {
    var found = [];
    if (root.matches && root.matches('.section-map')) found.push(root);
    var nested = root.querySelectorAll ? root.querySelectorAll('.section-map') : [];
    for (var i = 0; i < nested.length; i++) found.push(nested[i]);
    return found.filter(function (el) { return !!el.dataset.gl; });
  }

  // Idempotent: containers already initialised carry `data-rendered`, so this
  // is safe to call repeatedly (page load plus every htmx swap).
  // The one live map on the page, so a swap can hand its container over
  // rather than building a second map.
  var liveMap = null;

  function init(root) {
    if (typeof maptilersdk === 'undefined') return;
    var containers = containersUnder(root || document);
    // A swap to a page without a map drops the live one: undo the page-level
    // expanded state (html class, pinned scope bar), since no map remains to
    // do it, and release the map. Judged against the whole document, not
    // `root`: a swap fires htmx:load per swapped element, and the one for an
    // out-of-band fragment must not take the map from the page that has it.
    if (liveMap && !document.body.contains(liveMap.el) && !containersUnder(document).length) {
      if (liveMap.expanded) liveMap.setExpanded(false);
      liveMap.destroy();
      liveMap = null;
    }
    for (var i = 0; i < containers.length; i++) {
      var el = containers[i];
      if (el.dataset.rendered) continue;
      try {
        if (!webglAvailable()) {
          el.dataset.rendered = '1';
          showUnavailable(el);
          continue;
        }
        if (liveMap && !document.body.contains(liveMap.el)) {
          liveMap.adopt(el);
          continue;
        }
        el.dataset.rendered = '1';
        liveMap = new SectionMap(el);
      } catch (err) {
        logError('failed to initialize', err);
      }
    }
  }

  window.PesticidesSectionMapGL = {
    init: init,
    instances: function () { return liveMap ? [liveMap] : []; },
  };

  function initDocument() {
    init(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDocument);
  } else {
    initDocument();
  }
})();
