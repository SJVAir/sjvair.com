<template>
<div class="sensor-graph box">
  <div class="level">
    <div class="level-left">
      <div class="level-item">{{ label }}</div>
    </div>
    <div class="level-right">
      <div class="level-item">
        <strong>{{ latestValue }}</strong>
      </div>
    </div>
  </div>
  <apexchart type="line" :options="options" :series="series"></apexchart>
</div>
</template>

<script>
import _ from 'lodash';
import moment from 'moment';
import Vue from 'vue'
import VueApexCharts from 'vue-apexcharts'

Vue.component('apexchart', VueApexCharts)

export default {
  name: 'sensor-graph',
  props: {
    paths: String,
    label: String,
    sensor: Object,
    sensorData: Array,
  },

  mounted() {
  },

  computed: {
    latestValue(){
      return _.get(this.sensor.latest, this.paths[0]);
    },

    options() {
      return {
        chart: {
          id: `id_chart-${this.paths[0]}`,
          animations: {
            enabled: false
          },
          height: 150,
          width: '100%',
          toolbar: {
            show: false
          },
          zoom: {
            enabled: false
          }
        },
        markers: {
          size: 0
        },
        stroke: {
          show: true,
          curve: 'smooth',
          lineCap: 'round',
          width: 1,
          dashArray: 0,
        },
        tooltip: {
          enabled: true
        },
        xaxis: {
          type: 'datetime',
          lines: true
        },
        yaxis: {
          lines: true
        }
      };
    },

    series() {
      return _.map(
        this.paths,
        path => {
          return {
            name: path,
            data: _.map(this.sensorData, data => {
              return {
                x: data.timestamp,
                y: _.get(data, path)
              }
            })
          }
        }
      );
    }
  },

  methods: {

  }
}
</script>
