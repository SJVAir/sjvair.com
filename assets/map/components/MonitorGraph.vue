<template>
<div class="monitor-graph">
  <div class="level">
    <div class="level-left">
      <div class="level-item">{{ field.label }}</div>
    </div>
    <div class="level-right">
      <div class="level-item">
        <strong>Current: {{ field.latest(monitor) }}</strong>
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
    field: Object,
    attr: String,
    entries: Array,
  },

  mounted() {
    console.log('MOUNTED', this.field, this.attr)
  },

  computed: {
    latestValue(){
      return this.field.latest(this.monitor);
    },

    options() {
      return {
        chart: {
          id: `id_chart`,
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
      if(this.entries == null){
        return [];
      }

      return [{
        name: this.field.label,
        data: _.map(this.entries, data => {
          return {
            x: data.timestamp,
            y: _.get(data, this.attr)
          }
        })
      }];
    }
  },

  methods: {

  }
}
</script>
