<template>
<div v-if="monitor" class="monitor-detail">
  <div class="container is-fluid">
    <span class="monitor-close" v-on:click="on_close">
      <span class="far fa-window-close"></span>
    </span>
    <div class="monitor-header">
      <ul class="is-inline">
        <li class="monitor-name">{{ monitor.name }}</li>
        <li v-if="monitor.is_sjvair">
          <span class="tag is-info is-light">
            <span class="icon">
              <span class="fal fa-lungs has-text-info"></span>
            </span>
            <span>SJVAir</span>
          </span>
        </li>
        <li>
          <span class="tag is-light">
            <span class="icon">
              <span class="fal fa-router has-text-grey"></span>
            </span>
            <span>{{ monitor.device }}</span>
          </span>
        </li>
        <li v-if="monitor.county">
          <span class="tag is-light">
            <span class="icon">
              <span class="fal fa-map-marker-alt has-text-grey"></span>
            </span>
            <span>{{ monitor.county }}</span>
          </span>
        </li>
        <li>
          <span class="tag is-light">
            <span class="icon">
              <span class="fal fa-location has-text-grey"></span>
            </span>
            <span>{{ location }}</span>
          </span>
        </li>
      </ul>
    </div>
    <div class="columns">
      <div class="column">
        <monitor-graph :monitor="monitor" />
      </div>
      <div v-if="monitor.latest" class="column is-one-third">
        <table class="table is-striped is-fullwidth is-bordered latest-stats">
          <thead class="has-background-light">
            <tr>
              <th rowspan="2">
                <div class="is-size-7 has-text-grey has-text-weight-normal">Last updated</div>
                <div :class="monitor.is_active ? 'has-text-success' : 'has-text-danger'">{{ timesince }}</div>
              </th>
              <th colspan="3" class="is-size-7 has-text-centered">Latest Averages</th>
            </tr>
            <tr>
              <th class="is-size-7 has-text-centered">2m</th>
              <th class="is-size-7 has-text-centered">15m</th>
              <th class="is-size-7 has-text-centered">60m</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="monitor.latest.pm10_env">
              <th>PM 1.0</th>
              <td class="has-text-centered">{{ $parent.fields.pm10_env.latest(monitor) }}</td>
              <td class="has-text-centered">-</td>
              <td class="has-text-centered">-</td>
            </tr>
            <tr>
              <th>PM 2.5</th>
              <td class="has-text-centered">{{ $parent.fields.pm25_env.latest(monitor) }}</td>
              <td class="has-text-centered">{{ $parent.fields.pm25_avg_15.latest(monitor) }}</td>
              <td class="has-text-centered">{{ $parent.fields.pm25_avg_60.latest(monitor) }}</td>
            </tr>
            <tr v-f="monitor.latest.pm100_env">
              <th>PM 10.0</th>
              <td class="has-text-centered">{{ $parent.fields.pm100_env.latest(monitor) }}</td>
              <td class="has-text-centered">-</td>
              <td class="has-text-centered">-</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>
</template>

<script>
import MonitorGraph from './MonitorGraph';
import monitorsService from '../services/Monitors.service';

export default {
  name: 'monitor-detail',

  components: {
    MonitorGraph
  },

  data() {
    return {
      ctx: monitorsService
    }
  },

  computed: {
    monitor() { return this.ctx.activeMonitor; },
    params() { return this.$route.params; },
    query() { return this.$route.query; },
    timesince() {
      if(Object.keys(this.monitor.latest).length > 1){
        return this.monitor.latest.timestamp.fromNow();
      }
      return 'Never';
    },

    location() {
      return !!this.monitor && this.monitor.location[0].toUpperCase() + this.monitor.location.slice(1).toLowerCase();
    }
  },

  watch: {
    params: function() {
      this.setActiveMonitor();
    },
  },

  mounted() {
    if (this.params.id) {
      this.setActiveMonitor();
    }
  },

  methods: {
    setActiveMonitor() {
      this.ctx.setActiveMonitor(this.params.id, {
        startDate: this.query.timestamp__gte,
        endDate: this.query.timestamp__lte
      });
    },
    on_close() {
      monitorsService.clearActiveMonitor();
      this.$router.replace("/");
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
