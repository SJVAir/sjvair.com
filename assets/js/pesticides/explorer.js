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
  // Once per page. A Back/Forward restore (historyCacheSize is 0, so htmx
  // refetches the page and swaps the body) runs this script again, but the
  // document and body keep the listeners bound the first time. Binding them
  // twice made every toggle below (scope dropdowns, the schools list) flip
  // open and straight back shut.
  if (window.SJVAirExplorerBound) return;
  window.SJVAirExplorerBound = true;

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
    // Every map on the core: figures, the section map (and later ones).
    if (window.SJVAirMaps && window.SJVAirMaps.init) window.SJVAirMaps.init(root);
    if (window.PesticidesFindArea) window.PesticidesFindArea.init(root);
    if (window.PesticidesEntityPicker) window.PesticidesEntityPicker.init(root);
  });

  // Menu dropdowns: the scope bar's (year, county, narrow) and the
  // by-county table's column picker. A click on a trigger opens its menu, a
  // click anywhere else or Escape closes it. Delegated from the document, so
  // it survives the body swaps that replace them.
  var DROPDOWNS = '.explorer-scope-picker, .column-picker';
  var DROPDOWN_TRIGGERS = '.explorer-scope-picker .dropdown-trigger .button, .column-picker .dropdown-trigger .button';
  var DROPDOWNS_OPEN = '.explorer-scope-picker.is-active, .column-picker.is-active';
  document.addEventListener('click', function (evt) {
    var trigger = evt.target.closest ? evt.target.closest(DROPDOWN_TRIGGERS) : null;
    var open = trigger ? trigger.closest(DROPDOWNS) : null;
    document.querySelectorAll(DROPDOWNS_OPEN).forEach(function (picker) {
      if (picker === open) return;
      picker.classList.remove('is-active');
      var button = picker.querySelector('.dropdown-trigger .button');
      if (button) button.setAttribute('aria-expanded', 'false');
    });
    if (!open) return;
    var active = open.classList.toggle('is-active');
    trigger.setAttribute('aria-expanded', active ? 'true' : 'false');
  });
  // A list that renders every item and hides the ones past its first few
  // (`.is-collapsed`: the school districts box past five, the "In and around"
  // lists past a dozen) reveals them in place: the button's [data-reveal-toggle]
  // flips them within its [data-reveal-scope]. Delegated from the document
  // so it survives the htmx swaps a filter or sort makes, and driven off the
  // button's own data attributes so a re-render comes back collapsed
  // without any state to restore.
  document.addEventListener('click', function (evt) {
    var button = evt.target.closest ? evt.target.closest('[data-reveal-toggle]') : null;
    if (!button) return;
    var scope = button.closest('[data-reveal-scope]');
    if (!scope) return;
    var expanded = button.getAttribute('aria-expanded') === 'true';
    scope.querySelectorAll('.is-collapsed').forEach(function (item) {
      item.classList.toggle('is-revealed', !expanded);
    });
    button.setAttribute('aria-expanded', expanded ? 'false' : 'true');
    button.textContent = expanded
      ? button.getAttribute('data-show-label')
      : button.getAttribute('data-hide-label');
  });

  // The keyboard side of the dropdowns (they are disclosure widgets of plain
  // links, not ARIA menus): Escape closes the open one and puts focus back on
  // its trigger, which would otherwise be lost to the body when the menu
  // hides; ArrowDown on a trigger opens its menu and moves into the list, and
  // Up/Down walk the links.
  function menuItems(picker) {
    return Array.prototype.slice.call(picker.querySelectorAll('.dropdown-menu a[href], .dropdown-menu input:not([type="hidden"]), .dropdown-menu button'));
  }
  document.addEventListener('keydown', function (evt) {
    if (evt.key === 'Escape') {
      document.querySelectorAll(DROPDOWNS_OPEN).forEach(function (picker) {
        var button = picker.querySelector('.dropdown-trigger .button');
        var focusInside = picker.contains(document.activeElement) || document.activeElement === document.body;
        picker.classList.remove('is-active');
        if (button) {
          button.setAttribute('aria-expanded', 'false');
          if (focusInside) button.focus();
        }
      });
      return;
    }
    if (evt.key !== 'ArrowDown' && evt.key !== 'ArrowUp') return;
    var trigger = evt.target.closest ? evt.target.closest(DROPDOWN_TRIGGERS) : null;
    if (trigger && evt.key === 'ArrowDown') {
      var picker = trigger.closest(DROPDOWNS);
      if (!picker.classList.contains('is-active')) {
        document.querySelectorAll(DROPDOWNS_OPEN).forEach(function (other) {
          other.classList.remove('is-active');
          var otherButton = other.querySelector('.dropdown-trigger .button');
          if (otherButton) otherButton.setAttribute('aria-expanded', 'false');
        });
        picker.classList.add('is-active');
        trigger.setAttribute('aria-expanded', 'true');
      }
      var first = menuItems(picker)[0];
      if (first) {
        evt.preventDefault();
        first.focus();
      }
      return;
    }
    var item = evt.target.closest ? evt.target.closest('.dropdown-item') : null;
    var owner = item ? item.closest(DROPDOWNS) : null;
    if (!owner) return;
    var items = menuItems(owner);
    var index = items.indexOf(item);
    var next = items[index + (evt.key === 'ArrowDown' ? 1 : -1)];
    if (next) {
      evt.preventDefault();
      next.focus();
    } else if (evt.key === 'ArrowUp') {
      evt.preventDefault();
      owner.querySelector('.dropdown-trigger .button').focus();
    }
  });

  // A tooltip's bubble is centred on its element and up to 22rem wide, so one
  // near either edge of the screen would run off it. When the pointer or
  // focus arrives, anchor the bubble to the near edge instead (the
  // has-tooltip-end / -start rules in global.sass). Left on the element, so
  // a resize is corrected the next time it is shown.
  function placeTooltip(evt) {
    var el = evt.target && evt.target.closest ? evt.target.closest('[data-tooltip]') : null;
    if (!el) return;
    // Side tooltips are placed by the extension, and a class set by hand in
    // a template is the template's: this only adds and removes its own,
    // which it records in data-tooltip-auto.
    if (el.classList.contains('has-tooltip-left') || el.classList.contains('has-tooltip-right')) return;
    var auto = el.getAttribute('data-tooltip-auto');
    if (!auto && (el.classList.contains('has-tooltip-end') || el.classList.contains('has-tooltip-start'))) return;
    var rect = el.getBoundingClientRect();
    var center = rect.left + rect.width / 2;
    var viewport = document.documentElement.clientWidth;
    var half = Math.min(176, (viewport - 16) / 2);
    var want = center + half > viewport - 8 ? 'end' : (center - half < 8 ? 'start' : '');
    if (auto === want) return;
    if (auto) el.classList.remove('has-tooltip-' + auto);
    if (want) {
      el.classList.add('has-tooltip-' + want);
      el.setAttribute('data-tooltip-auto', want);
    } else {
      el.removeAttribute('data-tooltip-auto');
    }
  }
  document.addEventListener('mouseover', placeTooltip);
  document.addEventListener('focusin', placeTooltip);

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
