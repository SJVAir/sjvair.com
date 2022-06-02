<script setup lang="ts">
import { computed, toRefs } from "@vue/reactivity";
import MonitorSubscription from "../MonitorSubscription.vue";
import { Monitor } from "../../models/Monitor";

const props = defineProps<{ monitor: Monitor }>();
const { monitor } = toRefs(props);

const location = computed(() => {
  if (monitor.value) {
    return monitor.value.data.location[0].toUpperCase() + monitor.value.data.location.slice(1).toLowerCase();
  }
  return "";
})
</script>

<template>
  <div class="monitor-header is-flex is-justify-content-space-evenly is-align-items-center is-flex-direction-column">
    <p class="monitor-name is-flex-grow-1">{{ monitor.data.name }}</p>
    <ul class="is-flex is-justify-content-space-evenly is-align-items-center">
      <li v-if="monitor.data.is_sjvair">
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
          <span>{{ monitor.data.device }}</span>
        </span>
      </li>
      <li v-if="monitor.data.county">
        <span class="tag is-light">
          <span class="icon">
            <span class="fal fa-map-marker-alt has-text-grey"></span>
          </span>
          <span>{{ monitor.data.county }}</span>
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
    <monitor-subscription></monitor-subscription>
  </div>
</template>

<style>
.monitor-header {
  padding: var(--column-gap);
}

.monitor-header ul {
  width: 100%;
  margin-bottom: .5em;
}

.monitor-name {
  font-size: var(--size-5);
  font-weight: bold;
}
</style>
