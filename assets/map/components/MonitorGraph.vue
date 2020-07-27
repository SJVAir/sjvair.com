<template>
<div v-if="monitor" class="monitor-graph">
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
    <apexchart ref="chart" type="line" width="100%" height="150px" :options="options"></apexchart>
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
  },

  data() {
    return {
      entries: {},
      interval: null
    }
  },

  async mounted() {
    this.loadAllEntries();
    this.interval = setInterval(this.loadAllEntries, 1000 * 60 * 2);
  },

  destroyed() {
    if(this.interval) {
      clearInterval(this.interval);
      this.interval = null;
    }
  },

  watch: {
    entries: function() {
      this.updateChart();
    },
    monitor: async function(){
      this.$refs.chart.updateSeries([]);
      this.loadAllEntries();
    }
  },

  computed: {
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
        noData: {
          text: 'Loading...'
        },
        stroke: {
          show: true,
          curve: 'smooth',
          lineCap: 'round',
          width: 1,
          dashArray: 0,
        },
        theme: {
          palette: 'palette2'
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
    }
  },

  methods: {
    async loadAllEntries(){
      let sensors = {
        PurpleAir: ['a', 'b']
      };

      _.each(_.get(sensors, this.monitor.device, ['']), sensor => {
        this.loadEntries(sensor)
      });
    },

    async loadEntries(sensor, page, timestamp) {
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
          field: this.attr,
          page: page,
          timestamp__gte: timestamp,
          sensor: sensor
        }
      })
        .then(response => response.json(response))
        .then(async response => {
          let data = _.map(response.data, data => {
            data.timestamp = moment.utc(data.timestamp).local();
            return data;
          });
          if(response.has_next_page){
            let nextPage = await this.loadEntries(sensor, page + 1, timestamp);
            data.push(...nextPage);
          }

          if(page == 1){
            this.entries = Object.assign({}, this.entries, _.fromPairs([[sensor, _.uniqBy(data, 'id')]]));
          } else {
            return data;
          }
        })
    },

    updateChart() {
      let series = _.map(this.entries, (value, key) => {
        return {
          name: key,
          data: _.map(value, data => {
            return {
              x: data.timestamp,
              y: _.get(data, this.attr)
            }
          })
        }
      })

      this.$refs.chart.updateSeries(series, true);
    }
  }
}
</script>
