<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, onUpdated, watch } from "vue";
import { useRouter } from "vue-router";
import * as L from "leaflet";
import { mix, readableColor } from "color2k";
import { MonitorField } from "../models";
import "leaflet-svg-shape-markers";

import type { Monitor } from "../models";
import type { MonitorsService } from "../services";
import type { MonitorVisibility } from "../services";
import {dateUtil} from "../utils";

const monitorsService = inject<MonitorsService>("MonitorsService")!;
const visibility = inject<MonitorVisibility>("MonitorVisibility")!;
const router = useRouter();

const markers: Record<Monitor["data"]["id"], L.Marker> = {};
const markerGroup = new L.FeatureGroup();
const mapIsMaximised = computed(() => {
  return { "is-maximised": !monitorsService.activeMonitor};
});
const mapSettings = {
  // Initial location: Fresno, CA
  center: new L.LatLng( 36.746841, -119.772591 ),
  zoom: 8
};

let map: L.Map;
let centerCoords: L.LatLng = mapSettings.center;
let interval: number = 0;

function getColor(value: number) {
  const lastLvl = MonitorField.levels[MonitorField.levels.length - 1];

  if (value >= lastLvl.min) {
    return `#${lastLvl.color}`;

  } else if (value <= 0) {
    return `#${MonitorField.levels[0].color}`;

  } else {
    for (let i = 0; i <= MonitorField.levels.length - 1; i++) {
      if (MonitorField.levels[i].min > value) {
        // Level for current value
        const min = MonitorField.levels[i-1];
        // Level threshold for current value
        const max = MonitorField.levels[i]
        // Difference between max and min values => total steps in level
        const lvlDiff = min.min === -Infinity ? max.min : max.min - min.min;
        // Difference between threshold and current values => steps remaining for current level
        const valDiff = max.min - value;
        // Difference between total steps and steps remaining
        const divisable = lvlDiff - valDiff;
        // Percent of steps used in level
        const diff = divisable / lvlDiff;

        // Color magic
        return mix(`#${min.color}`, `#${max.color}`, diff);
      }
    }

    // Gentle way to signify an error
    return "#FFFFFF";
  }
}

function selectMonitor(marker: L.Marker, monitor: Monitor) {
  router.push({
    name: "details",
    params: {
      id: monitor.data.id
    }
  });

  centerCoords = marker.getLatLng();
}

function updateMapBounds() {
  if (!monitorsService.activeMonitor) {
    map.fitBounds(markerGroup.getBounds());
  }
}

function getMarkerShape(m: Monitor) {
  switch(m.data.device) {
    case "AirNow": 
      return "triangle";
    case "BAM1022":
      return "triangle";
    case "PurpleAir":
      return (m.data.is_sjvair) ? "circle" : "square";
    default:
      console.error(`Unknown device type for monitor ${ m.data.id }`);
      return "diamond";
  }
}

function updateMapMarkers() {
  for (let id in monitorsService.monitors) {
    const monitor = monitorsService.monitors[id];

    // No marker needed if there's no latest data
    if (!monitor.data.latest) {
      break;
    }

    const shape = getMarkerShape(monitor);
    const fillColor = getColor(+monitor.data.latest[monitor.displayField]);
    const textColor = readableColor(fillColor);
    // @ts-ignore: Property 'shapeMarker' does not exist on type Leaflet
    const marker = L.shapeMarker(monitor.data.position.coordinates.reverse(), {
      color: "#000000", // background color
      fillColor,
      fillOpacity: 1,
      radius: 12,
      shape
    })

    // Assign/reassign marker to record
    markers[monitor.data.id] = marker;

    marker.bindTooltip(`
      <div class="monitor-tooltip-container" style="background-color: ${ fillColor }; color: ${ textColor }">
        <p class="monitor-tooltip-date">${ dateUtil.$prettyPrint(monitor.data.latest.timestamp) }</p>
        <p class="monitor-tooltip-name">${ monitor.data.name }</p>
        <ul class="monior-tooltip-details is-inline">
          <li>
            <span class="tag is-dark">
              <span class="icon">
                <span class="fal fa-router has-text-white"></span>
              </span>
              <span>${ monitor.data.device }</span>
            </span>
          </li>
          <li>
            <span class="tag is-dark">
              <span class="icon">
                <span class="fal fa-map-marker-alt has-text-white"></span>
              </span>
              <span>${ monitor.data.county }</span>
            </span>
          </li>
          <li>
            <span class="tag is-dark">
              <span class="icon">
                <span class="fal fa-location has-text-white"></span>
              </span>
              <span>${ monitor.data.location[0].toUpperCase() + monitor.data.location.slice(1).toLowerCase() }</span>
            </span>
          </li>
        </ul>
        <p class="mt-2 is-size-7">
          PM2.5 15 minute average:
          <span class="is-block is-size-3 has-text-centered">${ Math.round(+monitor.data.latest[monitor.displayField]) }</span>
        </p>
      </div
    `, { offset: L.point(10, 0)});

    marker.addEventListener('click', () => {
      console.log(monitor)
      selectMonitor(marker, monitor);
    });

    
    if (visibility.isVisible(monitor)) {
      markerGroup.addLayer(marker);
    }
  }
}

async function loadMonitors() {
  //hideMarkers();
  await monitorsService.loadMonitors();
  updateMapMarkers();
}

function updateMapMarkerVisibility() {
  for (let id in markers) {
    const monitor = monitorsService.monitors[id];

    if (visibility.isVisible(monitor)) {
      markerGroup.addLayer(markers[id]);

    } else {
      markerGroup.removeLayer(markers[id]);
    }
  }
}


watch(
  () => visibility,
  () => updateMapMarkerVisibility(),
  { deep: true }
);

onMounted(async () => {
  map = L.map("leafletMapContainer", mapSettings);
  L.tileLayer(`https://api.maptiler.com/maps/topo/{z}/{x}/{y}.png?key={apiKey}`, {
    maxZoom: 19,
    apiKey: import.meta.env.VITE_MAPTILER_KEY,
    attribution: 'Map tiles &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  } as L.TileLayerOptions).addTo(map);
  // Wind
  //L.tileLayer('http://{s}.tile.openweathermap.org/map/wind/{z}/{x}/{y}.png?appid={apiKey}', {
  //  maxZoom: 19,
  //  attribution: 'Map data &copy; <a href="http://openweathermap.org">OpenWeatherMap</a>',
  //  apiKey: import.meta.env.VITE_OPENWEATHERMAP_KEY,
  //  opacity: 0.3
  //} as any).addTo(map);
  // Clouds
  //L.tileLayer('http://{s}.tile.openweathermap.org/map/clouds/{z}/{x}/{y}.png?appid={apiKey}', {
  //  maxZoom: 19,
  //  attribution: 'Map data &copy; <a href="http://openweathermap.org">OpenWeatherMap</a>',
  //  apiKey: import.meta.env.VITE_OPENWEATHERMAP_KEY,
  //  opacity: 0.5
  //} as any).addTo(map);

  markerGroup.addTo(map)

  interval = setInterval(async () => await loadMonitors(), 1000 * 60 * 2);

  await loadMonitors();
  updateMapBounds();
});

onUpdated(() => {
  // Tell Leaflet to re-evaluate the map container's dimensions
  map.invalidateSize();

  // If there's an active monitor, center it and zoom in
  if (monitorsService.activeMonitor) {
    // Don't adjust the zoom if we're already zoomed in greater than 10
    const zoom = Math.max(map.getZoom(), 10);
    map.setView(centerCoords, zoom, { animate: true });
  }
});

onBeforeUnmount(() => {
  // Ensure the monitor update interval is cleared
  if(interval) {
    clearInterval(interval);
    interval = 0;
  }
})
</script>

<template>
  <div :class="mapIsMaximised" class="notranslate map-container" translate="no">
    <div id="leafletMapContainer" class="map-el"></div>
  </div>
</template>

<style>
.leaflet-tooltip {
  font-weight: 600;
}

.leaflet-tooltip-right:before {
    margin-left: -1.5em;
    border-right-color: #000;
}

.leaflet-tooltip-left:before {
    margin-right: -1.5em;
    border-left-color: #000;
}

.monitor-tooltip-container {
  border: .3em solid #000;
  border-radius: 5px;
  margin: -1em;
  padding: 1em;
}

.monitor-tooltip-container .tag {
  font-weight: 500;
}

.monitor-tooltip-name {
  font-size: 1.5em;
  text-decoration: underline;
}

.monitor-tooltip-value {
  font-size: 2em;
  font-weight: 800;
}
</style>
