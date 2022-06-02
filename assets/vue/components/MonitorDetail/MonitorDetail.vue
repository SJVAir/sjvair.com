<script setup lang="ts">
import { inject, onBeforeUnmount, Ref, ref, watch, watchEffect } from "vue";
import { useRoute, useRouter } from "vue-router";

import MonitorChart from "./MonitorChart.vue";
import MonitorDataControl from "./MonitorDataControl.vue";
import MonitorInfo from "./MonitorInfo.vue";
import MonitorLatest from "./MonitorLatest.vue";
import { dateUtil } from "../../modules";

import type { MonitorsService } from "../../services";
import type { ChartDataArray } from "../../types";

const monitorsService = inject<MonitorsService>("MonitorsService")!;
const route = useRoute();
const router = useRouter();
let chartData: Ref<ChartDataArray> = ref([]);
let interval: number = 0;
let loading: Ref<boolean> = ref(false);

function close() {
  router.replace("/");
}


async function loadAllEntries(){
  if (dateUtil.dayjs(monitorsService.dateRange.end).unix() >= dateUtil.dayjs().startOf("day").unix()) {
    startSync();
  } else {
    stopSync();
  }
  loading.value = true;

  const data = await monitorsService.fetchChartData(monitorsService.activeMonitor!.data.id, monitorsService.dateRange);

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
  () => monitorsService.activeMonitor,
  async () => {
    if (monitorsService.activeMonitor) {
      await loadAllEntries();
    }
  }
);

watchEffect(() => route.params.id && monitorsService.setActiveMonitor(route.params.id as string));

onBeforeUnmount(() => {
  if(interval) {
    stopSync();
  }
  monitorsService.clearActiveMonitor();
});


</script>

<template>
<div v-if="monitorsService.activeMonitor" class="monitor-detail">
  <div class="container is-fluid">
    <span class="monitor-close" v-on:click="close">
      <span class="far fa-window-close"></span>
    </span>
    <div class="columns">
      <div class="column monitor-graph is-two-thirds">
        <h1 v-if="loading" class="loading-notice">Fetching Data...</h1>
        <div :class="{ 'is-hidden': loading }" class="chart">
          <monitor-chart :chartData="chartData" ></monitor-chart>
        </div>
      </div>
      <div v-if="monitorsService.activeMonitor.data.latest" class="column is-one-third">
        <monitor-info :monitor="monitorsService.activeMonitor"></monitor-info>
        <monitor-data-control @loadAll="loadAllEntries"></monitor-data-control>
        <monitor-latest :monitor="monitorsService.activeMonitor"></monitor-latest>
      </div>
    </div>
  </div>
</div>
</template>

<style scoped>
.loading-notice {
  font-size: 1.25em;
  font-weight: 800;
  text-align: center;
  margin-top: 5em;
}

.monitor-detail {
  padding-bottom: 1em;
  background-color: #fff;
  width: 100%;
}

.monitor-close {
  color: var(--grey-light);
  cursor: pointer;
  float: right;
  padding: var(--column-gap);
  font-size: 1.5em;
}
</style>
