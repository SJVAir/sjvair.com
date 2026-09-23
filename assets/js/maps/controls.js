/*
 * The map controls, stacked top-left in a fixed order: the SDK's zoom
 * buttons (no compass: the maps don't rotate), then locate, then home. Locate
 * and home are BarControls: one SDK control bar each, an anchor acting as a
 * button inside, in the SDK's control idiom.
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M || M.BarControl) return;

  function BarControl(className, label, icon, onClick) {
    this.className = className;
    this.label = label;
    this.icon = icon;
    this.onClick = onClick;
  }

  BarControl.prototype.onAdd = function () {
    var self = this;
    var container = document.createElement('div');
    container.className = 'maplibregl-ctrl maplibregl-ctrl-group ' + this.className;
    var link = document.createElement('a');
    link.href = '#';
    link.setAttribute('role', 'button');
    link.setAttribute('title', this.label);
    link.setAttribute('aria-label', this.label);
    link.innerHTML = '<span class="' + this.icon + '" aria-hidden="true"></span>';
    link.addEventListener('click', function (event) {
      event.preventDefault();
      // A click on a control isn't a click on the map (which turns wheel-zoom on).
      event.stopPropagation();
      self.onClick();
    });
    container.appendChild(link);
    this.container = container;
    return container;
  };

  BarControl.prototype.onRemove = function () {
    if (this.container && this.container.parentNode) this.container.parentNode.removeChild(this.container);
    this.container = null;
  };

  // The controls `names` asks for, always in the order zoom, locate, home.
  function addControls(shell, names) {
    names = names || [];
    if (names.indexOf('zoom') !== -1) {
      shell.map.addControl(new maptilersdk.NavigationControl({ showCompass: false }), 'top-left');
    }
    if (names.indexOf('locate') !== -1 && navigator.geolocation) {
      shell.locateControl = new BarControl('map-locate', 'Zoom to my location', 'fa-regular fa-location-crosshairs', function () {
        shell.locate();
      });
      shell.map.addControl(shell.locateControl, 'top-left');
    }
    if (names.indexOf('home') !== -1) {
      shell.map.addControl(new BarControl('map-reset', 'Zoom out to the whole map', 'fa-regular fa-house', function () {
        shell.home();
      }), 'top-left');
    }
  }

  M.BarControl = BarControl;
  M.addControls = addControls;
})();
