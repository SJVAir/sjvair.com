<template>
<div class="monitor-graph">
  <div class="level">
    <div class="level-left">
      <div class="level-item">{{ label }}</div>
    </div>
    <div class="level-right">
      <div class="level-item">
        <strong>Current: {{ $parent.$parent.getLatestValue[field](monitor) }}</strong>
      </div>
    </div>
  </div>
  <div class="chart">
    <apexchart type="line" width="100%" height="150px" :options="options" :series="series"></apexchart>
  </div>
</div>
</template>

<script>
import _ from 'lodash';
import moment from 'moment';
import Vue from 'vue'
import VueApexCharts from 'vue-apexcharts'

Vue.component('apexchart', VueApexCharts)

export default {
  name: 'monitor-graph',
  props: {
    monitor: Object,
    label: String,
    field: String,
    entries: Array,
  },

  mounted() {
  },

  computed: {
    latestValue(){
      return _.get(this.monitor.latest, this.field);
    },

    options() {
      return {
        chart: {
          id: `id_chart-${this.field}`,
          animations: {
            enabled: false
          },
          height: '150px',
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
      return [{
        name: this.label,
        data: _.map(this.entries, data => {
          return {
            x: data.timestamp,
            y: _.get(data, this.field)
          }
        })
      }];
    }
  },

  methods: {

  }
}
</script>
