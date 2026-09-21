/*
 * Charts for the Pesticides Explorer, drawn with uPlot.
 *
 * The server embeds each chart's data as JSON (`json_script`) next to an
 * empty `.chart-canvas[data-chart]`; init() finds those, draws them, and
 * remembers the instances so a later htmx swap can destroy the ones whose
 * markup has gone. explorer.js calls init() from its htmx:load hook, which
 * fires on page load and again for every swapped-in element.
 *
 * Two kinds: `line` (the by-year trend) and `bars` (the by-month totals).
 * Colours come from CSS custom properties on `.explorer-chart`, so the Sass
 * stays the one place the palette lives.
 */
(function () {
  'use strict';

  if (typeof window.uPlot === 'undefined') return;

  var instances = [];
  var LINE_HEIGHT = 150;
  var BARS_HEIGHT = 170;

  // "4,607", "0.19", "8.5" -- the same rules as the `lbs` template filter.
  function full(value) {
    var size = Math.abs(value);
    var digits = size && size < 1 ? 2 : (size && size < 10 ? 1 : 0);
    return value.toLocaleString('en-US', {minimumFractionDigits: digits, maximumFractionDigits: digits});
  }

  // "107M", "88.5M", "45.2k" for axis ticks; small numbers written out.
  function compact(value) {
    var size = Math.abs(value);
    if (size < 10000) return full(value);
    var steps = [[1e6, 'M'], [1e3, 'k']];
    for (var i = 0; i < steps.length; i++) {
      if (size >= steps[i][0]) {
        var scaled = value / steps[i][0];
        var text = Math.abs(scaled) < 100 ? scaled.toFixed(1) : scaled.toFixed(0);
        return text.replace(/\.0$/, '') + steps[i][1];
      }
    }
    return full(value);
  }

  function amount(value, unit) {
    if (unit === 'applications') {
      return Math.round(value).toLocaleString('en-US') + ' ' + (value === 1 ? 'application' : 'applications');
    }
    return full(value) + ' lbs';
  }

  function cssVar(el, name, fallback) {
    var value = getComputedStyle(el).getPropertyValue(name).trim();
    return value || fallback;
  }

  function size(el, height) {
    return {width: Math.max(el.clientWidth || el.parentNode.clientWidth || 0, 160), height: height};
  }

  function palette(figure) {
    return {
      color: cssVar(figure, '--chart-color', '#3273dc'),
      grid: cssVar(figure, '--chart-grid', '#ededed'),
      muted: cssVar(figure, '--chart-muted', '#7a7a7a'),
      text: cssVar(figure, '--chart-text', '#4a4a4a'),
      font: '11px ' + (getComputedStyle(document.body).fontFamily || 'sans-serif'),
    };
  }

  function axisBase(colors) {
    return {
      stroke: colors.muted,
      font: colors.font,
      ticks: {show: false},
      gap: 6,
    };
  }

  // Every year gets a tick while they fit; past that, every other year, and
  // so on, so a 20-year series doesn't run its labels together.
  function yearSplits(years) {
    return function (u) {
      var room = Math.max(1, Math.floor((u.bbox.width / devicePixelRatio) / 44));
      var step = Math.ceil(years.length / room);
      return years.filter(function (year, index) { return (years.length - 1 - index) % step === 0; });
    };
  }

  function line(el, figure, data) {
    var colors = palette(figure);
    var readout = figure.querySelector('.chart-readout');
    var x = data.x, y = data.y;
    var selectedIndex = data.selected == null ? -1 : x.indexOf(data.selected);
    var pad = x.length > 1 ? 0.5 : 1;
    var opts = Object.assign(size(el, LINE_HEIGHT), {
      legend: {show: false},
      select: {show: false},
      cursor: {y: false, drag: {x: false, y: false}, points: {size: 9, width: 2}},
      scales: {
        x: {time: false, range: [x[0] - pad, x[x.length - 1] + pad]},
        // From zero: a flat decade should look flat.
        y: {range: function (u, min, max) { return [0, (max || 1) * 1.12]; }},
      },
      axes: [
        Object.assign(axisBase(colors), {
          grid: {show: false},
          splits: yearSplits(x),
          values: function (u, splits) { return splits.map(function (value) { return String(value); }); },
          size: 26,
        }),
        Object.assign(axisBase(colors), {
          grid: {stroke: colors.grid, width: 1},
          values: function (u, splits) { return splits.map(compact); },
          // Ticks may sit closer than uPlot's default, or a short chart
          // gets only a zero and one other line.
          space: 24,
          size: 46,
        }),
      ],
      series: [
        {},
        {
          stroke: colors.color,
          width: 2,
          points: {show: true, size: 6, width: 1.5, stroke: colors.color, fill: '#fff'},
          spanGaps: false,
        },
      ],
      hooks: {
        // The scope year's point is filled, the way the old chart marked it.
        draw: [function (u) {
          if (selectedIndex < 0) return;
          var ctx = u.ctx;
          var cx = u.valToPos(x[selectedIndex], 'x', true);
          var cy = u.valToPos(y[selectedIndex], 'y', true);
          ctx.save();
          ctx.beginPath();
          ctx.arc(cx, cy, 4.5 * devicePixelRatio, 0, Math.PI * 2);
          ctx.fillStyle = colors.color;
          ctx.fill();
          ctx.restore();
        }],
        setCursor: [function (u) {
          if (!readout) return;
          var index = u.cursor.idx;
          readout.textContent = index == null ? '' : x[index] + ' · ' + amount(y[index], data.unit);
        }],
      },
    });
    return new uPlot(opts, [x, y], el);
  }

  function bars(el, figure, data) {
    var colors = palette(figure);
    var readout = figure.querySelector('.chart-readout');
    var x = data.x, y = data.y;
    var hovered = -1;
    var opts = Object.assign(size(el, BARS_HEIGHT), {
      legend: {show: false},
      select: {show: false},
      cursor: {x: false, y: false, drag: {x: false, y: false}, points: {show: false}},
      scales: {
        x: {time: false, distr: 2},
        y: {range: function (u, min, max) { return [0, (max || 1) * 1.08]; }},
      },
      axes: [
        Object.assign(axisBase(colors), {
          grid: {show: false},
          splits: function () { return x; },
          values: function (u, splits) { return splits.map(function (index) { return data.labels[index] || ''; }); },
          size: 26,
        }),
        Object.assign(axisBase(colors), {
          grid: {stroke: colors.grid, width: 1},
          values: function (u, splits) { return splits.map(compact); },
          // Ticks may sit closer than uPlot's default, or a short chart
          // gets only a zero and one other line.
          space: 24,
          size: 46,
        }),
      ],
      series: [
        {},
        {
          paths: uPlot.paths.bars({size: [0.7, 100], align: 0}),
          fill: colors.color + 'b3',
          stroke: colors.color,
          width: 0,
          points: {show: false},
        },
      ],
      hooks: {
        // The hovered bar goes solid.
        draw: [function (u) {
          if (hovered < 0 || y[hovered] == null) return;
          var ctx = u.ctx;
          var slot = u.bbox.width / x.length;
          var width = slot * 0.7;
          var left = u.valToPos(x[hovered], 'x', true) - width / 2;
          var top = u.valToPos(y[hovered], 'y', true);
          var bottom = u.valToPos(0, 'y', true);
          ctx.save();
          ctx.fillStyle = colors.color;
          ctx.fillRect(left, top, width, Math.max(bottom - top, 2 * devicePixelRatio));
          ctx.restore();
        }],
        setCursor: [function (u) {
          var index = u.cursor.idx == null ? -1 : u.cursor.idx;
          if (index !== hovered) {
            hovered = index;
            u.redraw(false);
          }
          if (!readout) return;
          if (index < 0) {
            readout.textContent = '';
            return;
          }
          var text = data.names[index] + ' · ' + amount(y[index], data.unit);
          if (data.applications && data.applications[index]) {
            text += ' · ' + amount(data.applications[index], 'applications');
          }
          readout.textContent = text;
        }],
      },
    });
    return new uPlot(opts, [x, y], el);
  }

  function init(root) {
    root = root || document;
    var canvases = root.querySelectorAll ? root.querySelectorAll('.chart-canvas[data-chart]') : [];
    Array.prototype.forEach.call(canvases, function (el) {
      if (el.dataset.rendered) return;
      var script = document.getElementById(el.dataset.chart);
      var figure = el.closest('.explorer-chart');
      if (!script || !figure) return;
      var data;
      try { data = JSON.parse(script.textContent); } catch (err) { return; }
      if (!data.x || !data.x.length) return;
      var plot = data.type === 'bars' ? bars(el, figure, data) : line(el, figure, data);
      el.dataset.rendered = '1';
      instances.push({el: el, plot: plot});
    });
    sweep();
  }

  // Drop the instances whose markup an htmx swap has replaced.
  function sweep() {
    instances = instances.filter(function (item) {
      if (document.body.contains(item.el)) return true;
      item.plot.destroy();
      return false;
    });
  }

  var resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      instances.forEach(function (item) {
        item.plot.setSize(size(item.el, item.plot.height));
      });
    }, 100);
  });

  window.PesticidesCharts = {init: init, sweep: sweep};

  // Without htmx (or before it loads), draw on the first paint anyway.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(document); });
  } else {
    init(document);
  }
})();
