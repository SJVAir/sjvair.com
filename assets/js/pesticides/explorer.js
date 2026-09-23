/*
 * htmx glue for the Pesticides Explorer.
 *
 * `#explorer` in `pesticides/base.html` carries `hx-boost`, so links and GET
 * forms inside it fetch the same full page the server already renders; htmx
 * pulls `#explorer` out of the response and swaps it in place, pushing the URL.
 * Every page still renders completely on a plain GET -- this only removes the
 * full-page reload.
 *
 * Responsibilities here:
 *   - htmx config (no history snapshot cache, instant scroll)
 *   - re-initialising our component scripts after each swap
 *   - failing safe: an error response falls back to a real navigation rather
 *     than leaving the page half-swapped
 */
(function () {
  'use strict';

  if (typeof window.htmx === 'undefined') return;

  // The map scripts mutate the DOM they are given, so a cached history
  // snapshot would restore dead map markup that our init() would then skip
  // (data-rendered is in the snapshot too). Setting the cache size to 0 makes
  // back/forward refetch from the server instead.
  window.htmx.config.historyCacheSize = 0;
  window.htmx.config.scrollBehavior = 'instant';
  // Boosted swaps scroll the target into view by default. A filter, sort, or
  // year change on the same page should leave the reader where they are;
  // only a move to a different page scrolls to the top (see afterSwap).
  window.htmx.config.scrollIntoViewOnBoost = false;

  // Re-run the component initialisers over freshly swapped content. htmx fires
  // htmx:load once on page load and again for each swapped-in element.
  document.body.addEventListener('htmx:load', function (evt) {
    var root = evt.detail && evt.detail.elt;
    if (!root) return;
    if (window.PesticidesCharts) window.PesticidesCharts.init(root);
    if (window.PesticidesSectionMap) window.PesticidesSectionMap.init(root);
    if (window.PesticidesFindArea) window.PesticidesFindArea.init(root);
    if (window.PesticidesEntityPicker) window.PesticidesEntityPicker.init(root);
    // Every map on the core: figures, the section map (and later ones).
    if (window.SJVAirMaps && window.SJVAirMaps.init) window.SJVAirMaps.init(root);
  });

  // The scope bar's dropdowns (year, county): a click on a trigger opens its
  // menu, a click anywhere else or Escape closes it. Delegated from the
  // document, so it survives the body swaps that replace the bar.
  document.addEventListener('click', function (evt) {
    var trigger = evt.target.closest ? evt.target.closest('.explorer-scope-picker .dropdown-trigger .button') : null;
    var open = trigger ? trigger.closest('.explorer-scope-picker') : null;
    document.querySelectorAll('.explorer-scope-picker.is-active').forEach(function (picker) {
      if (picker === open) return;
      picker.classList.remove('is-active');
      var button = picker.querySelector('.dropdown-trigger .button');
      if (button) button.setAttribute('aria-expanded', 'false');
    });
    if (!open) return;
    var active = open.classList.toggle('is-active');
    trigger.setAttribute('aria-expanded', active ? 'true' : 'false');
  });
  // The district page's schools table renders every matching row and hides
  // the ones past the first fifteen; this reveals them in place. Delegated
  // from the document so it survives the htmx swaps a filter or sort makes,
  // and driven off the button's own data attributes so a re-render comes
  // back collapsed without any state to restore.
  document.addEventListener('click', function (evt) {
    var button = evt.target.closest ? evt.target.closest('[data-schools-toggle]') : null;
    if (!button) return;
    var section = button.closest('.schools-nearby');
    var table = section ? section.querySelector('.schools-table') : null;
    if (!table) return;
    var expanded = button.getAttribute('aria-expanded') === 'true';
    table.querySelectorAll('tbody tr.is-collapsed').forEach(function (row) {
      row.classList.toggle('is-revealed', !expanded);
    });
    button.setAttribute('aria-expanded', expanded ? 'false' : 'true');
    button.textContent = expanded
      ? button.getAttribute('data-show-label')
      : button.getAttribute('data-hide-label');
  });

  document.addEventListener('keydown', function (evt) {
    if (evt.key !== 'Escape') return;
    document.querySelectorAll('.explorer-scope-picker.is-active').forEach(function (picker) {
      picker.classList.remove('is-active');
      var button = picker.querySelector('.dropdown-trigger .button');
      if (button) button.setAttribute('aria-expanded', 'false');
    });
  });

  // Filter forms carry hidden fields that are usually empty; dropping empty
  // values keeps the pushed URL to the parameters that mean something.
  document.body.addEventListener('htmx:configRequest', function (evt) {
    var params = evt.detail && evt.detail.parameters;
    if (!params) return;
    if (typeof params.keys === 'function' && typeof params.getAll === 'function') {
      Array.from(new Set(Array.from(params.keys()))).forEach(function (key) {
        var values = params.getAll(key);
        if (values.every(function (value) { return value === ''; })) params.delete(key);
      });
    } else {
      Object.keys(params).forEach(function (key) {
        if (params[key] === '') delete params[key];
      });
    }
  });

  // Typing in the filter search box swaps the region out from under the input
  // that has focus, so put the caret back where the user left it.
  var refocusId = null;
  var pathBeforeRequest = window.location.pathname;

  document.body.addEventListener('htmx:beforeRequest', function (evt) {
    var elt = evt.detail && evt.detail.elt;
    // Any search box in a filter form, not just the page-level one: the
    // district page's schools table has its own.
    refocusId = (elt && elt.tagName === 'INPUT' && elt.type === 'search' && elt.id) ? elt.id : null;
    pathBeforeRequest = window.location.pathname;
  });

  document.body.addEventListener('htmx:afterSwap', function () {
    // hx-push-url has already updated the address by now.
    if (window.location.pathname !== pathBeforeRequest) {
      window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
    }
    if (!refocusId) return;
    var input = document.getElementById(refocusId);
    refocusId = null;
    if (!input) return;
    input.focus();
    try {
      input.selectionStart = input.selectionEnd = input.value.length;
    } catch (err) {
      // `selectionStart` throws on some input types; focus alone is enough.
    }
  });

  // Don't swap anything but a successful response: a 404 or 500 page has no
  // `#explorer` to select, which would blank the region.
  document.body.addEventListener('htmx:beforeSwap', function (evt) {
    var status = evt.detail && evt.detail.xhr ? evt.detail.xhr.status : 0;
    if (status < 200 || status >= 400) {
      evt.detail.shouldSwap = false;
    }
  });

  // ...and fall back to a full navigation so the user still lands on the real
  // error page (or the page they asked for, rendered the plain way).
  document.body.addEventListener('htmx:responseError', function (evt) {
    var path = evt.detail && evt.detail.pathInfo && evt.detail.pathInfo.requestPath;
    if (path) window.location = path;
  });

  document.body.addEventListener('htmx:sendError', function (evt) {
    var path = evt.detail && evt.detail.pathInfo && evt.detail.pathInfo.requestPath;
    if (path) window.location = path;
  });
})();
