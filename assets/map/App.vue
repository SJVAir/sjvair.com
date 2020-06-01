<template>
  <div class="interface">
    <div class="viewport">
      <div class="select field-selector">
        <select id="id_data-selector" name="field-selector" v-on:change="updateField" v-model="currentField">
          <option v-for="(label, key) in fields" :value="key">{{ label }}</option>
        </select>
      </div>
      <div id="map" :class="mapIsMaximised"></div>
    </div>
    <monitor-detail v-if="activeMonitor" :monitor="activeMonitor" :field="currentField" />
  </div>
</template>

<script>
import _ from 'lodash';
import moment from 'moment';

import MonitorDetail from './components/MonitorDetail.vue'
import GoogleMapsInit from './utils/gmaps';


export default {
  name: 'app',

  components: {
    MonitorDetail
  },

  data() {
    return {
      map: null,
      monitors: {},
      activeMonitor: null,
      interval: null,
      currentField: 'pm25_env',
      fields: {
        fahrenheit: "Temp. (°F)",
        celcius: "Temp. (°C)",
        humidity: "Humidity",
        pressure: "Pressure",
        epa_pm25_aqi: "US EPA PM2.5 AQI",
        epa_pm100_aqi: "US EPA PM10 AQI",
        pm10_env: "PM 1",
        pm25_env: "PM 2.5",
        pm100_env: "PM 10",
        particles_03um: "Particles > 0.3µm / 0.1L air",
        particles_05um: "Particles > 0.5µm / 0.1L air",
        particles_100um: "Particles > 1.0µm / 0.1L air",
        particles_10um: "Particles > 2.5µm / 0.1L air",
        particles_25um: "Particles > 5.0µm / 0.1L air",
        particles_50um: "Particles > 10.0µm / 0.1L air"
      },
      getLatestValue: {
        fahrenheit: (monitor) => Math.round(monitor.latest.fahrenheit) + "°",
        celcius: (monitor) => Math.round(monitor.latest.celcius) + "°",
        humidity: (monitor) => Math.round(monitor.latest.humidity) + "%",
        pressure: (monitor) => Math.round(monitor.latest.pressure) + " hPa",
        pm10_env: (monitor) => monitor.latest.pm10_env,
        pm25_env: (monitor) => monitor.latest.pm25_env,
        pm100_env: (monitor) => monitor.latest.pm100_env,
        particles_3um: (monitor) => monitor.latest.particles_03um,
        particles_5um: (monitor) => monitor.latest.particles_05um,
        particles_10um: (monitor) => monitor.latest.particles_10um,
        particles_25um: (monitor) => monitor.latest.particles_25um,
        particles_50um: (monitor) => monitor.latest.particles_50um,
        particles_100um: (monitor) => monitor.latest.particles_100um
      }
    }
  },

  async mounted() {
    await GoogleMapsInit();
    this.map = new window.google.maps.Map(
      document.getElementById('map'),
      {
        zoomControl: true,
        mapTypeControl: false,
        scaleControl: true,
        streetViewControl: false,
        rotateControl: true,
        fullscreenControl: false
      }
    );
    this.loadMonitors()
      .then(this.setInitialViewport);

    this.interval = setInterval(this.loadMonitors, 1000 * 60 * 1);
  },

  destroyed() {
    if(this.interval) {
      clearInterval(this.interval);
      this.interval = null;
    }
  },

  computed: {
    mapIsMaximised() {
      return {
        'is-maximised': _.isNull(this.activeMonitor)
      };
    }
  },

  methods: {
    updateField() {
      _.forEach(this.monitors, (monitor) => {
        monitor._marker.setLabel(
          this.getMonitorLabel(monitor)
        );
      });
    },

    getMonitorLabel(monitor){
      if(_.isNull(monitor.latest) || !monitor.is_active){
        return ' ';
      }
      return _.get(this.getLatestValue, this.currentField)(monitor).toString();
    },

    showMonitorDetail(monitorId) {
      this.activeMonitor = null;
      this.activeMonitor = this.monitors[monitorId];
      this.map.panTo(this.activeMonitor._marker.getPosition())
    },

    hideMonitorDetail() {
      this.activeMonitor = null;
    },

    setInitialViewport() {
      const bounds = new window.google.maps.LatLngBounds();
      _.forIn(this.monitors, (monitor) => {
        bounds.extend(monitor._marker.position)
      })
      this.map.fitBounds(bounds);
    },

    loadMonitors() {
      return this.$http.get('monitors/')
        .then(response => response.json(response))
        .then(response => {
          _.map(response.data, (monitor) => {
            monitor.latest.timestamp = moment.utc(monitor.latest.timestamp).local();

            // Ensure we have record of this monitor
            if(_.isUndefined(this.monitors[monitor.id])){
              this.monitors[monitor.id] = {}
            }

            // Update the monitor data
            _.assign(this.monitors[monitor.id], monitor);

            // Create/update the marker
            if(_.isUndefined(this.monitors[monitor.id]._marker)){
              this.monitors[monitor.id]._marker = new window.google.maps.Marker({
                animation: window.google.maps.Animation.DROP,
                map: this.map,
              });
              this.monitors[monitor.id]._marker.addListener('click', () => {
              this.showMonitorDetail(monitor.id);
            });
            }

            this.monitors[monitor.id]._marker.setPosition(
              new window.google.maps.LatLng(
                monitor.position.coordinates[1],
                monitor.position.coordinates[0]
              )
            );

            this.monitors[monitor.id]._marker.setLabel(
              this.getMonitorLabel(monitor)
            );
          });
        })
    }
  }
}
</script>
