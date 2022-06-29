<script setup lang="ts">
import { ref } from "vue";
import MonitorMap from "./components/MonitorMap.vue";
import DisplayOptions from "./components/DisplayOptions.vue";
//import { DisplayOptions } from "./models";

const displayOptions = ref<InstanceType<typeof DisplayOptions> | null>(null);

</script>

<template >
  <div class="interface">
    <div class="viewport">
      <DisplayOptions ref="displayOptions"/>
      <MonitorMap :map-tileset="displayOptions?.mapTileset" :overlay-tilesets="displayOptions?.overlayTilesets" :visibility="displayOptions?.visibility"/>
    </div>
    <router-view></router-view>
  </div>
</template>

