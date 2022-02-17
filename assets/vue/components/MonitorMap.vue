<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, reactive, watch } from "vue";
import * as L from "leaflet";
import { Colors, TextColors } from "../utils";
import { Monitor } from "../models";
import type { MonitorsService } from "../services";
//import type { IMonitorVisibility } from "../types";

const monitorsService = inject<MonitorsService>("MonitorsService")!;
const markers: Record<Monitor["data"]["id"], L.Marker> = {};
const markerGroup = new L.FeatureGroup();
const monitors = reactive(monitorsService.monitors);
//const visibility: ToRefs<IMonitorVisibility> = toRefs(reactive(Monitor.visibility));
const visibility = computed(() => Monitor.visibility);
const mapIsMaximised = computed(() => ({ "is-maximised": !monitorsService.activeMonitor}));
const mapSettings = {
  // Initial location: Fresno, CA
  center: new L.LatLng( 36.746841, -119.772591 ),
  zoom: 8
};

let map: L.Map;
let interval: number = 0;

function genMapMarker(monitor: Monitor) {
  //const params = monitor.markerParams;
  const iconUrl = `/api/1.0/marker.png?${ new URLSearchParams(monitor.markerParams as Record<string, string>).toString() }`;
  const color = `#${ TextColors.get(monitor.markerParams.fill_color) || Colors.black }`;

  const label = (!monitor.data.is_active || monitor.data.latest === null)
    ? ' '
    : Math.round(parseInt(monitor.data.latest[monitor.displayField], 10)).toString();

  const icon = L.divIcon({
    html: `<div style="display: grid; grid-template-columns: 1fr" data-id="${ monitor.data.id }">
             <img style="width: 32px; height: 32px; grid-column: 1; grid-row: 1;" src="${ iconUrl }" />
             <p style="grid-column: 1; grid-row: 1; color: ${ color };">${ label }</p>
           </div>`
  })


  const marker = L.marker(monitor.data.position.coordinates as L.LatLngTuple, { icon });
  return marker;
  //return new gmaps.Marker({
  //  size: new gmaps.Size(32, 32),
  //  origin: new gmaps.Point(0, 0),
  //  anchor: new gmaps.Point(16, 16),
  //  title: monitor.name,
  //  label: { color, text },
  //  icon,
  //  position,
  //});
};

function hideMarkers() {
  //for (let id in markers) {
  //  markers[id].remove();
  //}
  markerGroup.eachLayer(marker => {
    marker.remove();
  })
}

async function loadMonitors() {
  hideMarkers();
  await monitorsService.loadMonitors();
  updateMapMarkers();
}

//function selectMonitor(monitor) {
//  const range = new DateRange();
//  $router.push({
//    name: "details",
//    params: {
//      id: monitor.id
//    },
//    query: {
//      timestamp__gte: range.gte,
//      timestamp__lte: range.lte
//    }
//  });
//  map.panTo(monitor._marker.getPosition());
//}

//function showMarkers() {
//  //for (let id in markers) {
//  //  markers[id].addTo(map);
//  //}
//  markerGroup.eachLayer(marker => {
//    marker.addTo(map);
//  });
//}

function updateMapBounds() {
  if (!monitorsService.activeMonitor) {
    map.fitBounds(markerGroup.getBounds());
  }
}

function updateMapMarkers() {
  for (let id in monitorsService.monitors) {
    const monitor = monitors[id] as Monitor;
    const marker = genMapMarker(monitor);
    markerGroup.addLayer(marker);

    marker.addEventListener('click', () => {
      monitorsService.setActiveMonitor(monitor.data.id);
      //selectMonitor(MonitorsService.activeMonitor);
    });

    if (monitor.isVisible) {
      marker.addTo(map);
    }
  }
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


watch(visibility, () => updateMapMarkerVisibility(), {
  deep: true
});

onMounted(async () => {
  map = L.map("map", mapSettings);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  interval = setInterval(async () => await loadMonitors(), 1000 * 60 * 2);

  await loadMonitors();
  updateMapBounds();
});

onBeforeUnmount(() => {
  if(interval) {
    clearInterval(interval);
    interval = 0;
  }
})

//export default {
//  name: "monitor-map",
//
//  data() {
//    return {
//      monitorService: MonitorService,
//      gmaps: null,
//      fullscreen: true,
//      interval: null,
//      map: null,
//      mapSettings,
//      markers: {},
//      visibility: Monitor.visibility
//    };
//  },
//
//  computed: {
//    activeMonitor() { return this.monitorService.activeMonitor; },
//    mapIsMaximised() {
//      return {
//        'is-maximised': !this.monitorService.activeMonitor
//      };
//    }
//  },
//
//  watch: {
//    "visibility.SJVAirPurple": function() {
//      this.updateMapMarkerVisibility();
//    },
//    "visibility.SJVAirBAM": function() {
//      this.updateMapMarkerVisibility();
//    },
//    "visibility.PurpleAir": function() {
//      this.updateMapMarkerVisibility();
//    },
//    "visibility.PurpleAirInside": function() {
//      this.updateMapMarkerVisibility();
//    },
//    "visibility.AirNow": function() {
//      this.updateMapMarkerVisibility();
//    },
//    "visibility.displayInactive": function() {
//      this.updateMapMarkerVisibility();
//    }
//  },
//  async mounted() {
//    const g = await GoogleMapsInit();
//
//    this.gmaps = g.maps;
//    this.map = new this.gmaps.Map(this.$refs.map, this.mapSettings);
//
//    await this.loadMonitors();
//    this.updateMapBounds();
//
//    // Reload the monitors every 2 minutes
//    this.interval = setInterval(async () => await this.loadMonitors(), 1000 * 60 * 2);
//  },
//
//  destroyed() {
//    if(this.interval) {
//      clearInterval(this.interval);
//      this.interval = null;
//    }
//  },
//
//  methods: {
//    genMapMarker(monitor) {
//      const params = monitor.getMarkerParams();
//      const color = `#${ TextColors.get(params.color) || Colors.black }`;
//      const icon = `/api/1.0/marker.png?${ new URLSearchParams(params).toString() }`;
//
//      const position = new this.gmaps
//        .LatLng(monitor.position.coordinates[1], monitor.position.coordinates[0]);
//
//      const text = (!monitor.is_active || monitor.latest === null)
//        ? ' '
//        : Math.round(monitor.latest[monitor.displayField]).toString();
//
//      return new this.gmaps.Marker({
//        size: new this.gmaps.Size(32, 32),
//        origin: new this.gmaps.Point(0, 0),
//        anchor: new this.gmaps.Point(16, 16),
//        title: monitor.name,
//        label: { color, text },
//        icon,
//        position,
//      });
//    },
//
//    hideMarkers() {
//      for (let id in this.monitorService.monitors) {
//        this.monitorService.monitors[id]._marker.setMap(null);
//      }
//    },
//
//    async loadMonitors() {
//      this.hideMarkers();
//      await this.monitorService.loadMonitors();
//      this.updateMapMarkers();
//    },
//
//    selectMonitor(monitor) {
//      const range = new DateRange();
//      this.$router.push({
//        name: "details",
//        params: {
//          id: monitor.id
//        },
//        query: {
//          timestamp__gte: range.gte,
//          timestamp__lte: range.lte
//        }
//      });
//      this.map.panTo(monitor._marker.getPosition());
//    },
//
//    showMarkers() {
//      for (let id in this.monitorService.monitors) {
//        this.monitorService.monitors[id]._marker.setMap(this.map);
//      }
//    },
//
//    updateMapBounds() {
//      if (!this.monitorService.activeMonitor) {
//        const bounds = new this.gmaps.LatLngBounds();
//
//        for (let id in this.monitorService.monitors) {
//          const monitor = this.monitorService.monitors[id];
//
//          if (monitor._marker.getMap()) {
//            bounds.extend(this.monitorService.monitors[id]._marker.position);
//          }
//        }
//        this.map.fitBounds(bounds);
//      }
//    },
//
//    updateMapMarkers() {
//      for (let id in this.monitorService.monitors) {
//        const monitor = this.monitorService.monitors[id];
//        const marker = this.genMapMarker(monitor);
//
//        marker.addListener('click', () => {
//          this.monitorService.setActiveMonitor(monitor.id);
//          this.selectMonitor(this.monitorService.activeMonitor);
//        });
//
//        monitor._marker = marker;
//
//        if (monitor.isVisible) {
//          marker.setMap(this.map);
//        }
//      }
//    },
//
//    updateMapMarkerVisibility() {
//      for (let id in this.monitorService.monitors) {
//        const monitor = this.monitorService.monitors[id];
//
//        if (monitor.isVisible) {
//          monitor._marker.setMap(this.map);
//
//        } else {
//          monitor._marker.setMap(null);
//        }
//      }
//    }
//  }
//}
</script>

<template>
  <div ref="map" :class="mapIsMaximised"
    id="map" class="notranslate" translate="no">
  </div>
</template>
