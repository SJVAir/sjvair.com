<script setup lang="ts">
import { inject, onBeforeUnmount, onMounted, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import MonitorGraph from "./MonitorGraph.vue";
import MonitorInfo from "./MonitorInfo.vue";
import MonitorLatest from "./MonitorLatest.vue";

import type { MonitorsService } from "../../services";


const monitorsService = inject<MonitorsService>("MonitorsService")!;
const route = useRoute();
const router = useRouter();

//let cachedQuery = {
//  timestamp__gte: null,
//  timestamp__lte: null
//};
//
//function cacheQuery() {
//  if (route.query) {
//    cachedQuery = {
//      timestamp__lte: route.query.timestamp__lte,
//      timestamp__gte: route.query.timestamp__gte
//    };
//    router.replace({ query: undefined })
//      .catch(e => {
//        if (e.name !== "NavigationDuplicated") {
//          throw e;
//        }
//      });
//  }
//}

//function setActiveMonitor() {
//  monitorsService.setActiveMonitor(route.params.id as string, {
//    startDate: cachedQuery.timestamp__gte,
//    endDate: cachedQuery.timestamp__lte
//  });
//}

function close() {
  router.replace("/");
}

watch(
  () => route.params.id as string,
  id => monitorsService.setActiveMonitor(id)
);

onMounted(() => {
  if (route.params.id) {
    monitorsService.setActiveMonitor(route.params.id as string);
  }
});

onBeforeUnmount(() => monitorsService.clearActiveMonitor());

</script>

<template>
<div v-if="monitorsService.activeMonitor" class="monitor-detail">
  <div class="container is-fluid">
    <span class="monitor-close" v-on:click="close">
      <span class="far fa-window-close"></span>
    </span>
    <monitor-info :monitor="monitorsService.activeMonitor"></monitor-info>
    <div class="columns">
      <div class="column">
        <monitor-graph :monitor="monitorsService.activeMonitor" />
      </div>
      <div v-if="monitorsService.activeMonitor.data.latest" class="column is-one-third">
        <monitor-latest :monitor="monitorsService.activeMonitor"></monitor-latest>
      </div>
    </div>
  </div>
</div>
</template>

