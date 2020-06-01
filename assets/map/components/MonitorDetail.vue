<template>
<div class="monitor-detail">
  <div class="container">
    <span class="monitor-close" v-on:click="on_close">
      <span class="far fa-window-close"></span>
    </span>
    <div class="monitor-header">
      <ul class="is-inline">
        <li class="monitor-name">{{ monitor.name }}</li>
        <li>
          <span class="icon">
            <span v-if="monitor.is_active" class="far fa-fw fa-check-circle has-text-success"></span>
            <span v-else class="far fa-fw fa-times-circle has-text-danger"></span>
          </span>
          <span class="monitor-timesince" v-bind:title="monitor.timestamp">{{ timesince }}</span>
        </li>
        <li class="is-size-7">{{ monitor.device }} <span class="is-family-monospace">{{ monitor.id }}</span></li>
      </ul>
    </div>
    <div class="columns">
      <div class="column content">
        <div v-if="monitor.is_active">
          <monitor-graph v-if="entries" :field="field" :label="$parent.fields[field]" :monitor="monitor" :entries="entries" />
          <div v-else class="content has-text-centered">
            <div class="fa-3x">
              <i class="fas fa-spinner fa-pulse"></i>
            </div>
          </div>
        </div>
      </div>
      <div class="column">
        <div class="columns is-multiline is-mobile">
          <div v-if="monitor.latest.fahrenheit" class="column is-6-mobile is-3-tablet latest-entry">
            <div class="latest-value">{{ monitor.latest.fahrenheit }}°</div>
            <div class="latest-label">Temp. (°F)</div>
          </div>
          <div v-if="monitor.latest.celcius" class="column is-6-mobile is-3-tablet latest-entry">
            <div class="latest-value">{{ monitor.latest.celcius }}°</div>
            <div class="latest-label">Temp. (°C)</div>
          </div>
          <div v-if="monitor.latest.humidity" class="column is-6-mobile is-3-tablet latest-entry">
            <div class="latest-value">{{ monitor.latest.humidity }}%</div>
            <div class="latest-label">Humidity</div>
          </div>
          <div v-if="monitor.latest.pressure" class="column is-6-mobile is-3-tablet latest-entry">
            <div class="latest-value">{{ monitor.latest.pressure }}</div>
            <div class="latest-label">Pressure</div>
          </div>

          <div v-if="monitor.latest.pm10_env" class="column is-6-mobile is-3-tablet latest-entry">
            <div class="latest-value">{{ monitor.latest.pm10_env }}</div>
            <div class="latest-label">PM 1.0</div>
          </div>
          <div v-if="monitor.latest.pm25_env" class="column is-6-mobile is-3-tablet latest-entry">
            <div class="latest-value">{{ monitor.latest.pm25_env }}</div>
            <div class="latest-label">PM 2.5</div>
          </div>
          <div v-if="monitor.latest.pm100_env" class="column is-6-mobile is-3-tablet latest-entry">
            <div class="latest-value">{{ monitor.latest.pm100_env }}</div>
            <div class="latest-label">PM 10</div>
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

  data() {
    return {
      entries: null,
      interval: null,
    }
  },

  watch: {
    field: () => {
      console.log('field updated')
      this.entries = null;
      this.entries = this.loadEntries();
    },
    monitor: () => {
      console.log('monitor updated')
      this.entries = null;
      this.entries = this.loadEntries();
    },
  },

  async mounted(){
    this.entries = await this.loadEntries();
    this.interval = setInterval(() => {
      console.log('reloading entries')
      this.entries = this.loadEntries
    }, 1000 * 60 * 1);
  },

  destroyed() {
    if(this.interval) {
      clearInterval(this.interval);
      this.interval = null;
    }
  },

  computed: {
    timesince() {
      if(!_.isNull(this.monitor.latest)){
        return this.monitor.latest.timestamp.fromNow();
      }
      return '';
    }
  },

  methods: {
    on_close() {
      this.$parent.hideMonitorDetail();
    },

    async loadEntries(page, timestamp) {
      if(!page) {
        page = 1;
      }

      if(!timestamp){
        timestamp = moment.utc()
          .subtract(1, 'days')
          .format('YYYY-MM-DD HH:mm:ss');
      }

      return await this.$http.get(`monitors/${this.monitor.id}/entries/`, {
        params: {
          field: this.field,
          page: page,
          timestamp__gte: timestamp
        }
      })
        .then(response => response.json(response))
        .then(async response => {
          let data = _.map(response.data, data => {
            data.timestamp = moment.utc(data.timestamp).local();
            return data;
          });
          if(response.has_next_page){
            let nextPage = await this.loadEntries(page + 1, timestamp);
            data.push(...nextPage);
          }
          return _.uniqBy(data, 'id');
        })
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
