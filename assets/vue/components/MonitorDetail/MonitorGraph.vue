<script setup lang="ts">
import { inject, onBeforeUnmount, onMounted, Ref, ref, toRefs, watch } from "vue";
import MonitorChart from "./MonitorChart.vue";
import MonitorDataControl from "./MonitorDataControl.vue";
import { dateUtil } from "../../utils";

import type { Monitor } from "../../models/Monitor";
import type { MonitorsServiceMono } from "../../services";
import type { ChartDataArray } from "../../types";

const monitorsService = inject<MonitorsServiceMono>("MonitorsService")!;
const props = defineProps<{ monitor: Monitor }>();
const { monitor } = toRefs(props);
let chartData: Ref<ChartDataArray> = ref([]);
let interval: number = 0;
let loading: Ref<boolean> = ref(false);

async function loadAllEntries(){
  if (dateUtil.dayjs(monitorsService.dateRange.end).unix() >= dateUtil.dayjs().startOf("day").unix()) {
    startSync();
  } else {
    stopSync();
  }
  loading.value = true;

  const data = await monitorsService.fetchChartData(monitor.value.data.id, monitorsService.dateRange);

  if (data) {
    chartData.value = data;
  }
  loading.value = false;
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

watch(
  () => monitor.value,
  async () => await loadAllEntries()
);

onMounted(async () => {
  await loadAllEntries();
  startSync();
});

onBeforeUnmount(() => {
  if(interval) {
    stopSync();
  }
});
</script>

<template>
<div v-if="monitor" class="monitor-graph">
  <monitor-data-control @loadAll="loadAllEntries"></monitor-data-control>
  <div :class="{ 'is-hidden': loading }" class="chart">
    <monitor-chart :chartData="chartData" ></monitor-chart>
  </div>
  <h1 v-if="loading" class="loading-notice">Fetching Data...</h1>
</div>
</template>

