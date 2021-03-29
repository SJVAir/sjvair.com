<template>
<div v-if="monitor" class="monitor-graph">
  <div class="date-select columns is-mobile">
    <div class="column is-3">
      <div class="field">
        <label for="startDate" class="label is-small has-text-weight-normal">Start Date</label>
        <div class="control">
          <datepicker id="startDate" format="yyyy-MM-dd" :disabled-dates="{customPredictor: checkStartDate}" input-class="input is-small" typeable placeholder="Start Date" v-model="startDate"></datepicker>
        </div>
      </div>
    </div>
    <div class="column is-3">
      <div class="field">
        <label for="endDate" class="label is-small has-text-weight-normal">End Date</label>
        <div class="control">
          <datepicker id="endDate" format="yyyy-MM-dd" :disabled-dates="{customPredictor: checkEndDate}" input-class="input is-small" typeable placeholder="End Date" v-model="endDate"></datepicker>
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
    <monitor-chart :chartData="monitor.chartData" :dataFields="monitor.dataFields"></monitor-chart>
  </div>
</div> 
</template>

<script>
import Datepicker from 'vuejs-datepicker/dist/vuejs-datepicker.esm.js';
import MonitorChart from './MonitorChart.vue';
import monitorsService from '../../services/Monitors.service';

export default {
  name: 'monitor-graph',
  components: {
    Datepicker,
    MonitorChart
  },
  props: {
    monitor: Object,
  },

  data() {
    const navigate = () => {
      this.$router.push({
        name: "details",
        params: {
          id: monitorsService.activeMonitor.id
        },
        query: {
          timestamp__gte: monitorsService.activeMonitor.dateRange.gte,
          timestamp__lte: monitorsService.activeMonitor.dateRange.lte
        }
      });
    }
    return {
      ctx: monitorsService,
      chartData: [],
      interval: null,
      loading: false,
      get startDate() {
        return this.ctx.activeMonitor.dateRange.gte;
      },
      set startDate(date) {
        this.ctx.activeMonitor.dateRange.gte = date;
        navigate();
      },
      get endDate() {
        return this.ctx.activeMonitor.dateRange.lte;
      },
      set endDate(date) {
        this.ctx.activeMonitor.dateRange.lte = date;
        navigate();
      },
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
      this.loadAllEntries();
    }
  },

  computed: {
    dataFields() {
        return this.monitor.datafields;
    },
  },

  methods: {
    checkStartDate(date) {
      // Date must be lte endDate and lte today.
      // true means disabled.
      const gteEnd = date > this.$date(this.endDate).endOf('day').toDate();
      const gteTonight = date > this.$date().endOf('day').toDate();
      return gteEnd || gteTonight;
    },
    checkEndDate(date) {
      // Date must be gte startDate and lte today.
      // true means disabled.
      const lteStart = date < this.$date(this.startDate).startOf('day').toDate();
      const gteTonight = date > this.$date().endOf('day').toDate();
      return lteStart || gteTonight;
    },
    downloadCSV () {
      let path = `${this.$http.options.root}monitors/${this.monitor.id}/entries/csv/`,
        params = {
          fields: Object.keys(this.dataFields).join(','),
          timestamp__gte: this.$date.$defaultFormat(this.monitor.dateRange.gte),
          timestamp__lte: this.$date.$defaultFormat(this.monitor.dateRange.lte),
          sensor: ''
        }

      if(this.sensors[this.monitor.device].length) {
        params.sensor = this.sensors[this.monitor.device][0]
      }

      params = new URLSearchParams(params).toString();
      window.open(`${path}?${params}`)
    },
    async loadAllEntries(){
      if (this.$date(this.monitor.dateRange.lte).unix() >= this.$date().startOf("day").unix()) {
        this.startSync();
      } else {
        this.stopSync();
      }
      this.loading = true;
      await this.monitor.loadEntries();
      this.loading = false;
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
