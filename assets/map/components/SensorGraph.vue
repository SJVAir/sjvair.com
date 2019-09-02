<template>
<div class="sensor-graph box">
  {{ label }}
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
    options() {
      return {
        chart: {
          id: `id_chart-${this.paths[0]}`,
          height: '150px',
          width: '100%',
          toolbar: {show: false},
        },
        markers: {
          size: 0
        },
        xaxis: {
          type: 'datetime'
        }
      };
    },

    series() {
      return _.map(
        this.paths,
        path => {
          return {
            name: path,
            data: _.map(this.sensorData, data => [
              data.timestamp.unix(),
              _.get(data, path)
            ])
          }
        }
      );
    }
  },

  methods: {

  }
}
</script>
