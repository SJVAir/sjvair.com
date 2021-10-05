<template>
  <div ref="map" :class="mapIsMaximised"
    id="map" class="notranslate" translate="no">
  </div>
</template>

<script>
import Colors from "../utils/colors";
import GoogleMapsInit from "../utils/gmaps";
import MonitorService, { DateRange } from "../services/Monitors.service";
import Monitor from "../models/monitor";

// TODO Notes: updateVisibility>How do we want to make it work?

const TextColors = new Map()
  .set(Colors.white, Colors.black)
  .set(Colors.gray, Colors.black)
  .set(Colors.black, Colors.white)
  .set(Colors.green, Colors.black)
  .set(Colors.yellow, Colors.black)
  .set(Colors.orange, Colors.white)
  .set(Colors.red, Colors.white)
  .set(Colors.purple, Colors.white)
  .set(Colors.maroon, Colors.white);

const mapSettings = {
  // Initial location: Fresno, CA
  center: {lat: 36.746841, lng: -119.772591},
  zoom: 8,

  // Controls
  fullscreenControl: false,
  mapTypeControl: false,
  rotateControl: true,
  scaleControl: true,
  streetViewControl: false,
  zoomControl: true
};


export default {
  name: "monitor-map",

  data() {
    return {
      monitorService: MonitorService,
      gmaps: null,
      fullscreen: true,
      interval: null,
      map: null,
      mapSettings,
      markers: {},
      visibility: Monitor.visibility
    };
  },

  computed: {
    activeMonitor() { return this.monitorService.activeMonitor; },
    mapIsMaximised() {
      return {
        'is-maximised': !this.monitorService.activeMonitor
      };
    }
  },

  watch: {
    "visibility.SJVAirPurple": function() {
      this.updateMapMarkerVisibility();
    },
    "visibility.SJVAirInactive": function() {
      this.updateMapMarkerVisibility();
    },
    "visibility.SJVAirBAM": function() {
      this.updateMapMarkerVisibility();
    },
    "visibility.PurpleAir": function() {
      this.updateMapMarkerVisibility();
    },
    "visibility.PurpleAirInside": function() {
      this.updateMapMarkerVisibility();
    },
    "visibility.AirNow": function() {
      this.updateMapMarkerVisibility();
    }
  },
  async mounted() {
    const g = await GoogleMapsInit();

    this.gmaps = g.maps;
    this.map = new this.gmaps.Map(this.$refs.map, this.mapSettings);

    await this.loadMonitors();
    this.updateMapBounds();

    // Reload the monitors every 2 minutes
    this.interval = setInterval(async () => await this.loadMonitors(), 1000 * 60 * 2);
  },

  destroyed() {
    if(this.interval) {
      clearInterval(this.interval);
      this.interval = null;
    }
  },

  methods: {
    genMapMarker(monitor) {
      const params = monitor.getMarkerParams();
      const color = `#${ TextColors.get(params.color) || Colors.black }`;
      const icon = `/api/1.0/marker.png?${ new URLSearchParams(params).toString() }`;

      const position = new this.gmaps
        .LatLng(monitor.position.coordinates[1], monitor.position.coordinates[0]);

      const text = (monitor.latest === null)
        ? ' '
        : Math.round(monitor.latest[monitor.displayField]).toString();

      return new this.gmaps.Marker({
        size: new this.gmaps.Size(32, 32),
        origin: new this.gmaps.Point(0, 0),
        anchor: new this.gmaps.Point(16, 16),
        title: monitor.name,
        label: { color, text },
        icon,
        position,
      });
    },

    hideMarkers() {
      for (let id in this.monitorService.monitors) {
        this.monitorService.monitors[id]._marker.setMap(null);
      }
    },

    async loadMonitors() {
      this.hideMarkers();
      await this.monitorService.loadMonitors();
      this.updateMapMarkers();
    },

    selectMonitor(monitor) {
      const range = new DateRange();
      this.$router.push({
        name: "details",
        params: {
          id: monitor.id
        },
        query: {
          timestamp__gte: range.gte,
          timestamp__lte: range.lte
        }
      });
      this.map.panTo(monitor._marker.getPosition());
    },

    showMarkers() {
      for (let id in this.monitorService.monitors) {
        this.monitorService.monitors[id]._marker.setMap(this.map);
      }
    },

    updateMapBounds() {
      if (!this.monitorService.activeMonitor) {
        const bounds = new this.gmaps.LatLngBounds();

        for (let id in this.monitorService.monitors) {
          const monitor = this.monitorService.monitors[id];

          if (monitor._marker.getMap()) {
            bounds.extend(this.monitorService.monitors[id]._marker.position);
          }
        }
        this.map.fitBounds(bounds);
      }
    },

    updateMapMarkers() {
      for (let id in this.monitorService.monitors) {
        const monitor = this.monitorService.monitors[id];
        const marker = this.genMapMarker(monitor);

        marker.addListener('click', () => {
          this.monitorService.setActiveMonitor(monitor.id);
          this.selectMonitor(this.monitorService.activeMonitor);
        });

        monitor._marker = marker;

        if (monitor.isVisible) {
          marker.setMap(this.map);
        }
      }
    },

    updateMapMarkerVisibility() {
      for (let id in this.monitorService.monitors) {
        const monitor = this.monitorService.monitors[id];

        if (monitor.isVisible) {
          monitor._marker.setMap(this.map);

        } else {
          monitor._marker.setMap(null);
        }
      }
    }
  }
}
</script>
