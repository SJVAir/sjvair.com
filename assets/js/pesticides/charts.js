/*
 * Charts for the Pesticides Explorer, drawn with uPlot.
 *
 * The server embeds each chart's data as JSON (`json_script`) next to an
 * empty `.chart-canvas[data-chart]`; init() finds those, draws them, and
 * remembers the instances so a later htmx swap can destroy the ones whose
 * markup has gone. explorer.js calls init() from its htmx:load hook, which
 * fires on page load and again for every swapped-in element.
 *
 * Two kinds: `line` (the by-year trend, optionally with a dashed second
 * series `y2`, readout `labels`, per-year readout `notes`, a marked year
 * `marker` and `whole` for counts) and `bars` (the by-month totals).
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
    // A whole tick is written whole: "5", not "5.0", on a count axis.
    if (size < 10000) return Number.isInteger(value) ? value.toLocaleString('en-US') : full(value);
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
    if (unit === 'tons') return full(value) + ' tons/yr';
    if (unit === '%') return full(value) + '%';
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
      color2: cssVar(figure, '--chart-color-2', '#d95f0e'),
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
    // Optional: a second series (dashed), labels for the readout, and a
    // marked year (the dairy trend's coverage change).
    var y2 = data.y2 || null;
    var labels = data.labels || null;
    var marker = data.marker || null;
    // Optional: a note per year for the readout (a share), and `whole` for
    // counts (whole-number ticks and readout).
    var notes = data.notes || null;
    var whole = !!data.whole;
    var count = function (value) { return whole ? Math.round(value).toLocaleString('en-US') : full(value); };
    // The baseline the line is read against (the average valley county), or
    // null where there's nothing to compare to.
    var compare = data.compare && data.compare.length ? data.compare : null;
    var selectedIndex = data.selected == null ? -1 : x.indexOf(data.selected);
    var pad = x.length > 1 ? 0.5 : 1;
    var series = [
      {},
      {
        stroke: colors.color,
        width: 2,
        points: {show: true, size: 6, width: 1.5, stroke: colors.color, fill: '#fff'},
        spanGaps: false,
      },
    ];
    if (y2) {
      series.push({
        stroke: colors.color2,
        width: 2,
        dash: [6, 4],
        points: {show: true, size: 5, width: 1.5, stroke: colors.color2, fill: '#fff'},
        spanGaps: false,
      });
    }
    if (compare) {
      // Dashed and muted: context, not a second measurement competing for
      // attention. No points, so the series with points stays the subject.
      series.push({
        stroke: colors.muted,
        width: 1.5,
        dash: [4, 3],
        points: {show: false},
        spanGaps: false,
      });
    }
    // A chart can ask for its own height (data.height); a wide one reads better taller.
    var opts = Object.assign(size(el, data.height || LINE_HEIGHT), {
      legend: {show: false},
      select: {show: false},
      cursor: {y: false, drag: {x: false, y: false}, points: {size: 9, width: 2}},
      scales: {
        x: {time: false, range: [x[0] - pad, x[x.length - 1] + pad]},
        // From zero: a flat decade should look flat. Across both series, so
        // a baseline above the line it explains doesn't draw off the top.
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
      series: series,
      hooks: {
        draw: [function (u) {
          var ctx = u.ctx;
          var ratio = devicePixelRatio;
          if (marker && x.indexOf(marker.x) !== -1) {
            var mx = u.valToPos(marker.x, 'x', true);
            ctx.save();
            ctx.strokeStyle = colors.muted;
            ctx.fillStyle = colors.muted;
            ctx.lineWidth = ratio;
            ctx.setLineDash([3 * ratio, 3 * ratio]);
            ctx.beginPath();
            ctx.moveTo(mx, u.bbox.top);
            ctx.lineTo(mx, u.bbox.top + u.bbox.height);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.font = colors.font.replace(/^(\d+)px/, function (match, px) { return (px * ratio) + 'px'; });
            ctx.fillText(marker.label, mx + 4 * ratio, u.bbox.top + 10 * ratio);
            ctx.restore();
          }
          // The scope year's point is filled, the way the old chart marked it.
          if (selectedIndex < 0) return;
          var cx = u.valToPos(x[selectedIndex], 'x', true);
          var cy = u.valToPos(y[selectedIndex], 'y', true);
          ctx.save();
          ctx.beginPath();
          ctx.arc(cx, cy, 4.5 * ratio, 0, Math.PI * 2);
          ctx.fillStyle = colors.color;
          ctx.fill();
          ctx.restore();
        }],
        setCursor: [function (u) {
          if (!readout) return;
          var index = u.cursor.idx;
          if (index == null) {
            readout.textContent = '';
            return;
          }
          var text;
          if (labels) {
            text = x[index] + ' · ' + count(y[index]) + ' ' + labels[0] +
              (y2 ? ' · ' + count(y2[index]) + ' ' + labels[1] : '');
          } else {
            text = x[index] + ' · ' + amount(y[index], data.unit);
          }
          if (notes && notes[index]) text += ' · ' + notes[index];
          if (compare && compare[index] != null) {
            text += ' · ' + (data.compare_label || 'valley average') + ' ' + amount(compare[index], data.unit);
          }
          readout.textContent = text;
        }],
      },
    });
    if (whole) opts.axes[1].incrs = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000];
    var columns = [x, y];
    if (y2) columns.push(y2);
    if (compare) columns.push(compare);
    return new uPlot(opts, columns, el);
  }

  // A 100% stacked bar per year: data.series [{label, values, color}], the
  // bottom of the stack first; each year's parts as shares of its total, so
  // the chart shows the mix, not the volume (the trend above has that). Each
  // part is a bar from 0 to its running share, drawn tallest first so the
  // ones below show through. The readout keeps to one line (the year and its
  // total); the hovered year's shares go into the legend, which is always
  // there, so the chart doesn't move as the cursor does.
  function stack(el, figure, data) {
    var colors = palette(figure);
    var readout = figure.querySelector('.chart-readout');
    var legendValues = figure.querySelectorAll('.chart-legend.is-series [data-share]');
    var x = data.x;
    var parts = data.series || [];
    var totals = x.map(function (year, j) {
      return parts.reduce(function (sum, part) { return sum + (part.values[j] || 0); }, 0);
    });
    var shares = parts.map(function (part) {
      return part.values.map(function (value, j) { return totals[j] ? 100 * (value || 0) / totals[j] : 0; });
    });
    var running = x.map(function () { return 0; });
    var cumulative = shares.map(function (share) {
      running = running.map(function (sum, j) { return sum + share[j]; });
      return running.slice();
    });
    var indexes = x.map(function (year, j) { return j; });
    var selectedIndex = data.selected == null ? -1 : x.indexOf(data.selected);
    // Every few years a label, so a 15-year axis doesn't crowd.
    var every = Math.max(1, Math.ceil(x.length / 8));
    var order = parts.map(function (part, i) { return i; }).reverse();
    var series = [{}].concat(order.map(function (i) {
      return {
        stroke: parts[i].color,
        width: 0,
        fill: parts[i].color,
        paths: uPlot.paths.bars({size: [0.75, 60], align: 0}),
        points: {show: false},
      };
    }));
    var showShares = function (index) {
      Array.prototype.forEach.call(legendValues, function (span) {
        var i = Number(span.getAttribute('data-share'));
        span.textContent = index == null ? '' : ' ' + Math.round(shares[i][index]) + '%';
      });
    };
    // The band under the cursor -- its sector, share and amount -- in a tip
    // that floats over the plot (absolutely placed in uPlot's over layer, so
    // it moves nothing).
    var tip = document.createElement('div');
    tip.className = 'chart-tip';
    tip.hidden = true;
    var showTip = function (u, index) {
      var top = u.cursor.top;
      if (index == null || top == null || top < 0) { tip.hidden = true; return; }
      var value = u.posToVal(top, 'y');
      var part = -1;
      for (var i = 0; i < parts.length; i++) {
        if (value <= cumulative[i][index] + 1e-9) { part = i; break; }
      }
      if (part < 0 || value < 0 || !shares[part][index]) { tip.hidden = true; return; }
      tip.innerHTML = '';
      var name = document.createElement('strong');
      name.textContent = parts[part].label;
      var line = document.createElement('span');
      line.textContent = x[index] + ' · ' + Math.round(shares[part][index]) + '% · ' + amount(parts[part].values[index] || 0, data.unit);
      tip.appendChild(name);
      tip.appendChild(line);
      tip.hidden = false;
      // Beside the cursor, flipped to its left near the right edge.
      var left = u.cursor.left + 12;
      if (left + tip.offsetWidth > u.over.clientWidth) left = u.cursor.left - tip.offsetWidth - 12;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, Math.min(top - tip.offsetHeight / 2, u.over.clientHeight - tip.offsetHeight)) + 'px';
    };
    var opts = Object.assign(size(el, data.height || BARS_HEIGHT), {
      legend: {show: false},
      select: {show: false},
      cursor: {x: false, y: false, drag: {x: false, y: false}, points: {show: false}},
      scales: {
        x: {time: false, distr: 2, range: function (u, min, max) { return [min - 0.5, max + 0.5]; }},
        y: {range: [0, 100]},
      },
      axes: [
        Object.assign(axisBase(colors), {
          grid: {show: false},
          splits: function () { return indexes; },
          values: function (u, splits) {
            return splits.map(function (index) { return index % every === (x.length - 1) % every ? String(x[index]) : ''; });
          },
          size: 26,
        }),
        Object.assign(axisBase(colors), {
          grid: {stroke: colors.grid, width: 1},
          splits: function () { return [0, 25, 50, 75, 100]; },
          values: function (u, splits) { return splits.map(function (value) { return value + '%'; }); },
          size: 46,
        }),
      ],
      series: series,
      hooks: {
        draw: [function (u) {
          // The scope year: its bar outlined.
          if (selectedIndex < 0) return;
          var ctx = u.ctx;
          var slot = u.bbox.width / x.length;
          var cx = u.valToPos(selectedIndex, 'x', true);
          ctx.save();
          ctx.strokeStyle = colors.text;
          ctx.lineWidth = 1.5 * devicePixelRatio;
          ctx.strokeRect(cx - slot * 0.375, u.bbox.top, slot * 0.75, u.bbox.height);
          ctx.restore();
        }],
        setCursor: [function (u) {
          var hovered = u.cursor.idx;
          var index = hovered == null ? (selectedIndex < 0 ? null : selectedIndex) : hovered;
          if (readout) readout.textContent = index == null ? '' : x[index] + ' · ' + amount(totals[index], data.unit) + ' in all';
          showShares(index);
          showTip(u, hovered);
        }],
      },
    });
    var plot = new uPlot(opts, [indexes].concat(order.map(function (i) { return cumulative[i]; })), el);
    plot.over.appendChild(tip);
    // Before any hover, the legend shows the scope year's shares.
    showShares(selectedIndex < 0 ? null : selectedIndex);
    return plot;
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
        // Ordinal, padded half a slot each side so the first and last bars
        // sit inside the plot instead of centred on its edges.
        x: {time: false, distr: 2, range: function (u, min, max) { return [min - 0.5, max + 0.5]; }},
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
          ctx.beginPath();
          ctx.rect(u.bbox.left, u.bbox.top, u.bbox.width, u.bbox.height);
          ctx.clip();
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
      var plot = data.type === 'bars' ? bars(el, figure, data) : data.type === 'stack' ? stack(el, figure, data) : line(el, figure, data);
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
