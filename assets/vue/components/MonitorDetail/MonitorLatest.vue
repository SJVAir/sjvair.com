<script setup lang="ts">
import { computed, toRefs } from "vue";
import type { Monitor } from "../../models";
import { dateUtil } from "../../utils";

const { monitor } = toRefs(defineProps<{ monitor: Monitor }>());
const timesince = computed(() => {
  if (Object.keys(monitor.value.data.latest).length > 1) {
    return dateUtil.dayjs(monitor.value.data.latest.timestamp).fromNow();
  }

  return 'Never';
});
//export default {
//  name: "monitor-latest",
//  props: ["monitor"],
//  data() {
//    return {
//      fields: Monitor.fields
//    };
//  },
//  computed: {
//    timesince() {
//      if(Object.keys(this.monitor.latest).length > 1){
//        return this.monitor.latest.timestamp.fromNow();
//      }
//      return 'Never';
//    },
//  }
//}
</script>

<template>
  <table class="table is-striped is-fullwidth is-bordered latest-stats">
    <thead class="has-background-light">
      <tr>
        <th rowspan="2">
          <div class="is-size-7 has-text-grey has-text-weight-normal">Last updated</div>
          <div :class="monitor.data.is_active ? 'has-text-success' : 'has-text-danger'">{{ timesince }}</div>
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
      <tr v-if="monitor.data.latest.pm10">
        <th>PM 1.0</th>
        <td class="has-text-centered">{{ monitor.monitorFields.pm10.latest(monitor) }}</td>
        <td class="has-text-centered">-</td>
        <td class="has-text-centered">-</td>
      </tr>
      <tr>
        <th>PM 2.5</th>
        <td class="has-text-centered">{{ monitor.monitorFields.pm25.latest(monitor) }}</td>
        <td class="has-text-centered">{{ monitor.monitorFields.pm25_avg_15.latest(monitor) }}</td>
        <td class="has-text-centered">{{ monitor.monitorFields.pm25_avg_60.latest(monitor) }}</td>
      </tr>
      <tr v-f="monitor.data.latest.pm100">
        <th>PM 10.0</th>
        <td class="has-text-centered">{{ monitor.monitorFields.pm100.latest(monitor) }}</td>
        <td class="has-text-centered">-</td>
        <td class="has-text-centered">-</td>
      </tr>
    </tbody>
  </table>
</template>

