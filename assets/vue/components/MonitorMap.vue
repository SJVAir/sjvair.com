<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, onUpdated, watch } from "vue";
import { useRouter } from "vue-router";
import * as L from "leaflet";
import { mix, readableColor } from "color2k";
import { MonitorField } from "../models";
import "leaflet-svg-shape-markers";

import type { Monitor } from "../models";
import type { MonitorsService } from "../services";
import {IMonitorVisibility} from "../types";
//import type { IMonitorVisibility } from "../types";

const monitorsService = inject<MonitorsService>("MonitorsService")!;
const visibility = inject<IMonitorVisibility>("MonitorVisibility");
const router = useRouter();

const markers: Record<Monitor["data"]["id"], L.Marker> = {};
const markerGroup = new L.FeatureGroup();
//const visibility: ToRefs<IMonitorVisibility> = toRefs(reactive(Monitor.visibility));
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

function hideMarkers() {
  //for (let id in markers) {
  //  markers[id].remove();
  //}
  //markerGroup.eachLayer(marker => {
  //  marker.remove();
  //})
  markerGroup.remove();
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

function showMarkers() {
  //for (let id in markers) {
  //  markers[id].addTo(map);
  //}
  //markerGroup.eachLayer(marker => {
  //  marker.addTo(map);
  //});
  markerGroup.addTo(map);
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
      if (m.data.is_sjvair) {
        return "circle";
      } else {
        return "square";
      }
    default:
      console.error(`Unknown device type for monitor ${ m.data.id }`)
      return "diamond";
  }
}

function updateMapMarkers() {
  for (let id in monitorsService.monitors) {
    const monitor = monitorsService.monitors[id];

    if (!monitor.data.latest) {
      break;
    }

    const shape = getMarkerShape(monitor);
    const fillColor = getColor(+monitor.data.latest[monitor.displayField]);
    const color = readableColor(fillColor);
    // @ts-ignore: Property 'shapeMarker' does not exist on type Leaflet
    const marker = L.shapeMarker(monitor.data.position.coordinates.reverse(), {
      color,
      fillColor,
      fillOpacity: 1,
      radius: 12,
      shape
    })
    markerGroup.addLayer(marker);
    markers[monitor.data.id] = marker;

    marker.addEventListener('click', () => {
      selectMonitor(marker, monitor);
    });

    if (monitor.isVisible) {
      marker.addTo(map);
    }
  }
}

async function loadMonitors() {
  hideMarkers();
  await monitorsService.loadMonitors();
  updateMapMarkers();
}

function updateMapMarkerVisibility() {
  for (let id in markers) {
    const monitor = monitorsService.monitors[id];
    const marker = markers[id];

    if (monitor.isVisible) {
     marker.addTo(map);

    } else {
      marker.remove();
    }
  }
}


watch(() => visibility, () => updateMapMarkerVisibility(), {
  deep: true
});

onMounted(async () => {
  map = L.map("leafletMapContainer", mapSettings);
  L.tileLayer(`https://api.maptiler.com/maps/topo/{z}/{x}/{y}.png?key=${ import.meta.env.VITE_MAPTILER_KEY}`, {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);
  // Wind
  //L.tileLayer('http://{s}.tile.openweathermap.org/map/wind/{z}/{x}/{y}.png?appid={apiKey}', {
  //  maxZoom: 19,
  //  attribution: 'Map data &copy; <a href="http://openweathermap.org">OpenWeatherMap</a>',
  //  apiKey: import.meta.env.VITE_OPENWEATHERMAP_KEY,
  //  opacity: 0.5
  //} as any).addTo(map);
  // Clouds
  //L.tileLayer('http://{s}.tile.openweathermap.org/map/clouds/{z}/{x}/{y}.png?appid={apiKey}', {
  //  maxZoom: 19,
  //  attribution: 'Map data &copy; <a href="http://openweathermap.org">OpenWeatherMap</a>',
  //  apiKey: import.meta.env.VITE_OPENWEATHERMAP_KEY,
  //  opacity: 0.5
  //} as any).addTo(map);

  markerGroup.addTo(map)

  // interval = setInterval(async () => await loadMonitors(), 1000 * 60 * 2);

  await loadMonitors();
  updateMapBounds();
});

onUpdated(() => {
  map.invalidateSize();
  map.panTo(centerCoords);
});

onBeforeUnmount(() => {
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
