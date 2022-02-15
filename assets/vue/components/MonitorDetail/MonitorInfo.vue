<script setup lang="ts">
import { computed } from "@vue/reactivity";
import { Monitor } from "../../models/Monitor";

const props = defineProps<{ monitor: Monitor }>();
const { monitor } = props;

const location = computed(() => {
  if (monitor) {
    return monitor.data.location[0].toUpperCase() + monitor.data.location.slice(1).toLowerCase();
  }
  return "";
})

//export default {
//  name: "monitor-info",
//  props: ["monitor"],
//  computed: {
//    location() {
//      if (this.monitor) {
//        return this.monitor.location[0].toUpperCase() + this.monitor.location.slice(1).toLowerCase();
//      } else {
//        return "";
//      }
//    }
//  }
//}
</script>

<template>
  <div class="monitor-header">
    <ul class="is-inline">
      <li class="monitor-name">{{ monitor.data.name }}</li>
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
  </div>
</template>
