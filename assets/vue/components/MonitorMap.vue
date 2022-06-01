<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, onUpdated, watch } from "vue";
import { useRouter } from "vue-router";
import * as L from "leaflet";
import "leaflet-svg-shape-markers";
import "leaflet/dist/leaflet.css";
import { darken, readableColor, toHex } from "color2k";
import { Point } from "leaflet";
import { Colors, dateUtil, valueToColor } from "../modules";

import { Display_Field, MonitorField } from "../models";

import type { Marker } from "leaflet";
import type { Monitor } from "../models";
import type { MonitorsService } from "../services";
import type { MonitorVisibility } from "../services";

const monitorsService = inject<MonitorsService>("MonitorsService")!;
const visibility = inject<MonitorVisibility>("MonitorVisibility")!;
const router = useRouter();

const markers: Record<Monitor["data"]["id"], L.Marker> = {};
const markersGroup = new L.FeatureGroup();
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

const tempLevels = [
  { min: -Infinity, color: Colors.blue },
  { min: 65, color: Colors.green },
  { min: 78, color: Colors.yellow },
  { min: 95, color: Colors.red }
];

function getMarkerPaneName(m: Monitor): string | undefined {
  switch(m.data.device) {
    case "AirNow": 
      return "airNow";
    case "BAM1022":
      return "sjvAirBam";
    case "PurpleAir":
      return (m.data.is_sjvair) ? "sjvAirPurpleAir" : "purpleAir";
    default:
      return "marker";
  }
}

function genMarker(m: Monitor): Marker | undefined {
  const displayField = m.monitorFields[Display_Field] || new MonitorField(Display_Field, "PM 2.5", "60", m.data);
  const markerOptions = {
    offset: new Point(10, 0),
    opacity: 1
  };
  // @ts-ignore: Property 'shapeMarker' does not exist on type Leaflet
  const marker = L.shapeMarker(m.data.position.coordinates.reverse(), {
    color: m.markerParams.border_color,
    weight: m.markerParams.border_size,
    fillColor: m.markerParams.fill_color,
    fillOpacity: 1,
    radius: m.markerParams.size,
    shape: m.markerParams.shape,
    pane: getMarkerPaneName(m)
  });


  const tempColor = valueToColor(+m.data.latest.fahrenheit, tempLevels);
  const temperatureTemplate = (m.data.latest.fahrenheit)
  ? `
      <div class="monitor-tooltip-data-box monitor-tooltip-temp" style="background-color: ${ tempColor }; color: ${ readableColor(tempColor) }; border: solid ${ toHex(darken(tempColor, .1))}">
        <p class="is-size-6 has-text-centered">Current Temp</p>
        <p class="is-size-2 has-text-centered is-flex-grow-1">
          ${ +m.data.latest.fahrenheit }&#176;F
        </p>
      </div>
    `
  : "";
  marker.bindTooltip(`
    <div class="monitor-tooltip-container is-flex is-flex-direction-row is-flex-wrap-nowrap">
      <div class="monitor-tooltip-data-box monitor-tooltip-pmvalue"
        style="background-color: ${ m.markerParams.value_color }; color: ${ readableColor(m.markerParams.value_color) }; border: solid ${ toHex(darken(m.markerParams.value_color, .1)) }">
        <p class="is-size-6">PM 2.5</p>
        <p class="is-size-2 has-text-centered is-flex-grow-1">
          ${ Math.round(+m.data.latest[Display_Field]) }
        </p>
        <p>(${ parseInt(displayField.updateDuration, 10) } minute average)</p>
      </div>
      ${ temperatureTemplate }
      <div class="monitor-tooltip-info is-flex is-flex-direction-column">
        <p class="monitor-tooltip-date">${ dateUtil.$prettyPrint(m.data.latest.timestamp) }</p>
        <p class="is-size-5 has-text-weight-bold is-underlined">${ m.data.name }</p>
        <p class="is-size-6">Last updated:</p>
        <p class="is-size-6">About ${ m.lastUpdated }</p>
      </div>
  `, markerOptions);

  return marker;
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
    map.fitBounds(markersGroup.getBounds());
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
      markersGroup.removeLayer(markers[id].remove());
      delete markers[id];
    }

    if (marker) {
      // Assign/reassign marker to record
      markers[id] = marker;

      marker.addEventListener('click', () => {
        selectMonitor(marker, monitor);
      });
      
      if (visibility.isVisible(monitor)) {
        markersGroup.addLayer(marker);
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
      markersGroup.addLayer(markers[id]);

    } else {
      markersGroup.removeLayer(markers[id]);
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
  L.tileLayer(`https://api.maptiler.com/maps/streets/256/{z}/{x}/{y}.png?key=NvYyjimTkUQBEjVebxLV`, {
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

  //const pane = map.getPane("markerPane");
  markersGroup.addTo(map);

  map.createPane("purpleAir").style.zIndex = "601";
  map.createPane("airNow").style.zIndex = "602";
  map.createPane("sjvAirPurpleAir").style.zIndex = "603";
  map.createPane("sjvAirBam").style.zIndex = "604";

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
    <div class="map-legend-container card is-flex is-flex-direction-column">
      <p class="has-text-centered has-font-weight-semibold">PM Value Colors</p>
      <div class="map-legend">&nbsp;</div>
      <div class="map-legend-lines is-flex">
        <div></div>
        <div></div>
        <div></div>
        <div></div>
        <div></div>
        <div></div>
      </div>
      <div class="map-legend-labels is-flex is-size-7-mobile">
        <span>0</span>
        <span>12</span>
        <span>35</span>
        <span>55</span>
        <span>150</span>
        <span>250</span>
      </div>
    </div>
  </div>
</template>

<style>

</style>

<style>
.map-container {
  height: calc((100vh - var(--navbar-height)) / 2);
}

.map-container.is-maximised {
  height: calc(100vh - var(--navbar-height));
}

.map-el {
  contain: paint;
  height: 100%;
  width: 100%;
  z-index: 0;
}

.leaflet-tooltip-right {
    margin-left: -.4em;
}

.leaflet-tooltip-left {
    margin-left: .4em;
}

.monitor-tooltip-container {
  margin: -1em;
  padding: 1.5em;
}

.monitor-tooltip-container .tag {
  font-weight: 500;
}

.monitor-tooltip-label {
  line-height: 1;
}

.monitor-tooltip-data-box {
  padding: .2em;
}

.monitor-tooltip-pmvalue {
  margin-right: 1em;
}

.monitor-tooltip-info {
  margin-left: 1em;
}

.map-legend-container {
  width: calc(25vw + 1em);
  position: absolute;
  margin: -7rem 0 -100% 0.65rem;
  padding: .5em 1em;
}

.map-legend {
  background: linear-gradient(90deg, #00e400 0%, #ffff00 20%, #ff7e00 40%, #ff0000 60%, #8f3f97 80%, #7e0023 100%);
  display: inline-block;
  width: 100%;
  height: 1.5em;
}

.map-legend-lines *, .map-legend-labels * {
  width: calc(100% / 5);
  flex-shrink: 0;
}

.map-legend-lines * {
  height: .5em;
  border-left: 1px solid black;
}

.map-legend-labels {
  text-align: center;
  position: relative;
  right: 2.4vw;
  margin-top: .25em;
}
</style>
