<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, onUpdated, watch } from "vue";
import { useRouter } from "vue-router";
import * as L from "leaflet";
import "leaflet-svg-shape-markers";

import type { Monitor } from "../models";
import type { MonitorsService } from "../services";
import type { MonitorVisibility } from "../services";
import { genMarker } from "../utils";

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

function updateMapMarkers() {
  for (let id in monitorsService.monitors) {
    const monitor = monitorsService.monitors[id];

    if (!monitor.data.latest) {
      continue;
    }

    const marker = genMarker(monitor);

    if (id in markers) {
      markerGroup.removeLayer(markers[id].remove());
      delete markers[id];
    }

    if (marker) {
      // Assign/reassign marker to record
      markers[id] = marker;

      marker.addEventListener('click', () => {
        selectMonitor(marker, monitor);
      });
      
      if (visibility.isVisible(monitor)) {
        markerGroup.addLayer(marker);
      }
    }
  }
}

async function loadMonitors() {
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

.monitor-tooltip-label {
  line-height: 1;
}

.monitor-tooltip-label p:last-of-type {
  font-size: .65rem;
}
</style>
