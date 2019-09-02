<template>
  <div class="interface">
    <div class="viewport">
      <div class="select field-selector">
        <select id="id_data-selector" name="field-selector" v-on:change="updateSensorLabels" v-model="labelDisplay">
          <option v-for="(label, key) in fields" :value="key">{{ label }}</option>
        </select>
      </div>
      <div id="map" :class="mapIsMaximised"></div>
    </div>
    <sensor-detail v-if="activeSensor" :sensor="activeSensor" />
  </div>
</template>

<script>
import _ from 'lodash';
import moment from 'moment';

import SensorDetail from './components/SensorDetail.vue'
import GoogleMapsInit from './utils/gmaps';


export default {
  name: 'app',

  components: {
    SensorDetail
  },

  data() {
    return {
      map: null,
      sensors: {},
      activeSensor: null,
      interval: null,
      labelDisplay: 'epa_pm25_aqi',
      fields: {
        temperature_f: "Temperature (°Fahrenheit)",
        temperature_c: "Temperature (°Celcius)",
        humidity: "Humidity",
        pressure: "Atmospheric Pressure",
        epa_pm25_aqi: "US EPA PM2.5 AQI",
        epa_pm100_aqi: "US EPA PM10 AQI",
        pm25: "PM2.5",
        pm50: "PM5",
        pm100: "PM10",
        particles_3: "Particles > 0.3µm / 0.1L air",
        particles_5: "Particles > 0.5µm / 0.1L air",
        particles_10: "Particles > 1.0µm / 0.1L air",
        particles_25: "Particles > 2.5µm / 0.1L air",
        particles_50: "Particles > 5.0µm / 0.1L air",
        particles_100: "Particles > 10.0µm / 0.1L air"
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
    this.loadSensors()
      .then(this.setInitialViewport);

    this.interval = setInterval(this.loadSensors, 1000 * 60 * 1);
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
        'is-maximised': _.isNull(this.activeSensor)
      };
    }
  },

  methods: {
    updateSensorLabels() {
      _.forEach(this.sensors, (sensor) => {
        sensor._marker.setLabel(
          this.getSensorLabel(sensor)
        );
      });
    },

    getSensorLabel(sensor){
      if(_.isNull(sensor.latest) || !sensor.is_active){
        return ' ';
      }

      return _.get({
        temperature_f: () => Math.round(sensor.latest.fahrenheit) + "°",
        temperature_c: () => Math.round(sensor.latest.celcius) + "°",
        humidity: () => Math.round(sensor.latest.humidity) + "%",
        pressure: () => Math.round(sensor.latest.pressure) + " hPa",
        epa_pm25_aqi: () => sensor.epa_pm25_aqi,
        epa_pm100_aqi: () => sensor.epa_pm100_aqi,
        pm10: () => sensor.latest.pm2_a.pm10_env,
        pm25: () => sensor.latest.pm2_a.pm25_env,
        pm100: () => sensor.latest.pm2_a.pm100_env,
        particles_3: () => sensor.latest.pm2_a.particles_03um,
        particles_5: () => sensor.latest.pm2_a.particles_05um,
        particles_10: () => sensor.latest.pm2_a.particles_10um,
        particles_25: () => sensor.latest.pm2_a.particles_25um,
        particles_50: () => sensor.latest.pm2_a.particles_50um,
        particles_100: () => sensor.latest.pm2_a.particles_100um
      }, this.labelDisplay)().toString();
    },

    showSensorDetail(sensorId) {
      // this.activeSensor = null;
      this.activeSensor = this.sensors[sensorId];
      this.map.panTo(this.activeSensor._marker.getPosition())
    },

    hideSensorDetail() {
      this.activeSensor = null;
    },

    setInitialViewport() {
      const bounds = new window.google.maps.LatLngBounds();
      _.forIn(this.sensors, (sensor) => {
        bounds.extend(sensor._marker.position)
      })
      this.map.fitBounds(bounds);
    },

    loadSensors() {
      return this.$http.get('sensors/')
        .then(response => response.json(response))
        .then(response => {
          _.map(response.data, (sensor) => {
            sensor.latest.timestamp = moment.utc(sensor.latest.timestamp).local();

            // Ensure we have record of this sensor
            if(_.isUndefined(this.sensors[sensor.id])){
              this.sensors[sensor.id] = {}
            }

            // Update the sensor data
            _.assign(this.sensors[sensor.id], sensor);

            // Create/update the marker
            if(_.isUndefined(this.sensors[sensor.id]._marker)){
              this.sensors[sensor.id]._marker = new window.google.maps.Marker({
                animation: window.google.maps.Animation.DROP,
                map: this.map,
              });
              this.sensors[sensor.id]._marker.addListener('click', () => {
              this.showSensorDetail(sensor.id);
            });
            }

            this.sensors[sensor.id]._marker.setPosition(
              new window.google.maps.LatLng(
                sensor.position.coordinates[1],
                sensor.position.coordinates[0]
              )
            );

            this.sensors[sensor.id]._marker.setLabel(
              this.getSensorLabel(sensor)
            );

          });
        })
    }
  }
}
</script>
