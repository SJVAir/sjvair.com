/*
 * The chrome around a map (templates/maps/includes/map.html): the toolbar's
 * dropdowns, foldable panels, the status pill, expanded mode, keeping popups
 * clear of the chrome, and folding the SDK's attribution. Everything here
 * acts on a Shell (shell.js); attach() re-finds and binds the chrome after
 * every adopt, since a swap brings new chrome elements.
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M || M.chrome) return;

  // Popups keep this far from the map's edges, and below the toolbar band.
  var POPUP_CLEAR_TOP = 56;
  var POPUP_CLEAR_EDGE = 10;
  var POPUP_MAX_WIDTH = 320;

  // -- panels: folded state per viewer in localStorage (wrapped: storage can
  // be absent or throw, and the panels must work regardless) --

  function panelKey(shell, panel) {
    var prefix = shell.spec.panelStoragePrefix || ('sjvair:map:' + shell.name + ':panel:');
    return prefix + panel;
  }

  function readPanelState(key) {
    try {
      var stored = window.localStorage.getItem(key);
      return stored === null ? null : stored === 'collapsed';
    } catch (err) {
      return null;
    }
  }

  function writePanelState(key, collapsed) {
    try {
      window.localStorage.setItem(key, collapsed ? 'collapsed' : 'open');
    } catch (err) {
      // The fold just won't be remembered.
    }
  }

  function setPanelCollapsed(panel, collapsed) {
    panel.classList.toggle('is-collapsed', collapsed);
    var toggle = panel.querySelector('.map-panel-toggle');
    if (toggle) toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  }

  // The panels the chrome renders; a shell with none of them has no panel
  // to fold, and must not touch another map's.
  var PANEL_FEATURES = ['legend'];

  function hasPanels(features) {
    return PANEL_FEATURES.some(function (feature) { return features[feature]; });
  }

  function bindPanels(shell) {
    var panels = shell.wrap.querySelectorAll('.map-panel[data-panel]');
    Array.prototype.forEach.call(panels, function (panel) {
      var key = panelKey(shell, panel.getAttribute('data-panel'));
      // Until the reader folds it, a panel starts open on a desktop and
      // folded on a phone, where it would cover the map.
      var stored = readPanelState(key);
      setPanelCollapsed(panel, stored === null ? M.isPhone() : stored);
      var toggle = panel.querySelector('.map-panel-toggle');
      if (!toggle || toggle.getAttribute('data-bound')) return;
      toggle.setAttribute('data-bound', '1');
      toggle.addEventListener('click', function () {
        var collapsed = !panel.classList.contains('is-collapsed');
        setPanelCollapsed(panel, collapsed);
        writePanelState(key, collapsed);
      });
    });
  }

  // -- toolbar dropdowns: a trigger opens its menu (and focuses its search
  // box or select), a click elsewhere or Escape closes it. Triggers are bound
  // once per toolbar element; the document-level closers once per map. --

  function closeDropdowns(shell, except) {
    if (!shell.toolbarEl) return;
    Array.prototype.forEach.call(shell.toolbarEl.querySelectorAll('.dropdown'), function (dropdown) {
      if (dropdown === except) return;
      dropdown.classList.remove('is-active');
      var trigger = dropdown.querySelector('.dropdown-trigger .button');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
    });
  }

  function bindToolbar(shell) {
    var toolbar = shell.toolbarEl;
    if (!toolbar || toolbar.getAttribute('data-bound')) return;
    toolbar.setAttribute('data-bound', '1');
    Array.prototype.forEach.call(toolbar.querySelectorAll('.dropdown'), function (dropdown) {
      var trigger = dropdown.querySelector('.dropdown-trigger .button');
      if (!trigger) return;
      trigger.addEventListener('click', function (event) {
        event.stopPropagation();
        var open = !dropdown.classList.contains('is-active');
        closeDropdowns(shell, dropdown);
        dropdown.classList.toggle('is-active', open);
        trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (!open) return;
        if (shell.module && shell.module.onDropdownOpen) shell.module.onDropdownOpen();
        var focusable = dropdown.querySelector('input[type="search"], select');
        if (focusable) focusable.focus();
      });
      // Clicks inside the menu (typing, picking) shouldn't close it.
      var menu = dropdown.querySelector('.dropdown-menu');
      if (menu) menu.addEventListener('click', function (event) { event.stopPropagation(); });
    });
  }

  function bindDocument(shell) {
    if (shell.documentHandlers) return;
    var handlers = shell.documentHandlers = {
      click: function () { closeDropdowns(shell, null); },
      keydown: function (event) {
        if (event.key !== 'Escape') return;
        closeDropdowns(shell, null);
        if (shell.expanded) setExpanded(shell, false);
      },
      resize: function () {
        if (shell.expanded) fitBelowNavbar(shell);
      },
    };
    document.addEventListener('click', handlers.click);
    document.addEventListener('keydown', handlers.keydown);
    window.addEventListener('resize', handlers.resize);
  }

  function unbindDocument(shell) {
    var handlers = shell.documentHandlers;
    if (!handlers) return;
    document.removeEventListener('click', handlers.click);
    document.removeEventListener('keydown', handlers.keydown);
    window.removeEventListener('resize', handlers.resize);
    shell.documentHandlers = null;
  }

  function setStatus(shell, message) {
    if (shell.statusEl) shell.statusEl.textContent = message || '';
  }

  // -- expanded mode: the map fills the viewport under the site navbar, with
  // the explorer's scope bar pinned above it. Escape or the button brings the
  // page back, and the reader lands where they were. --

  // The expanded map starts exactly where the navbar (and the pinned scope
  // bar) end, measured rather than assumed; the wrap starts 1px above so the
  // two borders coincide.
  function fitBelowNavbar(shell) {
    if (!shell.wrap) return;
    var nav = document.querySelector('nav.navbar');
    var bottom = nav ? nav.getBoundingClientRect().bottom : 0;
    var scopeBar = document.querySelector('.explorer-scope-bar');
    if (scopeBar) {
      scopeBar.style.top = Math.max(0, bottom) + 'px';
      bottom = scopeBar.getBoundingClientRect().bottom;
    }
    shell.wrap.style.top = Math.max(0, bottom - 1) + 'px';
  }

  function setExpanded(shell, on) {
    var was = !!shell.expanded;
    shell.expanded = on;
    // The navbar isn't fixed, so the expanded map sits below it only while
    // the page is at the top: go there on the way in, back on the way out.
    if (on && !was) {
      shell.scrollBeforeExpand = window.scrollY || window.pageYOffset || 0;
      window.scrollTo(0, 0);
    }
    // The html class first: it pins the scope bar, which fitBelowNavbar measures.
    document.documentElement.classList.toggle('map-expanded', on);
    if (shell.wrap) {
      shell.wrap.classList.toggle('is-expanded', on);
      if (on) {
        fitBelowNavbar(shell);
      } else {
        shell.wrap.style.top = '';
        var scopeBar = document.querySelector('.explorer-scope-bar');
        if (scopeBar) scopeBar.style.top = '';
      }
      var button = shell.wrap.querySelector('.map-expand');
      if (button) {
        button.setAttribute('aria-pressed', on ? 'true' : 'false');
        button.setAttribute('title', on ? 'Back to the page' : 'Expand the map');
        button.setAttribute('aria-label', on ? 'Back to the page' : 'Expand the map');
      }
    }
    if (!on && was) window.scrollTo(0, shell.scrollBeforeExpand || 0);
    // Resize once the new layout has applied, so the moveend that follows
    // measures the new size.
    setTimeout(function () { if (shell.map) shell.map.resize(); }, 0);
  }

  // (Re)finds the chrome around the container and binds what's new.
  function attach(shell) {
    // The chrome is the container's own .map-wrap (maps/includes/map.html).
    // A map rendered without that wrapper -- a figure, which asks for no
    // chrome -- falls back to its parent, which rests on nothing nesting a
    // map inside another map's wrapper: were one ever nested there, every
    // feature below is off for it, so it still finds nothing of the outer
    // map's to take over.
    var wrap = shell.el.closest('.map-wrap') || shell.el.parentNode;
    // Which of these is on comes from the container's data-features when the
    // server rendered the chrome, else from the module's spec (shell.js).
    var features = shell.features;
    shell.wrap = wrap;
    shell.toolbarEl = features.toolbar ? wrap.querySelector('.map-toolbar') : null;
    shell.legendPanelEl = features.legend ? wrap.querySelector('.map-legend-panel') : null;
    shell.legendBodyEl = shell.legendPanelEl ? shell.legendPanelEl.querySelector('.map-panel-body') : null;
    shell.statusEl = features.status ? wrap.querySelector('.map-status') : null;
    if (shell.toolbarEl) {
      shell.toolbarEl.hidden = false;
      bindToolbar(shell);
    }
    if (shell.legendPanelEl) shell.legendPanelEl.hidden = false;
    if (hasPanels(features)) bindPanels(shell);
    var expand = wrap.querySelector('.map-expand');
    if (features.expand && expand && !expand.getAttribute('data-bound')) {
      expand.setAttribute('data-bound', '1');
      expand.addEventListener('click', function () { setExpanded(shell, !shell.expanded); });
    }
    // An adopted map keeps its expanded state on the new page's chrome.
    if (features.expand && shell.expanded) setExpanded(shell, true);
  }

  // -- popups --

  // A popup's width: its own, or what the map can hold with the edge margin
  // on both sides (a phone). The SDK anchors a popup to whichever side of its
  // point has room, so one wider than that room has no stable side.
  function popupMaxWidth(shell) {
    var room = shell.el.clientWidth - 2 * POPUP_CLEAR_EDGE;
    return Math.min(POPUP_MAX_WIDTH, room > 0 ? room : POPUP_MAX_WIDTH) + 'px';
  }

  // Pans the map, by as little as it takes, so `popup` is clear of the map's
  // edges, the toolbar band and the legend panel (the SDK can't see the chrome
  // floating over the map). The popup can grow a beat after it opens (the icon
  // font swaps its glyphs in), so one more look follows the first.
  function panPopupIntoView(shell, popup, again) {
    if (!shell.map || !popup) return;
    var recheck = function () {
      setTimeout(function () { if (popup.isOpen()) panPopupIntoView(shell, popup, true); }, 0);
    };
    var el = popup.getElement();
    if (!el) return;
    var rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    var box = shell.el.getBoundingClientRect();
    // The toolbar band is measured: on a phone the filter buttons wrap.
    var toolbarBottom = box.top + POPUP_CLEAR_TOP;
    if (shell.toolbarEl && !shell.toolbarEl.hidden) {
      var toolbarRect = shell.toolbarEl.getBoundingClientRect();
      if (toolbarRect.height) toolbarBottom = Math.max(toolbarBottom, toolbarRect.bottom + POPUP_CLEAR_EDGE);
    }
    var inner = {
      left: box.left + POPUP_CLEAR_EDGE,
      top: toolbarBottom,
      right: box.right - POPUP_CLEAR_EDGE,
      bottom: box.bottom - POPUP_CLEAR_EDGE,
    };
    // panBy moves the view, so the content goes the other way. A popup bigger
    // than the room keeps its top-left edge in view.
    var dx = 0;
    var dy = 0;
    if (rect.right > inner.right) dx = rect.right - inner.right;
    if (rect.left - dx < inner.left) dx = rect.left - inner.left;
    if (rect.bottom > inner.bottom) dy = rect.bottom - inner.bottom;
    if (rect.top - dy < inner.top) dy = rect.top - inner.top;
    // The legend: over it (up) or past it (right), whichever is the shorter
    // move that keeps the popup in the room.
    var legend = shell.legendPanelEl && !shell.legendPanelEl.hidden ? shell.legendPanelEl.getBoundingClientRect() : null;
    if (legend && legend.width && legend.height) {
      var gap = POPUP_CLEAR_EDGE;
      var moved = { left: rect.left - dx, right: rect.right - dx, top: rect.top - dy, bottom: rect.bottom - dy };
      var overlaps = moved.left < legend.right + gap && moved.right > legend.left - gap &&
        moved.top < legend.bottom + gap && moved.bottom > legend.top - gap;
      if (overlaps) {
        var up = moved.bottom - (legend.top - gap);
        var right = moved.left - (legend.right + gap);
        var upFits = moved.top - up >= inner.top;
        var rightFits = moved.right - right <= inner.right;
        if (upFits && (!rightFits || up <= -right)) {
          dy += up;
        } else if (rightFits) {
          dx += right;
        } else {
          dy += up;
        }
      }
    }
    if (!dx && !dy) {
      if (!again) recheck();
      return;
    }
    // Before the pan: a snap (reduced motion) fires moveend inside panBy.
    if (!again) shell.map.once('moveend', recheck);
    shell.map.panBy([dx, dy], { animate: !shell.reducedMotion });
  }

  // The SDK's compact attribution starts open until the first move; fold it,
  // as its own toggle does, out of the legend's way.
  function collapseAttribution(shell) {
    if (!shell.map) return;
    var attrib = shell.el.querySelector('.maplibregl-ctrl-attrib.maplibregl-compact');
    if (attrib && attrib.classList.contains('maplibregl-compact-show')) {
      attrib.classList.remove('maplibregl-compact-show');
      attrib.setAttribute('open', '');
    }
  }

  M.chrome = {
    attach: attach,
    bindDocument: bindDocument,
    unbindDocument: unbindDocument,
    closeDropdowns: closeDropdowns,
    setStatus: setStatus,
    setExpanded: setExpanded,
    fitBelowNavbar: fitBelowNavbar,
    popupMaxWidth: popupMaxWidth,
    panPopupIntoView: panPopupIntoView,
    collapseAttribution: collapseAttribution,
  };
})();
