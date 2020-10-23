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
                    <input type="checkbox" v-model="showInactive" />
                    Inactive monitors
                </label>
              </div>
              <div class="dropdown-item">
                <label class="checkbox">
                    <input type="checkbox" v-model="showPrivate" />
                    Private monitors
                </label>
              </div>
              <div class="dropdown-item">
                <label class="checkbox">
                    <input type="checkbox" v-model="showInside" />
                    Indoor monitors
                </label>
              </div>
              <div class="dropdown-item">
                <label class="checkbox">
                    <input type="checkbox" v-model="showAirNow" />
                    AirNow monitors
                </label>
              </div>
              <hr class="dropdown-divider" />
              <div class="dropdown-item">
                <div>
                  <span class="icon">
                    <span class="fas fa-fw fa-circle has-text-grey-light"></span>
                  </span>
                  <span>SJVAir monitors</span>
                </div>
                <div>
                  <span class="icon">
                    <span class="fas fa-fw fa-square-full has-text-grey-light"></span>
                  </span>
                  <span>Private monitors</span>
                </div>
                <div>
                  <span class="icon">
                    <span class="fal fa-fw fa-circle has-text-black"></span>
                  </span>
                  <span>Inside monitors</span>
                </div>
                <div>
                  <span class="icon">
                    <span class="fas fa-fw fa-hexagon has-text-grey-light"></span>
                  </span>
                  <span>AirNow monitors</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div id="map" :class="mapIsMaximised" class="notranslate" translate="no"></div>
    </div>
    <monitor-detail v-if="activeMonitor" :monitor="activeMonitor" :field="activeField" />
  </div>
</template>

<script>
import _ from 'lodash';
import moment from 'moment';
import tinycolor from 'tinycolor2';

import MonitorDetail from './components/MonitorDetail.vue'
import GoogleMapsInit from './utils/gmaps';
import colors from './utils/colors'

export default {
  name: 'app',

  components: {
    MonitorDetail
  },

  data() {
    return {
      map: null,
      interval: null,
      displayOptionsActive: false,
      activeMonitor: null,
      monitors: {},
      activeField: 'pm25_avg_60',
      showInactive: false,
      showPrivate: true,
      showInside: false,
      showAirNow: true,
      fields: {
        pm25_env: {
          label: "PM 2.5",
          levels: [
            {min: 0, color: colors.green},
            {min: 12, color: colors.yellow},
            {min: 35, color: colors.orange},
            {min: 55, color: colors.red},
            {min: 150, color: colors.purple},
            {min: 250, color: colors.maroon}
          ],
          latest: (monitor) => Math.round(monitor.latest.pm25_env)
        },
        pm25_avg_15: {
          label: "PM 2.5 (15m)",
          levels: [
            {min: 0, color: colors.green},
            {min: 12, color: colors.yellow},
            {min: 35, color: colors.orange},
            {min: 55, color: colors.red},
            {min: 150, color: colors.purple},
            {min: 250, color: colors.maroon}
          ],
          latest: (monitor) => Math.round(monitor.latest.pm25_avg_15)
        },
        pm25_avg_60: {
          label: "PM 2.5 (1h)",
          levels: [
            {min: 0, color: colors.green},
            {min: 12, color: colors.yellow},
            {min: 35, color: colors.orange},
            {min: 55, color: colors.red},
            {min: 150, color: colors.purple},
            {min: 250, color: colors.maroon}
          ],
          latest: (monitor) => Math.round(monitor.latest.pm25_avg_60)
        },
        pm10_env: {
          label: "PM 1.0",
          levels: [
            {min: 0, color: colors.green},
            {min: 12, color: colors.yellow},
            {min: 35, color: colors.orange},
            {min: 55, color: colors.red},
            {min: 150, color: colors.purple},
            {min: 250, color: colors.maroon}
          ],
          latest: (monitor) => Math.round(monitor.latest.pm10_env)
        },
        pm100_env: {
          label: "PM 10",
          levels: [
            {min: 0, color: colors.green},
            {min: 12, color: colors.yellow},
            {min: 35, color: colors.orange},
            {min: 55, color: colors.red},
            {min: 150, color: colors.purple},
            {min: 250, color: colors.maroon}
          ],
          latest: (monitor) => Math.round(monitor.latest.pm100_env)
        }
      }
    }
  },

  async mounted() {
    await GoogleMapsInit();
    this.map = new window.google.maps.Map(
      document.getElementById('map'),
      {
        // Initial location: Fresno, CA
        center: {lat: 36.746841, lng: -119.772591},
        zoom: 8,

        // Controls
        fullscreenControl: false,
        mapTypeControl: false,
        rotateControl: true,
        scaleControl: true,
        streetViewControl: false,
        zoomControl: true
      }
    );
    this.loadMonitors()
      .then(this.setInitialViewport);

    // Reload the monitors every 2 minutes
    this.interval = setInterval(this.loadMonitors, 1000 * 60 * 2);
  },

  destroyed() {
    if(this.interval) {
      clearInterval(this.interval);
      this.interval = null;
    }
  },

  watch: {
    showInactive: function() {
      _.mapValues(this.monitors, this.setMarkerMap);
    },

    showPrivate: function() {
      _.mapValues(this.monitors, this.setMarkerMap);
    },

    showInside: function() {
      _.mapValues(this.monitors, this.setMarkerMap);
    },

    showAirNow: function() {
      _.mapValues(this.monitors, this.setMarkerMap);
    }
  },

  computed: {
    mapIsMaximised() {
      return {
        'is-maximised': _.isNull(this.activeMonitor)
      };
    }
  },

  methods: {
    toggleDisplayOptions() {
      this.displayOptionsActive = !this.displayOptionsActive;
    },

    setMarkerMap(monitor){
      // let checkActive = (this.showInactive && !monitor.is_active) || monitor.is_active;
      let checkActive = this.showInactive || monitor.is_active;
      // let checkSJVAir = (this.showPrivate && !monitor.is_sjvair) || monitor.is_sjvair;
      let checkSJVAir = this.showPrivate || monitor.is_sjvair;
      let checkInside = this.showInside || (monitor.location != 'inside');
      let checkAirNow = this.showAirNow || (monitor.device != 'AirNow');
      let checks = [checkActive, checkSJVAir, checkInside, checkAirNow]
      monitor._marker.setMap(checks.every(Boolean) ? this.map : null);
    },

    getTextColor(color){
      let textColors = {};
      textColors[colors.white] = colors.black;
      textColors[colors.gray] = colors.black;
      textColors[colors.black] = colors.white;

      textColors[colors.green] = colors.black;
      textColors[colors.yellow] = colors.black;
      textColors[colors.orange] = colors.white;
      textColors[colors.red] = colors.white;
      textColors[colors.purple] = colors.white;
      textColors[colors.maroon] = colors.white;

      return _.get(textColors, color, colors.black)
    },

    updateField() {
      _.forEach(this.monitors, (monitor) => {
        monitor._marker.setLabel(
          this.getMonitorLabel(monitor)
        );
      });
    },

    getMonitorLabel(monitor){
      if(_.isNull(monitor.latest) || !monitor.is_active){
        return ' ';
      }
      return _.get(this.fields, this.activeField).latest(monitor).toString();
    },

    getMarkerParams(monitor, field, value){
      let params = {
        border_size: 0,
        fill_color: colors.gray,
        shape: 'square'
      }

      if(monitor.device == 'PurpleAir') {
        params.shape = monitor.is_sjvair ? 'circle' : 'square';
      } else if(monitor.device == 'AirNow') {
        params.shape = 'polygon';
        params.sides = 6;
      }

      if(monitor.location == 'inside'){
        params.border_color = colors.black;
        params.border_size = 2;
      }

      if(monitor.is_active && value != null){
        for(let level of this.fields[field].levels){
          if(value >= level.min){
            params.fill_color = level.color;
          } else {
            break;
          }
        }
      }

      if(params.border_color == undefined){
        params.border_color = tinycolor(params.fill_color).darken(3).toHex();
        params.border_size = 1;
      }

      return params;
    },

    showMonitorDetail(monitorId) {
      this.hideMonitorDetail()
      this.activeMonitor = this.monitors[monitorId];
      this.map.panTo(this.activeMonitor._marker.getPosition());
    },

    hideMonitorDetail() {
      this.activeMonitor = null;
    },

    setInitialViewport() {
      const bounds = new window.google.maps.LatLngBounds();
      _.forIn(this.monitors, (monitor) => {
        bounds.extend(monitor._marker.position)
      })
      this.map.fitBounds(bounds);
    },

    loadMonitors() {
      return this.$http.get('monitors/')
        .then(response => response.json(response))
        .then(response => _.sortBy(response.data, [(monitor) => {
          return monitor.device;
        }]))
        .then(data => {
          _.map(data, (monitor) => {
            monitor.latest.timestamp = moment.utc(monitor.latest.timestamp).local();

            // Ensure we have record of this monitor
            if(_.isUndefined(this.monitors[monitor.id])){
              this.monitors[monitor.id] = {}
            }

            // Update the monitor data
            _.assign(this.monitors[monitor.id], monitor);

            // Create/update the marker
            if(_.isUndefined(this.monitors[monitor.id]._marker)){
              this.monitors[monitor.id]._marker = new window.google.maps.Marker({
                size: new window.google.maps.Size(32, 32),
                origin: window.google.maps.Point(0, 0),
                anchor: new window.google.maps.Point(16, 16),
                label: {
                  color: colors.black,
                  text: ''
                },
                title: this.monitors[monitor.id].name
              });
              this.monitors[monitor.id]._marker.addListener('click', () => {
                this.hideMonitorDetail()
                this.showMonitorDetail(monitor.id);
              });
            }

            let params = this.getMarkerParams(monitor, this.activeField, _.get(monitor.latest, this.activeField))
            this.monitors[monitor.id]._marker.setIcon(
              `/api/1.0/marker.png?${new URLSearchParams(params).toString()}`
            )

            let label = this.monitors[monitor.id]._marker.getLabel();
            label.text = this.getMonitorLabel(monitor)
            label.color = `#${this.getTextColor(params.fill_color)}`
            this.monitors[monitor.id]._marker.setLabel(label);

            this.monitors[monitor.id]._marker.setPosition(
              new window.google.maps.LatLng(
                monitor.position.coordinates[1],
                monitor.position.coordinates[0]
              )
            );

            this.setMarkerMap(this.monitors[monitor.id]);
          });
        })
    }
  }
}
</script>
