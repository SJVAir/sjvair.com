<template>
<div v-if="monitor" class="monitor-graph">
  <monitor-data-control @loadAll="loadAllEntries"></monitor-data-control>
  <div :class="{ 'is-hidden': loading }" class="chart">
    <monitor-chart :chartData="monitor.chartData" :dataFields="monitor.dataFields"></monitor-chart>
  </div>
  <h1 v-if="loading" class="loading-notice">Fetching Data...</h1>
</div>
</template>

<script>
import MonitorChart from './MonitorChart.vue';
import MonitorDataControl from './MonitorDataControl';
import monitorsService from '../../services/Monitors.service';

export default {
  name: 'monitor-graph',
  components: {
    MonitorChart,
    MonitorDataControl
  },
  props: {
    monitor: Object,
  },

  data() {
    return {
      ctx: monitorsService,
      chartData: [],
      interval: null,
      loading: false,
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
        return this.monitor.dataFields;
    },
  },

  methods: {
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
