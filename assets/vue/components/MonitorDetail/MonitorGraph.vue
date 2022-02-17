<script setup lang="ts">
import { inject, onBeforeUnmount, onMounted, toRefs } from "vue";
import MonitorChart from "./MonitorChart.vue";
import MonitorDataControl from "./MonitorDataControl.vue";
import { dateUtil } from "../../utils";

import type { Monitor } from "../../models/Monitor";
import type { MonitorsService } from "../../services";
import type { ChartDataArray } from "../../types";

const monitorsService = inject<MonitorsService>("MonitorsService")!;
const { monitor } = toRefs(defineProps<{ monitor: Monitor }>());
let chartData: ChartDataArray;
let interval: number = 0;
let loading: boolean = false;

async function loadAllEntries(){
  if (dateUtil.dayjs(monitorsService.dateRange.end).unix() >= dateUtil.dayjs().startOf("day").unix()) {
    startSync();
  } else {
    stopSync();
  }
  loading = true;

  const data = await monitorsService.fetchChartData(monitor.value.data.id);

  if (data) {
    chartData = data;
  }
  loading = false;
}

function startSync() {
  if (!interval) {
    interval = setInterval(loadAllEntries, 1000 * 60 * 2);
  }
}

function stopSync() {
  if (interval) {
    clearInterval(interval);
    interval = 0;
  }
}

onMounted(async () => {
  await loadAllEntries();
  startSync();
});

onBeforeUnmount(() => {
  if(interval) {
    stopSync();
  }
});
//export default {
//  name: 'monitor-graph',
//  components: {
//    MonitorChart,
//    MonitorDataControl
//  },
//  props: {
//    monitor: Object,
//  },
//
//  data() {
//    return {
//      ctx: monitorsService,
//      chartData: [],
//      interval: null,
//      loading: false,
//    }
//  },
//
//  async mounted() {
//    this.loadAllEntries();
//    this.startSync();
//  },
//
//  destroyed() {
//    if(this.interval) {
//      this.stopSync();
//    }
//  },
//
//  watch: {
//    monitor: async function() {
//      this.loadAllEntries();
//    }
//  },
//
//  computed: {
//    dataFields() {
//        return this.monitor.dataFields;
//    },
//  },
//
//  methods: {
//    async loadAllEntries(){
//      if (this.$date(this.monitor.dateRange.lte).unix() >= this.$date().startOf("day").unix()) {
//        this.startSync();
//      } else {
//        this.stopSync();
//      }
//      this.loading = true;
//      await this.monitor.loadEntries();
//      this.loading = false;
//    },
//
//    startSync() {
//      if (!this.interval) {
//        this.interval = setInterval(this.loadAllEntries, 1000 * 60 * 2);
//      }
//    },
//
//    stopSync() {
//      if (this.interval) {
//        clearInterval(this.interval);
//        this.interval = null;
//      }
//    }
//  }
//}
</script>

<template>
<div v-if="monitor" class="monitor-graph">
  <monitor-data-control @loadAll="loadAllEntries"></monitor-data-control>
  <div :class="{ 'is-hidden': loading }" class="chart">
    <monitor-chart :chartData="chartData" :dataFields="monitor.dataFields"></monitor-chart>
  </div>
  <h1 v-if="loading" class="loading-notice">Fetching Data...</h1>
</div>
</template>

