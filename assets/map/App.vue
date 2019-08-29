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
        activeSensor: null
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
    this.loadSensors();
  },

  methods: {
    getSensorLable(sensor){
      if(_.isNull(sensor.latest) || !sensor.is_active){
        return ' ';
      }
      return sensor.latest.pm2_a.pm25_env.toString();
    },

    showSensorDetail(sensorId) {
      console.log('showing sensor', sensorId, this.sensors[sensorId].name);
      this.activeSensor = this.sensors[sensorId];
      this.map.panTo(this.activeSensor._marker.getPosition())
    },

    hideSensorDetail() {
      this.activeSensor = null;
    },

    loadSensors() {
      const bounds = new window.google.maps.LatLngBounds();
      this.$http.get('sensors/')
        .then(response => response.json(response))
        .then(response => {
          this.sensors = _.keyBy(_.map(response.data, (sensor) => {
            sensor._marker = new window.google.maps.Marker({
              animation: window.google.maps.Animation.DROP,
              label: this.getSensorLable(sensor),
              map: this.map,
              position: new window.google.maps.LatLng(
                sensor.position.coordinates[1],
                sensor.position.coordinates[0]
              )
            });
            sensor._marker.addListener('click', () => {
              this.showSensorDetail(sensor.id);
            });
            bounds.extend(sensor._marker.position);
            return sensor;
          }), 'id');
        })
        .then(() => {
          this.map.fitBounds(bounds);
          console.log(this.sensors)
        });
    }
  }
}
</script>
