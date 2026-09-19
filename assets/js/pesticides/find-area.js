/*
 * "Find your area" block on the Pesticides Explorer landing page.
 *
 * One search box over two sources:
 *
 *   1. Our own place pages (counties, cities, ZIPs, places). The whole list
 *      is embedded in the page as JSON and matched here in the browser, so
 *      it answers on every keystroke with no network at all.
 *   2. Addresses, via MapTiler geocoding (debounced, aborted, >= 3 chars).
 *      This is the only thing that leaves the browser, and even then the
 *      server never sees the query text or the resolved coordinates -- the
 *      only thing carrying the location forward is the near-me URL this
 *      script builds and navigates to.
 *
 * Plain ES2017, no framework/bundler, single global side effect: none (IIFE).
 */
(function () {
  'use strict';

  var DEBOUNCE_MS = 300;
  var MIN_QUERY_LENGTH = 3;
  var GEOCODE_BBOX = '-121.9,34.8,-117.5,38.4';
  var MAX_LABEL_LENGTH = 120;
  var MAX_PLACES = 6;
  var MAX_ADDRESSES = 4;

  function escapeText(el, text) {
    el.textContent = text == null ? '' : String(text);
  }

  // Builds a "near X, Y County" label from a MapTiler feature: the feature's
  // own text plus, when present, the `text` of its `county.*` context entry.
  function labelForFeature(feature, fallback) {
    if (!feature) return fallback;
    var name = feature.text || feature.place_name;
    if (!name) return fallback;
    var county = null;
    var context = feature.context || [];
    for (var i = 0; i < context.length; i++) {
      if (context[i].id && context[i].id.indexOf('county.') === 0) {
        county = context[i];
        break;
      }
    }
    return 'near ' + name + (county && county.text ? ', ' + county.text : '');
  }

  // Prefix/word match against our own place list. ZIPs only match on a
  // prefix of the code -- "937" should find 93725, but "725" shouldn't.
  // Whole-name prefix matches rank above matches on a later word, so
  // "fresno" puts "Fresno County" ahead of "West Fresno".
  function matchPlaces(places, query) {
    var q = query.trim().toLowerCase();
    if (!q) return [];

    var starts = [];
    var words = [];

    for (var i = 0; i < places.length; i++) {
      var place = places[i];
      var name = String(place.name || '').toLowerCase();
      if (name.indexOf(q) === 0) {
        starts.push(place);
      } else if (place.type !== 'zipcode' && new RegExp('\\b' + escapeRegExp(q)).test(name)) {
        words.push(place);
      }
      if (starts.length >= MAX_PLACES) break;
    }

    return starts.concat(words).slice(0, MAX_PLACES);
  }

  function escapeRegExp(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function readPlaces() {
    var el = document.getElementById('find-area-places');
    if (!el) return [];
    try {
      var data = JSON.parse(el.textContent);
      return Array.isArray(data) ? data : [];
    } catch (err) {
      return [];
    }
  }

  function FindArea(el) {
    this.el = el;
    this.key = el.dataset.maptilerKey || '';
    this.nearUrl = el.dataset.nearUrl || '';
    this.year = el.dataset.year || '';

    this.input = el.querySelector('#find-area-query');
    this.locateButton = el.querySelector('#find-area-locate');
    this.resultsEl = el.querySelector('#find-area-results');
    this.statusEl = el.querySelector('#find-area-status');

    this.places = readPlaces();

    // `items` is the flat, keyboard-navigable list -- place items and
    // address items in the order they're rendered.
    this.items = [];
    this.placeMatches = [];
    this.addressFeatures = [];
    this.activeIndex = -1;
    this.debounceTimer = null;
    this.searchAbort = null;
    this.searchRequestId = 0;
    this.searching = false;

    this.bindEvents();
  }

  FindArea.prototype.bindEvents = function () {
    var self = this;

    if (this.input) {
      this.input.addEventListener('input', function () {
        self.onInput();
      });
      this.input.addEventListener('keydown', function (event) {
        self.onKeyDown(event);
      });
      this.input.addEventListener('blur', function () {
        // Let a click on a result register before the list disappears.
        window.setTimeout(function () {
          self.hideResults();
        }, 150);
      });
    }

    if (this.locateButton) {
      this.locateButton.addEventListener('click', function () {
        self.useMyLocation();
      });
    }
  };

  FindArea.prototype.setStatus = function (message) {
    if (this.statusEl) {
      escapeText(this.statusEl, message || '');
    }
  };

  FindArea.prototype.hideResults = function () {
    this.items = [];
    this.placeMatches = [];
    this.addressFeatures = [];
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

  FindArea.prototype.onInput = function () {
    var self = this;
    var query = this.input.value.trim();

    window.clearTimeout(this.debounceTimer);
    this.searchRequestId++; // invalidate any in-flight address search
    if (this.searchAbort) this.searchAbort.abort();
    this.addressFeatures = [];
    this.searching = false;

    if (!query) {
      this.hideResults();
      this.setStatus('');
      return;
    }

    this.placeMatches = matchPlaces(this.places, query);

    if (query.length >= MIN_QUERY_LENGTH && this.key) {
      this.searching = true;
      this.debounceTimer = window.setTimeout(function () {
        self.searchAddresses(query);
      }, DEBOUNCE_MS);
    }

    this.render();
  };

  FindArea.prototype.onKeyDown = function (event) {
    if (event.key === 'Escape') {
      this.hideResults();
      this.setStatus('');
      return;
    }

    if (!this.items.length) {
      return;
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.setActiveIndex(this.activeIndex + 1 >= this.items.length ? 0 : this.activeIndex + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.setActiveIndex(this.activeIndex <= 0 ? this.items.length - 1 : this.activeIndex - 1);
    } else if (event.key === 'Enter') {
      if (this.activeIndex >= 0 && this.activeIndex < this.items.length) {
        event.preventDefault();
        this.selectItem(this.items[this.activeIndex]);
      }
    }
  };

  FindArea.prototype.setActiveIndex = function (index) {
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

  FindArea.prototype.searchAddresses = function (query) {
    var self = this;

    var abort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    this.searchAbort = abort;
    var requestId = ++this.searchRequestId;

    var url = 'https://api.maptiler.com/geocoding/' + encodeURIComponent(query) + '.json'
      + '?key=' + encodeURIComponent(this.key)
      + '&country=us&bbox=' + GEOCODE_BBOX + '&limit=5&language=en';

    fetch(url, abort ? { signal: abort.signal } : undefined)
      .then(function (response) {
        if (!response.ok) {
          throw new Error('geocoding request failed');
        }
        return response.json();
      })
      .then(function (data) {
        if (requestId !== self.searchRequestId) return; // a newer search superseded this one
        self.searching = false;
        self.addressFeatures = ((data && data.features) || []).slice(0, MAX_ADDRESSES);
        self.render();
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (requestId !== self.searchRequestId) return;
        self.searching = false;
        self.addressFeatures = [];
        self.render("Couldn't search addresses right now. Try again in a moment.");
      });
  };

  FindArea.prototype.render = function (errorMessage) {
    this.items = [];
    this.activeIndex = -1;

    if (!this.resultsEl) {
      return;
    }

    this.resultsEl.innerHTML = '';

    if (this.placeMatches.length) {
      this.renderGroup('Places we have pages for');
      for (var i = 0; i < this.placeMatches.length; i++) {
        var place = this.placeMatches[i];
        this.renderOption({ kind: 'place', place: place }, place.name, place.type_label);
      }
    }

    if (this.addressFeatures.length) {
      this.renderGroup('Addresses');
      for (var j = 0; j < this.addressFeatures.length; j++) {
        var feature = this.addressFeatures[j];
        this.renderOption(
          { kind: 'address', feature: feature },
          feature.place_name || feature.text || '',
          null
        );
      }
    }

    if (!this.items.length) {
      this.resultsEl.hidden = true;
      if (this.input) this.input.setAttribute('aria-expanded', 'false');
      this.setStatus(errorMessage || (this.searching ? 'Searching addresses…' : 'No matches found.'));
      return;
    }

    this.resultsEl.hidden = false;
    if (this.input) this.input.setAttribute('aria-expanded', 'true');
    this.setStatus(errorMessage || (this.searching ? 'Searching addresses…' : ''));
  };

  FindArea.prototype.renderGroup = function (label) {
    var li = document.createElement('li');
    li.className = 'find-area-group';
    li.setAttribute('role', 'presentation');
    escapeText(li, label);
    this.resultsEl.appendChild(li);
  };

  FindArea.prototype.renderOption = function (item, label, meta) {
    var self = this;
    var index = this.items.length;
    this.items.push(item);

    var li = document.createElement('li');
    li.id = 'find-area-result-' + index;
    li.setAttribute('role', 'option');
    li.setAttribute('aria-selected', 'false');

    var name = document.createElement('span');
    name.className = 'find-area-result-name';
    escapeText(name, label);
    li.appendChild(name);

    if (meta) {
      var metaEl = document.createElement('span');
      metaEl.className = 'find-area-result-type';
      escapeText(metaEl, meta);
      li.appendChild(metaEl);
    }

    li.addEventListener('mousedown', function (event) {
      // mousedown (not click) fires before the input's blur handler hides the list.
      event.preventDefault();
      self.selectItem(item);
    });

    this.resultsEl.appendChild(li);
  };

  FindArea.prototype.selectItem = function (item) {
    if (!item) return;
    if (item.kind === 'place') {
      this.selectPlace(item.place);
    } else {
      this.selectFeature(item.feature);
    }
  };

  FindArea.prototype.selectPlace = function (place) {
    if (!place || !place.url) return;
    var url = place.url;
    if (this.year) {
      url += '?year=' + encodeURIComponent(this.year);
    }
    this.hideResults();
    window.location.assign(url);
  };

  FindArea.prototype.selectFeature = function (feature) {
    if (!feature || !feature.center || feature.center.length < 2) {
      return;
    }
    var lng = feature.center[0];
    var lat = feature.center[1];
    var label = labelForFeature(feature, 'near here').slice(0, MAX_LABEL_LENGTH);
    this.hideResults();
    if (this.input) {
      this.input.value = feature.place_name || feature.text || '';
    }
    this.goToLocation(lat, lng, label);
  };

  FindArea.prototype.goToLocation = function (lat, lng, label) {
    if (!this.nearUrl) {
      return;
    }
    var url = this.nearUrl + '?lat=' + lat.toFixed(4) + '&lng=' + lng.toFixed(4)
      + '&radius=1&label=' + encodeURIComponent(label);
    if (this.year) {
      url += '&year=' + encodeURIComponent(this.year);
    }
    window.location.assign(url);
  };

  FindArea.prototype.useMyLocation = function () {
    var self = this;

    if (!navigator.geolocation) {
      this.setStatus('Your browser does not support location lookup.');
      return;
    }

    this.setStatus('Finding your location…');

    navigator.geolocation.getCurrentPosition(
      function (position) {
        var lat = position.coords.latitude;
        var lng = position.coords.longitude;
        self.reverseGeocode(lat, lng);
      },
      function () {
        self.setStatus("Couldn't get your location. Check your browser's location permission and try again.");
      }
    );
  };

  FindArea.prototype.reverseGeocode = function (lat, lng) {
    var self = this;

    if (!this.key) {
      this.goToLocation(lat, lng, 'near you');
      return;
    }

    var url = 'https://api.maptiler.com/geocoding/' + lng + ',' + lat + '.json'
      + '?key=' + encodeURIComponent(this.key) + '&limit=1';

    fetch(url)
      .then(function (response) {
        if (!response.ok) {
          throw new Error('reverse geocoding request failed');
        }
        return response.json();
      })
      .then(function (data) {
        var feature = data && data.features && data.features[0];
        var label = (feature ? labelForFeature(feature, 'near you') : 'near you').slice(0, MAX_LABEL_LENGTH);
        self.goToLocation(lat, lng, label);
      })
      .catch(function () {
        self.goToLocation(lat, lng, 'near you');
      });
  };

  // Collect the `.find-area` containers at or under `root`. `root` may be a
  // document or an element (htmx hands us the element it just swapped in, and
  // that element can itself be a container).
  function containersUnder(root) {
    var found = [];
    if (root.matches && root.matches('.find-area')) found.push(root);
    var nested = root.querySelectorAll ? root.querySelectorAll('.find-area') : [];
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
        new FindArea(el);
      } catch (err) {
        window.console && console.error && console.error('find-area: failed to initialize', err);
      }
    }
  }

  window.PesticidesFindArea = { init: init };

  function initDocument() {
    init(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDocument);
  } else {
    initDocument();
  }
})();
