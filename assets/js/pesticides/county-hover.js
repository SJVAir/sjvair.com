/*
 * The county table and the county choropleth beside it, hovered together.
 *
 * The table IS the map's legend (includes/by-county-table.html), so a row and
 * its county on the map are one thing seen twice. Hovering either marks both:
 * the row takes `.is-hovered`, the area takes the outline and label the cursor
 * would give it on the map (map-figure.js: Figure.highlight / the
 * 'mapfigure:hover' event).
 *
 * Keyboard too: the row's county link taking focus marks the same pair, so
 * tabbing the table walks the map.
 *
 * Delegated from the document and paired on the county's sqid, so there is
 * nothing to re-initialise after an htmx swap.
 *
 * Plain ES2017.
 */
(function () {
  'use strict';

  var ROW = '.by-county-table tbody tr[data-county]';

  function highlightAreas(key) {
    var M = window.SJVAirMaps;
    // Figures are built when they scroll into view; before that there is
    // nothing to mark, which is the right answer anyway.
    var figures = M && M.instances ? M.instances('figure') : [];
    figures.forEach(function (figure) {
      if (figure && figure.highlight) figure.highlight(key);
    });
  }

  function markRows(key) {
    var rows = document.querySelectorAll(ROW);
    for (var i = 0; i < rows.length; i++) {
      rows[i].classList.toggle('is-hovered', key != null && rows[i].dataset.county === key);
    }
  }

  function rowFor(target) {
    return target && target.closest ? target.closest(ROW) : null;
  }

  document.addEventListener('mouseover', function (evt) {
    var row = rowFor(evt.target);
    if (row) highlightAreas(row.dataset.county);
  });

  document.addEventListener('mouseout', function (evt) {
    var row = rowFor(evt.target);
    // Moving between the cells of one row is not leaving it.
    if (row && !row.contains(evt.relatedTarget)) highlightAreas(null);
  });

  document.addEventListener('focusin', function (evt) {
    var row = rowFor(evt.target);
    if (row) highlightAreas(row.dataset.county);
  });

  document.addEventListener('focusout', function (evt) {
    var row = rowFor(evt.target);
    if (row && !row.contains(evt.relatedTarget)) highlightAreas(null);
  });

  document.addEventListener('mapfigure:hover', function (evt) {
    markRows(evt.detail ? evt.detail.key : null);
  });
})();
