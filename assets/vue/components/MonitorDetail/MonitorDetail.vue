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

//export default {
//  name: 'monitor-detail',
//
//  components: {
//    MonitorGraph,
//    MonitorInfo,
//    MonitorLatest
//  },
//
//  data() {
//    return {
//      ctx: MonitorsService,
//      cachedQuery: {
//        timestamp__gte: null,
//        timestamp__lte: null
//      }
//    }
//  },
//
//  computed: {
//    monitor() { return this.ctx.activeMonitor; },
//    params() { return this.$route.params; },
//    query() { return this.$route.query; },
//  },
//
//  watch: {
//    params: function() {
//      this.setActiveMonitor();
//    },
//    query: function() {
//      this.cacheQuery();
//    }
//  },
//
//  mounted() {
//    this.cacheQuery();
//
//    if (this.params.id) {
//      this.setActiveMonitor();
//    }
//  },
//
//  beforeDestroy() {
//    MonitorsService.clearActiveMonitor();
//    this.$router.replace("/");
//  },
//
//  methods: {
//    cacheQuery() {
//      if (this.query) {
//        this.cachedQuery = Object.assign({}, this.query);
//        this.$router.replace({ query: null })
//          .catch(e => {
//            if (e.name !== "NavigationDuplicated") {
//              throw e;
//            }
//          });
//      }
//    },
//    setActiveMonitor() {
//      this.ctx.setActiveMonitor(this.params.id, {
//        startDate: this.cachedQuery.timestamp__gte,
//        endDate: this.cachedQuery.timestamp__lte
//      });
//    },
//
//    close() {
//      this.$destroy();
//    },

    // [ Do we need | How can we use ] this?
    //aqi_label(aqi){
    //  aqi = parseFloat(aqi)
    //  if (aqi <= 50) {
    //    return 'Good';
    //  }
    //  else if (aqi > 50 && aqi <= 100){
    //    return 'Moderate';
    //  }
    //  else if (aqi > 100 && aqi <= 150){
    //    return 'Unhealthy for Sensitive Groups'
    //  }
    //  else if (aqi > 150 && aqi <= 200){
    //    return 'Unhealthy';
    //  }
    //  else if (aqi > 200 && aqi <= 300){
    //    return 'Very Unhealthy';
    //  }
    //  else if (aqi > 300 && aqi <= 400){
    //    return 'Hazardous';
    //  }
    //  else if (aqi > 400 && aqi <= 500){
    //    return 'Hazardous';
    //  }
    //  return 'Out of Range';
    //}
//  }
//}
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

