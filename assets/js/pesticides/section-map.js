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
 * A port of the Leaflet map it replaced; the behaviour it is held to is the
 * parity checklist, docs/superpowers/specs/2026-09-21-section-map-inventory.md.
 *
 * Plain ES2017, no framework/bundler; a module on the map core (assets/js/maps/), registered as 'section'.
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M || !M.register) return;

  // The core's helpers (assets/js/maps/core.js), under the names this file
  // has always used.
  var TILE_STYLES = M.TILE_STYLES;
  var styleFor = M.styleFor;
  var escapeHtml = M.escapeHtml;
  var EMPTY = M.EMPTY;
  var logError = M.logger('section-map');
  var debounce = M.debounce;
  var extendBounds = M.extendBounds;
  var geometryBounds = M.geometryBounds;
  var unionBounds = M.unionBounds;

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
  // How long the cursor must rest on an uncached township before its lens
  // sections are fetched, so a sweep across the map doesn't fetch for every
  // township it passes over.
  var LENS_FETCH_DELAY_MS = 50;
  // The grace between leaving a township (or one of its lens sections) and
  // dropping the lens, so moving between the two doesn't flicker it away.
  var LENS_CLEAR_DELAY_MS = 120;
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
  // Diverging ramps for the change view, stored already reversed: index 0 is
  // the largest decrease, the last the largest increase. Same stops as
  // camp.apps.pesticides.maps.DIVERGING_RAMPS. Kept in their own table so a
  // sequential `?ramp=` name can't grade signed data one-sided.
  var DIVERGING_RAMPS = {
    rdbu: ['#2166ac', '#67a9cf', '#d1e5f0', '#f7f7f7', '#fddbc7', '#ef8a62', '#b2182b'],
    puor: ['#542788', '#998ec3', '#d8daeb', '#f7f7f7', '#fee0b6', '#f1a340', '#b35806'],
    brbg: ['#01665e', '#5ab4ac', '#c7eae5', '#f5f5f5', '#f6e8c3', '#d8b365', '#8c510a'],
  };
  var rampMatch = /[?&]ramp=([a-z]+)/.exec(window.location.search || '');
  var RAMP = RAMPS[rampMatch && rampMatch[1]] || RAMPS.blues;
  var DIVERGING_RAMP = DIVERGING_RAMPS[rampMatch && rampMatch[1]] || DIVERGING_RAMPS.rdbu;
  var DIVERGING_CENTER = (DIVERGING_RAMP.length - 1) / 2;
  // How many quantile classes: ?bins=4|5|6|8|10 (quartiles ... deciles).
  var BIN_OPTIONS = [[4, 'Quartiles'], [5, 'Quintiles'], [6, 'Sextiles'], [8, 'Octiles'], [10, 'Deciles']];
  var binsMatch = /[?&]bins=(\d+)/.exec(window.location.search || '');
  var DEFAULT_BINS = 6;
  var NUM_CLASSES = binsMatch && BIN_OPTIONS.some(function (o) { return o[0] === +binsMatch[1]; }) ? +binsMatch[1] : DEFAULT_BINS;
  var NO_DATA_COLOR = '#f0f0f0';
  // A full 6x6 mile township in degrees around 36°N, for the lens reach
  // and the "all sections" blocks.
  var TOWNSHIP_DEGREES = { lat: 0.087, lng: 0.108 };
  // "All sections" mode: how many section blocks load at once...
  var ALL_SECTIONS_CONCURRENCY = 4;
  // ...and how often the growing layer is reshaded while they land.
  var ALL_SECTIONS_REDRAW_MS = 600;
  // Below this zoom, sections drawn at township level (the lens, "all
  // sections") are a few pixels each: their hairline strokes would outweigh
  // the fills and grey the map, so they draw fill-only.
  var SECTION_LINES_MIN_ZOOM = 10;

  var METRIC_UNITS = {
    lbs_chemical: 'lbs',
    applications: 'applications',
  };

  // Fetch a bbox padded by half a viewport on each side, then skip the next
  // fetch while the viewport is still inside what we already have, so a pan
  // doesn't rebuild the grid under an open popup.
  var BBOX_PAD = 0.5;

  var LEVEL_TEXT = {
    section: 'Each square is one square-mile section.',
    township: 'Each square is a 6 × 6 mile township; zoom in for square-mile sections.',
    allSections: 'Each square is one square-mile section, across every township in view.',
  };


  // The base grid: present, but barely, so the fills read as a surface.
  var GRID_LINE = { color: '#1f2d3d', opacity: 0.18 };
  // The section whose popup is open keeps an outline until it closes: the
  // link blue, so it reads apart from the dark hover stroke.
  var SELECTED_LINE = { color: '#3273dc', opacity: 1, width: 2 };
  // The page's own section (a section page), in the notices orange.
  var HIGHLIGHT_LINE = { color: '#d35400', opacity: 1, width: 3 };
  // Fill opacities [with data, without]: the grid, and sections drawn at
  // the township zoom (the lens, "all sections").
  var GRID_OPACITY = [0.7, 0.25];
  var LENS_OPACITY = [0.85, 0.35];

  // `count` colours evenly spaced along a ramp, interpolated in RGB
  // between its stops, so a ramp serves any number of classes.
  function sampleRamp(ramp, count) {
    if (count <= 1) return [ramp[ramp.length - 1]];
    var stops = ramp.map(function (hex) {
      return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
    });
    var out = [];
    for (var i = 0; i < count; i++) {
      var t = (i * (stops.length - 1)) / (count - 1);
      var lo = Math.floor(t), hi = Math.min(stops.length - 1, lo + 1), f = t - lo;
      var rgb = stops[lo].map(function (v, ch) { return Math.round(v + (stops[hi][ch] - v) * f); });
      out.push('#' + rgb.map(function (v) { return ('0' + v.toString(16)).slice(-2); }).join(''));
    }
    return out;
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
    var colors = sampleRamp(RAMP, count);
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

  // -- change classes --
  //
  // The same method as camp.apps.pesticides.maps.diverging_classes, so the
  // interactive map and the county figure grade a change the same way: the
  // magnitudes are quantiled and mirrored around zero, giving equal changes
  // up and down equal saturation. Classification runs on the magnitude and
  // then takes the sign; scanning the mirrored breaks would drop every
  // change smaller than the first bound into the neutral class, painting
  // the smallest decrease on the map as no change at all.
  function divergingClasses(values) {
    var neutral = DIVERGING_RAMP[DIVERGING_CENTER];
    var seen = {};
    var magnitudes = [];
    for (var i = 0; i < values.length; i++) {
      var value = values[i];
      if (!value) continue;
      var magnitude = Math.abs(value);
      if (!seen[magnitude]) {
        seen[magnitude] = true;
        magnitudes.push(magnitude);
      }
    }
    magnitudes.sort(function (a, b) { return a - b; });
    if (!magnitudes.length) {
      return { breaks: [], bounds: [], colors: [], members: [], neutral: neutral, diverging: true };
    }

    var perSide = Math.max(1, Math.min(Math.floor(NUM_CLASSES / 2), magnitudes.length));
    var bounds = [];
    for (var k = 1; k <= perSide; k++) {
      bounds.push(magnitudes[Math.ceil((k * magnitudes.length) / perSide) - 1]);
    }

    var breaks = [];
    for (var b = bounds.length - 1; b >= 0; b--) breaks.push(-bounds[b]);
    breaks.push(0);
    for (var c = 0; c < bounds.length; c++) breaks.push(bounds[c]);

    // Both halves include the centre stop then drop it, so the sides mirror
    // and the neutral class keeps the ramp's middle.
    var colors = sampleRamp(DIVERGING_RAMP.slice(0, DIVERGING_CENTER + 1), perSide + 1).slice(0, -1);
    colors.push(neutral);
    colors = colors.concat(sampleRamp(DIVERGING_RAMP.slice(DIVERGING_CENTER), perSide + 1).slice(1));

    var classes = {
      breaks: breaks, bounds: bounds, colors: colors, neutral: neutral, diverging: true,
      members: [],
    };
    for (var m = 0; m < colors.length; m++) classes.members.push([]);
    for (var v = 0; v < values.length; v++) {
      if (values[v] === null || values[v] === undefined) continue;
      classes.members[divergingIndexFor(classes, values[v])].push(values[v]);
    }
    for (var s = 0; s < classes.members.length; s++) {
      classes.members[s].sort(function (a, b) { return a - b; });
    }
    return classes;
  }

  function divergingIndexFor(classes, value) {
    var centre = classes.bounds.length;
    if (!value || !classes.bounds.length) return centre;
    var i = classes.bounds.length - 1;
    for (var k = 0; k < classes.bounds.length; k++) {
      if (Math.abs(value) <= classes.bounds[k]) { i = k; break; }
    }
    return value < 0 ? centre - 1 - i : centre + 1 + i;
  }

  // null means neither year had rows: no data, grey. 0 is a real "no
  // change" and takes the neutral centre -- collapsing the two would claim
  // a section was unsprayed in both years when nothing was reported.
  function divergingColorFor(classes, delta) {
    if (delta === null || delta === undefined) return NO_DATA_COLOR;
    if (!classes.colors.length) return classes.neutral;
    return classes.colors[divergingIndexFor(classes, delta)];
  }

  function renderLegend(el, classes, unit, caption) {
    if (classes.diverging) return renderDivergingLegend(el, classes, unit, caption);
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
    el.appendChild(noDataRow());
  }

  function noDataRow() {
    var li = document.createElement('li');
    li.innerHTML =
      '<span class="swatch" style="background-color: ' + NO_DATA_COLOR + ';"></span>' +
      '<span class="range">No data</span>';
    return li;
  }

  // Decreases, "No change", increases, then no data. The signed ranges make
  // the direction readable without the colour, which matters because a
  // diverging ramp can't be luminance-monotonic.
  function renderDivergingLegend(el, classes, unit, caption) {
    el.innerHTML = '';
    if (caption) {
      var head = document.createElement('li');
      head.className = 'legend-caption';
      head.textContent = caption;
      el.appendChild(head);
    }
    var centre = classes.bounds.length;
    for (var i = 0; i < classes.members.length; i++) {
      var values = classes.members[i];
      if (i !== centre && !values.length) continue;
      var label;
      if (i === centre) {
        label = 'No change';
      } else {
        var low = values[0];
        var high = values[values.length - 1];
        label = (low === high ? signed(low) : signed(low) + '–' + signed(high)) + ' ' + unit;
      }
      var li = document.createElement('li');
      li.innerHTML =
        '<span class="swatch" style="background-color: ' + classes.colors[i] + ';"></span>' +
        '<span class="range">' + escapeHtml(label) + '</span>';
      el.appendChild(li);
    }
    el.appendChild(noDataRow());
  }

  function signed(value) {
    return (value > 0 ? '+' : value < 0 ? '−' : '') + formatNumber(Math.abs(value));
  }

  // "Fresno County" -> "Fresno", where the label already says county.
  function shortCounty(name) {
    return /\sCounty$/.test(name) ? name.slice(0, -' County'.length) : name;
  }

  // Page URLs come from the container as patterns with `{id}` in them (see
  // views.section_map_config), so the routes live in the URLconf only.
  function fillUrl(pattern, id) {
    if (!pattern) return '';
    return pattern.replace('{id}', encodeURIComponent(id));
  }

  function linkHtml(url, text, extraClass) {
    if (!url) return escapeHtml(text);
    return '<a' + (extraClass ? ' class="' + extraClass + '"' : '') +
      ' href="' + escapeHtml(url) + '">' + escapeHtml(text) + '</a>';
  }

  function formatNumber(value) {
    var number = Number(value || 0);
    // A trace amount rounds to "0", which reads as none; say "<1" instead.
    if (number > 0 && number < 0.5) return '<1';
    try {
      return number.toLocaleString(undefined, { maximumFractionDigits: 0 });
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

  // The CDE and CDSS directories shout their names ("SELMA HIGH"). Same rule
  // as the title_case_name template filter: only touch a name that is
  // entirely upper case, so a deliberately-cased one (McKinley) is left be;
  // initialisms and roman numerals stay upper, a trailing "THE" goes back
  // to the front.
  var NAME_ACRONYMS = {USD: 1, EOC: 1, YMCA: 1, YWCA: 1, CDC: 1, CDCC: 1, CCC: 1, LLC: 1, INC: 1, KCAO: 1, CSU: 1, CSUF: 1, UC: 1, UCSF: 1, SJV: 1, CA: 1, PS: 1, HS: 1, JHS: 1, MS: 1, ES: 1, MLK: 1, JFK: 1, ABC: 1, HSA: 1, ROP: 1, STEM: 1, STEAM: 1, TK: 1};
  function titleCaseName(name) {
    var text = (name || '').replace(/\s+/g, ' ').trim();
    if (!text || text !== text.toUpperCase()) return text;
    var parts = text.split(' ');
    if (parts.length > 1 && /^(THE|A|AN)$/.test(parts[parts.length - 1])) parts.unshift(parts.pop());
    text = parts.join(' ');
    return text.replace(/[A-Za-z\u00C0-\u024F]+(?:'[A-Za-z\u00C0-\u024F]+)*/g, function (word) {
      var upper = word.toUpperCase();
      if (NAME_ACRONYMS[upper] || /^(?:[A-Z]{1,5}USD|[IVX]{2,4})$/.test(upper)) return upper;
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    });
  }

  // -- paint expressions --
  // The grids are shaded from properties the classing step writes on each
  // feature (`fill`, `opacity`, and `value`, the metric or 0), and hover is
  // a feature state, so a metric or hover change never touches the layers.
  // Whether a feature has anything to shade, written by classFeatures as
  // `shaded`. Not `value > 0`: comparing two years makes `value` the signed
  // change, so that test hid every decrease at the zooms it applies to --
  // the map showed increases only until you zoomed past
  // SECTION_LINES_MIN_ZOOM. `shaded` also keeps a change of exactly zero
  // (real, and its own legend class) apart from no data at all.
  var HAS_VALUE = ['>', ['to-number', ['get', 'shaded']], 0];

  function hoverCase(hovered, rest) {
    return ['case', ['boolean', ['feature-state', 'hover'], false], hovered, rest];
  }

  // Hovering a cell darkens and thickens its border so the reader can see
  // which square a click would open. The fill is left alone: it carries the
  // value. A cell with no reported use gets a lighter one, so the pointer
  // still lands somewhere visible (a reader finding their own square mile)
  // without drawing attention to nothing.
  var GRID_HOVER_COLOR = ['case', HAS_VALUE, '#222', '#999'];
  var LENS_HOVER_COLOR = ['case', HAS_VALUE, '#111', '#999'];

  // The townships under the lens lose their fill while it's up (a feature
  // state, see setHostFills), so the section shades aren't stacked on the
  // township shade beneath them.
  var LENS_HOST = ['boolean', ['feature-state', 'lensHost'], false];
  var GRID_FILL_OPACITY = ['case', LENS_HOST, 0, ['get', 'opacity']];

  // Sections drawn at the township zoom (the lens, "all sections"). Zoomed
  // out past SECTION_LINES_MIN_ZOOM the sections are a pixel or two:
  // no-data sections draw nothing at all (their pale wash would veil the
  // basemap across every section without use), and the rest get a hairline
  // seam in their own fill colour, which closes the gaps between
  // neighbouring fills without the grey a grid line would add.
  function sectionsFillPaint() {
    return {
      'fill-color': ['get', 'fill'],
      'fill-opacity': ['step', ['zoom'],
        ['case', HAS_VALUE, ['get', 'opacity'], 0],
        SECTION_LINES_MIN_ZOOM, ['get', 'opacity']],
    };
  }

  function sectionsLinePaint() {
    return {
      'line-color': ['step', ['zoom'],
        hoverCase(LENS_HOVER_COLOR, ['get', 'fill']),
        SECTION_LINES_MIN_ZOOM, hoverCase(LENS_HOVER_COLOR, GRID_LINE.color)],
      'line-opacity': ['step', ['zoom'],
        hoverCase(1, ['case', HAS_VALUE, ['get', 'opacity'], 0]),
        SECTION_LINES_MIN_ZOOM, hoverCase(1, GRID_LINE.opacity)],
      'line-width': ['step', ['zoom'], hoverCase(2, 1), SECTION_LINES_MIN_ZOOM, hoverCase(2, 0.5)],
    };
  }

  var COUNTY_COLOR = '#1f2d3d';
  // The page's own region (a city, ZIP, or place), in the notices orange.
  var OUTLINE_COLOR = '#d35400';
  // A wider pale line under each orange outline: two-tone, so the edge holds
  // its own over a dark class and a pale one alike.
  var CASING_COLOR = '#fff';
  var CASING_OPACITY = 0.9;
  var CASING_WIDTH = 3;
  // The locate radius circle, in Leaflet's default path style.
  var RADIUS_COLOR = '#3388ff';
  // How many vertices approximate the radius circle.
  var RADIUS_CIRCLE_POINTS = 64;

  // -- markers --
  // Orange is the notices colour throughout the explorer (the tab icon, the
  // chemicals-of-concern toggle, these markers).
  var NOTICE_COLOR = '#d35400';
  // Schools and child care markers (see loadLocations). Schools are slate,
  // child care teal; both are ringed in white like the notice markers so
  // they stay legible over a dark section fill. Teal rather than purple:
  // purple is the Chemicals section's colour, and a purple dot on a map of
  // chemical use reads as a chemical, not a day care.
  var LOCATION_COLORS = {
    public_school: '#5a6b7b',
    private_school: '#5a6b7b',
    child_care: '#1c9099',
  };
  var LOCATION_FALLBACK_COLOR = '#5a6b7b';
  // The legend rows for those markers, in the order they're listed.
  var MARKER_LEGEND = [
    { color: LOCATION_COLORS.public_school, label: 'School' },
    { color: LOCATION_COLORS.child_care, label: 'Child care' },
  ];
  // The markers' sizes: notices are the bigger dot, both ringed in white.
  // The popup offset clears the dot so its tip doesn't sit on the marker.
  var NOTICE_MARKER = { radius: 8, opacity: 0.9, stroke: 1.5 };
  var LOCATION_MARKER = { radius: 5, opacity: 0.95, stroke: 1.5 };
  // An invisible disc under each marker, wide enough for a finger, that
  // takes the marker's hover and click (see addLayers, bindMarkerEvents).
  var MARKER_HIT_RADIUS = 12;
  // Markers are points, not a grid: further out than this the viewport holds
  // thousands of them, so the layer stays off and the legend says why.
  var LOCATIONS_MIN_ZOOM = 9;
  // Mirrors MAX_BBOX_DEGREES on the locations endpoint. The padded fetch is
  // twice the viewport span (BBOX_PAD on each side), which at the layer's
  // minimum zoom on a very wide expanded map can run past the cap and come
  // back a 400 -- so when it would, the fetch goes out unpadded instead. At
  // zoom 9 the raw viewport is ~0.0027 degrees per pixel, so ~4 degrees on a
  // 1441px map (~8 padded, inside the cap) and still under the cap unpadded
  // on any plausible screen.
  var LOCATIONS_MAX_BBOX_DEGREES = 12;
  var LOCATIONS_ZOOM_NOTE = 'Zoom in to see schools and child care.';
  // "Within about a mile": a school's own square-mile section plus the ring
  // around it -- the sections whose centre is within 1.5 miles of that
  // section's centre. Same rule as stats.block_totals on the server.
  var BLOCK_MILES = 1.5;
  var BLOCK_METERS = 2414;
  var SPRAYDAYS_URL = 'https://spraydays.cdpr.ca.gov/';

  // The page's own region reads badly as a thin line over a dense grid, so
  // everything outside it is washed out: a polygon covering the world with
  // the region punched out of it. White, because the basemap under it is
  // light and the classes outside should read as "not this page".
  var OUTLINE_MASK_COLOR = '#fff';
  var OUTLINE_MASK_OPACITY = 0.55;
  var WORLD_RING = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];

  // Each part's outer ring becomes a hole. A region's own holes are left
  // covered: they aren't part of it, so they should dim with everything else.
  function maskFeature(geometry) {
    var rings = [];
    if (geometry && geometry.type === 'Polygon') {
      rings = [geometry.coordinates[0]];
    } else if (geometry && geometry.type === 'MultiPolygon') {
      rings = geometry.coordinates.map(function (part) { return part[0]; });
    }
    if (!rings.length) return EMPTY;
    return {
      type: 'Feature',
      properties: {},
      geometry: { type: 'Polygon', coordinates: [WORLD_RING].concat(rings) },
    };
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

  // -- geometry --
  // Data attributes and the Leaflet-era helpers speak "lat,lng"; the SDK
  // speaks [lng, lat]. Bounds are [[west, south], [east, north]].

  function lngLatOf(latlng) {
    return [latlng[1], latlng[0]];
  }

  // Bounds are [[west, south], [east, north]], which the SDK takes as is.
  function padBounds(bounds, ratio) {
    var dx = (bounds[1][0] - bounds[0][0]) * ratio;
    var dy = (bounds[1][1] - bounds[0][1]) * ratio;
    return [[bounds[0][0] - dx, bounds[0][1] - dy], [bounds[1][0] + dx, bounds[1][1] + dy]];
  }

  function boundsContains(outer, inner) {
    return inner[0][0] >= outer[0][0] && inner[0][1] >= outer[0][1] &&
      inner[1][0] <= outer[1][0] && inner[1][1] <= outer[1][1];
  }

  function boundsContainsPoint(bounds, lngLat) {
    return !!bounds && lngLat[0] >= bounds[0][0] && lngLat[0] <= bounds[1][0] &&
      lngLat[1] >= bounds[0][1] && lngLat[1] <= bounds[1][1];
  }

  function boundsIntersects(a, b) {
    return a[0][0] <= b[1][0] && a[1][0] >= b[0][0] && a[0][1] <= b[1][1] && a[1][1] >= b[0][1];
  }

  function boundsCenter(bounds) {
    return [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2];
  }

  function bboxParam(bounds) {
    return [bounds[0][0], bounds[0][1], bounds[1][0], bounds[1][1]].join(',');
  }

  // A feature's bounds, kept on its GeoJSON `bbox` member so each feature is
  // measured once; null for a feature without geometry.
  function featureBounds(feature) {
    if (!feature.bbox) {
      var bounds = geometryBounds(feature);
      if (!bounds) return null;
      feature.bbox = [bounds[0][0], bounds[0][1], bounds[1][0], bounds[1][1]];
    }
    return [[feature.bbox[0], feature.bbox[1]], [feature.bbox[2], feature.bbox[3]]];
  }

  // The popup HTML carries its centre the Leaflet way ({lat, lng}).
  function latLngOf(lngLat) {
    return { lat: lngLat[1], lng: lngLat[0] };
  }

  function findFeature(features, id) {
    for (var i = 0; i < features.length; i++) {
      if (features[i].properties.id === id) return features[i];
    }
    return null;
  }

  // The wider of a bounds' two spans, in degrees.
  function boundsSpan(bounds) {
    return Math.max(bounds[1][0] - bounds[0][0], bounds[1][1] - bounds[0][1]);
  }

  // Degrees covering `miles` in each direction at this latitude.
  function milesToDegrees(miles, lat) {
    return {
      lat: miles / 69,
      lng: miles / (69 * Math.max(Math.cos(lat * Math.PI / 180), 0.01)),
    };
  }

  // The `west,south,east,north` that is sure to hold the 3x3 block around
  // [lng, lat]: the point can sit at the corner of its own section, so the
  // block reaches a section further out on that side.
  function blockBbox(lngLat) {
    var pad = milesToDegrees(BLOCK_MILES + 1.1, lngLat[1]);
    return [lngLat[0] - pad.lng, lngLat[1] - pad.lat, lngLat[0] + pad.lng, lngLat[1] + pad.lat].join(',');
  }

  // Great-circle metres between two [lng, lat] points (Leaflet's
  // distanceTo: haversine on a 6371 km sphere).
  function distanceMeters(a, b) {
    var rad = Math.PI / 180;
    var lat1 = a[1] * rad;
    var lat2 = b[1] * rad;
    var sinDLat = Math.sin((b[1] - a[1]) * rad / 2);
    var sinDLng = Math.sin((b[0] - a[0]) * rad / 2);
    var h = sinDLat * sinDLat + Math.cos(lat1) * Math.cos(lat2) * sinDLng * sinDLng;
    return 2 * 6371000 * Math.asin(Math.sqrt(h));
  }

  // Sum the nine sections around [lng, lat] out of a sections response: the
  // section the point falls in, plus every section whose centre is within
  // 1.5 miles of that section's centre (stats.block_sections, client-side).
  function blockTotals(geojson, lngLat) {
    var features = ((geojson && geojson.features) || []).filter(function (f) { return f.geometry; });
    var measured = [];
    var home = null;
    for (var i = 0; i < features.length; i++) {
      var bounds = featureBounds(features[i]);
      if (!bounds) continue;
      var entry = { feature: features[i], center: boundsCenter(bounds) };
      measured.push(entry);
      if (boundsContainsPoint(bounds, lngLat) &&
          (!home || distanceMeters(entry.center, lngLat) < distanceMeters(home.center, lngLat))) {
        home = entry;
      }
    }
    if (!home) return { lbs: 0, applications: 0, lbs_prev: 0, applications_prev: 0, section: null };
    var totals = { lbs: 0, applications: 0, lbs_prev: 0, applications_prev: 0, section: home.feature.properties };
    for (var j = 0; j < measured.length; j++) {
      if (distanceMeters(measured[j].center, home.center) > BLOCK_METERS) continue;
      var props = measured[j].feature.properties;
      totals.lbs += props.lbs_chemical || 0;
      totals.applications += props.applications || 0;
      // Present only while comparing; zero otherwise, and unread.
      totals.lbs_prev += props.lbs_chemical_prev || 0;
      totals.applications_prev += props.applications_prev || 0;
    }
    return totals;
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

  function SectionMap(shell) {
    this.shell = shell;
    this.el = shell.el;
    // The container's live dataset: an adopt moves this same element into
    // the new page and rewrites its attributes, so this stays current.
    this.data = shell.data;
    this.map = shell.map;
    // The shell's, so a style swap's re-add (ensureSource) and the smoke
    // script both see what this map set.
    this.sourceData = shell.sourceData;
    this.reducedMotion = shell.reducedMotion;
    this.defaultTileStyle = this.data.style || 'dataviz';
    this.tileStyle = shell.tileStyle;
    // ?metric=applications and ?notices=1|0 preselect a view, so a link can
    // share it; the toggles write them back (see syncViewParams).
    var metricMatch = /[?&]metric=(lbs_chemical|applications)/.exec(window.location.search || '');
    this.metric = metricMatch ? metricMatch[1] : 'lbs_chemical';
    // The year being compared against, resolved by the main map's view and
    // handed over on the container (it isn't explorer scope, so no other
    // page sets it). Set, the grid shades the change between the two years;
    // it stays orthogonal to the metric, since change-in-pounds and
    // change-in-applications are both meaningful.
    this.compare = this.data.compare || '';
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
    this.counties = null;
    this.countyBounds = {};
    this.valleyBounds = null;
    this.outlineBounds = null;
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
    // What each family's request in flight covers (the grid's level and
    // bounds; bounds for the markers), so a second call while it's in the
    // air (the moveend a resize fires, see onAdopt) doesn't start the same
    // request over. Cleared when the request lands, whichever way.
    this.gridRequest = null;
    this.noticesRequest = null;
    this.locationsRequest = null;
    this.lensCache = {};
    this.pendingLocate = null;
    // The grid on the map: its features (classed in place), by id, and the
    // classes the legend shows -- over the grid, or over the "all sections"
    // layer while that stands in for the township grid.
    this.gridFeatures = [];
    this.gridById = {};
    this.currentClasses = { breaks: [], colors: [], members: [] };
    this.currentClassesAreSections = false;
    // Township outlines don't change with the filters; after the first
    // load only the numbers are fetched (see loadTownships).
    this.townshipGeometry = null;
    this.townshipGeometryBounds = null;
    // Feature ids of the popups that are open, so a rebuild can put them
    // back, and the section whose popup is (or was) open.
    this.openGridId = null;
    this.openAllSectionsId = null;
    this.openLensId = null;
    this.openNoticeId = null;
    this.openLocationId = null;
    this.selectedSectionId = null;
    // The markers on the map (notices of intent; schools and child care),
    // by id: a click gives the feature's id, and the popups read the
    // nested lists (products, chemicals) the SDK can't hand back.
    this.noticeById = {};
    this.locationById = {};
    // The one popup on the map, and whose it is (see openPopup).
    this.popup = null;
    this.popupKey = null;
    this.popupId = null;
    // The hovered feature id per source (a township and one of the lens
    // sections over it can both be hovered).
    this.hoverIds = {};
    // The lens: the hovered township (id and feature), its neighbourhood
    // (the hosts), the sections drawn and their classes, the rest and
    // clear timers, when it was last drawn, and whether a ring prefetch is
    // in flight (see showLens).
    this.lensId = null;
    this.lensHost = null;
    this.lensHosts = null;
    this.lensFeatures = [];
    this.lensClasses = { breaks: [], colors: [], members: [] };
    this.lensFetchTimer = null;
    this.lensClearTimer = null;
    this.lensDrawnAt = 0;
    this.prefetching = false;
    // "All sections": the run in progress, the reshade throttle, and what's
    // drawn (by township, and the features themselves).
    this.allSectionsRun = null;
    this.allSectionsDrawTimer = null;
    this.allSectionsAdded = null;
    this.allSectionsFeatures = [];
    this.allSectionsById = {};
    // The ramp and bins as loaded, so the URL keeps them (see syncViewParams).
    this.rampName = rampMatch && (RAMPS[rampMatch[1]] || DIVERGING_RAMPS[rampMatch[1]])
      ? rampMatch[1] : this.defaultRampName();
    this.bins = NUM_CLASSES;

    this.controlsEl = null;
    this.legendEl = null;
    this.levelEl = null;

    // For debugging from the console: document.querySelector('.section-map').sectionMap
    this.el.sectionMap = this;
  }

  // The chrome is the shell's (assets/js/maps/chrome.js); these keep the
  // names the drawing code and the smoke script use.
  Object.defineProperties(SectionMap.prototype, {
    loaded: { get: function () { return this.shell.loaded; } },
    wrapEl: { get: function () { return this.shell.wrap; } },
    toolbarEl: { get: function () { return this.shell.toolbarEl; } },
    legendPanelEl: { get: function () { return this.shell.legendPanelEl; } },
    statusEl: { get: function () { return this.shell.statusEl; } },
  });

  // The module's own controls, in the chrome the shell has just bound: the
  // Options menu (metric, layer toggles, experiment selects), the legend
  // body's elements, and the filter form's view params. Runs at build and
  // after every adopt (the swap brings new elements).
  SectionMap.prototype.onChrome = function (wrap) {
    var self = this;
    this.controlsEl = wrap.querySelector('.section-map-controls');
    this.legendEl = wrap.querySelector('.section-map-legend');
    this.levelEl = wrap.querySelector('.section-map-level');

    // The filter form only knows its own fields; the map's view settings
    // (metric, notices, all sections) ride along so the URL it lands on
    // still says how the map is being viewed.
    var form = wrap.querySelector('.map-toolbar-filters');
    if (form && !form.getAttribute('data-view-bound')) {
      form.setAttribute('data-view-bound', '1');
      form.addEventListener('htmx:configRequest', function (event) {
        var params = event.detail.parameters;
        if (self.metric !== 'lbs_chemical') params.metric = self.metric;
        if (self.showNotices !== (self.data.showNotices !== '0')) params.notices = self.showNotices ? '1' : '0';
        if (self.showLocations !== (self.data.showLocations === '1')) params.locations = self.showLocations ? '1' : '0';
        if (self.showAllSections) params.sections = '1';
      });
    }

    if (this.controlsEl) {
      var controls = this.controlsEl;
      Array.prototype.forEach.call(controls.querySelectorAll('input[name="metric"]'), function (radio) {
        radio.addEventListener('change', self.onMetricChange.bind(self));
      });
      var bindChange = function (selector, handler) {
        var input = controls.querySelector(selector);
        if (input) input.addEventListener('change', handler.bind(self));
        return input;
      };
      bindChange('input[name="notices"]', this.onNoticesToggle);
      bindChange('input[name="locations"]', this.onLocationsToggle);
      bindChange('input[name="sections"]', this.onSectionsToggle);
      // Experiment controls: basemap style, colour ramp and bins, applied
      // live and written to the URL (?tiles=, ?ramp=, ?bins=).
      var fill = function (select, pairs) {
        pairs.forEach(function (pair) {
          var option = document.createElement('option');
          option.value = pair[0];
          option.textContent = pair[1];
          select.appendChild(option);
        });
      };
      var tiles = bindChange('select[name="tiles"]', this.onTilesChange);
      if (tiles) fill(tiles, TILE_STYLES.map(function (style) { return [style, style]; }));
      this.rampSelect = bindChange('select[name="ramp"]', this.onRampChange);
      this.fillRampOptions = function () {
        // Diverging names while comparing: a sequential ramp can't grade
        // signed data, and vice versa.
        if (!self.rampSelect) return;
        self.rampSelect.innerHTML = '';
        fill(self.rampSelect, Object.keys(self.compare ? DIVERGING_RAMPS : RAMPS)
          .map(function (name) { return [name, name]; }));
        self.rampSelect.value = self.rampName;
      };
      this.fillRampOptions();
      var bins = bindChange('select[name="bins"]', this.onBinsChange);
      if (bins) fill(bins, BIN_OPTIONS.map(function (pair) { return [pair[0], pair[1] + ' (' + pair[0] + ')']; }));

    }
    this.syncControls();
  };

  // Puts the Options controls in line with this map's view: after a bind,
  // and after an adopt that changed a default (see onAdopt).
  SectionMap.prototype.syncControls = function () {
    if (!this.controlsEl) return;
    var controls = this.controlsEl;
    var metric = this.metric;
    Array.prototype.forEach.call(controls.querySelectorAll('input[name="metric"]'), function (radio) {
      radio.checked = radio.value === metric;
    });
    var set = function (selector, prop, value) {
      var input = controls.querySelector(selector);
      if (input) input[prop] = value;
    };
    set('input[name="notices"]', 'checked', this.showNotices);
    set('input[name="locations"]', 'checked', this.showLocations);
    set('input[name="sections"]', 'checked', this.showAllSections);
    set('select[name="tiles"]', 'value', this.tileStyle);
    set('select[name="ramp"]', 'value', this.rampName);
    set('select[name="bins"]', 'value', String(this.bins));
  };

  // A toolbar dropdown opened over the map: let go of the popup under it.
  SectionMap.prototype.onDropdownOpen = function () {
    if (this.popup) this.popup.remove();
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
    // The legend's marker rows follow the toggle (see appendMarkerLegend).
    this.updateLegend();
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
    // The legend's marker rows and the zoom note follow the toggle.
    this.updateLegend();
  };

  // Fetch and draw: the shell has built the map, its controls and chrome.
  SectionMap.prototype.load = function () {
    var self = this;
    var center = this.parseCenter(this.data.center) || [36.75, -119.80];

    // Escape closes the open popup, as Leaflet's did (closeOnEscapeKey);
    // the SDK's popup only closes from its button. Removing it is the
    // reader letting go (see the popup's close handler in openPopup).
    this.el.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && self.popup) self.popup.remove();
    });
    // The markers sit over the grid, so their click handlers are bound
    // first: layer listeners run in binding order, and a marker's marks
    // the click as taken before the grid's sees it.
    this.bindMarkerEvents();
    this.bindGridEvents();

    this.drawRadius(center);

    var debouncedLoad = debounce(this.loadGrid.bind(this), DEBOUNCE_MS);
    var debouncedNotices = debounce(this.loadNotices.bind(this), DEBOUNCE_MS);
    var debouncedLocations = debounce(this.loadLocations.bind(this), DEBOUNCE_MS);
    // moveend follows every camera change, a zoom included.
    this.map.on('moveend', debouncedLoad);
    this.map.on('moveend', debouncedNotices);
    this.map.on('moveend', debouncedLocations);
    // Section strokes switch on/off across SECTION_LINES_MIN_ZOOM.
    this.map.on('zoomend', this.restyleSectionLines.bind(this));

    // A page framed by a fit that follows the counties (the valley, or a
    // county filter) would otherwise load its grid at the placeholder view
    // and again where the fit lands: the loaders wait for the fit instead
    // (see settleFit).
    this.pendingFit = !!this.data.countiesUrl && (this.data.fit === 'valley' || !!this.data.county);
    this.loadCounties();
    this.loadOutline();
    this.loadGrid();
    this.loadNotices();
    this.loadLocations();
  };

  // -- sources and layers --

  // GeoJSON sources are keyed on our own feature ids (`promoteId`), so
  // feature state (hover, selection) can address them by id.
  SectionMap.prototype.ensureSource = function (id) { this.shell.ensureSource(id); };

  // Added on top of the whole basemap, labels included: the reader is here
  // for the data, and a place name or a road drawn over a shaded section
  // competes with it. The basemap still shows through everywhere the data
  // doesn't cover.
  SectionMap.prototype.ensureLayer = function (spec) { this.shell.ensureLayer(spec); };

  // Sets a source's data, remembering it for the next style load; before
  // the style is up the data just waits there for ensureSource. Nothing
  // to keep once the map is gone (a late response after destroy()).
  SectionMap.prototype.setSourceData = function (id, data) { this.shell.setSourceData(id, data); };

  // Our sources and their layers, bottom to top, all under the basemap's
  // labels: the fills (the radius circle, the grid, the sections drawn
  // over it at the township zoom -- "all sections", then the lens -- and
  // the page's own outline's wash), then the lines (the grids' strokes,
  // the hovered township's outline over the lens, the selected and
  // highlighted sections' outlines, the county lines, the page's own
  // outline), the school and child care markers, the notice markers; the
  // shell adds the reader's located position (`locate`/`locate-circle`)
  // after these, so it stays on top of every marker.
  // Idempotent, so it can run on every style load.
  SectionMap.prototype.addLayers = function () {
    this.ensureSource('radius');
    this.ensureSource('grid');
    this.ensureSource('all-sections');
    this.ensureSource('lens');
    this.ensureSource('lens-outline');
    this.ensureSource('selected');
    this.ensureSource('highlight');
    this.ensureSource('counties');
    this.ensureSource('outline');
    this.ensureSource('outline-mask');
    this.ensureSource('locations');
    this.ensureSource('notices');

    this.ensureLayer({
      id: 'radius-fill', type: 'fill', source: 'radius',
      paint: { 'fill-color': RADIUS_COLOR, 'fill-opacity': 0.2 },
    });
    this.ensureLayer({
      id: 'radius-line', type: 'line', source: 'radius',
      paint: { 'line-color': RADIUS_COLOR, 'line-width': 3 },
    });
    // The grid: the fills carry the data, over a faint base grid that
    // darkens on hover. Its opacity and widths follow the level and step
    // aside under "all sections" (see applyGridPaint).
    this.ensureLayer({
      id: 'grid-fill', type: 'fill', source: 'grid',
      paint: { 'fill-color': ['get', 'fill'], 'fill-opacity': GRID_FILL_OPACITY },
    });
    this.ensureLayer({
      id: 'grid-line', type: 'line', source: 'grid',
      paint: {
        'line-color': hoverCase(GRID_HOVER_COLOR, GRID_LINE.color),
        'line-opacity': hoverCase(1, GRID_LINE.opacity),
        'line-width': hoverCase(2, 0.5),
      },
    });
    // Every section in view at the township zoom ("all sections"), and the
    // lens (the hovered township's neighbourhood, see showLens): the same
    // paint, see sectionsFillPaint/sectionsLinePaint.
    this.ensureLayer({ id: 'all-sections-fill', type: 'fill', source: 'all-sections', paint: sectionsFillPaint() });
    this.ensureLayer({ id: 'all-sections-line', type: 'line', source: 'all-sections', paint: sectionsLinePaint() });
    this.ensureLayer({ id: 'lens-fill', type: 'fill', source: 'lens', paint: sectionsFillPaint() });
    this.ensureLayer({ id: 'lens-line', type: 'line', source: 'lens', paint: sectionsLinePaint() });
    // The hovered township's own outline, over the lens sections (which
    // would otherwise paint over its hover border), in the township hover
    // stroke of a township with data, the only kind that gets one (see
    // drawLensOutline).
    this.ensureLayer({
      id: 'lens-outline', type: 'line', source: 'lens-outline',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': '#222', 'line-opacity': 1, 'line-width': 2.5 },
    });
    // Everything outside the page's own region, washed out (see maskFeature).
    // Over the grid and the lens, under every outline and marker.
    this.ensureLayer({
      id: 'outline-mask', type: 'fill', source: 'outline-mask',
      paint: { 'fill-color': OUTLINE_MASK_COLOR, 'fill-opacity': OUTLINE_MASK_OPACITY },
    });
    // The section whose popup is open, and the page's own section.
    this.ensureLayer({
      id: 'selected-line', type: 'line', source: 'selected',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': SELECTED_LINE.color, 'line-opacity': SELECTED_LINE.opacity, 'line-width': SELECTED_LINE.width },
    });
    this.ensureLayer({
      id: 'highlight-casing', type: 'line', source: 'highlight',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': CASING_COLOR, 'line-opacity': CASING_OPACITY, 'line-width': HIGHLIGHT_LINE.width + CASING_WIDTH },
    });
    this.ensureLayer({
      id: 'highlight-line', type: 'line', source: 'highlight',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': HIGHLIGHT_LINE.color, 'line-opacity': HIGHLIGHT_LINE.opacity, 'line-width': HIGHLIGHT_LINE.width },
    });
    this.ensureLayer({
      id: 'counties-line', type: 'line', source: 'counties',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': COUNTY_COLOR, 'line-width': 1.5, 'line-opacity': 0.8 },
    });
    // The region this page is about, shaded faintly and outlined.
    this.ensureLayer({
      id: 'outline-fill', type: 'fill', source: 'outline',
      paint: { 'fill-color': OUTLINE_COLOR, 'fill-opacity': 0.08 },
    });
    this.ensureLayer({
      id: 'outline-casing', type: 'line', source: 'outline',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': CASING_COLOR, 'line-opacity': CASING_OPACITY, 'line-width': 2.5 + CASING_WIDTH },
    });
    this.ensureLayer({
      id: 'outline-line', type: 'line', source: 'outline',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': OUTLINE_COLOR, 'line-width': 2.5, 'line-opacity': 0.9 },
    });
    // The markers: schools and child care (coloured by type), and over
    // them the notices of intent. Both sit over the grid and outlines and
    // under the reader's located position. The locations layer hides
    // itself below the zoom the markers load at (see loadLocations, which
    // clears the source there too). Under each marker layer is its hit
    // disc: invisible, wide enough for a finger, taking the same hover and
    // click as the marker (see bindMarkerEvents).
    this.ensureLayer({
      id: 'locations-hit', type: 'circle', source: 'locations',
      minzoom: LOCATIONS_MIN_ZOOM,
      paint: { 'circle-radius': MARKER_HIT_RADIUS, 'circle-opacity': 0, 'circle-stroke-width': 0 },
    });
    this.ensureLayer({
      id: 'locations-circle', type: 'circle', source: 'locations',
      minzoom: LOCATIONS_MIN_ZOOM,
      paint: {
        'circle-radius': LOCATION_MARKER.radius,
        'circle-color': ['match', ['get', 'type'],
          'public_school', LOCATION_COLORS.public_school,
          'private_school', LOCATION_COLORS.private_school,
          'child_care', LOCATION_COLORS.child_care,
          LOCATION_FALLBACK_COLOR],
        'circle-opacity': LOCATION_MARKER.opacity,
        'circle-stroke-color': '#fff',
        'circle-stroke-width': LOCATION_MARKER.stroke,
      },
    });
    this.ensureLayer({
      id: 'notices-hit', type: 'circle', source: 'notices',
      paint: { 'circle-radius': MARKER_HIT_RADIUS, 'circle-opacity': 0, 'circle-stroke-width': 0 },
    });
    this.ensureLayer({
      id: 'notices-circle', type: 'circle', source: 'notices',
      paint: {
        'circle-radius': NOTICE_MARKER.radius,
        'circle-color': NOTICE_COLOR,
        'circle-opacity': NOTICE_MARKER.opacity,
        'circle-stroke-color': '#fff',
        'circle-stroke-width': NOTICE_MARKER.stroke,
      },
    });
    this.applyGridPaint();
    // Feature state (hover, the lens hosts) didn't survive a style swap:
    // forget the hovers (the next pointer move sets them again) and put
    // the lens hosts' state back if the lens is up.
    this.hoverIds = {};
    this.map.getCanvas().style.cursor = '';
    if (this.lensHosts) this.setHostFills(false);
  };

  // Home goes back to what the page is about: its own region when it has
  // one (the counties around it are context, not the subject), then its
  // county, then the whole valley; before the counties load, the shell's
  // fallback (the page's centre and zoom).
  SectionMap.prototype.home = function () {
    var bounds = this.outlineBounds || this.countyBounds[this.data.county] || this.valleyBounds;
    return bounds ? { bounds: bounds, padding: this.outlineBounds ? 24 : 20 } : null;
  };

  // The shell has found the reader and dropped the dot; zoom to their
  // square mile and select it once the section grid is on the map there
  // (the grid's render calls resolvePendingLocate).
  SectionMap.prototype.onLocate = function (lngLat) {
    this.pendingLocate = [lngLat[1], lngLat[0]];
    this.map.easeTo({ center: lngLat, zoom: this.sectionZoom(), animate: !this.reducedMotion });
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
  var DATA_KEYS = ['year', 'chemical', 'product', 'commodity', 'county', 'concern', 'compare'];

  // An htmx swap handed this map a new container (the shell has moved the
  // map into it, taken its data attributes and bound its chrome): follow
  // the page's defaults and refetch only what changed.
  SectionMap.prototype.onAdopt = function (changed) {
    var has = function (key) { return changed.indexOf(key) !== -1; };

    // A swap to a different page brings its own notices default with it;
    // adopt it so the checkbox and the layer agree with the page the reader
    // is now on. An unchanged attribute leaves their own toggle alone.
    var noticesDefaultChanged = has('showNotices');
    if (noticesDefaultChanged) {
      this.showNotices = this.data.showNotices !== '0';
      this.loadedNoticeBounds = null;
      if (!this.showNotices) {
        // A request already in flight would otherwise land after the swap
        // and put the markers back on a page that doesn't want them.
        if (this.noticesAbort) this.noticesAbort.abort();
        this.clearNotices();
      }
    }

    var locationsDefaultChanged = has('showLocations');
    if (locationsDefaultChanged) {
      this.showLocations = this.data.showLocations === '1';
      this.loadedLocationBounds = null;
      if (!this.showLocations) {
        if (this.locationsAbort) this.locationsAbort.abort();
        this.clearLocations();
      }
    }

    // The view re-resolves the comparison on every swap (a year change can
    // invalidate it), so take whatever the new container says. The ramp
    // table follows it: a sequential ramp can't grade signed data.
    if (has('compare')) {
      this.compare = this.data.compare || '';
      this.rampName = this.defaultRampName();
      if (this.fillRampOptions) this.fillRampOptions();
    }

    this.syncControls();

    var dataChanged = DATA_KEYS.some(has);
    var countyChanged = has('county');
    var viewChanged = has('center') || has('zoom');
    var radiusChanged = has('radius');
    var outlineChanged = has('outlineUrl');

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
      // A request in flight was for the old filters: it no longer covers
      // anything (the loaders below abort it).
      this.gridRequest = null;
      this.noticesRequest = null;
      this.locationsRequest = null;
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

  // Lets go of everything once its page is gone: requests in flight are cut
  // short so nothing lands on a map that isn't there.
  SectionMap.prototype.destroy = function () {
    this.abortRequests();
    this.allSectionsRun = null;
    this.cancelAllSectionsDraw();
    this.clearLens();
    this.closePopup();
    this.gridFeatures = [];
    this.gridById = {};
    this.noticeById = {};
    this.locationById = {};
    // The shell removes the map (and its WebGL context) after this.
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
        // No fit is coming; the grid loads where the map is.
        self.settleFit();
      });
  };

  // The fit the loaders were waiting for has been made (or isn't coming):
  // they run now, once, for where it lands. An animated fit is still
  // moving here, so they defer to its moveend (see loadGrid); a snap has
  // already fired its moveend, whose debounced loads find these in flight.
  SectionMap.prototype.settleFit = function () {
    if (!this.pendingFit) return;
    this.pendingFit = false;
    this.loadGrid();
    this.loadNotices();
    this.loadLocations();
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
      // frames itself (onAdopt() sets its view), and clearing the county
      // there must not zoom back out over it. The first-load fit snaps
      // rather than animating out from the placeholder view.
      var animate = !!this.valleyFitted && !this.reducedMotion;
      this.map.fitBounds(this.valleyBounds, { padding: 20, animate: animate });
      this.valleyFitted = true;
    }
    this.countyFitted = !!target;
    this.settleFit();
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
        self.setSourceData('outline-mask', maskFeature(geometry));
        self.outlineBounds = geometryBounds(feature);
        self.map.fitBounds(self.outlineBounds, { padding: 24, animate: !self.reducedMotion });
      })
      .catch(function (err) {
        if (isAbort(err) || self.outlineAbort !== abort) return;
        logError('failed to load the region outline', err);
      });
  };

  SectionMap.prototype.clearOutline = function () {
    if (this.outlineAbort) this.outlineAbort.abort();
    this.setSourceData('outline', EMPTY);
    this.setSourceData('outline-mask', EMPTY);
    this.outlineBounds = null;
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

  SectionMap.prototype.setStatus = function (message) { this.shell.setStatus(message); };

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

  // Which ramp this view draws with when `?ramp=` says nothing. The change
  // view and the ordinary one have different defaults, so the URL sync has
  // to ask rather than assume 'blues'.
  SectionMap.prototype.defaultRampName = function () {
    return this.compare ? 'rdbu' : 'blues';
  };

  SectionMap.prototype.onRampChange = function (event) {
    var name = event.target.value;
    var table = this.compare ? DIVERGING_RAMPS : RAMPS;
    if (!table[name]) return;
    if (this.compare) {
      DIVERGING_RAMP = DIVERGING_RAMPS[name];
      DIVERGING_CENTER = (DIVERGING_RAMP.length - 1) / 2;
    } else {
      RAMP = RAMPS[name];
    }
    this.rampName = name;
    // The lens goes (restyle would otherwise redraw it first); the next
    // hover draws it with the new ramp.
    this.clearLens();
    this.restyle();
    this.syncViewParams();
  };

  SectionMap.prototype.onBinsChange = function (event) {
    NUM_CLASSES = +event.target.value;
    this.bins = NUM_CLASSES;
    this.clearLens();
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
      if (this.rampName && this.rampName !== this.defaultRampName()) {
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
      compare: this.compare,
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

  // -- the grid --
  // Picks the grid for the current zoom: sections up close, townships
  // further out. Either way exactly one grid is in the `grid` source.
  SectionMap.prototype.loadGrid = function () {
    if (!this.map || this.pendingFit) return;
    // Mid-animation the viewport is nowhere yet: the moveend that ends the
    // animation loads the grid for where it lands. (A resize also fires
    // moveend, and its debounced load can fall inside a fit's animation.)
    if (this.map.isMoving()) return;
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
    // The same grid is already on its way (a resize fires moveend even at
    // an unchanged size, so the debounced load follows the immediate one).
    if (this.gridRequest && this.gridRequest.level === level && this.covers(this.gridRequest.bounds)) return;
    if (level === 'section') {
      this.loadSections();
    } else {
      this.loadTownships();
    }
  };

  // The viewport as [[west, south], [east, north]].
  SectionMap.prototype.mapBounds = function () {
    var bounds = this.map.getBounds();
    return [[bounds.getWest(), bounds.getSouth()], [bounds.getEast(), bounds.getNorth()]];
  };

  // True when `bounds` (from a previous padded fetch) still contains the
  // current viewport.
  SectionMap.prototype.covers = function (bounds) {
    return !!bounds && boundsContains(bounds, this.mapBounds());
  };

  SectionMap.prototype.fetchBounds = function (unpadded) {
    var bounds = this.mapBounds();
    return unpadded ? bounds : padBounds(bounds, BBOX_PAD);
  };

  SectionMap.prototype.loadSections = function (unpadded) {
    if (!this.data.sectionsUrl) return;
    var abort = this.startRequest('grid');
    var bounds = this.fetchBounds(unpadded);
    var request = this.gridRequest = { level: 'section', bounds: bounds };
    var params = this.commonParams();
    params.bbox = bboxParam(bounds);
    this.setStatus('Loading sections…');

    var self = this;
    fetchJson(this.data.sectionsUrl, params, abort)
      .then(function (geojson) {
        if (self.gridRequest === request) self.gridRequest = null;
        if (self.gridAbort !== abort) return; // stale response
        self.setStatus('');
        self.loadedBounds = bounds;
        self.loadedLevel = 'section';
        self.renderGrid(geojson, 'section');
      })
      .catch(function (err) {
        if (self.gridRequest === request) self.gridRequest = null;
        if (isAbort(err) || self.gridAbort !== abort) return;
        if (err.status === 400) {
          // The endpoint caps how many sections it will return, and the padded
          // bbox asks for more than the viewport needs. Try the bare viewport
          // once, then fall back to the township grid rather than leaving the
          // map bare.
          if (!unpadded) {
            self.loadSections(true);
          } else {
            self.loadTownships();
          }
          return;
        }
        if (err.status) {
          // The server answered, but not with a grid.
          self.clearGrid();
          if (self.legendEl) self.legendEl.innerHTML = '';
        } else {
          logError('failed to load sections', err);
        }
        self.loadedBounds = null;
        self.loadedLevel = null;
        self.setStatus('Couldn\'t load sections; try again');
      });
  };

  SectionMap.prototype.loadTownships = function () {
    if (!this.data.townshipsUrl) return;
    var abort = this.startRequest('grid');
    var bounds = this.fetchBounds();
    var request = this.gridRequest = { level: 'township', bounds: bounds };
    var params = this.commonParams();
    params.bbox = bboxParam(bounds);
    // Outlines don't change between years or filters, so after the first
    // load only the numbers are requested and the outlines are re-attached
    // from the cache (see attachTownshipGeometry). A township outside what
    // was cached (a wider bbox) falls back to a full request.
    var valuesOnly = !!this.townshipGeometry && this.townshipGeometryCovers(bounds);
    if (valuesOnly) params.geometry = '0';
    this.setStatus('Loading grid…');

    var self = this;
    fetchJson(this.data.townshipsUrl, params, abort)
      .then(function (geojson) {
        if (self.gridRequest === request) self.gridRequest = null;
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
        if (self.gridRequest === request) self.gridRequest = null;
        if (isAbort(err) || self.gridAbort !== abort) return;
        logError('failed to load townships', err);
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
    this.townshipGeometryBounds = [[bounds[0][0], bounds[0][1]], [bounds[1][0], bounds[1][1]]];
  };

  SectionMap.prototype.townshipGeometryCovers = function (bounds) {
    return !!this.townshipGeometryBounds && boundsContains(this.townshipGeometryBounds, bounds);
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

  SectionMap.prototype.allSectionsActive = function () {
    return this.showAllSections && this.level === 'township';
  };

  // Writes each feature's shade onto its properties for the paint to read:
  // `value` (the metric, 0 for none), `fill`, and `opacity` from
  // `opacities` ([with data, without]).
  // What a feature is shaded by: the metric, or the change in it against the
  // compared year. null means neither year had rows -- no data, which stays
  // distinct from a change of exactly zero.
  SectionMap.prototype.valueFor = function (props) {
    var value = Number(props[this.metric]) || 0;
    if (!this.compare) return value;
    var previous = Number(props[this.metric + '_prev']) || 0;
    if (!value && !previous) return null;
    return value - previous;
  };

  // The classes for a set of features, diverging while comparing.
  SectionMap.prototype.classify = function (features) {
    var self = this;
    var values = features.map(function (feature) { return self.valueFor(feature.properties); });
    return this.compare ? divergingClasses(values) : quantileClasses(values);
  };

  SectionMap.prototype.classFeatures = function (features, classes, opacities) {
    for (var i = 0; i < features.length; i++) {
      var props = features[i].properties;
      var value = this.valueFor(props);
      var missing = value === null || (!classes.diverging && !value);
      props.value = value === null ? 0 : value;
      props.shaded = missing ? 0 : 1;
      props.fill = classes.diverging ? divergingColorFor(classes, value) : colorFor(classes, value);
      props.opacity = missing ? opacities[1] : opacities[0];
    }
  };

  SectionMap.prototype.renderGrid = function (geojson, level) {
    var self = this;
    var reopenId = this.openGridId;
    this.level = level;
    var features = (geojson && geojson.features) || [];
    this.currentClasses = this.classify(features);
    this.currentClassesAreSections = false;

    // The lens and the "all sections" layer were drawn over the grid this
    // one replaces; the selected section's outline comes back with
    // whichever section layer next holds it (see reopenSelectedSection).
    this.clearLens();
    this.resetAllSections();
    this.showSelectedOutline(null);
    this.clearHover('grid');

    this.gridFeatures = features;
    this.gridById = {};
    for (var i = 0; i < features.length; i++) this.gridById[features[i].properties.id] = features[i];
    this.classFeatures(features, this.currentClasses, GRID_OPACITY);
    this.setSourceData('grid', { type: 'FeatureCollection', features: features });
    this.applyGridPaint();
    this.updateHighlight();
    this.updateLegend();
    this.reopenGridPopup(reopenId);
    if (level === 'section') {
      this.reopenSelectedSection(features, 'grid');
      this.resolvePendingLocate();
    }
  };

  SectionMap.prototype.clearGrid = function () {
    this.clearLens();
    this.resetAllSections();
    this.showSelectedOutline(null);
    this.clearHover('grid');
    // No grid cell is left for a popup to belong to (clearLens and
    // resetAllSections above keep theirs only for a grid about to load).
    if (this.popup && ['openGridId', 'openLensId', 'openAllSectionsId'].indexOf(this.popupKey) !== -1) this.closePopup();
    this.gridFeatures = [];
    this.gridById = {};
    this.setSourceData('grid', EMPTY);
    this.setSourceData('highlight', EMPTY);
  };

  // The grid's paint follows the level (township lines are a touch
  // heavier, and their hover stroke too) and, with every section drawn on
  // top ("all sections"), the township grid steps aside: no fill, no line,
  // just the interactive shape.
  SectionMap.prototype.applyGridPaint = function () {
    if (!this.map || !this.map.getLayer('grid-fill')) return;
    var hidden = this.allSectionsActive();
    var township = this.level === 'township';
    this.map.setPaintProperty('grid-fill', 'fill-opacity', hidden ? 0 : GRID_FILL_OPACITY);
    this.map.setPaintProperty('grid-line', 'line-opacity', hidden ? 0 : hoverCase(1, GRID_LINE.opacity));
    this.map.setPaintProperty('grid-line', 'line-width', hoverCase(township ? 2.5 : 2, township ? 0.75 : 0.5));
  };

  // The page's own section (a section page) wears an orange outline while
  // the section grid is up.
  SectionMap.prototype.updateHighlight = function () {
    var feature = this.level === 'section' && this.data.highlight ? this.gridById[this.data.highlight] : null;
    this.setSourceData('highlight', feature || EMPTY);
  };

  // Reclasses the grid (a metric, ramp, or bins change) and reshades it in
  // place; a township popup's headline follows the metric.
  SectionMap.prototype.restyle = function () {
    if (!this.map || !this.gridFeatures.length) return;
    var self = this;
    this.currentClasses = this.classify(this.gridFeatures);
    this.currentClassesAreSections = false;
    this.classFeatures(this.gridFeatures, this.currentClasses, GRID_OPACITY);
    this.setSourceData('grid', { type: 'FeatureCollection', features: this.gridFeatures });
    this.applyGridPaint();
    this.updateHighlight();
    if (this.level === 'township' && this.popup && this.popupKey === 'openGridId') {
      var feature = this.gridById[this.popupId];
      if (feature) this.popup.setHTML(this.townshipPopupHtml(feature.properties, latLngOf(boundsCenter(featureBounds(feature)))));
    }
    // A lens that's up (a metric change under it, possibly pinned by one
    // of its popups) is reclassed in place rather than left in the old
    // metric's shades over townships that just got their fill back.
    if (this.lensId && this.lensFeatures.length) this.drawLens(this.lensId, this.lensFeatures);
    if (this.allSectionsActive() && this.allSectionsAdded) {
      this.restyleAllSections();
    } else {
      this.updateLegend();
    }
  };

  // Sections drawn at the township zoom (the lens, "all sections") switch
  // between fill-only and stroked across SECTION_LINES_MIN_ZOOM. The paint
  // does that by itself (a zoom step), so crossing it only drops the lens,
  // which is redrawn with the right strokes on the next hover.
  SectionMap.prototype.restyleSectionLines = function () {
    var lines = this.map.getZoom() >= SECTION_LINES_MIN_ZOOM;
    if (lines === this.sectionLinesShown) return;
    this.sectionLinesShown = lines;
    this.clearLens();
  };

  SectionMap.prototype.legendUnit = function () {
    var unit = METRIC_UNITS[this.metric] || '';
    if (this.level === 'township' && !this.allSectionsActive()) unit += ' per township';
    return unit;
  };

  // Named once above the rows rather than repeated on each: "Change, 2022 to
  // 2023". In order, so a signed range never has to be read against the
  // colour alone -- a diverging ramp can't be luminance-monotonic.
  SectionMap.prototype.legendCaption = function () {
    if (!this.compare) return '';
    return 'Change, ' + this.compare + ' to ' + this.data.year;
  };

  SectionMap.prototype.updateLegend = function () {
    if (this.legendEl) {
      renderLegend(this.legendEl, this.currentClasses, this.legendUnit(), this.legendCaption());
      this.appendMarkerLegend();
    }
    // "All sections" only means something at the township zoom.
    var sectionsToggle = this.controlsEl ? this.controlsEl.querySelector('input[name="sections"]') : null;
    if (sectionsToggle) sectionsToggle.disabled = this.level === 'section';
    if (this.levelEl) {
      this.levelEl.textContent = this.allSectionsActive() ? LEVEL_TEXT.allSections : (LEVEL_TEXT[this.level] || '');
    }
    this.updateLocationsNote();
  };

  // -- markers: hover and click --
  // Bound once, before the grid's listeners (see init): a click on a marker
  // is the marker's, not the cell under it. Notices sit over locations, so
  // a notice takes a click where the two overlap.
  // Each marker layer and its hit disc (see addLayers) share one set of
  // handlers; the disc is bound after the marker, so a pointer sliding off
  // the dot into the disc is re-hovered in the same event.
  SectionMap.prototype.bindMarkerEvents = function () {
    var self = this;
    var map = this.map;
    var onNoticeMove = function (event) { self.setHover('notices', event.features[0].id); };
    var onNoticeLeave = function () { self.clearHover('notices'); };
    var onNoticeClick = function (event) {
      if (event.originalEvent.sectionMapTaken) return;
      var feature = self.noticeById[event.features[0].id];
      if (!feature) return;
      event.originalEvent.sectionMapTaken = true;
      self.openNoticePopup(feature);
    };
    var onLocationMove = function (event) { self.setHover('locations', event.features[0].id); };
    var onLocationLeave = function () { self.clearHover('locations'); };
    var onLocationClick = function (event) {
      if (event.originalEvent.sectionMapTaken) return;
      var feature = self.locationById[event.features[0].id];
      if (!feature) return;
      event.originalEvent.sectionMapTaken = true;
      self.openLocationPopup(feature);
    };
    ['notices-circle', 'notices-hit'].forEach(function (layer) {
      map.on('mousemove', layer, onNoticeMove);
      map.on('mouseleave', layer, onNoticeLeave);
      map.on('click', layer, onNoticeClick);
    });
    ['locations-circle', 'locations-hit'].forEach(function (layer) {
      map.on('mousemove', layer, onLocationMove);
      map.on('mouseleave', layer, onLocationLeave);
      map.on('click', layer, onLocationClick);
    });
  };

  // -- hover and click --
  // Bound once: the SDK keeps layer listeners across style swaps and skips
  // a layer that isn't in the style yet.
  SectionMap.prototype.bindGridEvents = function () {
    var self = this;
    var map = this.map;
    map.on('mousemove', 'grid-fill', function (event) {
      // Under "all sections" the townships are only click plumbing.
      if (self.allSectionsActive()) return;
      var id = event.features[0].id;
      if (self.level === 'township') {
        // Hovering a township brings up its lens; the pointer is still
        // over the township while it's over one of the lens sections, so
        // a scheduled clear is cancelled here as well as there.
        self.cancelLensClear();
        if (self.lensId !== id) {
          var feature = self.gridById[id];
          if (feature) self.showLens(feature);
        }
      }
      self.setHover('grid', id);
    });
    map.on('mouseleave', 'grid-fill', function () {
      self.clearHover('grid');
      // Off the grid: the lens goes after its grace, unless the pointer
      // comes back onto a township (or one of the lens sections) first.
      if (self.level === 'township' && self.lensId) self.scheduleLensClear();
    });
    // The lens sections cover the townships, so this is where a move into
    // a neighbouring township is noticed too: recentre the lens on it.
    map.on('mousemove', 'lens-fill', function (event) {
      self.cancelLensClear();
      var feature = findFeature(self.lensFeatures, event.features[0].id);
      if (!feature || self.recentreLens(feature)) return;
      self.setHover('lens', event.features[0].id);
    });
    map.on('mouseleave', 'lens-fill', function () {
      self.clearHover('lens');
      // Delegated listeners run in binding order within one event, so on
      // a move from a lens section straight onto a township outside the
      // block the grid handler above has already recentred the lens on it
      // (and hovered it) by the time this runs; scheduling a clear then
      // would drop the new lens once the pointer rests (nothing cancels
      // it). Leaving the grid altogether clears the township hover first
      // (its own mouseleave), so the clear is scheduled only then.
      if (self.hoverIds.grid != null && self.hoverIds.grid === self.lensId) return;
      self.scheduleLensClear();
    });
    map.on('mousemove', 'all-sections-fill', function (event) {
      self.setHover('all-sections', event.features[0].id);
    });
    map.on('mouseleave', 'all-sections-fill', function () { self.clearHover('all-sections'); });
    // Sections drawn over the townships take the click; a township is
    // reached where no section covers it. Layer listeners fire in the order
    // they're bound, so the section ones mark the event as taken.
    map.on('click', 'lens-fill', function (event) {
      if (event.originalEvent.sectionMapTaken) return; // a marker's
      var feature = findFeature(self.lensFeatures, event.features[0].id);
      if (!feature) return;
      event.originalEvent.sectionMapTaken = true;
      self.showSectionPopup(feature, 'lens');
    });
    map.on('click', 'all-sections-fill', function (event) {
      if (event.originalEvent.sectionMapTaken) return; // a marker's
      var feature = self.allSectionsById[event.features[0].id];
      if (!feature) return;
      event.originalEvent.sectionMapTaken = true;
      self.showSectionPopup(feature, 'all-sections');
    });
    map.on('click', 'grid-fill', function (event) {
      if (event.originalEvent.sectionMapTaken) return;
      var feature = self.gridById[event.features[0].id];
      if (!feature) return;
      if (self.level === 'township') {
        self.openTownshipPopup(feature);
      } else {
        self.showSectionPopup(feature, 'grid');
      }
    });
  };

  // Hover is a feature state, one cell per source (the township under the
  // pointer and the lens section over it are hovered together); the line
  // paint reads it (see addLayers). The cursor is a pointer over any
  // hovered cell.
  SectionMap.prototype.setHover = function (source, id) {
    if (this.hoverIds[source] === id) return;
    this.clearHover(source);
    this.hoverIds[source] = id;
    this.map.setFeatureState({ source: source, id: id }, { hover: true });
    this.map.getCanvas().style.cursor = 'pointer';
  };

  SectionMap.prototype.clearHover = function (source) {
    if (!this.map || this.hoverIds[source] == null) return;
    if (this.map.getSource(source)) this.map.setFeatureState({ source: source, id: this.hoverIds[source] }, { hover: false });
    delete this.hoverIds[source];
    if (!Object.keys(this.hoverIds).length) this.map.getCanvas().style.cursor = '';
  };

  // -- popups --
  // One popup at a time, in the SDK's popup with the Leaflet popups' class
  // hooks, rising from the cell's centre. It stays until its close button
  // or another cell is clicked; clicking empty map (or a pan that ends on
  // it) doesn't dismiss it. `key` (openGridId, openAllSectionsId,
  // openLensId, openNoticeId, openLocationId) records whose popup is up so
  // a rebuilt layer can put it back (see reopenGridPopup,
  // reopenSelectedSection, renderNotices, renderLocations). `offset` lifts
  // the popup off a marker (pixels); a cell's popup sits on its centre.
  SectionMap.prototype.openPopup = function (lngLat, html, key, id, offset) {
    var self = this;
    if (this.popupKey && this[this.popupKey] === this.popupId) this[this.popupKey] = null;
    // Opening another feature's popup is letting go of this one: a
    // selected section loses its selection (a township popup replacing a
    // lens or all-sections section's; a section's own reopen keeps it).
    if (this.popupId && this.popupId !== id && this.selectedSectionId === this.popupId) this.clearSelection();
    this.popupKey = key;
    this.popupId = id;
    this[key] = id;
    if (this.popup) {
      // Moving the one popup rather than replacing it keeps a section's
      // popup from blinking when its grid is rebuilt under it.
      this.popup.setOffset(offset || 0).setMaxWidth(this.popupMaxWidth()).setLngLat(lngLat).setHTML(html);
      this.panPopupIntoView();
      return this.popup;
    }
    var popup = new maptilersdk.Popup({
      className: 'section-popup-wrap',
      maxWidth: this.popupMaxWidth(),
      closeButton: true,
      closeOnClick: false,
      focusAfterOpen: false,
      offset: offset || 0,
    });
    popup.setLngLat(lngLat).setHTML(html).addTo(this.map);
    popup.on('close', function () {
      // Only a close with the popup still current is the reader letting
      // go; closePopup() has already let go of the ones it removes.
      if (self.popup !== popup) return;
      self.popup = null;
      var closedKey = self.popupKey;
      var closedId = self.popupId;
      self.popupKey = null;
      self.popupId = null;
      if (closedKey && self[closedKey] === closedId) self[closedKey] = null;
      if (closedId && self.selectedSectionId === closedId) self.clearSelection();
      // A lens section's popup was pinning the lens; it's let go of too.
      if (closedKey === 'openLensId') self.scheduleLensClear();
    });
    this.popup = popup;
    this.bindPopupButtons(popup.getElement());
    this.panPopupIntoView();
    return popup;
  };

  // The popup's width: its own, or what the map can hold with the edge
  // margin on both sides (a phone). The SDK anchors a popup to whichever
  // side of its point has room, so one wider than that room has no stable
  // side: the nudge panPopupIntoView gives it can flip the anchor and put
  // it off the other edge. Inside the room, a nudge is at most the margin
  // and never crosses the band where the SDK centres it.
  SectionMap.prototype.popupMaxWidth = function () { return this.shell.popupMaxWidth(); };

  // Pans the map, by as little as it takes, so the open popup is clear of
  // the map's edges, the toolbar band across the top, and the legend
  // panel. The SDK's popup flips its anchor to stay inside the map, but
  // can't see the chrome floating over it; this can. Also run when a
  // popup grows (its detail landing), since that can push it under them.
  // The popup can also grow a beat after it opens (the icon font swaps its
  // glyphs in and the pills wrap), so one more look follows the first:
  // once the pan has landed or, without one, on the next tick.
  SectionMap.prototype.panPopupIntoView = function (again) { this.shell.panPopupIntoView(this.popup, again); };

  // Takes the popup down on the map's own account (a rebuilt layer, a
  // zoom), which is not the reader letting go: the selected section stays
  // selected and comes back with its popup wherever the section next
  // appears. The reader's own closes go through the popup's close event.
  SectionMap.prototype.closePopup = function () {
    var popup = this.popup;
    if (!popup) return;
    this.popup = null;
    if (this.popupKey && this[this.popupKey] === this.popupId) this[this.popupKey] = null;
    this.popupKey = null;
    this.popupId = null;
    popup.remove();
  };

  // The "Zoom in" buttons are served by one listener on the popup's outer
  // element, which survives setHTML replacing the content.
  SectionMap.prototype.bindPopupButtons = function (container) {
    var self = this;
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
        self.closePopup();
      }
      self.map.easeTo({ center: [lng, lat], zoom: self.sectionZoom(), animate: !self.reducedMotion });
    });
  };

  // "in 2023", or "across 2014–2023" when the map sums every year.
  SectionMap.prototype.yearPhrase = function () {
    var label = this.data.yearLabel || this.data.year;
    if (!label) return '';
    return (this.data.year === 'all' ? ' across ' : ' in ') + escapeHtml(label);
  };

  // The headline figure of a grid popup: "5,966 lbs applied in 2023" or
  // "312 applications in 2023", following the metric toggle.
  SectionMap.prototype.metricLine = function (props) {
    if (this.compare) return this.changeLine(props);
    var value = formatNumber(props[this.metric] || 0);
    var year = this.yearPhrase();
    var text = this.metric === 'applications'
      ? '<strong>' + value + '</strong> application' + (props.applications === 1 ? '' : 's') + year
      : '<strong>' + value + ' lbs</strong> applied' + year;
    return '<p class="section-popup-metric">' + text + '</p>';
  };

  // While comparing: the scope year's figure and how it moved, in words --
  // "670 lbs in 2023, up 470 from 2022". One line, so the popup is no taller
  // than it is on a single-year map, and the direction reads without having
  // to decode a sign.
  SectionMap.prototype.changeLine = function (props) {
    var applications = this.metric === 'applications';
    var unit = applications ? ' application' : ' lbs';
    var previous = Number(props[this.metric + '_prev']) || 0;
    var current = Number(props[this.metric]) || 0;
    if (!previous && !current) {
      return '<p class="section-popup-metric">No use reported in ' +
        escapeHtml(this.compare) + ' or ' + escapeHtml(this.data.year) + '.</p>';
    }
    var delta = current - previous;
    var headline = formatNumber(current) + unit + (applications && current === 1 ? '' : applications ? 's' : '');
    // No "from <year>": the legend caption names the pair, and a second
    // rendered line makes the popup too tall to pan clear of the panels.
    var movement = !delta ? 'unchanged' : (delta > 0 ? 'up ' : 'down ') + formatNumber(Math.abs(delta));
    return (
      '<p class="section-popup-metric">' +
        '<strong>' + headline + '</strong> in ' + escapeHtml(this.data.year) +
        ', <span class="section-popup-change">' + movement + '</span>' +
      '</p>'
    );
  };

  SectionMap.prototype.townshipPopupHtml = function (props, center) {
    var sections = props.sections || 0;
    // The target is carried on the button so the popup's own listener (see
    // bindPopupButtons) can serve it after the content is replaced.
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

  SectionMap.prototype.openTownshipPopup = function (feature) {
    var center = boundsCenter(featureBounds(feature));
    this.openPopup(center, this.townshipPopupHtml(feature.properties, latLngOf(center)), 'openGridId', feature.properties.id);
  };

  // `detailHtml` is the top-chemicals block: a list once loaded, a loading
  // or empty note otherwise.
  // `center` is passed when the popup was opened from the lens; the
  // township popup is unreachable there (the sections cover it),
  // so its "zoom in" action rides along on the section popup instead.
  SectionMap.prototype.sectionPopupHtml = function (props, detailHtml, center) {
    var sub = 'Square-mile section' + (props.county ? ' · ' + escapeHtml(shortCounty(props.county)) : '');
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

  // The open popup's section wears SELECTED_LINE (the `selected` source's
  // outline) for as long as the popup is up.
  SectionMap.prototype.selectSection = function (id, feature) {
    this.selectedSectionId = id;
    this.showSelectedOutline(feature);
  };

  SectionMap.prototype.clearSelection = function () {
    this.selectedSectionId = null;
    this.showSelectedOutline(null);
  };

  // The outline is drawn only while a section layer holds the section (the
  // section grid, the lens, "all sections"); the selection itself outlives
  // the layer.
  SectionMap.prototype.showSelectedOutline = function (feature) {
    this.setSourceData('selected', feature || EMPTY);
  };

  // After a layer of sections is (re)built, put the selected section's
  // popup back on it if it's there.
  SectionMap.prototype.reopenSelectedSection = function (features, source) {
    var id = this.selectedSectionId;
    if (!id || !features) return;
    var feature = findFeature(features, id);
    if (!feature) return;
    if (this.popup && this.popupId === id) {
      this.showSelectedOutline(feature);
      return;
    }
    this.showSectionPopup(feature, source);
  };

  // A refetch rebuilds the grid; if the popup that was open belongs to a
  // feature that's still there, put it back rather than making the reader
  // click again. A popup whose feature is gone goes with it. A marker's
  // popup (a notice, a school) isn't the grid's: its own layer keeps or
  // drops it (see renderNotices, renderLocations).
  SectionMap.prototype.reopenGridPopup = function (id) {
    var feature = id ? this.gridById[id] : null;
    if (feature) {
      if (this.level === 'township') {
        this.openTownshipPopup(feature);
      } else {
        this.showSectionPopup(feature, 'grid');
      }
    } else if (this.popup && !this.isMarkerPopup()) {
      this.closePopup();
    }
  };

  SectionMap.prototype.isMarkerPopup = function () {
    return this.popupKey === 'openNoticeId' || this.popupKey === 'openLocationId';
  };

  // `source` says which layer the section was clicked on ('grid',
  // 'all-sections', or 'lens'), which is whose popup this is.
  SectionMap.prototype.showSectionPopup = function (feature, source) {
    var self = this;
    var props = feature.properties;
    var center = boundsCenter(featureBounds(feature));
    var latlng = latLngOf(center);
    var key = source === 'grid' ? 'openGridId' : (source === 'lens' ? 'openLensId' : 'openAllSectionsId');
    this.openPopup(center, this.sectionPopupHtml(props, '<p class="section-popup-note">Loading…</p>', latlng), key, props.id);
    this.selectSection(props.id, feature);

    if (!this.data.sectionUrlPattern) return;
    var url = this.data.sectionUrlPattern.replace('{id}', props.id) + '?year=' + encodeURIComponent(this.data.year || '');
    fetchJson(url)
      .then(function (detail) {
        if (!self.popup || self.popupId !== props.id) return; // popup was closed before this resolved
        var chemicals = (detail && detail.top_chemicals) || [];
        var detailHtml = '<p class="section-popup-note">No use reported' + (self.data.year === 'all' ? ' in any year.' : ' this year.') + '</p>';
        if (chemicals.length) {
          detailHtml = '<ul class="section-popup-chems">' + chemicals.slice(0, 3).map(function (c) {
            return '<li>' +
              '<span class="name' + (c.is_of_concern ? ' is-of-concern' : '') + '">' + linkHtml(self.chemicalUrl(c.id), c.display_name || c.name) + '</span>' +
              '<span class="amount">' + formatNumber(c.lbs) + ' lbs</span>' +
              '</li>';
          }).join('') + '</ul>';
        }
        self.popup.setHTML(self.sectionPopupHtml(props, detailHtml, latlng));
        self.panPopupIntoView();
      })
      .catch(function (err) {
        logError('failed to load section detail', err);
        if (!self.popup || self.popupId !== props.id) return;
        self.popup.setHTML(self.sectionPopupHtml(props, '<p class="section-popup-note">Couldn\'t load the top chemicals.</p>', latlng));
      });
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

  // The located point is held until the section grid for its viewport is
  // on the map (renderGrid calls this after a section load); then the
  // section under it opens.
  SectionMap.prototype.resolvePendingLocate = function () {
    var latlng = this.pendingLocate;
    if (!latlng || this.level !== 'section' || !this.gridFeatures.length) return;
    var point = lngLatOf(latlng);
    if (!boundsContainsPoint(this.mapBounds(), point)) return;
    var hit = null;
    for (var i = 0; i < this.gridFeatures.length && !hit; i++) {
      if (boundsContainsPoint(featureBounds(this.gridFeatures[i]), point)) hit = this.gridFeatures[i];
    }
    if (!hit) {
      // Grid loaded but nothing under the point (outside the valley's
      // sections): nothing to select, and nothing more to wait for.
      if (this.loadedBounds && boundsContainsPoint(this.loadedBounds, point)) this.pendingLocate = null;
      return;
    }
    this.pendingLocate = null;
    this.showSectionPopup(hit, 'grid');
  };

  // -- "all sections" --
  // At the township zoom, every section in the padded viewport is drawn
  // instead of the township grid. Sections load in the same 5x5 township
  // blocks the lens prefetches, a few at a time, and go into the same
  // per-township cache, so the two modes share their work.
  SectionMap.prototype.visibleTownships = function () {
    if (this.level !== 'township') return [];
    var bounds = padBounds(this.mapBounds(), 0.15);
    return this.gridFeatures.filter(function (feature) {
      var featureBox = featureBounds(feature);
      return !!featureBox && boundsIntersects(featureBox, bounds);
    });
  };

  SectionMap.prototype.loadAllSections = function () {
    if (!this.showAllSections || this.level !== 'township' || !this.gridFeatures.length || !this.data.sectionsUrl) return;
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
      if (self.lensCache[host.properties.id]) return;
      var center = boundsCenter(featureBounds(host));
      var key = Math.floor(center[0] / tileLng) + ':' + Math.floor(center[1] / tileLat);
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

  // One request for a set of townships: the bbox is the union of their
  // bounds, and the response is filed per township so any later hover over
  // one of them draws from cache. `done` runs after filing (also on
  // failure, so a draw can still proceed with whatever is cached). Not
  // abortable: a superseded fetch's result is either still-good cache, or
  // lands in a cache onAdopt() has already replaced (see below).
  SectionMap.prototype.fetchLensSections = function (hosts, done) {
    var ids = hosts.map(function (host) { return host.properties.id; });
    var union = null;
    hosts.forEach(function (host) { union = unionBounds(union, featureBounds(host)); });
    var params = this.commonParams();
    params.bbox = bboxParam(union);
    // Results go into the cache that was current when the fetch started:
    // if the filters change meanwhile, onAdopt() swaps in a fresh cache and
    // this one is simply dropped.
    var cache = this.lensCache;
    fetchJson(this.data.sectionsUrl, params)
      .then(function (body) {
        if (!body || !body.features) return;
        var byTownship = {};
        ids.forEach(function (townshipId) { byTownship[townshipId] = []; });
        body.features.forEach(function (section) {
          var mtrs = section.properties.mtrs || '';
          var townshipId = mtrs.slice(0, mtrs.lastIndexOf('-'));
          if (byTownship[townshipId]) byTownship[townshipId].push(section);
        });
        ids.forEach(function (townshipId) { cache[townshipId] = byTownship[townshipId]; });
      })
      .catch(function () {})
      .then(function () { if (done) done(); });
  };

  SectionMap.prototype.cachedLensSections = function (ids) {
    var self = this;
    return ids.reduce(function (all, townshipId) {
      return all.concat(self.lensCache[townshipId] || []);
    }, []);
  };

  // Adds any cached, visible sections that aren't drawn yet. The source is
  // grown, never rebuilt: the SDK applies the additions in its worker,
  // which costs less than re-sending every polygon each time a block lands.
  SectionMap.prototype.drawAllSections = function () {
    if (!this.showAllSections || this.level !== 'township' || !this.gridFeatures.length) return;
    var self = this;
    if (!this.allSectionsAdded) {
      this.allSectionsAdded = {};
      this.allSectionsFeatures = [];
      this.allSectionsById = {};
      // The township grid steps aside (see applyGridPaint) once the layer
      // is up; the legend follows in restyleAllSections.
      this.applyGridPaint();
    }

    var fresh = [];
    this.visibleTownships().forEach(function (host) {
      var id = host.properties.id;
      if (self.allSectionsAdded[id] || !self.lensCache[id]) return;
      self.allSectionsAdded[id] = true;
      fresh = fresh.concat(self.lensCache[id]);
    });
    if (!fresh.length) {
      if (!this.currentClassesAreSections) this.restyleAllSections();
      return;
    }
    this.allSectionsFeatures = this.allSectionsFeatures.concat(fresh);
    for (var i = 0; i < fresh.length; i++) this.allSectionsById[fresh[i].properties.id] = fresh[i];
    // First sections in: classes over them so they don't draw unshaded
    // (a first block with no data at all gives no classes; the next one
    // with data classes again rather than waiting on the reshade).
    if (!this.currentClassesAreSections || !this.currentClasses.breaks.length) {
      this.currentClasses = this.classify(this.allSectionsFeatures);
      this.currentClassesAreSections = true;
      this.updateLegend();
    }
    this.classFeatures(fresh, this.currentClasses, LENS_OPACITY);
    this.updateAllSectionsSource({ add: fresh });
    this.reopenSelectedSection(this.allSectionsFeatures, 'all-sections');
  };

  // Recomputes the classes over everything drawn and reshades it; also
  // what a metric change calls.
  SectionMap.prototype.restyleAllSections = function () {
    if (!this.allSectionsAdded) return;
    var self = this;
    this.currentClasses = this.classify(this.allSectionsFeatures);
    this.currentClassesAreSections = true;
    this.classFeatures(this.allSectionsFeatures, this.currentClasses, LENS_OPACITY);
    this.updateAllSectionsSource({
      update: this.allSectionsFeatures.map(function (f) {
        var props = f.properties;
        return {
          id: props.id,
          addOrUpdateProperties: [
            { key: 'value', value: props.value },
            { key: 'shaded', value: props.shaded },
            { key: 'fill', value: props.fill },
            { key: 'opacity', value: props.opacity },
          ],
        };
      }),
    });
    this.updateLegend();
  };

  // Applies a change to the "all sections" source as a diff the SDK works
  // through in its worker (added features, or new shades on the drawn
  // ones), keeping the whole collection on the instance for the next style
  // load. Falls back to resetting the source where diffs aren't supported.
  SectionMap.prototype.updateAllSectionsSource = function (diff) {
    var data = { type: 'FeatureCollection', features: this.allSectionsFeatures };
    this.sourceData['all-sections'] = data;
    var source = this.map ? this.map.getSource('all-sections') : null;
    if (!source) return;
    if (typeof source.updateData === 'function') {
      source.updateData(diff);
    } else {
      source.setData(data);
    }
  };

  // The mode switched off (the toggle unchecked): the drawn sections go
  // (see resetAllSections) and the township grid gets its shades back. A
  // zoom to the section level leaves the toggle on; renderGrid resets the
  // layer there.
  SectionMap.prototype.clearAllSections = function () {
    this.allSectionsRun = null;
    this.cancelAllSectionsDraw();
    this.showAllSections = false;
    if (this.allSectionsAdded) {
      // The mode is going, so a popup on one of its sections goes with it
      // (nothing is about to reopen it); the selection outlives the layer.
      if (this.popup && this.popupKey === 'openAllSectionsId') this.closePopup();
      this.resetAllSections();
      this.setStatus('');
      if (this.gridFeatures.length) this.restyle();
    }
  };

  // Drops the drawn sections and their state; the cache stays. A popup on
  // one of them goes too, unless what loads next is going to reopen it:
  // the section grid after its "Zoom in" button (openGridId), or the
  // section layer that next holds the selected section.
  SectionMap.prototype.resetAllSections = function () {
    this.clearHover('all-sections');
    if (this.popup && this.popupKey === 'openAllSectionsId' && this.openGridId !== this.popupId && this.selectedSectionId !== this.popupId) this.closePopup();
    this.allSectionsAdded = null;
    this.allSectionsFeatures = [];
    this.allSectionsById = {};
    this.currentClassesAreSections = false;
    this.setSourceData('all-sections', EMPTY);
    this.applyGridPaint();
  };

  // -- the lens --
  // Zoomed out, hovering a township shows the sections of that township
  // and its neighbours (its Moore neighborhood, a 3x3 block), shaded by the
  // same metric with quantile classes over the block, so the reader can
  // see where within the neighborhood the use concentrates. Each section
  // can be hovered and clicked like the zoomed-in grid. The sections come
  // from the same endpoint the zoomed-in grid uses and are kept per
  // township for the life of the map (lensCache, shared with "all
  // sections").

  // The townships whose bounds touch the hovered one (itself included): a
  // 3x3 block in the regular grid, fewer at the valley edge. `reach` is in
  // townships from the centre: 1.5 is the 3x3 block, 2.5 the 5x5 block
  // around it (used to prefetch the ring beyond the lens). Measured over
  // the township grid on the map (each feature's bounds are measured once,
  // see featureBounds); nothing at any other level.
  SectionMap.prototype.neighborhoodOf = function (hostId, reach) {
    var hosts = [];
    var host = this.level === 'township' ? this.gridById[hostId] : null;
    var bounds = host ? featureBounds(host) : null;
    if (!bounds) return hosts;
    reach = reach || 1.5;
    // Neighbours by centre distance rather than touching bounds: diagonal
    // townships meet the hovered one only at a corner, and survey offsets
    // between ranges leave small gaps, so an intersection test drops them.
    // Anything whose centre is within `reach` townships on both axes is in;
    // the next ring starts a whole township further out.
    var center = boundsCenter(bounds);
    // A partial township (county edge, survey gap) has small bounds, so the
    // reach is floored at a full township's size.
    var maxDx = Math.max(bounds[1][0] - bounds[0][0], TOWNSHIP_DEGREES.lng) * reach;
    var maxDy = Math.max(bounds[1][1] - bounds[0][1], TOWNSHIP_DEGREES.lat) * reach;
    for (var i = 0; i < this.gridFeatures.length; i++) {
      var other = this.gridFeatures[i];
      var otherBounds = featureBounds(other);
      if (!otherBounds) continue;
      var c = boundsCenter(otherBounds);
      if (Math.abs(c[0] - center[0]) <= maxDx && Math.abs(c[1] - center[1]) <= maxDy) hosts.push(other);
    }
    return hosts;
  };

  SectionMap.prototype.showLens = function (feature) {
    if (!this.data.sectionsUrl) return;
    var id = feature.properties.id;
    // While one of the lens sections has its popup open the lens is pinned:
    // hovering a neighbouring township mustn't pull it (and the popup) away.
    if (this.openLensId) return;
    this.clearLens();
    this.lensId = id;
    this.lensHost = feature;

    var self = this;
    var hosts = this.neighborhoodOf(id);
    this.lensHosts = hosts;
    var ids = hosts.map(function (host) { return host.properties.id; });
    var draw = function () {
      // The lens has moved on (or gone) meanwhile: nothing to draw, and the
      // ring to prefetch is the new centre's, not this one's.
      if (self.lensId !== id) return;
      self.drawLens(id, self.cachedLensSections(ids));
      self.prefetchRing(id);
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

  // Once the lens is drawn, warm the cache for the ring of townships one
  // step beyond it, in idle time, so recentring the lens in any direction
  // draws without waiting on the network. One prefetch at a time; a lens
  // that has moved on by the time it runs prefetches around its new centre
  // instead.
  SectionMap.prototype.prefetchRing = function (hostId) {
    if (this.prefetching || !this.data.sectionsUrl) return;
    var self = this;
    var run = function () {
      if (self.prefetching || !self.map) return;
      var inner = {};
      self.neighborhoodOf(hostId, 1.5).forEach(function (host) { inner[host.properties.id] = true; });
      var ring = self.neighborhoodOf(hostId, 2.5).filter(function (host) {
        var townshipId = host.properties.id;
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

  // The nine townships under the lens lose their fill while it's up (the
  // `lensHost` feature state, which grid-fill's opacity reads), so the
  // section shades aren't stacked on the township shade beneath them; the
  // hovered one keeps its darker outline.
  SectionMap.prototype.setHostFills = function (visible) {
    var map = this.map;
    if (map && map.getSource('grid')) {
      (this.lensHosts || []).forEach(function (host) {
        map.setFeatureState({ source: 'grid', id: host.properties.id }, { lensHost: !visible });
      });
    }
    this.drawLensOutline(!visible);
  };

  // The hovered township's own outline, on its own layer above the lens
  // sections (which would otherwise paint over the township's border), in
  // the township hover stroke -- and only for a township with data, as the
  // Leaflet map drew it: a township without draws nothing to outline.
  SectionMap.prototype.drawLensOutline = function (show) {
    var host = show ? this.lensHost : null;
    var data = host && host.properties.value > 0 ? host : EMPTY;
    // Every clearLens and every redraw passes through here: the source is
    // only re-sent when it changes. The host feature is the same object
    // across a restyle, so its `value` is compared too: a metric change
    // can turn data into no data, and the outline with it.
    var value = data === EMPTY ? null : data.properties.value;
    if (this.sourceData['lens-outline'] === data && this.lensOutlineValue === value) return;
    this.lensOutlineValue = value;
    this.setSourceData('lens-outline', data);
  };

  // Keeps the township under the pointer at the centre of the lens. Returns
  // true when the lens was redrawn around a different township (the caller's
  // section is gone by then). A pinned lens (popup open) stays put.
  SectionMap.prototype.recentreLens = function (section) {
    var mtrs = section.properties.mtrs || '';
    var townshipId = mtrs.slice(0, mtrs.lastIndexOf('-'));
    if (!townshipId || townshipId === this.lensId || this.openLensId || this.level !== 'township') return false;
    var host = this.gridById[townshipId];
    if (!host) return false;
    this.showLens(host);
    return true;
  };

  // Also what a restyle calls with the lens's own features (a reclass in
  // place; a hovered section keeps its state, its id being the same).
  SectionMap.prototype.drawLens = function (id, features) {
    if (!this.map) return;
    var self = this;
    this.lensId = id;
    this.lensDrawnAt = Date.now();
    this.lensFeatures = features;
    if (!features.length) {
      this.setSourceData('lens', EMPTY);
      return;
    }
    // The township shade stays until the sections are here to replace it,
    // so the lens never shows an empty grid while the request is in flight.
    this.setHostFills(false);
    this.lensClasses = this.classify(features);
    this.classFeatures(features, this.lensClasses, LENS_OPACITY);
    this.setSourceData('lens', { type: 'FeatureCollection', features: features });
    // The selected section wears its outline while a section layer holds it.
    var selected = this.selectedSectionId ? findFeature(features, this.selectedSectionId) : null;
    if (selected) this.showSelectedOutline(selected);
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
      // mouseleave came from a section the redraw removed.
      if (self.openLensId) return;
      if (self.lensDrawnAt && self.lensDrawnAt >= scheduledAt) return;
      self.clearLens();
    }, LENS_CLEAR_DELAY_MS);
  };

  SectionMap.prototype.cancelLensClear = function () {
    if (this.lensClearTimer) {
      clearTimeout(this.lensClearTimer);
      this.lensClearTimer = null;
    }
  };

  // Takes the lens down: timers, the pin, the hosts' fills, the sections.
  // A popup on one of its sections goes too, unless the section grid about
  // to load is going to reopen it (its "Zoom in" button set openGridId);
  // the selection outlives the lens either way, its outline hidden until a
  // section layer holds the section again. Unlike resetAllSections, a
  // popup on the selected section is not kept: resetAllSections only runs
  // where a section layer follows (renderGrid, or the mode switching off,
  // which closes the popup itself), while the lens clears from hover flows
  // (leaving the grid, a ramp change) where nothing would reopen it and
  // the popup would be left floating over the township grid.
  SectionMap.prototype.clearLens = function () {
    this.cancelLensClear();
    this.cancelLensFetch();
    this.lensId = null;
    this.openLensId = null;
    this.setHostFills(true);
    this.lensHosts = null;
    this.lensHost = null;
    this.clearHover('lens');
    if (this.popup && this.popupKey === 'openLensId' && this.openGridId !== this.popupId) this.closePopup();
    if (this.lensFeatures.length) {
      if (this.selectedSectionId && findFeature(this.lensFeatures, this.selectedSectionId)) this.showSelectedOutline(null);
      this.lensFeatures = [];
      this.setSourceData('lens', EMPTY);
    }
  };

  // -- the marker legend --
  // Marker rows under the shade classes, for whichever marker layers are on.
  // Dots, not squares: the markers aren't a class of the grid.
  SectionMap.prototype.appendMarkerLegend = function () {
    if (!this.legendEl) return;
    var rows = [];
    if (this.showLocations) rows = rows.concat(MARKER_LEGEND);
    if (this.showNotices) rows.push({ color: NOTICE_COLOR, label: 'Notice of intent' });
    for (var i = 0; i < rows.length; i++) {
      var li = document.createElement('li');
      li.className = 'is-marker';
      li.innerHTML =
        '<span class="swatch is-dot" style="background-color: ' + rows[i].color + ';"></span>' +
        '<span class="range">' + escapeHtml(rows[i].label) + '</span>';
      this.legendEl.appendChild(li);
    }
  };

  // -- notices of intent --
  SectionMap.prototype.loadNotices = function () {
    if (!this.map || !this.data.noticesUrl || this.pendingFit) return;
    if (!this.showNotices) return;
    // Mid-animation the viewport is nowhere yet; the moveend that ends the
    // animation loads the markers for where it lands (as loadGrid).
    if (this.map.isMoving()) return;
    // Same padded-fetch/skip deal as the grid: don't rebuild the markers (and
    // drop an open popup) for a pan we already have data for.
    if (this.covers(this.loadedNoticeBounds)) return;
    // ...or one already on its way (see loadGrid).
    if (this.noticesRequest && this.covers(this.noticesRequest.bounds)) return;

    var abort = this.startRequest('notices');
    var bounds = this.fetchBounds();
    var request = this.noticesRequest = { bounds: bounds };
    var params = {
      bbox: bboxParam(bounds),
      chemical: this.data.chemical,
      product: this.data.product,
      county: this.data.county,
    };

    var self = this;
    fetchJson(this.data.noticesUrl, params, abort)
      .then(function (geojson) {
        if (self.noticesRequest === request) self.noticesRequest = null;
        if (self.noticesAbort !== abort) return; // stale response
        // The toggle (or a page swap) can turn the markers off while the
        // request is in the air; AbortController isn't everywhere, and an
        // already-resolved response isn't cancelled by aborting either.
        if (!self.showNotices) return;
        self.loadedNoticeBounds = bounds;
        self.renderNotices(geojson);
      })
      .catch(function (err) {
        if (self.noticesRequest === request) self.noticesRequest = null;
        if (isAbort(err) || self.noticesAbort !== abort) return;
        // Zoomed way out the bbox can cover more notices than the endpoint
        // will return (it 400s past its cap); drop the markers and move on.
        logError('failed to load notices', err);
        self.loadedNoticeBounds = null;
        self.clearNotices();
      });
  };

  // Takes the markers off the map; a notice popup goes with them (its
  // marker is gone), as it did with the Leaflet layer.
  SectionMap.prototype.clearNotices = function () {
    this.clearHover('notices');
    this.noticeById = {};
    if (this.popup && this.popupKey === 'openNoticeId') this.closePopup();
    this.setSourceData('notices', EMPTY);
  };

  // Puts a response's notices on the map, reopening the popup that was up
  // if its notice is still there.
  SectionMap.prototype.renderNotices = function (geojson) {
    var reopenId = this.openNoticeId;
    var features = ((geojson && geojson.features) || []).filter(function (f) { return f.geometry; });
    this.clearHover('notices');
    this.noticeById = {};
    for (var i = 0; i < features.length; i++) this.noticeById[features[i].properties.id] = features[i];
    this.setSourceData('notices', { type: 'FeatureCollection', features: features });
    if (reopenId) {
      var feature = this.noticeById[reopenId];
      if (feature) {
        this.openNoticePopup(feature);
      } else if (this.popup && this.popupKey === 'openNoticeId') {
        this.closePopup();
      }
    }
  };

  SectionMap.prototype.openNoticePopup = function (feature) {
    var props = feature.properties;
    this.openPopup(feature.geometry.coordinates, this.noticePopupHtml(props), 'openNoticeId', props.id,
      NOTICE_MARKER.radius + NOTICE_MARKER.stroke);
  };

  // A notice popup in the section popup's idiom: title, grey subline,
  // headline, labelled lists, pill actions.
  SectionMap.prototype.noticePopupHtml = function (props) {
    var self = this;
    var list = function (items) {
      return items.length
        ? '<ul class="section-popup-chems">' + items.join('') + '</ul>'
        : '<p class="section-popup-note">None listed.</p>';
    };
    var chemicals = list((props.chemicals || []).map(function (c) {
      return '<li><span class="name' + (c.is_of_concern ? ' is-of-concern' : '') + '">' +
        linkHtml(self.chemicalUrl(c.id), c.display_name || c.name) + '</span></li>';
    }));
    var products = list((props.products || []).map(function (p) {
      return '<li><span class="name">' + linkHtml(self.productUrl(p.id), p.name) + '</span></li>';
    }));

    var subParts = [];
    if (props.county) subParts.push(escapeHtml(shortCounty(props.county)));
    if (props.section) subParts.push(linkHtml(props.section_id ? this.sectionUrl(props.section_id) : '', props.section));
    var sub = 'Notice of intent' + (subParts.length ? ' · ' + subParts.join(' · ') : '');

    var when = escapeHtml(formatDateTime(props.scheduled_application));
    var through = props.scheduled_end ? ', may begin through ' + escapeHtml(formatDate(props.scheduled_end)) : '';
    var treated = props.treated_amount
      ? '<strong>' + formatNumber(props.treated_amount) + ' ' + escapeHtml((props.treated_units || '').toLowerCase()) + '</strong>'
      : '';
    var method = props.application_method ? escapeHtml(props.application_method.toLowerCase()) : '';
    var headline = treated && method ? treated + ' by ' + method
      : treated || (method ? method.charAt(0).toUpperCase() + method.slice(1) : '');

    var noticeUrl = props.id ? this.noticeUrl(props.id) : '';
    var actions = (noticeUrl
      ? '<a class="section-popup-action" href="' + escapeHtml(noticeUrl) + '"><span class="fa-regular fa-fw fa-circle-info"></span> Full notice</a>'
      : '') +
      '<a class="section-popup-action" href="' + SPRAYDAYS_URL + '" target="_blank" rel="noopener"><span class="fa-regular fa-fw fa-bell"></span> Sign up with SprayDays</a>';

    return (
      '<div class="section-popup notice-popup">' +
      '<h4>' + when + ' <span class="tag is-warning is-light">Active</span></h4>' +
      '<p class="section-popup-sub">' + sub + through + '</p>' +
      (headline ? '<p class="section-popup-metric">' + headline + '</p>' : '') +
      '<p class="section-popup-label">Products</p>' + products +
      '<p class="section-popup-label mt">Chemicals</p>' + chemicals +
      '<div class="section-popup-actions">' + actions + '</div>' +
      '</div>'
    );
  };

  // -- schools and child care --
  SectionMap.prototype.loadLocations = function () {
    if (!this.map || !this.data.locationsUrl || this.pendingFit) return;
    if (this.map.isMoving()) return;
    this.updateLocationsNote();
    if (!this.showLocations) return;
    // Zoomed out the endpoint's bbox cap would reject the request anyway,
    // and thousands of dots would say nothing; the legend note explains.
    if (this.map.getZoom() < LOCATIONS_MIN_ZOOM) {
      this.loadedLocationBounds = null;
      this.clearLocations();
      return;
    }
    // Same padded-fetch/skip deal as the grid and the notices, except the
    // padding is dropped rather than asking for a bbox the endpoint refuses
    // (see LOCATIONS_MAX_BBOX_DEGREES).
    if (this.covers(this.loadedLocationBounds)) return;
    if (this.locationsRequest && this.covers(this.locationsRequest.bounds)) return;

    var abort = this.startRequest('locations');
    var bounds = this.fetchBounds();
    if (boundsSpan(bounds) > LOCATIONS_MAX_BBOX_DEGREES) bounds = this.fetchBounds(true);
    var request = this.locationsRequest = { bounds: bounds };
    // The county scope goes along: the fetch bbox always overhangs the county
    // line, and a marker outside it would carry a popup figure from a county
    // this page isn't showing.
    var params = {
      bbox: bboxParam(bounds),
      county: this.data.county,
    };

    var self = this;
    fetchJson(this.data.locationsUrl, params, abort)
      .then(function (geojson) {
        if (self.locationsRequest === request) self.locationsRequest = null;
        if (self.locationsAbort !== abort) return; // stale response
        if (!self.showLocations) return;  // turned off while in flight
        self.loadedLocationBounds = bounds;
        self.renderLocations(geojson);
      })
      .catch(function (err) {
        if (self.locationsRequest === request) self.locationsRequest = null;
        if (isAbort(err) || self.locationsAbort !== abort) return;
        logError('failed to load locations', err);
        self.loadedLocationBounds = null;
        self.clearLocations();
      });
  };

  SectionMap.prototype.clearLocations = function () {
    this.clearHover('locations');
    this.locationById = {};
    if (this.popup && this.popupKey === 'openLocationId') this.closePopup();
    this.setSourceData('locations', EMPTY);
  };

  // Puts a response's markers on the map, reopening the popup that was up
  // if its marker is still there (which fetches its block figure afresh:
  // after a filter change the markers are the same but the figure isn't).
  SectionMap.prototype.renderLocations = function (geojson) {
    var reopenId = this.openLocationId;
    var features = ((geojson && geojson.features) || []).filter(function (f) { return f.geometry; });
    this.clearHover('locations');
    this.locationById = {};
    for (var i = 0; i < features.length; i++) this.locationById[features[i].properties.id] = features[i];
    this.setSourceData('locations', { type: 'FeatureCollection', features: features });
    if (reopenId) {
      var feature = this.locationById[reopenId];
      if (feature) {
        this.openLocationPopup(feature);
      } else if (this.popup && this.popupKey === 'openLocationId') {
        this.closePopup();
      }
    }
  };

  // The popup opens at once with its "Loading nearby use…" line; the
  // "within about a mile" figure is a second request, so it only happens
  // when someone actually opens the popup.
  SectionMap.prototype.openLocationPopup = function (feature) {
    var props = feature.properties;
    var lngLat = feature.geometry.coordinates;
    this.openPopup(lngLat, this.locationPopupHtml(props), 'openLocationId', props.id,
      LOCATION_MARKER.radius + LOCATION_MARKER.stroke);
    this.loadLocationBlock(props, lngLat);
  };

  // Fill in a school popup's headline once its block of sections lands.
  // `block` is undefined while loading and null when the fetch failed.
  SectionMap.prototype.loadLocationBlock = function (props, lngLat) {
    var self = this;
    var params = this.commonParams();
    // The filter set this figure belongs to. An htmx swap can hand the live
    // map a new scope (year, county, entity) while the fetch is in flight,
    // and the popup may be reopened under it; a response from the old filter
    // set is then stale and gets dropped rather than filling in numbers for
    // a scope that's no longer on screen.
    var scope = buildQuery(params);
    params.bbox = blockBbox(lngLat);
    var open = function () {
      return !!self.popup && self.popupKey === 'openLocationId' && self.popupId === props.id &&
        buildQuery(self.commonParams()) === scope;
    };
    // Without the endpoint there is no figure to fetch: say so rather than
    // leave the popup on "Loading nearby use...".
    if (!this.data.sectionsUrl) {
      if (open()) this.popup.setHTML(this.locationPopupHtml(props, null));
      return;
    }

    fetchJson(this.data.sectionsUrl, params)
      .then(function (geojson) {
        if (!open()) return;
        self.popup.setHTML(self.locationPopupHtml(props, blockTotals(geojson, lngLat)));
        self.panPopupIntoView();
      })
      .catch(function (err) {
        logError('failed to load a location block', err);
        if (!open()) return;
        self.popup.setHTML(self.locationPopupHtml(props, null));
      });
  };

  // A school or child care popup in the section popup's idiom: name, grey
  // subline, the block headline, pill actions.
  SectionMap.prototype.locationPopupHtml = function (props, block) {
    // type · address, city. The district is already a pill action below, so
    // it doesn't take the sub-line's room -- the street address is what
    // tells two schools of the same name apart.
    var where = [props.address, props.city]
      .filter(function (part) { return !!part; })
      .map(titleCaseName)
      .join(', ');
    var subParts = [];
    if (props.type_label) subParts.push(escapeHtml(props.type_label));
    if (where) subParts.push(escapeHtml(where));
    if (!subParts.length && props.school_district) subParts.push(escapeHtml(props.school_district));
    var sub = subParts.join(' · ');

    var headline;
    if (block === undefined) {
      headline = '<p class="section-popup-note">Loading nearby use…</p>';
    } else if (block === null) {
      headline = '<p class="section-popup-note">Couldn\'t load nearby use.</p>';
    } else {
      var within = ' within about a mile' + this.yearPhrase();
      var text;
      if (this.compare) {
        // The same "both years, then the change" shape as a grid popup.
        var applications = this.metric === 'applications';
        var previous = applications ? block.applications_prev : block.lbs_prev;
        var current = applications ? block.applications : block.lbs;
        var moved = current - previous;
        text = '<strong>' + formatNumber(current) + (applications ? ' application' + (current === 1 ? '' : 's') : ' lbs') +
          '</strong> within about a mile in ' + escapeHtml(this.data.year) +
          ', <span class="section-popup-change">' + (!moved ? 'unchanged from ' + escapeHtml(this.compare)
            : (moved > 0 ? 'up ' : 'down ') + formatNumber(Math.abs(moved)) + ' from ' + escapeHtml(this.compare)) +
          '</span>';
      } else {
        text = this.metric === 'applications'
          ? '<strong>' + formatNumber(block.applications) + '</strong> application' + (block.applications === 1 ? '' : 's') + within
          : '<strong>' + formatNumber(block.lbs) + ' lbs</strong> applied' + within;
      }
      headline = '<p class="section-popup-metric">' + text + '</p>';
    }

    var actions = '';
    var section = block && block.section;
    if (section && section.id) {
      actions += '<a class="section-popup-action" href="' + escapeHtml(this.sectionUrl(section.id)) + '">' +
        '<span class="fa-regular fa-fw fa-circle-info"></span> Section details</a>';
    }
    if (props.school_district_url) {
      actions += '<a class="section-popup-action" href="' + escapeHtml(props.school_district_url) + '">' +
        '<span class="fa-regular fa-fw fa-school"></span> District page</a>';
    }

    return (
      '<div class="section-popup location-popup">' +
      '<h4>' + escapeHtml(titleCaseName(props.name)) + '</h4>' +
      (sub ? '<p class="section-popup-sub">' + sub + '</p>' : '') +
      headline +
      (actions ? '<div class="section-popup-actions">' + actions + '</div>' : '') +
      '</div>'
    );
  };

  // Why the markers aren't there: the toggle is on but the map is zoomed
  // out past where they load.
  SectionMap.prototype.updateLocationsNote = function () {
    var tooFar = !!(this.showLocations && this.map && this.map.getZoom() < LOCATIONS_MIN_ZOOM);
    var note = this.wrapEl ? this.wrapEl.querySelector('.section-map-locations-note') : null;
    if (note) note.textContent = tooFar ? LOCATIONS_ZOOM_NOTE : '';
    // The legend it lives in collapses, so say it in the live region too --
    // otherwise turning the layer on at a wide zoom just does nothing
    // visible. Only ours to clear: a load in progress owns the line.
    if (tooFar) {
      this.setStatus(LOCATIONS_ZOOM_NOTE);
    } else if (this.statusEl && this.statusEl.textContent === LOCATIONS_ZOOM_NOTE) {
      this.setStatus('');
    }
  };

  M.register('section', {
    selector: '.section-map',
    lifecycle: 'adopt',
    features: { controls: ['zoom', 'locate', 'home'], toolbar: true, legend: true, status: true, expand: true },
    // The key readers' folded legends were saved under before the core.
    panelStoragePrefix: 'pesticides:section-map:panel:',
    create: function (shell) { return new SectionMap(shell); },
  });

  // The smoke script and the console still reach the map here.
  window.PesticidesSectionMap = {
    init: M.init,
    instances: function () { return M.instances('section'); },
  };
})();
