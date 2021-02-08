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
                  <input type="checkbox" v-model="ctx.flags.SJVAirPurple" />
                  <span class="icon">
                    <span class="fas fa-fw fa-circle has-text-success"></span>
                  </span>
                  SJVAir (PurpleAir)
                </label>
              </div>
              <div class="dropdown-item is-indented">
                <label class="checkbox">
                  <input type="checkbox" v-model="ctx.flags.SJVAirInactive" />
                  <span class="icon">
                    <span class="fas fa-fw fa-circle has-text-grey-light"></span>
                  </span>
                  <span>Inactive monitors</span>
                </label>
              </div>
              <div class="dropdown-item">
                <label class="checkbox">
                  <input type="checkbox" v-model="ctx.flags.SJVAirBAM" />
                  <span class="icon">
                    <span class="fas fa-fw fa-triangle has-text-success"></span>
                  </span>
                  SJVAir (BAM1022)
                </label>
              </div>
              <div class="dropdown-item">
                <label class="checkbox">
                  <input type="checkbox" v-model="ctx.flags.PurpleAir" />
                  <span class="icon">
                    <span class="fas fa-fw fa-square has-text-success"></span>
                  </span>
                  PurpleAir network
                </label>
              </div>
              <div class="dropdown-item is-indented">
                <label class="checkbox">
                  <input type="checkbox" v-model="ctx.flags.PurpleAirInside" />
                  <span class="icon">
                    <span class="far fa-fw fa-square has-text-dark"></span>
                  </span>
                  <span>Inside monitors</span>
                </label>
              </div>
              <div class="dropdown-item">
                <label class="checkbox">
                  <input type="checkbox" v-model="ctx.flags.AirNow" />
                  <span class="icon">
                    <span class="fas fa-fw fa-hexagon has-text-success"></span>
                  </span>
                  AirNow network
                </label>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div id="map" :class="mapIsMaximised" class="notranslate" translate="no"></div>
    </div>
    <monitor-detail v-if="ctx.activeMonitor" :monitor="ctx.activeMonitor" />
  </div>
</template>

<script>
  import MonitorDetail from './components/MonitorDetail.vue';
  import AppController from "./controllers/App.controller";

  export default {
    name: 'app',

    components: {
      MonitorDetail
    },

    data() {
      return {
        ctx: AppController,
        fields: AppController.monitorFields,
        interval: null,
        displayOptionsActive: false,
      }
    },

    async mounted() {
      await this.ctx.init();
      console.log(this.fields);
      // Reload the monitors every 2 minutes
      this.interval = setInterval(this.ctx.loadMonitors, 1000 * 60 * 2);
    },

    destroyed() {
      if(this.interval) {
        clearInterval(this.interval);
        this.interval = null;
      }
    },

    watch: {
      "ctx.flags.SJVAirPurple": function() {
        this.ctx.updateVisibility();
      },
      "ctx.flags.SJVAirInactive": function() {
        this.ctx.updateVisibility();
      },
      "ctx.flags.SJVAirBAM": function() {
        this.ctx.updateVisibility();
      },
      "ctx.flags.PurpleAir": function() {
        this.ctx.updateVisibility();
      },
      "ctx.flags.PurpleAirInside": function() {
        this.ctx.updateVisibility();
      },
      "ctx.flags.AirNow": function() {
        this.ctx.updateVisibility();
      }
    },

    computed: {
      mapIsMaximised() {
        return {
          'is-maximised': (this.ctx.activeMonitor === null)
        };
      }
    },

    methods: {
      toggleDisplayOptions() {
        this.displayOptionsActive = !this.displayOptionsActive;
      },
    }
  }
</script>
