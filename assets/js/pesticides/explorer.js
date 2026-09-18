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

  // Leaflet mutates the DOM it is given, so a cached history snapshot would
  // restore dead map markup that our init() would then skip (data-rendered is
  // in the snapshot too). Setting the cache size to 0 makes back/forward
  // refetch from the server instead.
  window.htmx.config.historyCacheSize = 0;
  window.htmx.config.scrollBehavior = 'instant';

  // Re-run the component initialisers over freshly swapped content. htmx fires
  // htmx:load once on page load and again for each swapped-in element.
  document.body.addEventListener('htmx:load', function (evt) {
    var root = evt.detail && evt.detail.elt;
    if (!root) return;
    if (window.PesticidesSectionMap) window.PesticidesSectionMap.init(root);
    if (window.PesticidesFindArea) window.PesticidesFindArea.init(root);
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
