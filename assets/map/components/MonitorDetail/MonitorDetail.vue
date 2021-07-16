<template>
<div v-if="monitor" class="monitor-detail">
  <div class="container is-fluid">
    <span class="monitor-close" v-on:click="close">
      <span class="far fa-window-close"></span>
    </span>
    <monitor-info :monitor="monitor"></monitor-info>
    <div class="columns">
      <div class="column">
        <monitor-graph :monitor="monitor" />
      </div>
      <div v-if="monitor.latest" class="column is-one-third">
        <monitor-latest :monitor="monitor"></monitor-latest>
      </div>
    </div>
  </div>
</div>
</template>

<script>
import MonitorGraph from './MonitorGraph';
import MonitorInfo from './MonitorInfo';
import MonitorLatest from './MonitorLatest';
import monitorsService from '../../services/Monitors.service';

export default {
  name: 'monitor-detail',

  components: {
    MonitorGraph,
    MonitorInfo,
    MonitorLatest
  },

  data() {
    return {
      ctx: monitorsService,
      cachedQuery: {
        timestamp__gte: null,
        timestamp__lte: null
      }
    }
  },

  computed: {
    monitor() { return this.ctx.activeMonitor; },
    params() { return this.$route.params; },
    query() { return this.$route.query; },
  },

  watch: {
    params: function() {
      this.setActiveMonitor();
    },
    query: function() {
      this.cacheQuery();
    }
  },

  mounted() {
    this.cacheQuery();

    if (this.params.id) {
      this.setActiveMonitor();
    }
  },

  beforeDestroy() {
    monitorsService.clearActiveMonitor();
    this.$router.replace("/");
  },

  methods: {
    cacheQuery() {
      if (this.query) {
        this.cachedQuery = Object.assign({}, this.query);
        this.$router.replace({ query: null })
          .catch(e => {
            if (e.name !== "NavigationDuplicated") {
              throw e;
            }
          });
      }
    },
    setActiveMonitor() {
      this.ctx.setActiveMonitor(this.params.id, {
        startDate: this.cachedQuery.timestamp__gte,
        endDate: this.cachedQuery.timestamp__lte
      });
    },

    close() {
      this.$destroy();
    },

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
  }
}
</script>
