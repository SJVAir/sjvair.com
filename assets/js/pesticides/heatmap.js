/*
 * Hover for the seasonality heatmap (pesticides/includes/month-heatmap.html).
 *
 * A cell is a month in a year, so reading one means finding its row and its
 * column at once -- which is exactly what a grid of same-sized squares makes
 * hard. Hovering marks the row, the column, the month and year headers, and
 * writes the cell's own value into the figure's readout.
 *
 * Delegated from the document rather than bound per grid: the explorer swaps
 * #explorer-body on every boosted navigation, and a delegated listener
 * survives that with no re-init. Keyboard and touch users get the same
 * marking through focusin, and every cell carries its value as text for a
 * screen reader regardless.
 */
(function () {
  'use strict';

  var CELL = 'heatmap-cell';

  function clear(grid) {
    var marked = grid.querySelectorAll('.is-cross, .is-hovered, .is-band');
    Array.prototype.forEach.call(marked, function (el) {
      el.classList.remove('is-cross', 'is-hovered', 'is-band');
    });
    var figure = grid.closest('.explorer-chart');
    var readout = figure && figure.querySelector('.chart-readout');
    if (readout) readout.textContent = '';
  }

  function mark(cell) {
    var grid = cell.closest('.heatmap-grid');
    if (!grid) return;
    clear(grid);

    var row = cell.parentNode;
    // +1 for the year header cell, which is a <th> in the same row.
    var index = Array.prototype.indexOf.call(row.children, cell);

    cell.classList.add('is-hovered');
    // The bands themselves: a background on the row and on the column, both
    // of which paint beneath the cells, so the fills stay exactly as they
    // are. The headers take a class of their own so they can go bold too.
    row.classList.add('is-band');
    var col = grid.querySelectorAll('colgroup col')[index];
    if (col) col.classList.add('is-band');
    var header = grid.rows[0] && grid.rows[0].children[index];
    if (header) header.classList.add('is-cross');
    var rowHeader = row.children[0];
    if (rowHeader && rowHeader !== cell) rowHeader.classList.add('is-cross');

    var figure = grid.closest('.explorer-chart');
    var readout = figure && figure.querySelector('.chart-readout');
    if (readout) readout.textContent = cell.dataset.readout || '';
  }

  function handle(event) {
    var cell = event.target.closest ? event.target.closest('.' + CELL) : null;
    if (cell) {
      mark(cell);
      return;
    }
    // Left the grid entirely: drop the marking rather than leave a stale row
    // lit after the cursor has moved on.
    var grid = event.target.closest ? event.target.closest('.heatmap-grid') : null;
    if (!grid) {
      var lit = document.querySelectorAll('.heatmap-grid .is-hovered');
      Array.prototype.forEach.call(lit, function (el) {
        clear(el.closest('.heatmap-grid'));
      });
    }
  }

  document.addEventListener('mouseover', handle);
  document.addEventListener('focusin', handle);
  document.addEventListener('mouseleave', function (event) {
    var grid = event.target.closest && event.target.closest('.heatmap-grid');
    if (grid) clear(grid);
  }, true);
})();
