<template>
<div v-if="monitor" class="monitor-graph">
  <!-- <div class="level">
    <div class="level-left">
      <div class="level-item">{{ field.label }}</div>
    </div>
    <div class="level-right">
      <div class="level-item">
        <strong>Current: {{ field.latest(monitor) }}</strong>
      </div>
    </div>
  </div> -->
  <div class="chart">
    <apexchart ref="chart" type="line" width="100%" height="250px" :options="options"></apexchart>
  </div>
</div>
</template>

<script>
import _ from 'lodash';
import moment from 'moment-timezone';
import Vue from 'vue'
import VueApexCharts from 'vue-apexcharts'

Vue.component('apexchart', VueApexCharts)

export default {
  name: 'monitor-graph',
  props: {
    monitor: Object,
  },

  data() {
    return {
      entries: {},
      interval: null,
      fields: {
        'pm25_env': 'PM2.5',
        'pm25_avg_15': 'PM2.5 (15m)',
        'pm25_avg_60': 'PM2.5 (1h)'
      },
      sensors: {
        PurpleAir: ['a']
      }
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
          height: '250px',
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
        colors: ['#000033', '#006699', '#00ccff'],
        // theme: {
        //   // palette: 'palette2',
        //   monochrome: {
        //     enabled: true,
        //     color: '#209cee',
        //     shadeTo: 'light',
        //     shadeIntensity: 0.85
        //   }
        // },
        tooltip: {
          enabled: true,
          x: {
            format: 'MMM d, h:mmtt'
          }
        },
        xaxis: {
          type: 'datetime',
          lines: true,
          labels: {
            datetimeUTC: false
          }
        },
        yaxis: {
          lines: true
        }
      };
    }
  },

  methods: {
    async loadAllEntries(){
      _.each(_.get(this.sensors, this.monitor.device, ['']), sensor => {
          this.loadEntries(sensor)
      });
    },

    async loadEntries(sensor, page, timestamp) {
      if(!page) {
        page = 1;
      }

      if(!timestamp){
        timestamp = moment.utc()
          .subtract(36, 'hours')
          .format('YYYY-MM-DD HH:mm:ss');
      }

      return await this.$http.get(`monitors/${this.monitor.id}/entries/`, {
        params: {
          fields: _.join(_.keys(this.fields), ','),
          page: page,
          timestamp__gte: timestamp,
          sensor: sensor
        }
      })
        .then(response => response.json(response))
        .then(async response => {
          let data = response.data;
          if(response.has_next_page){
            let nextPage = await this.loadEntries(sensor, page + 1, timestamp);
            data.push(...nextPage);
          }

          if(page == 1){
            this.entries = Object.assign({}, this.entries, _.fromPairs([[sensor, _.uniqBy(data, 'timestamp')]]));
          } else {
            return data;
          }
        })
    },

    async updateChart() {
      let series = _.reverse(_.flatten(_.map(this.entries, (entries, sensor) => {
        return _.map(this.fields, (label, field) => {
          let name = label;
          if(_.get(this.sensors, this.monitor.device, ['']).length > 1 && sensor) {
            name += ` (${sensor})`;
          }
          return {
            name: name,
            data: _.map(entries, data => {
              return {
                // TODO: convert to appropriate tz for monitor on the api rather than hardcoding
                x: moment
                  .utc(data.timestamp)
                  .tz('America/Los_Angeles'),
                y: _.get(data, field)
              }
            })
          }
        })
      })));

      this.$refs.chart.updateSeries(series, true);
    }
  }
}
</script>
