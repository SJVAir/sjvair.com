<template>
  <div class="columns is-gapless">
    <div class="column">
      <div id="map"></div>
    </div>
  </div>
</template>

<script>
import _ from 'lodash';
import GoogleMapsInit from './utils/gmaps';

export default {
  name: 'app',

  components: {
  },

  data() {
    return {
        map: null,
        sensors: {},
    }
  },

  async mounted() {
    await GoogleMapsInit();
    this.map = new window.google.maps.Map(this.$el, {
      zoomControl: true,
      mapTypeControl: false,
      scaleControl: true,
      streetViewControl: false,
      rotateControl: true,
      fullscreenControl: false
    });
    this.loadSensors();
  },

  methods: {
    getSensorLable(sensor){
      if(!_.isNull(sensor.latest)){
        return sensor.latest.pm2_a.pm25_env.toString();
      }
      return ' ';
    },

    loadSensors() {
      const bounds = new window.google.maps.LatLngBounds();
      this.$http.get('/api/1.0/sensors/')
        .then(response => response.json(response))
        .then(response => {
          this.sensors = _.keyBy(_.map(response.data, (sensor) => {
            sensor._marker = new window.google.maps.Marker({
              position: new window.google.maps.LatLng(
                sensor.position.coordinates[1],
                sensor.position.coordinates[0]
              ),
              label: this.getSensorLable(sensor),
              map: this.map
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
