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
  // It's a floor: a wide viewport needs to be closer still, or the sections
  // in view would exceed what the endpoint returns (see sectionZoom()).
  var SECTION_ZOOM = 11;
  // The most sections a viewport should ask for at once, under the API's
  // 2,500 cap with room for the padded bbox fetch to fall back unpadded.
  var MAX_VIEWPORT_SECTIONS = 2000;
  var METERS_PER_MILE = 1609.34;
  // A full 6x6 mile township in degrees around 36°N, for the lens reach.
  var TOWNSHIP_DEGREES = { lat: 0.087, lng: 0.108 };
  var DEBOUNCE_MS = 300;
  // How long the cursor must rest on an uncached township before its lens
  // block is fetched; cached blocks draw immediately.
  var LENS_FETCH_DELAY_MS = 50;
  // "All sections" mode: how many section blocks load at once.
  var ALL_SECTIONS_CONCURRENCY = 4;
  // ...and how often the growing layer is redrawn while they land.
  var ALL_SECTIONS_REDRAW_MS = 600;
  // Candidate ramps, selectable with ?ramp=<name> while we pick one.
  var RAMPS = {
    blues: ['#deebf7', '#9ecae1', '#6baed6', '#3182bd', '#08519c'],
    purd: ['#f1eef6', '#d7b5d8', '#df65b0', '#dd1c77', '#980043'],
    bupu: ['#edf8fb', '#b3cde3', '#8c96c6', '#8856a7', '#810f7c'],
    ylorbr: ['#ffffd4', '#fed98e', '#fe9929', '#d95f0e', '#993404'],
  };
  var rampMatch = /[?&]ramp=([a-z]+)/.exec(window.location.search || '');
  var RAMP = RAMPS[rampMatch && rampMatch[1]] || RAMPS.blues;
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
    allSections: 'Each square is one square-mile section, across every township in view.',
  };

  var COUNTY_COLOR = '#1f2d3d';
  // The base grid: present, but barely, so the fills read as a surface.
  var GRID_LINE = { color: '#1f2d3d', opacity: 0.18 };
  // The section whose popup is open keeps a modest outline until it closes.
  var SELECTED_LINE = { stroke: true, color: '#1f2d3d', opacity: 0.9, weight: 1.5 };

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
    // ?metric=applications and ?notices=1|0 preselect a view, so a link can
    // share it; the toggles write them back (see syncViewParams).
    var metricMatch = /[?&]metric=(lbs_chemical|applications)/.exec(window.location.search || '');
    this.metric = metricMatch ? metricMatch[1] : 'lbs_chemical';
    // Notice markers are on by default only where notices are the subject of
    // the page; `data-show-notices` says which this is, a ?notices= param
    // overrides it, and the "Show notices" checkbox flips it from there.
    var noticesMatch = /[?&]notices=([01])/.exec(window.location.search || '');
    this.showNotices = noticesMatch ? noticesMatch[1] === '1' : this.data.showNotices !== '0';
    // "All sections": at the township zoom, draw every section in view
    // instead of the township grid (loaded in blocks, see loadAllSections).
    this.showAllSections = /[?&]sections=1/.test(window.location.search || '');
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

  // The controls, legend, and level note live beside the map container, so
  // they are re-found (and re-wired) whenever the container gets a new home.
  SectionMap.prototype.attachControls = function () {
    var wrap = this.el.closest('.section-map-wrap') || this.el.parentNode;
    this.wrapEl = wrap;
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
  // closes them. Bound once per toolbar element; a swapped-in toolbar is
  // a new element and gets bound again.
  SectionMap.prototype.bindToolbar = function (wrap) {
    var toolbar = wrap.querySelector('.section-map-toolbar');
    if (!toolbar || toolbar.getAttribute('data-bound')) return;
    toolbar.setAttribute('data-bound', '1');
    var dropdowns = toolbar.querySelectorAll('.dropdown');

    var closeAll = function (except) {
      for (var i = 0; i < dropdowns.length; i++) {
        if (dropdowns[i] === except) continue;
        dropdowns[i].classList.remove('is-active');
        var trigger = dropdowns[i].querySelector('.dropdown-trigger .button');
        if (trigger) trigger.setAttribute('aria-expanded', 'false');
      }
    };

    for (var i = 0; i < dropdowns.length; i++) {
      (function (dropdown) {
        var trigger = dropdown.querySelector('.dropdown-trigger .button');
        if (!trigger) return;
        trigger.addEventListener('click', function (event) {
          event.stopPropagation();
          var open = !dropdown.classList.contains('is-active');
          closeAll(dropdown);
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

    document.addEventListener('click', function () { closeAll(null); });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') closeAll(null);
    });
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
    if (this.wrapEl) {
      this.wrapEl.classList.toggle('is-expanded', on);
      if (on) {
        this.fitBelowNavbar();
      } else {
        this.wrapEl.style.top = '';
      }
    }
    document.documentElement.classList.toggle('section-map-expanded', on);
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
    // The container changed size; Leaflet needs telling once the new
    // layout has applied, and its moveend then fills in the wider grid.
    setTimeout(function () { self.map.invalidateSize(); }, 0);
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

  SectionMap.prototype.init = function () {
    this.attachControls();

    var center = this.parseCenter(this.data.center) || [36.75, -119.80];
    var zoom = parseInt(this.data.zoom, 10) || 8;

    // A popup stays until its close button or another cell is clicked;
    // clicking empty map (or a pan that ends on it) doesn't dismiss it.
    this.map = L.map(this.el, { zoomControl: true, scrollWheelZoom: false, closePopupOnClick: false });
    // For debugging from the console: document.querySelector('.section-map').sectionMap
    this.el.sectionMap = this;

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

    // The lens (the section grid drawn under a hovered township and its
    // neighbours) sits just above the township fills and below the county
    // lines.
    var lensPane = this.map.createPane('pesticide-lens');
    lensPane.style.zIndex = 410;
    // The hovered township's outline is redrawn on top of the lens, since
    // the lens sections would otherwise paint over its border.
    var lensOutlinePane = this.map.createPane('pesticide-lens-outline');
    lensOutlinePane.style.zIndex = 415;
    lensOutlinePane.style.pointerEvents = 'none';
    this.lensCache = {};

    this.drawRadius(center);

    var debouncedLoad = debounce(this.loadGrid.bind(this), DEBOUNCE_MS);
    var debouncedNotices = debounce(this.loadNotices.bind(this), DEBOUNCE_MS);
    this.map.on('moveend zoomend', debouncedLoad);
    this.map.on('moveend zoomend', debouncedNotices);
    this.map.on('zoomend', this.restyleCounties.bind(this));
    this.bindZoomButtons();

    this.addLocateControl();

    this.loadCounties();
    this.loadOutline();
    this.loadGrid();
    this.loadNotices();
  };

  // A locate button under the zoom buttons: zooms to the reader's square
  // mile and selects it (popup and outline), with a dot at their position.
  SectionMap.prototype.addLocateControl = function () {
    if (!navigator.geolocation) return;
    var self = this;
    var Locate = L.Control.extend({
      options: { position: 'topleft' },
      onAdd: function () {
        var container = L.DomUtil.create('div', 'leaflet-bar leaflet-control section-map-locate');
        var link = L.DomUtil.create('a', '', container);
        link.href = '#';
        link.setAttribute('role', 'button');
        link.setAttribute('title', 'Zoom to my location');
        link.setAttribute('aria-label', 'Zoom to my location');
        link.innerHTML = '<span class="fa-regular fa-location-crosshairs" aria-hidden="true"></span>';
        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.on(link, 'click', L.DomEvent.preventDefault);
        L.DomEvent.on(link, 'click', function () { self.locate(); });
        self.locateEl = container;
        return container;
      },
    });
    this.map.addControl(new Locate());
  };

  SectionMap.prototype.locate = function () {
    var self = this;
    if (this.locateEl) this.locateEl.classList.add('is-locating');
    this.setStatus('Finding your location…');
    navigator.geolocation.getCurrentPosition(function (position) {
      var latlng = L.latLng(position.coords.latitude, position.coords.longitude);
      self.showLocation(latlng);
    }, function () {
      if (self.locateEl) self.locateEl.classList.remove('is-locating');
      self.setStatus('Couldn\'t get your location');
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  };

  SectionMap.prototype.showLocation = function (latlng) {
    if (this.locateEl) this.locateEl.classList.remove('is-locating');
    this.setStatus('');
    if (this.locationMarker) this.map.removeLayer(this.locationMarker);
    this.locationMarker = L.circleMarker(latlng, {
      pane: 'pesticide-notices',
      radius: 6,
      color: '#fff',
      weight: 2,
      fillColor: '#3273dc',
      fillOpacity: 1,
      interactive: false,
    }).addTo(this.map);
    // Selecting the section has to wait for the section grid to be on the
    // map at this spot; renderGrid calls resolvePendingLocate when it is.
    this.pendingLocate = latlng;
    this.map.setView(latlng, this.sectionZoom(), { animate: !this.reducedMotion });
    this.resolvePendingLocate();
  };

  SectionMap.prototype.resolvePendingLocate = function () {
    var latlng = this.pendingLocate;
    if (!latlng || this.level !== 'section' || !this.gridLayer) return;
    if (!this.map.getBounds().contains(latlng)) return;
    var hit = null;
    this.gridLayer.eachLayer(function (layer) {
      if (!hit && layer.feature && layer.getBounds && layer.getBounds().contains(latlng)) hit = layer;
    });
    if (!hit) {
      // Grid loaded but nothing under the point (outside the valley's
      // sections): nothing to select, and nothing more to wait for.
      if (this.loadedBounds && this.loadedBounds.contains(latlng)) this.pendingLocate = null;
      return;
    }
    this.pendingLocate = null;
    this.showSectionPopup(hit.feature, hit);
  };

  SectionMap.prototype.drawRadius = function (center) {
    if (this.radiusCircle) {
      this.map.removeLayer(this.radiusCircle);
      this.radiusCircle = null;
    }
    var radiusMiles = parseFloat(this.data.radius);
    if (!(radiusMiles > 0)) return;
    this.radiusCircle = L.circle(center, { radius: milesToMeters(radiusMiles), interactive: false }).addTo(this.map);
    this.map.fitBounds(this.radiusCircle.getBounds(), { animate: !this.reducedMotion });
  };

  // Keys whose change means the data on the map is different.
  var DATA_KEYS = ['year', 'chemical', 'product', 'commodity', 'county'];

  // Take over a freshly rendered container (an htmx swap put a new page in
  // place): move this live map into its slot, read its data attributes, and
  // refetch only what changed. Keeping the Leaflet instance avoids the grey
  // flash of tearing the map down and reloading its tiles on every filter
  // change.
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
      if (!this.showNotices) this.clearNotices();
    }

    this.attachControls();
    this.map.invalidateSize();

    var dataChanged = DATA_KEYS.some(function (k) { return (oldData[k] || '') !== (newData[k] || ''); });
    var countyChanged = (oldData.county || '') !== (newData.county || '');
    var viewChanged = (oldData.center || '') !== (newData.center || '') || (oldData.zoom || '') !== (newData.zoom || '');
    var radiusChanged = (oldData.radius || '') !== (newData.radius || '');
    var outlineChanged = (oldData.outlineUrl || '') !== (newData.outlineUrl || '');

    if (outlineChanged) {
      if (this.outlineLayer) {
        this.map.removeLayer(this.outlineLayer);
        this.outlineLayer = null;
      }
      this.loadOutline();
    }

    var center = this.parseCenter(this.data.center) || [36.75, -119.80];
    if (radiusChanged) {
      this.drawRadius(center);
    } else if (viewChanged) {
      this.map.setView(center, parseInt(this.data.zoom, 10) || 8, { animate: !this.reducedMotion });
    }

    if (countyChanged) this.fitCounty();
    if (dataChanged) {
      this.loadedBounds = null;
      this.loadedNoticeBounds = null;
      this.loadGrid();
      this.loadNotices();
    } else {
      if (noticesDefaultChanged && this.showNotices) this.loadNotices();
      // Same data; the legend/level notes are new elements and need filling.
      this.updateLegend();
      this.restyle();
    }
  };

  SectionMap.prototype.countyStyle = function () {
    return {
      color: COUNTY_COLOR,
      weight: 1.5,
      fill: false,
      opacity: 0.8,
      // Dashed once the section grid is on, so the two don't compete.
      dashArray: this.atSectionZoom() ? '4 3' : null,
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
        self.fitCounty();
      })
      .catch(function (err) {
        window.console && console.error && console.error('section-map: failed to load counties', err);
      });
  };

  // With a county filter the map shows that county alone (the grid
  // endpoints leave the others out), so it also frames it: fit to the
  // county's outline, or back out to the whole valley when the filter goes.
  SectionMap.prototype.fitCounty = function () {
    if (!this.countiesLayer) return;
    var slug = this.data.county;
    var target = null;
    this.countiesLayer.eachLayer(function (layer) {
      if (layer.feature && layer.feature.properties.slug === slug) target = layer;
    });
    if (target) {
      this.map.fitBounds(target.getBounds(), { padding: [20, 20], animate: !this.reducedMotion });
    } else if (this.countyFitted) {
      this.map.fitBounds(this.countiesLayer.getBounds(), { padding: [20, 20], animate: !this.reducedMotion });
    }
    this.countyFitted = !!target;
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
      if (this.showAllSections) {
        url.searchParams.set('sections', '1');
      } else {
        url.searchParams.delete('sections');
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
    };
  };

  // Picks the grid for the current zoom: sections up close, townships further
  // out. Either way exactly one grid layer is on the map.
  // The zoom at which this viewport can show sections: SECTION_ZOOM, or
  // closer when the map is wide enough that zoom 11 would put more sections
  // in view than one request can return. Web Mercator: metres per pixel at
  // zoom z is 156543 * cos(lat) / 2^z.
  SectionMap.prototype.sectionZoom = function () {
    var size = this.map.getSize();
    var lat = this.map.getCenter().lat * Math.PI / 180;
    for (var zoom = SECTION_ZOOM; zoom < 18; zoom++) {
      var milesPerPx = 156543.03 * Math.cos(lat) / Math.pow(2, zoom) / METERS_PER_MILE;
      var squareMiles = size.x * size.y * milesPerPx * milesPerPx;
      if (squareMiles <= MAX_VIEWPORT_SECTIONS) return zoom;
    }
    return 18;
  };

  SectionMap.prototype.atSectionZoom = function () {
    return this.map.getZoom() >= this.sectionZoom();
  };

  SectionMap.prototype.loadGrid = function () {
    var level = this.atSectionZoom() ? 'section' : 'township';
    // Crossing into section zoom with "all sections" on: stop loading more
    // blocks, but leave the layer up until the section grid replaces it
    // (renderGrid clears it), so the townships don't flash in between.
    if (level === 'section' && this.allSectionsRun) {
      this.allSectionsRun = null;
      this.cancelAllSectionsDraw();
      this.setStatus('');
    }
    // Crossing the section/township threshold always refetches; otherwise the
    // padded bbox we already hold may still cover the viewport.
    if (level === this.loadedLevel && this.covers(this.loadedBounds)) {
      // Same township grid, new viewport: "all sections" may need more blocks.
      if (level === 'township' && this.showAllSections) this.loadAllSections();
      return;
    }
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

  // A canvas renderer stays on the map after its last layer is removed,
  // and an empty canvas still catches pointer events for whatever sits
  // beneath it. So renderers go with their layers and are recreated on
  // demand.
  SectionMap.prototype.dropRenderer = function (name) {
    if (this[name]) {
      this.map.removeLayer(this[name]);
      this[name] = null;
    }
  };

  SectionMap.prototype.clearGrid = function () {
    this.clearLens();
    if (this.allSectionsLayer) {
      this.map.removeLayer(this.allSectionsLayer);
      this.allSectionsLayer = null;
      this.allSectionsAdded = null;
      this.allSectionsFeatures = [];
      this.currentClassesAreSections = false;
    }
    this.dropRenderer('allSectionsRenderer');
    this.dropRenderer('sectionRenderer');
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
    // Outlines don't change between years or filters, so after the first
    // load only the numbers are requested and the outlines are re-attached
    // from the cache (see attachTownshipGeometry). A township outside what
    // was cached (a wider bbox) falls back to a full request.
    var valuesOnly = !!this.townshipGeometry && this.townshipGeometryCovers(bounds);
    if (valuesOnly) params.geometry = '0';
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
        if (valuesOnly && !self.attachTownshipGeometry(geojson)) {
          // Something in view isn't in the outline cache: fetch it fully.
          self.townshipGeometry = null;
          self.loadTownships();
          return;
        }
        if (!valuesOnly) self.rememberTownshipGeometry(geojson, bounds);
        self.setStatus('');
        self.loadedBounds = bounds;
        self.loadedLevel = 'township';
        self.renderGrid(geojson, 'township');
        if (self.showAllSections) self.loadAllSections();
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

  SectionMap.prototype.rememberTownshipGeometry = function (geojson, bounds) {
    var cache = {};
    (geojson.features || []).forEach(function (feature) {
      cache[feature.id || feature.properties.id] = feature.geometry;
    });
    this.townshipGeometry = cache;
    this.townshipGeometryBounds = L.latLngBounds([]).extend(bounds);
  };

  SectionMap.prototype.townshipGeometryCovers = function (bounds) {
    return !!this.townshipGeometryBounds && this.townshipGeometryBounds.contains(bounds);
  };

  // Puts cached outlines back onto a values-only response; false if any
  // feature has no cached outline.
  SectionMap.prototype.attachTownshipGeometry = function (geojson) {
    var cache = this.townshipGeometry || {};
    var features = geojson.features || [];
    for (var i = 0; i < features.length; i++) {
      var geometry = cache[features[i].id || features[i].properties.id];
      if (!geometry) return false;
      features[i].geometry = geometry;
    }
    return true;
  };

  SectionMap.prototype.isHighlighted = function (feature) {
    return this.level === 'section' && !!this.data.highlight && feature.id === this.data.highlight;
  };

  SectionMap.prototype.allSectionsActive = function () {
    return this.showAllSections && this.level === 'township';
  };

  SectionMap.prototype.featureStyle = function (feature) {
    var value = feature.properties[this.metric];
    // With every section drawn on top, the township grid steps aside: no
    // fill, no line, just the interactive shape.
    if (this.allSectionsActive()) {
      return { fillOpacity: 0, stroke: false, fillColor: NO_DATA_COLOR };
    }
    // A faint base grid; the fills carry the data. Only the page's own
    // section (orange) and a hovered cell with data get a real outline.
    var style = {
      fillColor: colorFor(this.currentClasses, value),
      fillOpacity: value ? 0.7 : 0.25,
      stroke: true,
      color: GRID_LINE.color,
      opacity: GRID_LINE.opacity,
      weight: this.level === 'township' ? 0.75 : 0.5,
    };
    if (this.isSelected(feature)) Object.assign(style, SELECTED_LINE);
    if (this.isHighlighted(feature)) {
      style.color = '#d35400';
      style.opacity = 1;
      style.weight = 3;
    }
    return style;
  };

  // Hovering a cell darkens and thickens its border so the reader can see
  // which square a click would open. The fill is left alone: it carries the
  // value. The highlighted section (the page's own) keeps its orange outline.
  // Hovered cells get a dark outline; a cell with no reported use gets a
  // lighter one, so the pointer still lands somewhere visible (a reader
  // finding their own square mile) without drawing attention to nothing.
  SectionMap.prototype.hoverStyle = function (feature) {
    var weight = this.level === 'township' ? 2.5 : 2;
    if (feature && !feature.properties[this.metric]) return { stroke: true, color: '#999', opacity: 1, weight: weight };
    return { stroke: true, color: '#222', opacity: 1, weight: weight };
  };

  SectionMap.prototype.lensHoverStyle = function (section) {
    return { stroke: true, color: section.properties[this.metric] ? '#111' : '#999', opacity: 1, weight: 2 };
  };

  SectionMap.prototype.bindHover = function (feature, layer) {
    var self = this;
    layer.on('mouseover', function () {
      if (self.showAllSections && self.level === 'township') return;
      if (self.level === 'township') {
        self.cancelLensClear();
        if (self.lensId !== feature.properties.id) self.showLens(feature, layer);
      }
      if (self.isHighlighted(feature)) return;
      var hover = self.hoverStyle(feature);
      if (self.level === 'township' && self.lensLayer) hover.fillOpacity = 0;
      layer.setStyle(hover);
      if (layer.bringToFront) layer.bringToFront();
      self.bringHighlightToFront();
    });
    layer.on('mouseout', function () {
      if (self.level === 'township' && self.lensId === feature.properties.id) {
        // The pointer may just be moving onto one of this township's own
        // sections, which sit on top of it; let that cancel the clear.
        self.scheduleLensClear();
        return;
      }
      layer.setStyle(self.featureStyle(feature));
    });
  };

  // The lens: zoomed out, hovering a township shows the sections of that
  // township and its neighbours (its Moore neighborhood, a 3x3 block),
  // shaded by the same metric with quantile classes over the block, so the
  // reader can see where within the neighborhood the use concentrates. Each
  // section can be hovered and clicked like the zoomed-in grid. The sections
  // come from the same endpoint the zoomed-in grid uses and are kept per
  // township for the life of the map.
  // The townships whose bounds touch the hovered one (itself included): a
  // 3x3 block in the regular grid, fewer at the valley edge.
  // `reach` is in townships from the centre: 1.5 is the 3x3 block, 2.5 the
  // 5x5 block around it (used to prefetch the ring beyond the lens).
  SectionMap.prototype.neighborhoodOf = function (layer, reach) {
    var hosts = [];
    if (!this.gridLayer) return hosts;
    reach = reach || 1.5;
    // Neighbours by centre distance rather than touching bounds: diagonal
    // townships meet the hovered one only at a corner, and survey offsets
    // between ranges leave small gaps, so an intersection test drops them.
    // Anything whose centre is within `reach` townships on both axes is in;
    // the next ring starts a whole township further out.
    var bounds = layer.getBounds();
    var center = bounds.getCenter();
    // A partial township (county edge, survey gap) has small bounds, so the
    // reach is floored at a full township's size.
    var maxDx = Math.max(bounds.getEast() - bounds.getWest(), TOWNSHIP_DEGREES.lng) * reach;
    var maxDy = Math.max(bounds.getNorth() - bounds.getSouth(), TOWNSHIP_DEGREES.lat) * reach;
    this.gridLayer.eachLayer(function (other) {
      if (!other.feature || !other.getBounds) return;
      var c = other.getBounds().getCenter();
      if (Math.abs(c.lng - center.lng) <= maxDx && Math.abs(c.lat - center.lat) <= maxDy) hosts.push(other);
    });
    return hosts;
  };

  SectionMap.prototype.showLens = function (feature, layer) {
    if (!this.data.sectionsUrl) return;
    var id = feature.properties.id;
    // While one of the lens sections has its popup open the lens is pinned:
    // hovering a neighbouring township mustn't pull it (and the popup) away.
    if (this.openLensId) return;
    this.clearLens();
    this.lensId = id;
    this.lensHost = { feature: feature, layer: layer };

    var self = this;
    var hosts = this.neighborhoodOf(layer);
    this.lensHosts = hosts;
    var ids = hosts.map(function (host) { return host.feature.properties.id; });
    var draw = function () {
      if (self.lensId === id) self.drawLens(id, self.cachedLensSections(ids));
      self.prefetchRing(layer);
    };
    if (!this.uncached(ids).length) {
      draw();
      return;
    }
    // A cursor sweeping across the map crosses many townships; fetch only
    // for the one it settles on. Cached blocks above draw at once.
    this.cancelLensFetch();
    this.lensFetchTimer = setTimeout(function () {
      self.lensFetchTimer = null;
      if (self.lensId !== id) return;
      self.fetchLensSections(hosts, draw);
    }, LENS_FETCH_DELAY_MS);
  };

  SectionMap.prototype.cancelLensFetch = function () {
    if (this.lensFetchTimer) {
      clearTimeout(this.lensFetchTimer);
      this.lensFetchTimer = null;
    }
  };

  SectionMap.prototype.uncached = function (ids) {
    var self = this;
    return ids.filter(function (townshipId) { return !self.lensCache[townshipId]; });
  };

  // One request for a set of townships: the bbox is the union of their
  // bounds, and the response is filed per township so any later hover over
  // one of them draws from cache. `done` runs after filing (also on
  // failure, so a draw can still proceed with whatever is cached).
  SectionMap.prototype.fetchLensSections = function (hosts, done) {
    var self = this;
    var ids = hosts.map(function (host) { return host.feature.properties.id; });
    // Built from a fresh bounds: L.latLngBounds(bounds) hands back the same
    // object, and extend() mutates, so seeding with a layer's own getBounds()
    // would grow that layer's cached bounds with every hover.
    var union = L.latLngBounds([]);
    hosts.forEach(function (host) { union.extend(host.getBounds()); });
    var params = this.commonParams();
    params.bbox = bboxParam(union);
    var query = buildQuery(params);
    fetch(this.data.sectionsUrl + (query ? '?' + query : ''))
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (body) {
        if (!body || !body.features) return;
        var byTownship = {};
        ids.forEach(function (townshipId) { byTownship[townshipId] = []; });
        body.features.forEach(function (section) {
          var mtrs = section.properties.mtrs || '';
          var townshipId = mtrs.slice(0, mtrs.lastIndexOf('-'));
          if (byTownship[townshipId]) byTownship[townshipId].push(section);
        });
        ids.forEach(function (townshipId) { self.lensCache[townshipId] = byTownship[townshipId]; });
      })
      .catch(function () {})
      .then(function () { if (done) done(); });
  };

  // Once the lens is drawn, warm the cache for the ring of townships one
  // step beyond it, in idle time, so recentring the lens in any direction
  // draws without waiting on the network. One prefetch at a time; a lens
  // that has moved on by the time it runs prefetches around its new centre
  // instead.
  SectionMap.prototype.prefetchRing = function (layer) {
    if (this.prefetching || !this.data.sectionsUrl) return;
    var self = this;
    var run = function () {
      if (self.prefetching) return;
      var inner = {};
      self.neighborhoodOf(layer, 1.5).forEach(function (host) { inner[host.feature.properties.id] = true; });
      var ring = self.neighborhoodOf(layer, 2.5).filter(function (host) {
        var townshipId = host.feature.properties.id;
        return !inner[townshipId] && !self.lensCache[townshipId];
      });
      if (!ring.length) return;
      self.prefetching = true;
      self.fetchLensSections(ring, function () { self.prefetching = false; });
    };
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(run, { timeout: 500 });
    } else {
      setTimeout(run, 150);
    }
  };

  // The nine townships under the lens lose their fill while it's up, so the
  // section shades aren't stacked on the township shade beneath them; the
  // hovered one keeps its darker outline.
  SectionMap.prototype.setHostFills = function (visible) {
    var self = this;
    (this.lensHosts || []).forEach(function (host) {
      var style = self.featureStyle(host.feature);
      if (!visible) style.fillOpacity = 0;
      host.setStyle(style);
    });
    this.drawLensOutline(!visible);
  };

  // The hovered township's outline, on its own pane above the lens sections
  // (which would otherwise paint over the township's border). Only when the
  // township has data, matching the hover rule elsewhere.
  SectionMap.prototype.drawLensOutline = function (show) {
    if (this.lensOutline) {
      this.map.removeLayer(this.lensOutline);
      this.lensOutline = null;
    }
    var host = this.lensHost;
    if (!show || !host || !host.layer.getLatLngs) return;
    this.lensOutline = L.polygon(host.layer.getLatLngs(), Object.assign(
      { pane: 'pesticide-lens-outline', interactive: false, fill: false },
      this.hoverStyle(host.feature)
    )).addTo(this.map);
  };

  // Keeps the township under the pointer at the centre of the lens. Returns
  // true when the lens was redrawn around a different township (the caller's
  // section layer is gone by then). A pinned lens (popup open) stays put.
  SectionMap.prototype.recentreLens = function (section) {
    var mtrs = section.properties.mtrs || '';
    var townshipId = mtrs.slice(0, mtrs.lastIndexOf('-'));
    if (!townshipId || townshipId === this.lensId || this.openLensId || !this.gridLayer) return false;
    var host = null;
    this.gridLayer.eachLayer(function (layer) {
      if (layer.feature && layer.feature.properties.id === townshipId) host = layer;
    });
    if (!host) return false;
    this.showLens(host.feature, host);
    return true;
  };

  // "All sections" mode. At the township zoom, every section in the padded
  // viewport is drawn instead of the township grid. Sections load in the
  // same 5x5 township blocks the lens prefetches, a few at a time, and go
  // into the same per-township cache, so the two modes share their work.
  // Drawing uses a canvas renderer: a valley-wide view is ~28k polygons,
  // which SVG handles badly and canvas handles fine.
  SectionMap.prototype.visibleTownships = function () {
    var hosts = [];
    if (!this.gridLayer) return hosts;
    var bounds = this.map.getBounds().pad(0.15);
    this.gridLayer.eachLayer(function (layer) {
      if (layer.feature && layer.getBounds && layer.getBounds().intersects(bounds)) hosts.push(layer);
    });
    return hosts;
  };

  SectionMap.prototype.loadAllSections = function () {
    if (!this.showAllSections || this.level !== 'township' || !this.gridLayer || !this.data.sectionsUrl) return;
    var self = this;
    // Uncached townships are tiled into a fixed 5x5-township grid of
    // blocks, so a valley-wide view is ~36 requests of ~25 townships each
    // (well under the endpoint's cap) rather than a request per hover-sized
    // neighbourhood.
    var tiles = {};
    var blocks = [];
    var tileLng = TOWNSHIP_DEGREES.lng * 5;
    var tileLat = TOWNSHIP_DEGREES.lat * 5;
    this.visibleTownships().forEach(function (host) {
      if (self.lensCache[host.feature.properties.id]) return;
      var c = host.getBounds().getCenter();
      var key = Math.floor(c.lng / tileLng) + ':' + Math.floor(c.lat / tileLat);
      if (!tiles[key]) {
        tiles[key] = [];
        blocks.push(tiles[key]);
      }
      tiles[key].push(host);
    });

    // Draw what's cached right away; the blocks fill in as they land.
    this.drawAllSections();
    if (!blocks.length) return;

    // A new run supersedes any in flight: its callbacks see a different
    // token and stop scheduling more work (fetches already started finish
    // and still land in the cache).
    var run = { total: blocks.length, done: 0 };
    this.allSectionsRun = run;
    var queue = blocks.slice();
    var active = 0;
    var next = function () {
      if (self.allSectionsRun !== run) return;
      while (active < ALL_SECTIONS_CONCURRENCY && queue.length) {
        active += 1;
        self.fetchLensSections(queue.shift(), function () {
          active -= 1;
          if (self.allSectionsRun !== run) return;
          run.done += 1;
          self.setStatus(run.done < run.total ? 'Loading sections… ' + run.done + ' of ' + run.total : '');
          // New sections join the layer at once, styled by the current
          // classes; the classes themselves (and so every section's shade)
          // are refreshed on a throttle while blocks land, and once more
          // when the last one has.
          self.drawAllSections();
          if (run.done < run.total) {
            self.scheduleAllSectionsDraw();
          } else {
            self.cancelAllSectionsDraw();
            self.restyleAllSections();
          }
          next();
        });
      }
    };
    this.setStatus('Loading sections… 0 of ' + run.total);
    next();
  };

  SectionMap.prototype.scheduleAllSectionsDraw = function () {
    if (this.allSectionsDrawTimer) return;
    var self = this;
    this.allSectionsDrawTimer = setTimeout(function () {
      self.allSectionsDrawTimer = null;
      self.restyleAllSections();
    }, ALL_SECTIONS_REDRAW_MS);
  };

  SectionMap.prototype.cancelAllSectionsDraw = function () {
    if (this.allSectionsDrawTimer) {
      clearTimeout(this.allSectionsDrawTimer);
      this.allSectionsDrawTimer = null;
    }
  };

  // Adds any cached, visible sections that aren't in the layer yet. The
  // layer is built once and grown, never rebuilt: rebuilding meant parsing
  // and re-creating every polygon each time a block landed, which cost
  // more than the requests did.
  SectionMap.prototype.drawAllSections = function () {
    if (!this.showAllSections || this.level !== 'township' || !this.gridLayer) return;
    var self = this;
    if (!this.allSectionsLayer) {
      if (!this.allSectionsRenderer) this.allSectionsRenderer = L.canvas({ pane: 'pesticide-lens' });
      this.allSectionsAdded = {};
      this.allSectionsFeatures = [];
      this.allSectionsLayer = L.geoJSON(null, {
        pane: 'pesticide-lens',
        renderer: this.allSectionsRenderer,
        style: function (section) { return self.lensSectionStyle(section, self.currentClasses); },
        onEachFeature: function (section, sectionLayer) {
          sectionLayer.on('mouseover', function () {
            sectionLayer.setStyle(self.lensHoverStyle(section));
            if (sectionLayer.bringToFront) sectionLayer.bringToFront();
          });
          sectionLayer.on('mouseout', function () {
            sectionLayer.setStyle(self.lensSectionStyle(section, self.currentClasses));
          });
          sectionLayer.on('click', function (event) {
            L.DomEvent.stopPropagation(event);
            self.showSectionPopup(section, sectionLayer);
          });
          self.trackPopup(sectionLayer, section.properties.id, 'openAllSectionsId');
        },
      }).addTo(this.map);
      // The township grid steps aside (see featureStyle) once the layer
      // exists; the legend follows in restyleAllSections.
      this.gridLayer.eachLayer(function (layer) { layer.setStyle(self.featureStyle(layer.feature)); });
    }

    var fresh = [];
    this.visibleTownships().forEach(function (host) {
      var id = host.feature.properties.id;
      if (self.allSectionsAdded[id] || !self.lensCache[id]) return;
      self.allSectionsAdded[id] = true;
      fresh = fresh.concat(self.lensCache[id]);
    });
    if (!fresh.length) {
      if (!this.currentClassesAreSections) this.restyleAllSections();
      return;
    }
    this.allSectionsFeatures = this.allSectionsFeatures.concat(fresh);
    // First sections in: classes over them so they don't draw unshaded.
    if (!this.currentClassesAreSections) {
      this.currentClasses = quantileClasses(this.allSectionsFeatures.map(function (f) { return f.properties[self.metric]; }));
      this.currentClassesAreSections = true;
      this.updateLegend();
    }
    this.allSectionsLayer.addData({ type: 'FeatureCollection', features: fresh });
    this.reopenSelectedSection(this.allSectionsLayer);
  };

  // Recomputes the classes over everything in the layer and reshades it;
  // also what a metric change calls.
  SectionMap.prototype.restyleAllSections = function () {
    if (!this.allSectionsLayer) return;
    var self = this;
    this.currentClasses = quantileClasses(this.allSectionsFeatures.map(function (f) { return f.properties[self.metric]; }));
    this.currentClassesAreSections = true;
    this.allSectionsLayer.eachLayer(function (layer) {
      layer.setStyle(self.lensSectionStyle(layer.feature, self.currentClasses));
    });
    this.updateLegend();
  };

  // `keepFlag` leaves the toggle on (a zoom to section level, where the
  // mode is moot) rather than turning it off.
  SectionMap.prototype.clearAllSections = function (keepFlag) {
    this.allSectionsRun = null;
    this.cancelAllSectionsDraw();
    if (!keepFlag) this.showAllSections = false;
    if (this.allSectionsLayer) {
      this.map.removeLayer(this.allSectionsLayer);
      this.allSectionsLayer = null;
      this.allSectionsAdded = null;
      this.allSectionsFeatures = [];
      this.currentClassesAreSections = false;
      this.openAllSectionsId = null;
      this.setStatus('');
      if (this.gridLayer) this.restyle();
    }
    this.dropRenderer('allSectionsRenderer');
  };

  SectionMap.prototype.cachedLensSections = function (ids) {
    var self = this;
    return ids.reduce(function (all, townshipId) {
      return all.concat(self.lensCache[townshipId] || []);
    }, []);
  };

  SectionMap.prototype.lensSectionStyle = function (feature, classes) {
    var value = feature.properties[this.metric];
    var style = {
      fillColor: colorFor(classes, value),
      fillOpacity: value ? 0.85 : 0.35,
      stroke: true,
      color: GRID_LINE.color,
      opacity: GRID_LINE.opacity,
      weight: 0.5,
    };
    if (this.isSelected(feature)) Object.assign(style, SELECTED_LINE);
    return style;
  };

  SectionMap.prototype.isSelected = function (feature) {
    return !!this.selectedSectionId && feature.properties.id === this.selectedSectionId;
  };

  SectionMap.prototype.drawLens = function (id, features) {
    if (this.lensLayer) {
      this.map.removeLayer(this.lensLayer);
      this.lensLayer = null;
    }
    this.lensId = id;
    this.lensDrawnAt = Date.now();
    if (!features.length) return;
    // The township shade stays until the sections are here to replace it,
    // so the lens never shows an empty grid while the request is in flight.
    this.setHostFills(false);
    var self = this;
    var classes = quantileClasses(features.map(function (section) { return section.properties[self.metric]; }));
    this.lensClasses = classes;
    this.lensLayer = L.geoJSON({ type: 'FeatureCollection', features: features }, {
      pane: 'pesticide-lens',
      style: function (section) { return self.lensSectionStyle(section, classes); },
      onEachFeature: function (section, sectionLayer) {
        sectionLayer.on('mouseover', function () {
          self.cancelLensClear();
          // The lens covers the townships, so this is where a move into a
          // neighbouring township is noticed: recentre the lens on it.
          if (self.recentreLens(section)) return;
          sectionLayer.setStyle(self.lensHoverStyle(section));
          if (sectionLayer.bringToFront) sectionLayer.bringToFront();
        });
        sectionLayer.on('mouseout', function () {
          sectionLayer.setStyle(self.lensSectionStyle(section, classes));
          self.scheduleLensClear();
        });
        sectionLayer.on('click', function (event) {
          L.DomEvent.stopPropagation(event);
          self.showSectionPopup(section, sectionLayer);
        });
        self.trackPopup(sectionLayer, section.properties.id, 'openLensId');
        sectionLayer.on('popupclose', function () { self.scheduleLensClear(); });
      },
    }).addTo(this.map);
  };

  // A short grace period between leaving a township (or one of its
  // sections) and dropping the lens, so moving between the two doesn't
  // flicker it away.
  SectionMap.prototype.scheduleLensClear = function () {
    this.cancelLensClear();
    var self = this;
    var scheduledAt = Date.now();
    this.lensClearTimer = setTimeout(function () {
      self.lensClearTimer = null;
      // Keep the lens while one of its section popups is open, or when it
      // was redrawn (recentred) after this clear was scheduled: that
      // mouseout came from a section the redraw removed.
      if (self.openLensId) return;
      if (self.lensDrawnAt && self.lensDrawnAt >= scheduledAt) return;
      self.clearLens();
    }, 120);
  };

  SectionMap.prototype.cancelLensClear = function () {
    if (this.lensClearTimer) {
      clearTimeout(this.lensClearTimer);
      this.lensClearTimer = null;
    }
  };

  SectionMap.prototype.clearLens = function () {
    this.cancelLensClear();
    this.cancelLensFetch();
    this.lensId = null;
    this.openLensId = null;
    this.setHostFills(true);
    this.lensHosts = null;
    this.lensHost = null;
    if (this.lensLayer) {
      this.map.removeLayer(this.lensLayer);
      this.lensLayer = null;
    }
  };

  SectionMap.prototype.legendUnit = function () {
    var unit = METRIC_UNITS[this.metric] || '';
    return this.level === 'township' && !this.allSectionsActive() ? unit + ' per township' : unit;
  };

  SectionMap.prototype.updateLegend = function () {
    if (this.legendEl) renderLegend(this.legendEl, this.currentClasses, this.legendUnit());
    // "All sections" only means something at the township zoom.
    var sectionsToggle = this.controlsEl ? this.controlsEl.querySelector('input[name="sections"]') : null;
    if (sectionsToggle) sectionsToggle.disabled = this.level === 'section';
    if (this.levelEl) {
      this.levelEl.textContent = this.allSectionsActive() ? LEVEL_TEXT.allSections : (LEVEL_TEXT[this.level] || '');
    }
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
    this.currentClasses = quantileClasses(features.map(function (feature) { return feature.properties[self.metric]; }));

    this.clearGrid();

    // The section grid can run to a couple of thousand polygons, which SVG
    // pans and restyles sluggishly; canvas handles it easily. Townships
    // stay on SVG, where hover reordering is free.
    if (level === 'section' && !this.sectionRenderer) this.sectionRenderer = L.canvas();
    this.gridLayer = L.geoJSON(geojson, {
      renderer: level === 'section' ? this.sectionRenderer : undefined,
      style: function (feature) {
        return self.featureStyle(feature);
      },
      onEachFeature: function (feature, layer) {
        self.trackPopup(layer, feature.properties.id, 'openGridId');
        self.bindHover(feature, layer);
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
    if (level === 'section') {
      this.reopenSelectedSection(this.gridLayer);
      this.resolvePendingLocate();
    }
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
      values.push(layer.feature.properties[self.metric]);
    });
    this.currentClasses = quantileClasses(values);
    this.gridLayer.eachLayer(function (layer) {
      layer.setStyle(self.featureStyle(layer.feature));
      if (self.level === 'township' && layer.getPopup()) {
        layer.setPopupContent(self.townshipPopupHtml(layer.feature.properties, layer.getBounds().getCenter()));
      }
    });
    this.bringHighlightToFront();
    if (this.allSectionsActive() && this.allSectionsLayer) {
      this.restyleAllSections();
    } else {
      this.updateLegend();
    }
  };

  // The headline figure of a grid popup: "5,966 lbs applied in 2023" or
  // "312 applications in 2023", following the metric toggle.
  SectionMap.prototype.metricLine = function (props) {
    var value = formatNumber(props[this.metric] || 0);
    var year = this.data.year ? ' in ' + escapeHtml(this.data.year) : '';
    var text = this.metric === 'applications'
      ? '<strong>' + value + '</strong> application' + (props.applications === 1 ? '' : 's') + year
      : '<strong>' + value + ' lbs</strong> applied' + year;
    return '<p class="section-popup-metric">' + text + '</p>';
  };

  SectionMap.prototype.townshipPopupHtml = function (props, center) {
    var sections = props.sections || 0;
    // The target is carried on the button so a delegated listener (see init)
    // can serve it; per-popup listeners would be lost when restyle() swaps
    // the popup content.
    return (
      '<div class="section-popup">' +
      '<h4>' + escapeHtml(props.name || props.id) + '</h4>' +
      '<p class="section-popup-sub">Township · ' + formatNumber(sections) + ' square-mile section' + (sections === 1 ? '' : 's') + '</p>' +
      this.metricLine(props) +
      '<div class="section-popup-actions"><button type="button" class="section-popup-action section-map-zoom" data-lat="' + center.lat + '" data-lng="' + center.lng + '">' +
      '<span class="fa-regular fa-fw fa-magnifying-glass-plus"></span> Zoom in to sections</button></div>' +
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
        // A section popup rides through the zoom: the section grid that
        // loads at the new zoom re-opens the popup for this id (see
        // reopenGridPopup). A township popup just closes.
        var sectionId = button.getAttribute('data-id');
        if (sectionId) {
          self.openGridId = sectionId;
        } else {
          self.map.closePopup();
        }
        self.map.setView([lat, lng], self.sectionZoom(), { animate: !self.reducedMotion });
      });
    });
  };

  // `detailHtml` is the top-chemicals block: a list once loaded, a loading
  // or empty note otherwise.
  // `center` is passed when the popup was opened from the lens; the
  // township popup is unreachable there (the sections cover it),
  // so its "zoom in" action rides along on the section popup instead.
  SectionMap.prototype.sectionPopupHtml = function (props, detailHtml, center) {
    var sub = 'Square-mile section' + (props.county ? ' · ' + escapeHtml(props.county) : '');
    var url = this.sectionUrl(props.id);
    var links = url
      ? '<a class="section-popup-action" href="' + escapeHtml(url) + '"><span class="fa-regular fa-fw fa-circle-info"></span> Section details</a>'
      : '';
    if (center && this.level === 'township') {
      links += '<button type="button" class="section-popup-action section-map-zoom" data-id="' + escapeHtml(props.id) + '" data-lat="' + center.lat + '" data-lng="' + center.lng + '">' +
        '<span class="fa-regular fa-fw fa-magnifying-glass-plus"></span> Zoom in</button>';
    }
    return (
      '<div class="section-popup">' +
      '<h4>' + escapeHtml(props.mtrs || props.id) + '</h4>' +
      '<p class="section-popup-sub">' + sub + '</p>' +
      this.metricLine(props) +
      '<p class="section-popup-label">Top chemicals</p>' +
      detailHtml +
      '<div class="section-popup-actions">' + links + '</div>' +
      '</div>'
    );
  };

  // The open popup's section wears SELECTED_LINE (see the style functions)
  // for as long as the popup is up. Restyling goes through the normal style
  // function so hover in and out doesn't lose it.
  SectionMap.prototype.selectSection = function (id, layer) {
    var self = this;
    this.selectedSectionId = id;
    this.restyleSection(layer);
    if (layer.bringToFront) layer.bringToFront();
    if (layer._selectionBound) return;
    layer._selectionBound = true;
    layer.on('popupclose', function () {
      if (self.selectedSectionId !== id) return;
      // A grid rebuild (zoom across the township threshold, a refetch)
      // removes the layer and closes its popup with it; the selection
      // outlives that and is reopened wherever the section next appears
      // (see reopenSelectedSection). Only a close with the layer still on
      // the map is the reader letting go.
      if (!self.map.hasLayer(layer)) return;
      self.selectedSectionId = null;
      self.restyleSection(layer);
    });
  };

  // After a layer of sections is (re)built, put the selected section's
  // popup back on it if it's there.
  SectionMap.prototype.reopenSelectedSection = function (group) {
    var id = this.selectedSectionId;
    if (!id || !group) return;
    var self = this;
    group.eachLayer(function (layer) {
      if (!layer.feature || layer.feature.properties.id !== id) return;
      if (layer.isPopupOpen && layer.isPopupOpen()) return;
      self.showSectionPopup(layer.feature, layer);
    });
  };

  // Re-applies whichever style function owns this layer: the grid's for the
  // section grid, the lens one for lens and all-sections layers.
  SectionMap.prototype.restyleSection = function (layer) {
    if (!layer.feature || !this.map.hasLayer(layer)) return;
    if (this.gridLayer && this.gridLayer.hasLayer(layer)) {
      layer.setStyle(this.featureStyle(layer.feature));
    } else if (this.lensLayer && this.lensLayer.hasLayer(layer)) {
      layer.setStyle(this.lensSectionStyle(layer.feature, this.lensClasses));
    } else {
      layer.setStyle(this.lensSectionStyle(layer.feature, this.currentClasses));
    }
  };

  SectionMap.prototype.showSectionPopup = function (feature, layer) {
    var props = feature.properties;
    var center = layer.getBounds().getCenter();
    var html = this.sectionPopupHtml(props, '<p class="section-popup-note">Loading…</p>', center);
    layer.bindPopup(html, this.popupOptions('section-popup-wrap'));
    openPopupAtCenter(layer);
    layer.openPopup(layer.getBounds().getCenter());
    this.selectSection(props.id, layer);

    if (!this.data.sectionUrlPattern) return;
    var year = this.data.year;
    var url = this.data.sectionUrlPattern.replace('{id}', props.id) + '?year=' + encodeURIComponent(year || '');

    var self = this;
    fetch(url)
      .then(function (response) { return response.json(); })
      .then(function (detail) {
        if (!layer.getPopup() || !layer.isPopupOpen()) return; // popup was closed before this resolved
        var chemicals = (detail && detail.top_chemicals) || [];
        var detailHtml = '<p class="section-popup-note">No use reported this year.</p>';
        if (chemicals.length) {
          detailHtml = '<ul class="section-popup-chems">' + chemicals.slice(0, 3).map(function (c) {
            return '<li>' +
              '<span class="name' + (c.is_of_concern ? ' is-of-concern' : '') + '">' + linkHtml(self.chemicalUrl(c.id), c.display_name || c.name) + '</span>' +
              '<span class="amount">' + formatNumber(c.lbs) + ' lbs</span>' +
              '</li>';
          }).join('') + '</ul>';
        }
        layer.getPopup().setContent(self.sectionPopupHtml(props, detailHtml, center));
      })
      .catch(function (err) {
        window.console && console.error && console.error('section-map: failed to load section detail', err);
        if (!layer.getPopup() || !layer.isPopupOpen()) return;
        layer.getPopup().setContent(self.sectionPopupHtml(props, '<p class="section-popup-note">Couldn\'t load the top chemicals.</p>', center));
      });
  };

  SectionMap.prototype.loadNotices = function () {
    if (!this.data.noticesUrl) return;
    if (!this.showNotices) return;
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
        linkHtml(self.chemicalUrl(c.id), c.display_name || c.name) + '</li>';
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
  // The one live map on the page, so a swap can hand its container over
  // rather than building a second Leaflet instance.
  var liveMap = null;

  function init(root) {
    if (typeof L === 'undefined') return;
    var containers = containersUnder(root || document);
    for (var i = 0; i < containers.length; i++) {
      var el = containers[i];
      if (el.dataset.rendered) continue;
      try {
        if (liveMap && !document.body.contains(liveMap.el)) {
          liveMap.adopt(el);
          continue;
        }
        el.dataset.rendered = '1';
        liveMap = new SectionMap(el);
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
