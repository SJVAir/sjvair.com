/*
 * Cross-entity autocomplete filters on the Pesticides Explorer.
 *
 * One of these backs each `.entity-picker` rendered by
 * `pesticides/includes/entity-picker.html`: a search box over
 * /api/2.0/pesticides/search/ for one kind (chemical, product, or commodity),
 * whose selection lands in a hidden input named after that kind -- the same
 * `?chemical=`/`?product=`/`?commodity=` the list and records views already
 * resolve.
 *
 * Two behaviours, per the container's `data-autosubmit`:
 *   1 -- the lists, whose filter form is boosted by htmx: picking or clearing
 *        submits the form, so the results swap in place.
 *   0 -- the records page, which submits on Apply only: picking or clearing
 *        just updates the field in place.
 *
 * Plain ES2017, no framework/bundler. Same shape as find-area.js: debounced,
 * aborted, stale-guarded, textContent only (never innerHTML with API text).
 */
(function () {
  'use strict';

  var DEBOUNCE_MS = 250;
  var MIN_QUERY_LENGTH = 2;
  var LIMIT = 10;

  function setText(el, text) {
    el.textContent = text == null ? '' : String(text);
  }

  function EntityPicker(el) {
    this.el = el;
    this.kind = el.dataset.kind || '';
    this.searchUrl = el.dataset.searchUrl || '';
    this.autosubmit = el.dataset.autosubmit === '1';

    this.hidden = el.querySelector('input[type="hidden"]');
    this.label = el.querySelector('label.label');

    this.results = [];
    this.activeIndex = -1;
    this.debounceTimer = null;
    this.abort = null;
    this.requestId = 0;

    this.bind();
  }

  // Re-bound after every re-render, since selecting and clearing replace the
  // control the listeners were attached to.
  EntityPicker.prototype.bind = function () {
    var self = this;

    this.input = this.el.querySelector('input[type="search"]');
    this.resultsEl = this.el.querySelector('.entity-picker-results');
    this.clearButton = this.el.querySelector('.entity-picker-clear');

    if (this.input) {
      this.input.addEventListener('input', function () {
        self.onInput();
      });
      this.input.addEventListener('keydown', function (event) {
        self.onKeyDown(event);
      });
      // The lists' filter form submits on any `change` that bubbles up to it.
      // The search box isn't a filter in its own right -- only the hidden
      // input is -- so keep its change events to itself; otherwise blurring a
      // half-typed query would swap the page out from under the picker.
      this.input.addEventListener('change', function (event) {
        event.stopPropagation();
      });
      this.input.addEventListener('blur', function () {
        // Let a click on a result register before the list disappears.
        window.setTimeout(function () {
          self.hideResults();
        }, 150);
      });
    }

    if (this.clearButton) {
      this.clearButton.addEventListener('click', function () {
        self.clear();
      });
    }
  };

  EntityPicker.prototype.hideResults = function () {
    this.results = [];
    this.activeIndex = -1;
    if (this.resultsEl) {
      this.resultsEl.hidden = true;
      this.resultsEl.innerHTML = '';
    }
    if (this.input) {
      this.input.removeAttribute('aria-activedescendant');
      this.input.setAttribute('aria-expanded', 'false');
    }
  };

  EntityPicker.prototype.onInput = function () {
    var self = this;
    var query = this.input.value.trim();

    window.clearTimeout(this.debounceTimer);
    this.requestId++; // invalidate any in-flight search
    if (this.abort) this.abort.abort();

    if (query.length < MIN_QUERY_LENGTH) {
      this.hideResults();
      return;
    }

    this.debounceTimer = window.setTimeout(function () {
      self.search(query);
    }, DEBOUNCE_MS);
  };

  EntityPicker.prototype.onKeyDown = function (event) {
    if (event.key === 'Escape') {
      this.hideResults();
      return;
    }

    if (!this.results.length) return;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.setActiveIndex(this.activeIndex + 1 >= this.results.length ? 0 : this.activeIndex + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.setActiveIndex(this.activeIndex <= 0 ? this.results.length - 1 : this.activeIndex - 1);
    } else if (event.key === 'Enter') {
      // Enter with a highlighted result picks it; without one, fall through to
      // the form's own submit rather than swallowing the key.
      if (this.activeIndex >= 0 && this.activeIndex < this.results.length) {
        event.preventDefault();
        this.select(this.results[this.activeIndex]);
      }
    }
  };

  EntityPicker.prototype.setActiveIndex = function (index) {
    this.activeIndex = index;
    var options = this.resultsEl ? this.resultsEl.querySelectorAll('li[role="option"]') : [];
    for (var i = 0; i < options.length; i++) {
      options[i].setAttribute('aria-selected', i === index ? 'true' : 'false');
    }
    if (index >= 0 && options[index] && this.input) {
      this.input.setAttribute('aria-activedescendant', options[index].id);
    } else if (this.input) {
      this.input.removeAttribute('aria-activedescendant');
    }
  };

  EntityPicker.prototype.search = function (query) {
    var self = this;

    if (!this.searchUrl || !this.kind) return;

    var abort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    this.abort = abort;
    var requestId = ++this.requestId;

    var url = this.searchUrl
      + '?type=' + encodeURIComponent(this.kind)
      + '&q=' + encodeURIComponent(query)
      + '&limit=' + LIMIT
      + this.scopeParams();

    fetch(url, abort ? { signal: abort.signal } : undefined)
      .then(function (response) {
        if (!response.ok) throw new Error('search request failed');
        return response.json();
      })
      .then(function (data) {
        if (requestId !== self.requestId) return; // a newer search superseded this one
        self.results = (data && data.results) || [];
        self.render();
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (requestId !== self.requestId) return;
        window.console && console.error && console.error('entity-picker: search failed', err);
        self.hideResults();
      });
  };

  EntityPicker.prototype.render = function () {
    var self = this;

    if (!this.resultsEl) return;

    this.resultsEl.innerHTML = '';
    this.activeIndex = -1;

    if (!this.results.length) {
      var empty = document.createElement('li');
      empty.className = 'entity-picker-empty';
      empty.setAttribute('role', 'presentation');
      setText(empty, 'No matches');
      this.resultsEl.appendChild(empty);
      this.resultsEl.hidden = false;
      if (this.input) this.input.setAttribute('aria-expanded', 'true');
      return;
    }

    this.results.forEach(function (result, index) {
      var li = document.createElement('li');
      li.id = 'picker-' + self.kind + '-result-' + index;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', 'false');

      var name = document.createElement('span');
      name.className = 'entity-picker-result-name';
      setText(name, result.name);
      li.appendChild(name);

      if (result.detail) {
        var detail = document.createElement('span');
        detail.className = 'entity-picker-result-detail';
        setText(detail, result.detail);
        li.appendChild(detail);
      }

      li.addEventListener('mousedown', function (event) {
        // mousedown (not click) fires before the input's blur handler hides the list.
        event.preventDefault();
        self.select(result);
      });

      self.resultsEl.appendChild(li);
    });

    this.resultsEl.hidden = false;
    if (this.input) this.input.setAttribute('aria-expanded', 'true');
  };

  // The page's year, county and concern scope, so the suggestions are names with use in
  // the same scope the list shows: the enclosing form's fields when it has
  // them (the lists), else the page's ?year=.
  EntityPicker.prototype.scopeParams = function () {
    var form = this.el.closest('form');
    var params = '';
    var year = form && form.elements.year ? form.elements.year.value : '';
    if (!year) {
      var match = /[?&]year=([^&]+)/.exec(window.location.search || '');
      year = match ? decodeURIComponent(match[1]) : '';
    }
    if (!year) {
      // A page whose map is showing the latest year carries no ?year=; the
      // map's own config knows which year that is.
      var map = document.querySelector('.section-map[data-year]');
      year = map ? map.dataset.year : '';
    }
    if (year) params += '&year=' + encodeURIComponent(year);
    var county = form && form.elements.county ? form.elements.county.value : '';
    if (county) params += '&county=' + encodeURIComponent(county);
    // The chemicals-of-concern scope, from the same three places as the year.
    var concern = form && form.elements.concern ? form.elements.concern.value : '';
    if (!concern) {
      var concernMatch = /[?&]concern=([^&]+)/.exec(window.location.search || '');
      concern = concernMatch ? decodeURIComponent(concernMatch[1]) : '';
    }
    if (!concern) {
      var concernMap = document.querySelector('.section-map[data-concern]');
      concern = concernMap ? concernMap.dataset.concern : '';
    }
    if (concern) params += '&concern=' + encodeURIComponent(concern);
    return params;
  };

  EntityPicker.prototype.select = function (result) {
    if (!result || !this.hidden) return;
    this.hideResults();
    this.hidden.value = result.id || '';
    this.renderSelected(result.name);
    this.submit();
  };

  EntityPicker.prototype.clear = function () {
    if (!this.hidden) return;
    this.hideResults();
    this.hidden.value = '';
    this.renderSearch();
    this.submit();
  };

  // Submitting is what re-runs the query on the lists. On the records page
  // (autosubmit off) the field just sits there until the reader hits Apply.
  EntityPicker.prototype.submit = function () {
    if (!this.autosubmit) return;
    var form = this.el.closest('form');
    if (!form) return;
    if (typeof form.requestSubmit === 'function') {
      form.requestSubmit();
    } else {
      form.submit();
    }
  };

  // The two states of the control below the label: the chosen entity as a
  // removable tag, or the search box. The hidden input and the label are left
  // alone; everything after them is replaced.
  EntityPicker.prototype.replaceControl = function (nodes) {
    var el = this.el;
    var children = Array.prototype.slice.call(el.children);
    children.forEach(function (child) {
      if (child === el.querySelector('label.label')) return;
      if (child.tagName === 'INPUT' && child.type === 'hidden') return;
      el.removeChild(child);
    });
    nodes.forEach(function (node) {
      el.appendChild(node);
    });
    this.bind();
  };

  EntityPicker.prototype.renderSelected = function (name) {
    var control = document.createElement('div');
    control.className = 'control';

    var tag = document.createElement('span');
    tag.className = 'tag is-info is-light is-medium';
    setText(tag, name);

    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'delete is-small entity-picker-clear';
    button.setAttribute('aria-label', 'Clear');
    tag.appendChild(document.createTextNode(' '));
    tag.appendChild(button);

    control.appendChild(tag);
    this.replaceControl([control]);
  };

  EntityPicker.prototype.renderSearch = function () {
    var control = document.createElement('div');
    control.className = 'control has-icons-left';

    var input = document.createElement('input');
    input.className = 'input';
    input.type = 'search';
    input.id = 'picker-' + this.kind;
    input.placeholder = 'Type to search…';
    input.autocomplete = 'off';
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', 'picker-' + this.kind + '-results');
    control.appendChild(input);

    var icon = document.createElement('span');
    icon.className = 'icon is-small is-left';
    var glyph = document.createElement('span');
    glyph.className = 'fa-regular fa-magnifying-glass';
    icon.appendChild(glyph);
    control.appendChild(icon);

    var results = document.createElement('ul');
    results.className = 'entity-picker-results';
    results.id = 'picker-' + this.kind + '-results';
    results.setAttribute('role', 'listbox');
    results.hidden = true;

    this.replaceControl([control, results]);
    if (this.input) this.input.focus();
  };

  // Collect the `.entity-picker` containers at or under `root`. `root` may be
  // a document or an element (htmx hands us the element it just swapped in,
  // and that element can itself be a container).
  function containersUnder(root) {
    var found = [];
    if (root.matches && root.matches('.entity-picker')) found.push(root);
    var nested = root.querySelectorAll ? root.querySelectorAll('.entity-picker') : [];
    for (var i = 0; i < nested.length; i++) found.push(nested[i]);
    return found;
  }

  // Idempotent: containers already initialised carry `data-rendered`, so this
  // is safe to call repeatedly (page load plus every htmx swap).
  function init(root) {
    var containers = containersUnder(root || document);
    for (var i = 0; i < containers.length; i++) {
      var el = containers[i];
      if (el.dataset.rendered) continue;
      el.dataset.rendered = '1';
      try {
        new EntityPicker(el);
      } catch (err) {
        window.console && console.error && console.error('entity-picker: failed to initialize', err);
      }
    }
  }

  window.PesticidesEntityPicker = { init: init };

  function initDocument() {
    init(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDocument);
  } else {
    initDocument();
  }
})();
