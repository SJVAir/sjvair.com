<template>
<div class="monitor-detail container is-fluid">
  <div class="monitor-header columns">
    <div class="column is-two-thirds content">
      <h2>{{ monitor.name }}</h2>
      <p class="is-size-7">ID: <span class="is-family-monospace">{{ monitor.id }}</span></p>
      <p class="monitor-status">
        <span class="icon">
          <span v-if="monitor.is_active" class="far fa-fw fa-check-circle has-text-success"></span>
          <span v-else class="far fa-fw fa-times-circle has-text-danger"></span>
        </span>
        <span class="monitor-timesince" v-bind:title="monitor.timestamp">{{ timesince }}</span>
      </p>
      <p v-if="!monitor.is_active" class="has-text-weight-bold has-text-danger">This monitor is not currently active.</p>
    </div>
    <div class="column">
      <div class="box content">
        <div class="level is-mobile">
          <div class="level-item has-text-centered">
            <div>
              <p class="heading">US EPA PM2.5 AQI</p>
              <p class="title">{{ monitor.epa_pm25_aqi }}</p>
            </div>
          </div>
          <div class="level-item has-text-centered">
            <div>
              <p class="heading">US EPA PM10 AQI</p>
              <p class="title">{{ monitor.epa_pm100_aqi }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div v-if="monitor.is_active">
    <div v-if="monitorData" class="columns is-multiline">
      <div class="column is-one-third">
        <monitor-graph :paths="['fahrenheit']" label="Temperature (°F)" :monitor="monitor" :monitorData="monitorData">
      </div>
    </div>
    <div v-else class="content has-text-centered">
      <div class="fa-3x">
        <i class="fas fa-spinner fa-pulse"></i>
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
    monitor: Object
  },

  data() {
    return {
      monitorData: null
    }
  },

  async mounted(){
    this.monitorData = _.uniqBy(await this.getMonitorData(), 'id')
  },

  computed: {
    timesince() {
      if(!_.isNull(this.monitor.latest)){
        return this.monitor.latest.timestamp.fromNow()
      }
    }
  },

  methods: {
    async getMonitorData(page, timestamp) {
      if(!page) {
        page = 1;
      }

      if(!timestamp){
        timestamp = moment.utc()
          .subtract(3, 'days')
          .format('YYYY-MM-DD HH:mm:ss');
      }

      return await this.$http.get(`monitors/${this.monitor.id}/data/`, {
        params: {
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
            let nextPage = await this.getMonitorData(page + 1, timestamp);
            data.push(...nextPage);
          }
          return data;
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
