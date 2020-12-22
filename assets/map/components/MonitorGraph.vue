<template>
<div v-if="monitor" class="monitor-graph">
  <div class="date-select columns is-mobile">
    <div class="column">
      <div class="field">
        <div class="control">
          <datepicker id="startDate" :disabled-dates="{customPredictor: checkStartDate}" input-class="input is-small" typeable placeholder="Start Date" v-model="dateStart"></datepicker>
        </div>
        <label for="startDate" class="label is-small has-text-weight-normal">Start Date</label>
      </div>
    </div>
    <div class="column">
      <div class="field">
        <div class="control">
          <datepicker id="endDate" :disabled-dates="{customPredictor: checkEndDate}" input-class="input is-small" typeable placeholder="End Date" v-model="dateEnd"></datepicker>
        </div>
        <label for="endDate" class="label is-small has-text-weight-normal">End Date</label>
      </div>
    </div>
    <div class="column">
      <div class="field">
        <div class="control">
          <button class="button is-small is-info" v-on:click="loadAllEntries">Update</button>
        </div>
      </div>
    </div>
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
import Vue from 'vue'
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
          pm25_env: '2m',
          pm25_avg_15: '15m',
          pm25_avg_60: '60m'
        },
        AirNow: {
          pm25_env: '60m'
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
    checkStartDate(date) {
      // Date must be lte endDate and lte today.
      // true means disabled, so not the logic.
      return !(date <= dayjs(this.dateEnd).endOf('day').toDate() && date <= dayjs().endOf('day').toDate())
    },
    checkEndDate(date) {
      // Date must be gte startDate and lte today.
      // true means disabled, so not the logic.
      return !(date >= dayjs(this.dateStart).startOf('day').toDate() && date <= dayjs().endOf('day').toDate())
    },
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
