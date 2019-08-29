<template>
<div class="content sensor-detail">
  <h2>{{ sensor.name }}</h2>
  <div class="sensor-status">
    <span class="icon">
      <span v-if="sensor.is_active" class="far fa-check-circle is-success fa-fw"></span>
      <span v-else class="far fa-times-circle is-danger fa-fw"></span>
    </span>
    <span class="sensor-timesince">{{ this.timesince() }}</span>
  </div>
  <table class="sensor-conditions">
    <tr>
      <td style="width: 50%">
        <span class="icon">
          <span class="far fa-temperature-high"></span>
        </span>
      </td>
      <td>{{ sensor.latest.fahrenheit }}°F / {{ sensor.latest.celcius }}°C</td>
    </tr>
    <tr>
      <td style="width: 50%">
        <span class="icon">
          <span class="far fa-humidity"></span>
        </span>
      </td>
      <td>{{ sensor.latest.humidity }}%</td>
    </tr>
    <tr>
      <td style="width: 50%">
        <span class="icon">
          <span class="far fa-tire-pressure-warning"></span>
        </span>
      </td>
      <td>{{ sensor.latest.pressure }} hPa</td>
    </tr>
  </table>
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
