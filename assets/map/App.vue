<template>
  <div class="interface">
    <div class="viewport">
      <div class="display-options">
        <div class="dropdown" :class="displayOptionsActive ? 'is-active' : ''">
          <div class="dropdown-trigger">
            <button class="button" aria-haspopup="true" aria-controls="dropdown-display" v-on:click="toggleDisplayOptions">
              <span class="icon">
                <span class="fal fa-cog"></span>
              </span>
              <span class="is-size-7">Display options</span>
              <span class="icon is-small">
                <span class="fas" :class="displayOptionsActive ? 'fa-angle-up' : 'fa-angle-down'" aria-hidden="true"></span>
              </span>
            </button>
          </div>
          <div class="dropdown-menu" id="dropdown-display" role="menu">
            <div class="dropdown-content">
              <div class="dropdown-item">
                <label class="checkbox">
                  <input type="checkbox" v-model="visibility.SJVAirPurple" />
                  <span class="icon">
                    <span class="fas fa-fw fa-circle has-text-success"></span>
                  </span>
                  SJVAir (PurpleAir)
                </label>
              </div>
              <div class="dropdown-item">
                <label class="checkbox">
                  <input type="checkbox" v-model="visibility.SJVAirBAM" />
                  <span class="icon">
                    <span class="fas fa-fw fa-triangle has-text-success"></span>
                  </span>
                  SJVAir (BAM1022)
                </label>
              </div>
              <div class="dropdown-item">
                <label class="checkbox">
                  <input type="checkbox" v-model="visibility.AirNow" />
                  <span class="icon">
                    <span class="fas fa-fw fa-triangle has-text-success"></span>
                  </span>
                  AirNow network
                </label>
              </div>
              <div class="dropdown-item">
                <label class="checkbox">
                  <input type="checkbox" v-model="visibility.PurpleAir" />
                  <span class="icon">
                    <span class="fas fa-fw fa-square has-text-success"></span>
                  </span>
                  PurpleAir network
                </label>
              </div>
              <div class="dropdown-item is-indented">
                <label class="checkbox">
                  <input type="checkbox" v-model="visibility.PurpleAirInside" />
                  <span class="icon">
                    <span class="far fa-fw fa-square has-text-dark"></span>
                  </span>
                  <span>Inside monitors</span>
                </label>
              </div>
              <div class="dropdown-item">
                <label class="checkbox">
                  <input type="checkbox" v-model="visibility.displayInactive" />
                  <span class="icon">
                    <span class="fas fa-fw fa-square has-text-grey-light"></span>
                  </span>
                  <span>Inactive monitors</span>
                </label>
              </div>
            </div>
          </div>
        </div>
      </div>
      <monitor-map></monitor-map>
    </div>
    <router-view></router-view>
  </div>
</template>

<script>
  import Monitor from './models/monitor';

  import MonitorMap from "./components/MonitorMap";

  export default {
    name: 'app',

    components: {
      MonitorMap
    },

    data() {
      return {
        displayOptionsActive: false,
        visibility: Monitor.visibility,
      }
    },

    methods: {
      toggleDisplayOptions() {
        this.displayOptionsActive = !this.displayOptionsActive;
      },
    }
  }
</script>
