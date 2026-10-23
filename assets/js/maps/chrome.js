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

  // Once, when a panel the reader hasn't folded first has content: fold it
  // if, open, it would take more than half the map's height. Its own
  // scrolling body keeps it inside the map either way (map.css).
  function fitPanels(shell) {
    if (!shell.wrap || !shell.wrap.clientHeight) return;
    var panels = shell.wrap.querySelectorAll('.map-panel[data-autofit]');
    Array.prototype.forEach.call(panels, function (panel) {
      var body = panel.querySelector('.map-panel-body');
      if (!body || !body.childElementCount) return;
      panel.removeAttribute('data-autofit');
      var height = panel.offsetHeight + body.scrollHeight - body.clientHeight;
      if (height > shell.wrap.clientHeight * 0.5) setPanelCollapsed(panel, true);
    });
  }

  function bindPanels(shell) {
    var panels = shell.wrap.querySelectorAll('.map-panel[data-panel]');
    Array.prototype.forEach.call(panels, function (panel) {
      var key = panelKey(shell, panel.getAttribute('data-panel'));
      // Until the reader folds it, a panel starts open on a desktop and
      // folded on a phone, where it would cover the map. An open one is
      // checked again once it has content (fitPanels): on a map too short
      // for it, it folds too.
      var stored = readPanelState(key);
      setPanelCollapsed(panel, stored === null ? M.isPhone() : stored);
      if (stored === null && !M.isPhone()) panel.setAttribute('data-autofit', '1');
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
      // Clear any nudge from keepMenuInView: a stale shift must not carry
      // into the next open, where the trigger (and so the overflow) may differ.
      var menu = dropdown.querySelector('.dropdown-menu');
      if (menu) menu.style.transform = '';
    });
  }

  // A dropdown near the toolbar's own left or right end (the Dairies map's
  // Size and Digester controls, right after the view switch, unlike the
  // wider dropdowns further along the row) can open with its menu running
  // past the map's edge on a narrow phone, however the toolbar wraps that
  // day. Rather than guess safe widths per control and viewport, nudge the
  // opened menu back into view with a transform -- it still opens from the
  // same trigger, just shifted the least amount needed.
  function keepMenuInView(menu) {
    if (!menu) return;
    menu.style.transform = '';
    var rect = menu.getBoundingClientRect();
    var margin = 8;
    var shift = 0;
    // clientWidth, not window.innerWidth: the latter includes the
    // scrollbar's own width, which would let the nudge undershoot on
    // browsers with a visible scrollbar.
    var viewportWidth = document.documentElement.clientWidth;
    if (rect.right > viewportWidth - margin) shift = (viewportWidth - margin) - rect.right;
    if (rect.left + shift < margin) shift = margin - rect.left;
    if (shift) menu.style.transform = 'translateX(' + Math.round(shift) + 'px)';
  }

  // What a menu focuses on open: its search box; else, for a panel of
  // controls (the Options or Tweaks dialog), its first control -- the checked one of a
  // radio group -- not the last select a query for "select" would find; a
  // menu of plain links takes no focus (the reader arrows or tabs in).
  function firstControl(menu) {
    if (!menu) return null;
    var search = menu.querySelector('input[type="search"]');
    if (search) return search;
    var control = menu.querySelector('input:not([type="hidden"]), select');
    if (control && control.type === 'radio' && control.name) {
      var checked = menu.querySelector('input[type="radio"][name="' + control.name + '"]:checked');
      if (checked) control = checked;
    }
    return control;
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
        // Nudge before focusing: focus() can itself scroll the page (even
        // with preventScroll on some browsers) and shift the menu's
        // measured position, so settle the transform first.
        keepMenuInView(dropdown.querySelector('.dropdown-menu'));
        var focusable = firstControl(dropdown.querySelector('.dropdown-menu'));
        if (focusable) focusable.focus({ preventScroll: true });
      });
      // ArrowDown on a trigger opens the menu and moves into it.
      trigger.addEventListener('keydown', function (event) {
        if (event.key !== 'ArrowDown') return;
        event.preventDefault();
        if (!dropdown.classList.contains('is-active')) trigger.click();
        var first = firstControl(dropdown.querySelector('.dropdown-menu')) ||
          dropdown.querySelector('.dropdown-menu a[href]');
        if (first) first.focus({ preventScroll: true });
      });
      // Clicks inside the menu (typing, picking) shouldn't close it.
      var menu = dropdown.querySelector('.dropdown-menu');
      if (menu) menu.addEventListener('click', function (event) { event.stopPropagation(); });
      // Up and Down walk a menu of links.
      if (menu) menu.addEventListener('keydown', function (event) {
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
        var item = event.target.closest ? event.target.closest('a.dropdown-item') : null;
        if (!item) return;
        var items = Array.prototype.slice.call(menu.querySelectorAll('a.dropdown-item'));
        var next = items[items.indexOf(item) + (event.key === 'ArrowDown' ? 1 : -1)];
        event.preventDefault();
        (next || trigger).focus();
      });
    });
  }

  function bindDocument(shell) {
    if (shell.documentHandlers) return;
    // A mobile browser fires `resize` for a height-only change too -- the
    // URL bar collapsing or expanding as the reader scrolls -- which must
    // not close a dropdown they're mid-use with. Only clientWidth actually
    // changing (a real narrower/wider layout, or an orientation change)
    // means a nudged menu's measurement is stale.
    shell.lastWidth = document.documentElement.clientWidth;
    var handlers = shell.documentHandlers = {
      click: function () { closeDropdowns(shell, null); },
      keydown: function (event) {
        if (event.key !== 'Escape' || event.defaultPrevented) return;
        // An open menu closes first, and focus goes back to its trigger
        // (the menu hiding would drop it to the body); only with none open
        // does Escape leave expanded mode.
        var open = shell.toolbarEl && shell.toolbarEl.querySelector('.dropdown.is-active');
        if (open) {
          var trigger = open.querySelector('.dropdown-trigger .button');
          var focusInside = open.contains(document.activeElement) || document.activeElement === document.body;
          closeDropdowns(shell, null);
          if (trigger && focusInside) trigger.focus();
          return;
        }
        if (shell.expanded) setExpanded(shell, false);
      },
      resize: function () {
        if (shell.expanded) fitBelowNavbar(shell);
        var width = document.documentElement.clientWidth;
        if (width === shell.lastWidth) return;
        shell.lastWidth = width;
        // A nudged dropdown menu was measured against the viewport at
        // open time; rather than re-measure on every width change, just
        // close it -- the reader can reopen it in the new layout.
        closeDropdowns(shell, null);
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

  // The loading bar along the map's top edge, on every map with a wrapper:
  // shown while the map's data is still on its way (shell.track()). Made
  // here rather than in the template so no map can be without it.
  function loadingBar(wrap) {
    if (!wrap.classList.contains('map-wrap')) return null;
    var bar = wrap.querySelector(':scope > .map-loading');
    if (!bar) {
      bar = document.createElement('div');
      bar.className = 'map-loading';
      bar.setAttribute('aria-hidden', 'true');
      wrap.appendChild(bar);
    }
    return bar;
  }

  function setLoading(shell, on) {
    shell.loadingShown = !!on;
    if (shell.loadingEl) shell.loadingEl.classList.toggle('is-active', !!on);
    // Screen readers hear it as the map being busy, not as a bar.
    if (shell.wrap && shell.loadingEl) shell.wrap.setAttribute('aria-busy', on ? 'true' : 'false');
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
    // In expanded mode the page's filter box is off-screen: into the slide-out with it (and back out after).
    syncFilters(shell);
    if (!on && was) window.scrollTo(0, shell.scrollBeforeExpand || 0);
    // Resize once the new layout has applied, so the moveend that follows
    // measures the new size.
    setTimeout(function () { if (shell.map) shell.map.resize(); }, 0);
  }

  // -- the page's filter box, when it's out of sight: on a phone (stacked
  // above the map) or in expanded mode (off-screen), a Filters button first
  // in the toolbar, with how many are on, opens a slide-out with the box
  // itself in it -- moved there, never copied, so its form, its htmx and the
  // location search's bindings come along -- and chips over the map say
  // what's on. On a desktop page the box sits beside the map, as it's laid
  // out. Which box: the one in the map's own row (.columns). --

  var NARROW = '(max-width: 768px)';

  function filterBox(shell) {
    var row = shell.wrap && shell.wrap.closest('.columns');
    if (!row) return null;
    // `.explorer-filters`, or any box marked data-filter-box (pesticides' notices and records boxes).
    var boxes = Array.prototype.filter.call(row.querySelectorAll('.explorer-filters, [data-filter-box]'), function (box) {
      return !box.closest('.map-wrap') || box.closest('.map-filters-slot');
    });
    return boxes[0] || null;
  }

  function filtersTucked(shell) {
    return !!shell.expanded || !!(window.matchMedia && window.matchMedia(NARROW).matches);
  }

  // A field's label: its <label for>, its fieldset's legend, or its name.
  function fieldLabel(box, field) {
    var label = field.id ? box.querySelector('label[for="' + field.id + '"]') : null;
    if (!label) {
      var fieldset = field.closest('fieldset');
      label = fieldset ? fieldset.querySelector('legend') : null;
    }
    return label ? label.textContent.replace(/\s+/g, ' ').trim() : field.name;
  }

  // What's on in the box, each with how to turn it off: a search's text, a
  // select away from its first (the "all") option, a single checkbox ticked,
  // or a group of checkboxes with some left off.
  function activeFilters(box) {
    var chips = [];
    var groups = {};
    Array.prototype.forEach.call(box.querySelectorAll('input[name], select[name]'), function (field) {
      if (field.disabled) return;
      if (field.type === 'hidden') {
        // A picker (pesticides' entity-picker.html): the value is a hidden
        // id, what's picked a tag beside it. Other hidden fields are scope.
        var picker = field.value && field.closest('.field');
        var picked = picker && picker.querySelector('.tag');
        if (picked) {
          var label = picker.querySelector('.label');
          chips.push({
            text: (label ? label.textContent.trim() + ': ' : '') + picked.textContent.trim(),
            clear: function () { field.value = ''; },
          });
        }
        return;
      }
      if (field.tagName === 'SELECT') {
        if (field.selectedIndex > 0) {
          chips.push({ text: fieldLabel(box, field) + ': ' + field.options[field.selectedIndex].text, clear: function () { field.selectedIndex = 0; } });
        }
      } else if (field.type === 'checkbox') {
        (groups[field.name] = groups[field.name] || []).push(field);
      } else if (field.type === 'radio') {
        // A switch (Scheduled | Past): on when anything but its first choice is picked.
        var group = box.querySelectorAll('input[type="radio"][name="' + field.name + '"]');
        if (field.checked && group[0] !== field) {
          var first = group[0];
          var text = field.closest('label') ? field.closest('label').textContent.trim() : field.value;
          chips.push({ text: fieldLabel(box, field) + ': ' + text, clear: function () { first.checked = true; } });
        }
      } else if (field.value.trim()) {
        chips.push({ text: fieldLabel(box, field) + ': ' + field.value.trim(), clear: function () { field.value = ''; } });
      }
    });
    Object.keys(groups).forEach(function (name) {
      var boxes = groups[name];
      if (boxes.length === 1) {
        var only = boxes[0];
        if (only.checked) {
          var text = only.closest('label') ? only.closest('label').textContent.trim() : fieldLabel(box, only);
          chips.push({ text: text, clear: function () { only.checked = false; } });
        }
        return;
      }
      var on = boxes.filter(function (b) { return b.checked; });
      if (on.length && on.length < boxes.length) {
        chips.push({
          text: fieldLabel(box, boxes[0]) + ': ' + on.map(function (b) { return b.closest('label') ? b.closest('label').textContent.trim() : b.value; }).join(', '),
          clear: function () { boxes.forEach(function (b) { b.checked = true; }); },
        });
      }
    });
    return chips;
  }

  // Applies the box's form after a chip cleared a field: the box's own
  // submit, so its htmx (and the map's view-carrying) runs as if the reader did it.
  function submitBox(box) {
    var form = box.tagName === 'FORM' ? box : box.querySelector('form');
    if (!form) return;
    if (form.requestSubmit) form.requestSubmit(); else form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  }

  function renderChips(shell, box, tucked) {
    var chipsEl = shell.wrap.querySelector('.map-filter-chips');
    var count = shell.wrap.querySelector('.map-filters-count');
    var chips = box ? activeFilters(box) : [];
    if (count) {
      count.textContent = chips.length ? String(chips.length) : '';
      count.hidden = !chips.length;
    }
    if (!chipsEl) return;
    chipsEl.innerHTML = '';
    // While the slide-out is open, the box itself says what's on.
    chipsEl.hidden = !(tucked && chips.length && !shell.filtersOpen);
    chips.forEach(function (chip) {
      var tag = document.createElement('span');
      tag.className = 'tag is-white map-filter-chip';
      tag.title = chip.text;
      var text = document.createElement('span');
      text.className = 'map-filter-chip-text';
      text.textContent = chip.text;
      tag.appendChild(text);
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'delete is-small';
      remove.setAttribute('aria-label', 'Remove the filter: ' + chip.text);
      remove.addEventListener('click', function () { chip.clear(); submitBox(box); });
      tag.appendChild(remove);
      chipsEl.appendChild(tag);
    });
  }

  function setFiltersOpen(shell, open) {
    shell.filtersOpen = !!open;
    var chipsEl = shell.wrap && shell.wrap.querySelector('.map-filter-chips');
    if (chipsEl) chipsEl.hidden = shell.filtersOpen || !chipsEl.children.length || !filtersTucked(shell);
    var panel = shell.wrap && shell.wrap.querySelector('.map-filters-panel');
    var toggle = shell.wrap && shell.wrap.querySelector('.map-filters-toggle');
    if (panel) panel.hidden = !shell.filtersOpen;
    if (toggle) {
      toggle.setAttribute('aria-expanded', shell.filtersOpen ? 'true' : 'false');
      toggle.classList.toggle('is-selected', shell.filtersOpen);
    }
  }

  // Puts the box where it belongs now: in the slide-out while it'd be out of
  // sight, back in its own place (marked when first moved) otherwise. Keeps
  // the focus of a field being typed in across the move.
  function syncFilters(shell) {
    if (!shell.wrap) return;
    var toggle = shell.wrap.querySelector('.map-filters-toggle');
    var slot = shell.wrap.querySelector('.map-filters-slot');
    var box = filterBox(shell);
    var tucked = !!(box && slot && filtersTucked(shell));
    if (toggle) toggle.hidden = !tucked;
    if (box) {
      var active = document.activeElement;
      var focused = active && box.contains(active) ? active : null;
      var caret = focused && typeof focused.selectionStart === 'number' ? focused.selectionStart : null;
      if (tucked && box.parentNode !== slot) {
        if (!box.mapFiltersHome) {
          box.mapFiltersHome = document.createComment('map filters');
          box.parentNode.insertBefore(box.mapFiltersHome, box);
        }
        slot.appendChild(box);
      } else if (!tucked && box.mapFiltersHome && box.parentNode === slot) {
        box.mapFiltersHome.parentNode.insertBefore(box, box.mapFiltersHome);
      }
      if (focused && document.activeElement !== focused) {
        focused.focus({ preventScroll: true });
        if (caret !== null && focused.setSelectionRange) focused.setSelectionRange(caret, caret);
      }
    }
    if (!tucked) setFiltersOpen(shell, false);
    else setFiltersOpen(shell, shell.filtersOpen);
    renderChips(shell, box, tucked);
    placeUnderToolbar(shell);
  }

  // The slide-out and the chips start just under the toolbar, however many rows it wrapped to.
  function placeUnderToolbar(shell) {
    if (!shell.toolbarEl || !shell.wrap) return;
    var top = shell.toolbarEl.getBoundingClientRect().bottom - shell.wrap.getBoundingClientRect().top;
    if (!(top > 0)) return;
    ['.map-filters-panel', '.map-filter-chips'].forEach(function (selector) {
      var el = shell.wrap.querySelector(selector);
      if (el) el.style.top = Math.round(top + 8) + 'px';
    });
  }

  function bindFilters(shell) {
    var toggle = shell.wrap.querySelector('.map-filters-toggle');
    if (toggle && !toggle.getAttribute('data-bound')) {
      toggle.setAttribute('data-bound', '1');
      toggle.addEventListener('click', function () {
        setFiltersOpen(shell, !shell.filtersOpen);
        placeUnderToolbar(shell);
      });
    }
    var close = shell.wrap.querySelector('.map-filters-close');
    if (close && !close.getAttribute('data-bound')) {
      close.setAttribute('data-bound', '1');
      close.addEventListener('click', function () {
        setFiltersOpen(shell, false);
        if (toggle) toggle.focus();
      });
    }
    var panel = shell.wrap.querySelector('.map-filters-panel');
    if (panel && !panel.getAttribute('data-bound')) {
      panel.setAttribute('data-bound', '1');
      panel.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
          event.stopPropagation();
          setFiltersOpen(shell, false);
          if (toggle) toggle.focus();
        }
      });
      // A field changed in the slide-out: the count and chips follow before the swap does.
      panel.addEventListener('change', function () { renderChips(shell, filterBox(shell), filtersTucked(shell)); });
    }
    // A phone turned sideways, a window resized past the breakpoint.
    if (!shell.filtersMedia && window.matchMedia) {
      shell.filtersMedia = window.matchMedia(NARROW);
      shell.onFiltersMedia = function () { syncFilters(shell); };
      if (shell.filtersMedia.addEventListener) shell.filtersMedia.addEventListener('change', shell.onFiltersMedia);
      else if (shell.filtersMedia.addListener) shell.filtersMedia.addListener(shell.onFiltersMedia);
    }
    syncFilters(shell);
  }

  function unbindFilters(shell) {
    if (!shell.filtersMedia) return;
    if (shell.filtersMedia.removeEventListener) shell.filtersMedia.removeEventListener('change', shell.onFiltersMedia);
    else if (shell.filtersMedia.removeListener) shell.filtersMedia.removeListener(shell.onFiltersMedia);
    shell.filtersMedia = null;
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
    // A new page's wrapper picks up a load already under way.
    shell.loadingEl = loadingBar(wrap);
    setLoading(shell, shell.loadingShown);
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
    if (shell.toolbarEl) bindFilters(shell);
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
          // No room either way (a tall popup on a phone, between the wrapped
          // toolbar and the folded legend): up only as far as keeps its top
          // -- the title and close button -- clear of the toolbar; the
          // legend is the one that gets covered.
          dy += Math.min(up, moved.top - inner.top);
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
    setLoading: setLoading,
    fitPanels: fitPanels,
    setExpanded: setExpanded,
    syncFilters: syncFilters,
    unbindFilters: unbindFilters,
    fitBelowNavbar: fitBelowNavbar,
    popupMaxWidth: popupMaxWidth,
    panPopupIntoView: panPopupIntoView,
    collapseAttribution: collapseAttribution,
  };
})();
