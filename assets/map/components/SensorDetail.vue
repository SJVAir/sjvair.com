<template>
<div class="content sensor-detail">
  <h2>{{ sensor.name }}</h2>
  <p class="is-size-7">ID: <span class="is-family-monospace">{{ sensor.id }}</span></p>
  <p class="sensor-status">
    <span class="icon">
      <span v-if="sensor.is_active" class="far fa-fw fa-check-circle has-text-success"></span>
      <span v-else class="far fa-fw fa-times-circle has-text-danger"></span>
    </span>
    <span class="sensor-timesince" v-bind:title="sensor.timestamp">{{ this.timesince() }}</span>
  </p>
  <p v-if="!sensor.is_active" class="has-text-weight-bold has-text-danger">This sensor is not currently active.</p>
  <div v-if="sensor.is_active">
    <table class="table is-striped sensor-realtime">
      <thead>
        <tr>
          <th colspan="2">Current Conditions</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <th>Temperature</th>
          <td>{{ sensor.latest.fahrenheit }}°F <small>({{ sensor.latest.celcius }}°C)</small></td>
        </tr>
        <tr>
          <th>Humidity</th>
          <td>{{ sensor.latest.humidity }}%</td>
        </tr>
        <tr>
          <th>Atmospheric Pressure</th>
          <td>{{ sensor.latest.pressure }} hPa</td>
        </tr>
        <tr>
          <th>US EPA PM2.5 AQI</th>
          <td v-if="sensor.epa_pm25_aqi">{{ sensor.epa_pm25_aqi }}</td>
          <td v-else>-</td>
        </tr>
        <tr>
          <th>US EPA PM10 AQI</th>
          <td v-if="sensor.epa_pm100_aqi">{{ sensor.epa_pm100_aqi }}</td>
          <td v-else>-</td>
        </tr>
      </tbody>
    </table>
    <table class="table is-striped is-size-7">
      <thead>
        <tr>
          <th>Air Quality Conditions</th>
          <td class="has-text-centered">Sensor A</td>
          <td class="has-text-centered">Sensor B</td>
        </tr>
      </thead>
      <tbody>
        <tr>
          <th>PM 1</th>
          <td class="has-text-centered">{{ sensor.latest.pm2_a.pm10_env }}</td>
          <td class="has-text-centered">{{ sensor.latest.pm2_b.pm10_env }}</td>
        </tr>
        <tr>
          <th>PM 2.5</th>
          <td class="has-text-centered">{{ sensor.latest.pm2_a.pm25_env }}</td>
          <td class="has-text-centered">{{ sensor.latest.pm2_b.pm25_env }}</td>
        </tr>
        <tr>
          <th>PM 10</th>
          <td class="has-text-centered">{{ sensor.latest.pm2_a.pm100_env }}</td>
          <td class="has-text-centered">{{ sensor.latest.pm2_b.pm100_env }}</td>
        </tr>

        <tr>
          <th>Particles > 0.3um / 0.1L air</th>
          <td class="has-text-centered">{{ sensor.latest.pm2_a.particles_03um }}</td>
          <td class="has-text-centered">{{ sensor.latest.pm2_b.particles_03um }}</td>
        </tr>
        <tr>
          <th>Particles > 0.5um / 0.1L air</th>
          <td class="has-text-centered">{{ sensor.latest.pm2_a.particles_05um }}</td>
          <td class="has-text-centered">{{ sensor.latest.pm2_b.particles_05um }}</td>
        </tr>
        <tr>
          <th>Particles > 1.0um / 0.1L air</th>
          <td class="has-text-centered">{{ sensor.latest.pm2_a.particles_10um }}</td>
          <td class="has-text-centered">{{ sensor.latest.pm2_b.particles_10um }}</td>
        </tr>
        <tr>
          <th>Particles > 2.5um / 0.1L air</th>
          <td class="has-text-centered">{{ sensor.latest.pm2_a.particles_25um }}</td>
          <td class="has-text-centered">{{ sensor.latest.pm2_b.particles_25um }}</td>
        </tr>
        <tr>
          <th>Particles > 5.0um / 0.1L air</th>
          <td class="has-text-centered">{{ sensor.latest.pm2_a.particles_50um }}</td>
          <td class="has-text-centered">{{ sensor.latest.pm2_b.particles_50um }}</td>
        </tr>
        <tr>
          <th>Particles > 10.0um / 0.1L air</th>
          <td class="has-text-centered">{{ sensor.latest.pm2_a.particles_100um }}</td>
          <td class="has-text-centered">{{ sensor.latest.pm2_b.particles_100um }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
</template>

<script>
import _ from 'lodash';
import moment from 'moment';

export default {
  name: 'sensor-detail',
  props: {
    sensor: Object
  },

  mounted(){
    this.timesince()
  },

  methods: {
    timesince() {
      if(!_.isNull(this.sensor.latest)){
        return moment.utc(this.sensor.latest.timestamp).local().fromNow()
      }
    },

    aqi_label(aqi){
      aqi = parseFloat(aqi)
      if (aqi <= 50) {
        return 'Good';
      }
      else if (aqi > 50 && aqi <= 100){
        return 'Moderate';
      }
      else if (aqi > 100 && aqi <= 150){
        return 'Unhealthy for Sensitive Groups'
      }
      else if (aqi > 150 && aqi <= 200){
        return 'Unhealthy';
      }
      else if (aqi > 200 && aqi <= 300){
        return 'Very Unhealthy';
      }
      else if (aqi > 300 && aqi <= 400){
        return 'Hazardous';
      }
      else if (aqi > 400 && aqi <= 500){
        return 'Hazardous';
      }
      return 'Out of Range';
    }
  }
}
</script>
