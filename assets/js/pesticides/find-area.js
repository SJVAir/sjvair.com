/*
 * "Find your area" block on the Pesticides Explorer landing page.
 *
 * Turns each `.find-area` container into a MapTiler-backed address/city/ZIP
 * search plus a "Use my location" button. All geocoding happens directly in
 * the browser against MapTiler -- the server never sees or stores the
 * query text or the resolved coordinates. The only thing that carries the
 * location forward is the near-me URL this script builds and navigates to.
 *
 * Plain ES2017, no framework/bundler, single global side effect: none (IIFE).
 */
(function () {
  'use strict';

  var DEBOUNCE_MS = 300;
  var MIN_QUERY_LENGTH = 3;
  var GEOCODE_BBOX = '-121.9,34.8,-117.5,38.4';

  function escapeText(el, text) {
    el.textContent = text == null ? '' : String(text);
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

    this.features = [];
    this.activeIndex = -1;
    this.debounceTimer = null;

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
    this.features = [];
    this.activeIndex = -1;
    if (this.resultsEl) {
      this.resultsEl.hidden = true;
      this.resultsEl.innerHTML = '';
    }
    if (this.input) {
      this.input.removeAttribute('aria-activedescendant');
    }
  };

  FindArea.prototype.onInput = function () {
    var self = this;
    var query = this.input.value.trim();

    window.clearTimeout(this.debounceTimer);

    if (query.length < MIN_QUERY_LENGTH) {
      this.hideResults();
      this.setStatus('');
      return;
    }

    this.debounceTimer = window.setTimeout(function () {
      self.search(query);
    }, DEBOUNCE_MS);
  };

  FindArea.prototype.onKeyDown = function (event) {
    if (event.key === 'Escape') {
      this.hideResults();
      this.setStatus('');
      return;
    }

    if (!this.features.length) {
      return;
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.setActiveIndex(this.activeIndex + 1 >= this.features.length ? 0 : this.activeIndex + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.setActiveIndex(this.activeIndex <= 0 ? this.features.length - 1 : this.activeIndex - 1);
    } else if (event.key === 'Enter') {
      if (this.activeIndex >= 0 && this.activeIndex < this.features.length) {
        event.preventDefault();
        this.selectFeature(this.features[this.activeIndex]);
      }
    }
  };

  FindArea.prototype.setActiveIndex = function (index) {
    this.activeIndex = index;
    var items = this.resultsEl ? this.resultsEl.querySelectorAll('li') : [];
    for (var i = 0; i < items.length; i++) {
      var active = i === index;
      items[i].setAttribute('aria-selected', active ? 'true' : 'false');
    }
    if (index >= 0 && items[index] && this.input) {
      this.input.setAttribute('aria-activedescendant', items[index].id);
    } else if (this.input) {
      this.input.removeAttribute('aria-activedescendant');
    }
  };

  FindArea.prototype.search = function (query) {
    var self = this;

    if (!this.key) {
      this.setStatus('Search is unavailable.');
      return;
    }

    this.setStatus('Searching…');

    var url = 'https://api.maptiler.com/geocoding/' + encodeURIComponent(query) + '.json'
      + '?key=' + encodeURIComponent(this.key)
      + '&country=us&bbox=' + GEOCODE_BBOX + '&limit=5&language=en';

    fetch(url)
      .then(function (response) {
        if (!response.ok) {
          throw new Error('geocoding request failed');
        }
        return response.json();
      })
      .then(function (data) {
        self.renderResults((data && data.features) || []);
      })
      .catch(function () {
        self.hideResults();
        self.setStatus("Couldn't search right now. Try again in a moment.");
      });
  };

  FindArea.prototype.renderResults = function (features) {
    this.features = features;
    this.activeIndex = -1;

    if (!this.resultsEl) {
      return;
    }

    this.resultsEl.innerHTML = '';

    if (!features.length) {
      this.resultsEl.hidden = true;
      this.setStatus('No matches found.');
      return;
    }

    var self = this;
    features.forEach(function (feature, index) {
      var li = document.createElement('li');
      li.id = 'find-area-result-' + index;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', 'false');
      escapeText(li, feature.place_name || feature.text || '');
      li.addEventListener('mousedown', function (event) {
        // mousedown (not click) fires before the input's blur handler hides the list.
        event.preventDefault();
        self.selectFeature(feature);
      });
      self.resultsEl.appendChild(li);
    });

    this.resultsEl.hidden = false;
    this.setStatus('');
  };

  FindArea.prototype.selectFeature = function (feature) {
    if (!feature || !feature.center || feature.center.length < 2) {
      return;
    }
    var lng = feature.center[0];
    var lat = feature.center[1];
    var label = 'near ' + (feature.text || feature.place_name || 'here');
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
        var label = feature ? 'near ' + (feature.text || feature.place_name || 'you') : 'near you';
        self.goToLocation(lat, lng, label);
      })
      .catch(function () {
        self.goToLocation(lat, lng, 'near you');
      });
  };

  function init() {
    var containers = document.querySelectorAll('.find-area');
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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
