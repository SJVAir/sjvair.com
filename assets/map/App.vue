<template>
  <div class="columns is-gapless">
    <div class="column">
      <div id="map"></div>
    </div>
    <div v-if="activeSensor" class="column is-one-third">
      <sensor-detail :sensor="activeSensor" />
    </div>
  </div>
</template>

<script>
import _ from 'lodash';
import GoogleMapsInit from './utils/gmaps';
import SensorDetail from './components/SensorDetail.vue'

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

  methods: {
    getSensorLabel(sensor){
      if(_.isNull(sensor.latest) || !sensor.is_active){
        return ' ';
      }
      return sensor.latest.pm2_a.pm25_env.toString();
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

            this.sensors[sensor.id]._marker.setLabel(
              this.getSensorLabel(sensor)
            )

            this.sensors[sensor.id]._marker.setPosition(
              new window.google.maps.LatLng(
                sensor.position.coordinates[1],
                sensor.position.coordinates[0]
              )
            )

          });
        })
    }
  }
}
</script>
