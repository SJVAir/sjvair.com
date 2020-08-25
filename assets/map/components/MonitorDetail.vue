<template>
<div class="monitor-detail">
  <div class="container">
    <span class="monitor-close" v-on:click="on_close">
      <span class="far fa-window-close"></span>
    </span>
    <div class="monitor-header">
      <ul class="is-inline">
        <li class="monitor-name">{{ monitor.name }}</li>
        <li v-if="monitor.is_sjvair">
          <span class="tag is-info is-light">
            <span class="icon">
              <span class="fal fa-lungs has-text-info"></span>
            </span>
            <span>SJVAir</span>
          </span>
        </li>
        <li>
          <span class="tag is-light">
            <span class="icon">
              <span class="fal fa-router has-text-grey"></span>
            </span>
            <span>{{ monitor.device }}</span>
          </span>
        </li>
        <li v-if="monitor.county">
          <span class="tag is-light">
            <span class="icon">
              <span class="fal fa-map-marker-alt has-text-grey"></span>
            </span>
            <span>{{ monitor.county }}</span>
          </span>
        </li>
        <li>
          <span class="tag is-light">
            <span class="icon">
              <span class="fal fa-location has-text-grey"></span>
            </span>
            <span>{{ location }}</span>
          </span>
        </li>
        <li :title="monitor.timestamp">
          <span class="tag is-light" :class="monitor.is_active ? 'is-success' : 'is-danger'">
            <span class="icon">
              <span class="fal fa-history" :class="monitor.is_active ? 'has-text-success' : 'has-text-danger'"></span>
            </span>
            <span class="monitor-timesince">{{ timesince }}</span>
          </span>
        </li>
      </ul>
    </div>
    <div class="columns">
      <div class="column">
        <monitor-graph :monitor="monitor" />
      </div>
      <div class="column">
        <div class="columns is-multiline is-mobile">
          <div v-for="(field, key) in $parent.fields" class="column is-6-mobile is-3-tablet is-4-desktop latest-entry">
            <div class="latest-value">{{ field.latest(monitor) }}</div>
            <div class="latest-label">{{ field.label }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</template>

<script>
import _ from 'lodash';
import moment from 'moment';
import MonitorGraph from './MonitorGraph.vue'

export default {
  name: 'monitor-detail',

  components: {
    MonitorGraph
  },

  props: {
    monitor: Object,
    field: String
  },

  watched: {
    monitor: async function(monitor) {
      // this.$refs.chart.updateChart();
    }
  },

  computed: {
    timesince() {
      if(!_.isEmpty(this.monitor.latest)){
        return this.monitor.latest.timestamp.fromNow();
      }
      return '';
    },

    location() {
      return _.capitalize(this.monitor.location)
    }
  },

  methods: {
    on_close() {
      this.$parent.hideMonitorDetail();
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
