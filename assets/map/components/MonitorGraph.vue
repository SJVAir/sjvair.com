<template>
<div v-if="monitor" class="monitor-graph">
  <div class="date-select columns is-mobile">
    <div class="column is-3">
      <div class="field">
        <label for="startDate" class="label is-small has-text-weight-normal">Start Date</label>
        <div class="control">
          <datepicker id="startDate" format="yyyy-MM-dd" :disabled-dates="{customPredictor: checkStartDate}" input-class="input is-small" typeable placeholder="Start Date" v-model="dateStart"></datepicker>
        </div>
      </div>
    </div>
    <div class="column is-3">
      <div class="field">
        <label for="endDate" class="label is-small has-text-weight-normal">End Date</label>
        <div class="control">
          <datepicker id="endDate" format="yyyy-MM-dd" :disabled-dates="{customPredictor: checkEndDate}" input-class="input is-small" typeable placeholder="End Date" v-model="dateEnd"></datepicker>
        </div>
      </div>
    </div>
    <div class="column is-6">
      <div class="field is-grouped">
        <div class="control">
          <br />
          <button class="button is-small is-info" v-on:click="loadAllEntries">
            <span class="icon is-small">
              <span :class="{ 'fa-spin': loading }" class="fal fa-redo"></span>
            </span>
            <span>Update</span>
          </button>
        </div>
        <div class="control">
          <br />
          <button class="button is-small is-success" v-on:click="downloadCSV">
            <span class="icon is-small">
              <span class="fal fa-download"></span>
            </span>
            <span>Download</span>
          </button>
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
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import VueApexCharts from 'vue-apexcharts'
import Datepicker from 'vuejs-datepicker/dist/vuejs-datepicker.esm.js';
import GraphData from "../utils/GraphData.js";

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
    const fields = {
      PurpleAir: {
        pm25_env: '2m',
        pm25_avg_15: '15m',
        pm25_avg_60: '60m'
      },
      AirNow: {
        pm25_env: '60m'
      },
      BAM1022: {
        pm25_env: '60m'
      }
    };

    return {
      dateEnd,
      dateStart,
      fields,
      interval: null,
      loading: false,
      sensors: {
        PurpleAir: ['a'],
        AirNow: [''],
        BAM1022: ['']
      }
    }
  },

  async mounted() {
    this.loadAllEntries();
    this.startSync();
  },

  destroyed() {
    if(this.interval) {
      this.stopSync();
    }
  },

  watch: {
    monitor: async function() {
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
    downloadCSV () {
      let path = `${this.$http.options.root}monitors/${this.monitor.id}/entries/csv/`,
        params = {
          fields: Object.keys(this.fields[this.monitor.device]).join(','),
          timestamp__gte: formatDate(this.dateStart),
          timestamp__lte: formatDate(this.dateEnd),
          sensor: ''
        }

      if(this.sensors[this.monitor.device].length) {
        params.sensor = this.sensors[this.monitor.device][0]
      }

      params = new URLSearchParams(params).toString();
      window.open(`${path}?${params}`)
    },
    async loadAllEntries(){
      for (let sensorGroup of this.sensors[this.monitor.device]) {
        this.loadEntries(sensorGroup)
      }
    },

    async loadEntries(sensor, page) {
      const series = new GraphData(this.fields[this.monitor.device]);
      this.loading = true;

      if (dayjs(this.dateEnd).unix() >= dayjs().startOf("day").unix()) {
        this.startSync();
      } else {
        this.stopSync();
      }

      if(!page) {
        page = 1;
      }

      await this.$http.get(`monitors/${this.monitor.id}/entries/`, {
        params: {
          fields: Object.keys(this.fields[this.monitor.device]).join(','),
          page: page,
          timestamp__gte: formatDate(this.dateStart),
          timestamp__lte: formatDate(this.dateEnd),
          sensor: sensor
        }
      })
        .then(async response => {
          response = await response.json();
          series.addData(response.data);

          if(response.has_next_page){
            await this.loadEntries(sensor, page + 1);

          } else {
            await this.$refs.chart.updateSeries(series.data, true);
            this.loading = false;
          }
        })
    },

    startSync() {
      if (!this.interval) {
        this.interval = setInterval(this.loadAllEntries, 1000 * 60 * 2);
      }
    },

    stopSync() {
      if (this.interval) {
        clearInterval(this.interval);
        this.interval = null;
      }
    }
  }
}
</script>
