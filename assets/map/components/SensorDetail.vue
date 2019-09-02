<template>
<div class="sensor-detail container is-fluid">
  <div class="sensor-header columns">
    <div class="column is-two-thirds content">
      <h2>{{ sensor.name }}</h2>
      <p class="is-size-7">ID: <span class="is-family-monospace">{{ sensor.id }}</span></p>
      <p class="sensor-status">
        <span class="icon">
          <span v-if="sensor.is_active" class="far fa-fw fa-check-circle has-text-success"></span>
          <span v-else class="far fa-fw fa-times-circle has-text-danger"></span>
        </span>
        <span class="sensor-timesince" v-bind:title="sensor.timestamp">{{ timesince }}</span>
      </p>
      <p v-if="!sensor.is_active" class="has-text-weight-bold has-text-danger">This sensor is not currently active.</p>
    </div>
    <div class="column">
      <div class="box content">
        <div class="level is-mobile">
          <div class="level-item has-text-centered">
            <div>
              <p class="heading">US EPA PM2.5 AQI</p>
              <p class="title">{{ sensor.epa_pm25_aqi }}</p>
            </div>
          </div>
          <div class="level-item has-text-centered">
            <div>
              <p class="heading">US EPA PM10 AQI</p>
              <p class="title">{{ sensor.epa_pm100_aqi }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div v-if="sensor.is_active">
    <div v-if="sensorData" class="columns is-multiline">
      <div class="column is-one-third">
        <sensor-graph :paths="['fahrenheit']" label="Temperature (°F)" :sensor="sensor" :sensorData="sensorData">
      </div>
      <div class="column is-one-third">
        <sensor-graph :paths="['humidity']" label="Humidity" :sensor="sensor" :sensorData="sensorData">
      </div>
      <div class="column is-one-third">
        <sensor-graph :paths="['pressure']" label="Atmospheric Pressure" :sensor="sensor" :sensorData="sensorData">
      </div>
      <div class="column is-one-third">
        <sensor-graph :paths="['pm2_a.pm10_env', 'pm2_b.pm10_env']" label="PM 1.0" :sensor="sensor" :sensorData="sensorData">
      </div>
      <div class="column is-one-third">
        <sensor-graph :paths="['pm2_a.pm25_env', 'pm2_b.pm25_env']" label="PM 2.5" :sensor="sensor" :sensorData="sensorData">
      </div>
      <div class="column is-one-third">
        <sensor-graph :paths="['pm2_a.pm100_env', 'pm2_b.pm100_env']" label="PM 10" :sensor="sensor" :sensorData="sensorData">
      </div>
      <div class="column is-one-third">
        <sensor-graph :paths="['pm2_a.particles_03um', 'pm2_b.particles_03um']" label="Particles > 0.3µm / 0.1L air" :sensor="sensor" :sensorData="sensorData">
      </div>
      <div class="column is-one-third">
        <sensor-graph :paths="['pm2_a.particles_05um', 'pm2_b.particles_05um']" label="Particles > 0.5µm / 0.1L air" :sensor="sensor" :sensorData="sensorData">
      </div>
      <div class="column is-one-third">
        <sensor-graph :paths="['pm2_a.particles_10um', 'pm2_b.particles_10um']" label="Particles > 1.0µm / 0.1L air" :sensor="sensor" :sensorData="sensorData">
      </div>
      <div class="column is-one-third">
        <sensor-graph :paths="['pm2_a.particles_25um', 'pm2_b.particles_25um']" label="Particles > 2.5µm / 0.1L air" :sensor="sensor" :sensorData="sensorData">
      </div>
      <div class="column is-one-third">
        <sensor-graph :paths="['pm2_a.particles_50um', 'pm2_b.particles_50um']" label="Particles > 5.0µm / 0.1L air" :sensor="sensor" :sensorData="sensorData">
      </div>
      <div class="column is-one-third">
        <sensor-graph :paths="['pm2_a.particles_100um', 'pm2_b.particles_100um']" label="Particles > 10.0µm / 0.1L air" :sensor="sensor" :sensorData="sensorData">
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
import SensorGraph from './SensorGraph.vue'

export default {
  name: 'sensor-detail',

  components: {
    SensorGraph
  },

  props: {
    sensor: Object
  },

  data() {
    return {
      sensorData: null
    }
  },

  async mounted(){
    this.sensorData = _.uniqBy(await this.getSensorData(), 'id')
  },

  computed: {
    timesince() {
      if(!_.isNull(this.sensor.latest)){
        return this.sensor.latest.timestamp.fromNow()
      }
    }
  },

  methods: {
    async getSensorData(page, timestamp) {
      if(!page) {
        page = 1;
      }

      if(!timestamp){
        timestamp = moment.utc()
          .subtract(3, 'days')
          .format('YYYY-MM-DD HH:mm:ss');
      }

      return await this.$http.get(`sensors/${this.sensor.id}/data/`, {
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
            let nextPage = await this.getSensorData(page + 1, timestamp);
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
