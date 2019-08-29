<template>
<div class="content sensor-detail">
  <h2>{{ sensor.name }}</h2>
  <p class="sensor-status">
    <span class="icon">
      <span v-if="sensor.is_active" class="far fa-fw fa-check-circle is-text-success"></span>
      <span v-else class="far fa-fw fa-times-circle is-text-danger"></span>
    </span>
    <span class="sensor-timesince">{{ this.timesince() }}</span>
  </p>
  <p v-if="!sensor.is_active" class="has-text-weight-bold has-text-danger">This sensor is not currently active.</p>
  <div v-if="sensor.is_active">
    <table class="sensor-conditions">
      <tr>
        <td class="has-text-centered" style="width: 33%">
          <div>
            <span class="icon">
              <span class="far fa-2x fa-temperature-high"></span>
            </span>
          </div>
          <div>
            {{ sensor.latest.fahrenheit }}°F / {{ sensor.latest.celcius }}°C
          </div>
        </td>
        <td class="has-text-centered" style="width: 33%">
          <div>
            <span class="icon">
              <span class="far fa-2x fa-humidity"></span>
            </span>
          </div>
          <div>
            {{ sensor.latest.humidity }}%
          </div>
        </td>
        <td class="has-text-centered" style="width: 33%">
          <div>
            <span class="icon">
              <span class="far fa-2x fa-tire-pressure-warning"></span>
            </span>
          </div>
          <div>
            {{ sensor.latest.pressure }} hPa
          </div>
        </td>
      </tr>
    </table>
    <table class="is-size-7">
      <thead>
        <tr>
          <td></td>
          <td class="has-text-centered">Sensor A</td>
          <td class="has-text-centered">Sensor B</td>
        </tr>
      </thead>
      <tr>
        <th>PM 1 (Standard)</th>
        <td class="has-text-centered">{{ sensor.latest.pm2_a.pm10_standard }}</td>
        <td class="has-text-centered">{{ sensor.latest.pm2_b.pm10_standard }}</td>
      </tr>
      <tr>
        <th>PM 2.5 (Standard)</th>
        <td class="has-text-centered">{{ sensor.latest.pm2_a.pm25_standard }}</td>
        <td class="has-text-centered">{{ sensor.latest.pm2_b.pm25_standard }}</td>
      </tr>
      <tr>
        <th>PM 10 (Standard)</th>
        <td class="has-text-centered">{{ sensor.latest.pm2_a.pm100_standard }}</td>
        <td class="has-text-centered">{{ sensor.latest.pm2_b.pm100_standard }}</td>
      </tr>

      <tr>
        <th>PM 1 (Environmental)</th>
        <td class="has-text-centered">{{ sensor.latest.pm2_a.pm10_env }}</td>
        <td class="has-text-centered">{{ sensor.latest.pm2_b.pm10_env }}</td>
      </tr>
      <tr>
        <th>PM 2.5 (Environmental)</th>
        <td class="has-text-centered">{{ sensor.latest.pm2_a.pm25_env }}</td>
        <td class="has-text-centered">{{ sensor.latest.pm2_b.pm25_env }}</td>
      </tr>
      <tr>
        <th>PM 10 (Environmental)</th>
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
    }
  }
}
</script>
