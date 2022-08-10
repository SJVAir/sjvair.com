<script setup lang="ts">
import { reactive, Ref, ref } from "vue";
import type { IDisplayOptionsExports, ILeafletTileLayer, IMonitorVisibility, IOverlayTileset } from "../types";

const mapTilesets: Array<ILeafletTileLayer> = [
  {
    label: "Streets",
    isDefault: true,
    urlTemplate: "https://api.maptiler.com/maps/streets/256/{z}/{x}/{y}.png?key={apiKey}",
    options: {
      maxZoom: 19,
      apiKey: import.meta.env.VITE_MAPTILER_KEY,
      attribution: '<a href="https://www.maptiler.com/copyright/" target="_blank">&copy; MapTiler</a> <a href="https://www.openstreetmap.org/copyright" target="_blank">&copy; OpenStreetMap contributors</a>',
    }
  },
  {
    label: "Satellite Hybrid",
    urlTemplate: "https://api.maptiler.com/maps/hybrid/{z}/{x}/{y}.jpg?key={apiKey}",
    options: {
      maxZoom: 19,
      apiKey: import.meta.env.VITE_MAPTILER_KEY,
      attribution: '<a href="https://www.maptiler.com/copyright/" target="_blank">&copy; MapTiler</a> <a href="https://www.openstreetmap.org/copyright" target="_blank">&copy; OpenStreetMap contributors</a>',
    }
  },
  {
    label: "Topographique",
    urlTemplate: "https://api.maptiler.com/maps/topographique/{z}/{x}/{y}.png?key={apiKey}",
    options: {
      maxZoom: 19,
      apiKey: import.meta.env.VITE_MAPTILER_KEY,
      attribution: '<a href="https://www.maptiler.com/copyright/" target="_blank">&copy; MapTiler</a> <a href="https://www.openstreetmap.org/copyright" target="_blank">&copy; OpenStreetMap contributors</a>'
    }
  }
];

const displayOptionsActive: Ref<boolean> = ref(false);

// @ts-ignore: Cannot find name 'structuredClone' - typeings included by TS4.8
let mapTileset: ILeafletTileLayer = reactive(structuredClone(mapTilesets.find(t => t.isDefault)!));

const overlayTilesets: Array<IOverlayTileset> = reactive([
  {
    icon: "fa-wind",
    isChecked: false,
    label: "Wind",
    urlTemplate: "https://{s}.tile.openweathermap.org/map/wind/{z}/{x}/{y}.png?appid={apiKey}",
    options: {
      maxZoom: 19,
      attribution: 'Map data &copy; <a href="http://openweathermap.org">OpenWeatherMap</a>',
      apiKey: import.meta.env.VITE_OPENWEATHERMAP_KEY,
      opacity: 0.3,
      zIndex: 11
    }
  },
  {
    icon: "fa-cloud",
    isChecked: false,
    label: "Clouds",
    urlTemplate: "https://{s}.tile.openweathermap.org/map/clouds/{z}/{x}/{y}.png?appid={apiKey}",
    options: {
      maxZoom: 19,
      attribution: 'Map data &copy; <a href="http://openweathermap.org">OpenWeatherMap</a>',
      apiKey: import.meta.env.VITE_OPENWEATHERMAP_KEY,
      opacity: 0.5,
      zIndex: 12
    }
  }
]);

const visibility: IMonitorVisibility = reactive({
  SJVAirPurple: {
    icon: "fa-circle",
    isChecked: true,
    label: "SJVAir (PurpleAir)"
  },
  SJVAirBAM: {
    icon: "fa-triangle",
    isChecked: true,
    label: "SJVAir (BAM1022)"
  },
  AirNow: {
    icon: "fa-triangle",
    isChecked: true,
    label: "AirNow network"
  },
  PurpleAir: {
    icon: "fa-square",
    isChecked: true,
    label: "PurpleAir network"
  },
  PurpleAirInside: {
    containerClass: "is-indented",
    icon: "fa-square",
    isChecked: false,
    label: "Inside monitors"
  },
  displayInactive: {
    icon: "fa-square",
    isChecked: false,
    label: "Inactive monitors"
  },
});

function toggleDisplayOptions() {
  displayOptionsActive.value = !displayOptionsActive.value;
}

defineExpose<IDisplayOptionsExports>({ mapTileset, overlayTilesets, visibility });

function updateIt(tileset: ILeafletTileLayer) {
  Object.assign(mapTileset, tileset);
}

</script>

<template>
  <div class="display-options">
    <div class="dropdown" :class="displayOptionsActive ? 'is-active' : ''">
      <div class="dropdown-trigger">
        <button class="button" aria-haspopup="true" aria-controls="dropdown-display" v-on:click="toggleDisplayOptions">
          <span class="icon">
            <span class="fal fa-cog"></span>
          </span>
          <span class="is-size-7">Display Options</span>
          <span class="icon is-small">
            <span class="fas" :class="displayOptionsActive ? 'fa-angle-up' : 'fa-angle-down'" aria-hidden="true"></span>
          </span>
        </button>
      </div>
      <div class="dropdown-menu" id="dropdown-display" role="menu">
        <div class="dropdown-content">
          <div class="columns">

            <div class="map-visibility column">
              <p class="display-group-label">Visibility</p>
              <div v-for="deviceType in visibility" class="dropdown-item" :class="deviceType.containerClass">
                <label class="checkbox">
                  <input type="checkbox" v-model="deviceType.isChecked" />
                  <span class="icon">
                    <span class="fas fa-fw has-text-success" :class="deviceType.icon"></span>
                  </span>
                  {{ deviceType.label }}
                </label>
              </div>
            </div>

            <div class="map-layers column">

              <div class="map-overlays">
                <p class="display-group-label">Map Overlays</p>
                <div v-for="overlay in overlayTilesets" class="dropdown-item" :class="overlay.containerClass">
                  <label class="checkbox">
                    <input type="checkbox" v-model="overlay.isChecked" />
                    <span class="icon">
                      <span class="fas fa-fw has-text-success" :class="overlay.icon"></span>
                    </span>
                    {{ overlay.label }}
                  </label>
                </div>
              </div>

              <div class="map-tiles">
                <p class="display-group-label">Map Tiles</p>
                <div v-for="tileset in mapTilesets" class="dropdown-item">
                  <label class="checkbox">
                    <input type="radio" :checked="tileset.isDefault" name="tiles" @change.preventDefault="updateIt(tileset)" />
                    {{ tileset.label }}
                  </label>
                </div>
              </div>

            </div>

          </div>

        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dropdown-menu {
  white-space: nowrap;
}
.display-options {
  float: left;
  position: relative;
  margin: .5rem 0 -100% 2.5rem;
  padding: .5rem 1rem;
  z-index: 9999;
}

.dropdown-content {
  overflow-y: auto;
  overflow-x: hidden;
  max-height: 300px;
}

.dropdown-content .columns {
  margin: 0 0 0 .5em;
}

.dropdown-item.is-indented {
  padding-left: var(--gap);
}

.display-group-label {
  text-decoration: underline;
  font-weight: bold;
}

.map-overlays, .map-tiles {
  height: 50%;
}
</style>
