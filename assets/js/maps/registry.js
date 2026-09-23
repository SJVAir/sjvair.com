/*
 * The map registry: map modules register a spec, and init(root) (on page
 * load, and from explorer.js on every htmx:load) finds their containers and
 * runs one of two lifecycles:
 *
 *   'adopt'  one live map per page (per module). A swap to a page with a
 *            container of the same module adopts the live map in place
 *            (Shell.adopt); a swap to a page without one releases it.
 *   'figure' any number per page, each built once scrolled into view
 *            (a little before), released once its container has left the
 *            document; never adopted.
 *
 * Containers are claimed with `data-rendered`, so init is idempotent. Without
 * WebGL a container gets a note instead of a map. An htmx history restore
 * re-runs this file; a second copy defers to the first.
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M) return;
  if (M.register) {
    M.init(document);
    return;
  }

  // How far below the fold a figure is built ahead of being scrolled to.
  var BUILD_AHEAD = '200px';
  var log = M.logger('maps');

  var specs = {};    // name -> spec
  var live = {};     // name -> Shell ('adopt')
  var figures = {};  // name -> [Shell] ('figure')
  var pending = {};  // name -> [el] waiting to be scrolled to ('figure')
  var observer = null;

  function containersUnder(root, selector) {
    var found = [];
    if (root.matches && root.matches(selector)) found.push(root);
    var nested = root.querySelectorAll ? root.querySelectorAll(selector) : [];
    for (var i = 0; i < nested.length; i++) found.push(nested[i]);
    // An htmx history restore re-parses the page with scripting off, turning
    // the markup inside <noscript> (static fallbacks) into hidden elements;
    // they're not ours to draw.
    return found.filter(function (el) { return !(el.closest && el.closest('noscript')); });
  }

  function build(name, el) {
    try {
      return new M.Shell(el, name, specs[name]);
    } catch (err) {
      log('failed to initialize ' + name, err);
      return null;
    }
  }

  // -- 'adopt' --

  function initAdopt(name, root) {
    var spec = specs[name];
    var shell = live[name];
    // Judged against the whole document, not `root`: htmx fires htmx:load per
    // swapped element, and the one for an out-of-band fragment must not take
    // the map from the page that has it.
    if (shell && !document.body.contains(shell.el) && !containersUnder(document, spec.selector).length) {
      shell.destroy();
      live[name] = shell = null;
    }
    containersUnder(root, spec.selector).forEach(function (el) {
      if (el.dataset.rendered) return;
      if (!M.webglAvailable()) {
        el.dataset.rendered = '1';
        M.showUnavailable(el);
        return;
      }
      if (shell && !document.body.contains(shell.el)) {
        try {
          shell.adopt(el);
        } catch (err) {
          log('failed to adopt ' + name, err);
        }
        return;
      }
      el.dataset.rendered = '1';
      shell = live[name] = build(name, el);
    });
  }

  // -- 'figure' --

  function unschedule(name, el) {
    var list = pending[name] || [];
    var at = list.indexOf(el);
    if (at !== -1) list.splice(at, 1);
    if (observer) observer.unobserve(el);
  }

  function buildFigure(name, el) {
    var shell = build(name, el);
    if (shell) figures[name].push(shell);
  }

  function schedule(name, el) {
    if (!('IntersectionObserver' in window)) {
      buildFigure(name, el);
      return;
    }
    if (!observer) {
      observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          var target = entry.target;
          var figureName = target.getAttribute('data-map-module');
          unschedule(figureName, target);
          buildFigure(figureName, target);
        });
      }, { rootMargin: BUILD_AHEAD });
    }
    el.setAttribute('data-map-module', name);
    pending[name].push(el);
    observer.observe(el);
  }

  function sweep(name) {
    figures[name] = figures[name].filter(function (shell) {
      if (document.body.contains(shell.el)) return true;
      shell.destroy();
      return false;
    });
    var list = pending[name];
    for (var i = list.length - 1; i >= 0; i--) {
      if (!document.body.contains(list[i])) unschedule(name, list[i]);
    }
  }

  function initFigures(name, root) {
    sweep(name);
    containersUnder(root, specs[name].selector).forEach(function (el) {
      if (el.dataset.rendered) return;
      el.dataset.rendered = '1';
      if (!M.webglAvailable()) {
        M.showUnavailable(el);
        return;
      }
      schedule(name, el);
    });
  }

  // -- public --

  function initName(name, root) {
    if (specs[name].lifecycle === 'figure') {
      initFigures(name, root);
    } else {
      initAdopt(name, root);
    }
  }

  function init(root) {
    if (typeof maptilersdk === 'undefined') return;
    // One module's throw (a figure's destroy during sweep, say) must not
    // stop the others' init, and must not escape into the htmx:load
    // handler that called us -- it would skip whatever runs after us there.
    Object.keys(specs).forEach(function (name) {
      try {
        initName(name, root || document);
      } catch (err) {
        log('failed to init ' + name, err);
      }
    });
  }

  function register(name, spec) {
    // A second copy of a module (an htmx history restore) keeps the first spec.
    if (specs[name]) {
      init(document);
      return;
    }
    specs[name] = spec;
    figures[name] = [];
    pending[name] = [];
    if (document.readyState !== 'loading' && typeof maptilersdk !== 'undefined') initName(name, document);
  }

  function instances(name) {
    if (!specs[name]) return [];
    if (specs[name].lifecycle === 'figure') return figures[name].map(function (shell) { return shell.module; });
    return live[name] ? [live[name].module] : [];
  }

  M.register = register;
  M.init = init;
  M.instances = instances;
  M.pending = function (name) { return (pending[name] || []).slice(); };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(document); });
  }
})();
