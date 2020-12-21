<template>
<div v-if="monitor" class="monitor-graph">
  <div class="date-select columns is-multiline is-mobile">
    <div class="date-select-column">
      <div class="columns">
        <div class="date-select-column">
          <label for="startDate">Start Date:</label>
          <datepicker id="startDate" typeable placeholder="Start Date" v-model="dateStart"></datepicker>
        </div>
        <div class="date-select-column">
          <label for="endDate">End Date:</label>
          <datepicker id="endDate" typeable placeholder="Start Date" v-model="dateEnd"></datepicker>
        </div>
      </div>
    </div>
    <button class="button date-select-column" v-on:click="loadAllEntries">View Data!</button>
  </div>
  <div class="chart">
    <apexchart ref="chart" type="line" width="100%" height="250px" :options="options"></apexchart>
  </div>
</div>
</template>

<script>
import _ from 'lodash';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import VueApexCharts from 'vue-apexcharts'
import Datepicker from "vuejs-datepicker/dist/vuejs-datepicker.esm.js";

dayjs.extend(utc);
dayjs.extend(timezone);

function formatDate(date) {
  return dayjs.utc(date).format('YYYY-MM-DD HH:mm:ss');
}

export default {
  name: 'monitor-graph',
  components: {
    'apexchart': VueApexCharts,
    Datepicker
  },
  props: {
    monitor: Object,
  },

  data() {
    // Set the inital values for the date pickers
    // Default range: last 3 days
    const dateEnd = dayjs().endOf('day').toString();
    const dateStart = dayjs(dateEnd).subtract(3, 'day').startOf('day').toString();

    return {
      dateEnd,
      dateStart,
      entries: {},
      interval: null,
      fields: {
        PurpleAir: {
          pm25_env: 'PM2.5',
          pm25_avg_15: 'PM2.5 (15m)',
          pm25_avg_60: 'PM2.5 (1h)'
        },
        AirNow: {
          pm25_env: 'PM2.5'
        }
      },
      sensors: {
        PurpleAir: ['a'],
        AirNow: ['']
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
          legend: {
            show: true
          },
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
          forceNiceScale: true,
          lines: true,
          min: 0,
          labels: {
            formatter: Math.trunc
          }
        }
      };
    }
  },

  methods: {
    async loadAllEntries(){
      this.entries = {};
      _.each(this.sensors[this.monitor.device], sensor => {
          this.loadEntries(sensor)
      });
    },

    async loadEntries(sensor, page) {
      if(!page) {
        page = 1;
      }

      return await this.$http.get(`monitors/${this.monitor.id}/entries/`, {
        params: {
          fields: _.join(_.keys(this.fields[this.monitor.device]), ','),
          page: page,
          timestamp__gte: formatDate(this.dateStart),
          timestamp__lte: formatDate(this.dateEnd),
          sensor: sensor
        }
      })
        .then(response => response.json(response))
        .then(async response => {
          let data = response.data;
          if(response.has_next_page){
            let nextPage = await this.loadEntries(sensor, page + 1);
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
        return _.map(this.fields[this.monitor.device], (label, field) => {
          let name = label;
          if(this.sensors[this.monitor.device].length > 1 && sensor) {
            name += ` (${sensor})`;
          }
          return {
            name: name,
            data: _.map(entries, data => {
              return {
                // TODO: convert to appropriate tz for monitor on the api rather than hardcoding
                x: dayjs
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
