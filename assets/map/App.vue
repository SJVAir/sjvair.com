<template>
  <div class="interface">
    <div class="viewport">
      <div class="select field-selector">
        <select id="id_data-selector" name="field-selector" v-on:change="updateMonitorLabels" v-model="labelDisplay">
          <option v-for="(label, key) in fields" :value="key">{{ label }}</option>
        </select>
      </div>
      <div id="map" :class="mapIsMaximised"></div>
    </div>
    <monitor-detail v-if="activeMonitor" :monitor="activeMonitor" />
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
      labelDisplay: 'epa_pm25_aqi',
      fields: {
        fahrenheit: "Temperature (°F)",
        celcius: "Temperature (°C)",
        humidity: "Humidity",
        pressure: "Atmospheric Pressure",
        epa_pm25_aqi: "US EPA PM2.5 AQI",
        epa_pm100_aqi: "US EPA PM10 AQI",
        pm100_env: "PM 2.5",
        pm10_env: "PM 5",
        pm25_env: "PM 10",
        particles_03um: "Particles > 0.3µm / 0.1L air",
        particles_05um: "Particles > 0.5µm / 0.1L air",
        particles_100um: "Particles > 1.0µm / 0.1L air",
        particles_10um: "Particles > 2.5µm / 0.1L air",
        particles_25um: "Particles > 5.0µm / 0.1L air",
        particles_50um: "Particles > 10.0µm / 0.1L air"
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
    updateMonitorLabels() {
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

      return _.get({
        temperature_f: () => Math.round(monitor.latest.fahrenheit) + "°",
        temperature_c: () => Math.round(monitor.latest.celcius) + "°",
        humidity: () => Math.round(monitor.latest.humidity) + "%",
        pressure: () => Math.round(monitor.latest.pressure) + " hPa",
        epa_pm25_aqi: () => monitor.epa_pm25_aqi,
        epa_pm100_aqi: () => monitor.epa_pm100_aqi,
        pm10: () => monitor.latest.pm10_env,
        pm25: () => monitor.latest.pm25_env,
        pm100: () => monitor.latest.pm100_env,
        particles_3: () => monitor.latest.particles_03um,
        particles_5: () => monitor.latest.particles_05um,
        particles_10: () => monitor.latest.particles_10um,
        particles_25: () => monitor.latest.particles_25um,
        particles_50: () => monitor.latest.particles_50um,
        particles_100: () => monitor.latest.particles_100um
      }, this.labelDisplay)().toString();
    },

    showMonitorDetail(monitorId) {
      // this.activeMonitor = null;
      this.activeMonitor = this.monitors[monitorId];
      this.map.panTo(this.activeMonitor._marker.getPosition())
    },

    hideMonitorDetail() {
      this.activeMonitor = null;
    },

    setInitialViewport() {
      console.log('Setting Viewport')
      console.log(this.monitors)
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
