<template>
  <div class="interface">
    <div class="viewport">
      <div class="display-options">
        <div>
          <label class="checkbox">
              <input type="checkbox" v-model="showInactive" />
              Show inactive monitors
          </label>
        </div>
        <div>
          <label class="checkbox">
              <input type="checkbox" v-model="showPrivate" />
              Show private monitors
          </label>
        </div>
        <hr />
        <ul class="fa-ul legend">
          <li>
            <span class="fa-stack fa-li">
              <span class="fas fa-circle fa-stack-1x has-text-grey-lighter"></span>
              <span class="fal fa-circle fa-stack-1x"></span>
            </span>
            <span>SJVAir monitors</span>
          </li>
          <li>
            <span class="fa-stack fa-li">
              <span class="fas fa-square-full fa-stack-1x has-text-grey-lighter"></span>
              <span class="fal fa-square-full fa-stack-1x"></span>
            </span>
            <span>Private monitors</span>
          </li>
        </ul>
      </div>
      <div id="map" :class="mapIsMaximised"></div>
    </div>
    <monitor-detail v-if="activeMonitor" :monitor="activeMonitor" :field="activeField" />
  </div>
</template>

<script>
import _ from 'lodash';
import moment from 'moment';

import MonitorDetail from './components/MonitorDetail.vue'
import GoogleMapsInit from './utils/gmaps';

export default {
  name: 'app',

  components: {
    MonitorDetail
  },

  data() {
    return {
      map: null,
      interval: null,
      activeMonitor: null,
      monitors: {},
      activeField: 'pm25_avg_15',
      showInactive: false,
      showPrivate: true,
      fields: {
        fahrenheit: {
          label: "Temp. (°F)",
          levels: [],
          latest: (monitor) => Math.round(monitor.latest.fahrenheit) + "°"
        },
        celcius: {
          label: "Temp. (°C)",
          levels: [],
          latest: (monitor) => Math.round(monitor.latest.celcius) + "°"
        },
        humidity: {
          label: "Humidity",
          levels: [],
          latest: (monitor) => Math.round(monitor.latest.humidity) + "%"
        },
        // pressure: {
        //   label: "Pressure",
        //   levels: [],
        //   latest: (monitor) => Math.round(monitor.latest.pressure) + " hPa"
        // },
        pm25_env: {
          label: "PM 2.5",
          levels: [
            {min: 0, color: '68e143'},
            {min: 12, color: 'ffff55'},
            {min: 35, color: 'ef8533'},
            {min: 55, color: 'ea3324'},
            {min: 150, color: '8c1a4b'},
            {min: 250, color: '731425'}
          ],
          latest: (monitor) => Math.round(monitor.latest.pm25_env)
        },
        pm25_avg_15: {
          label: "PM 2.5 (15m)",
          levels: [
            {min: 0, color: '68e143'},
            {min: 12, color: 'ffff55'},
            {min: 35, color: 'ef8533'},
            {min: 55, color: 'ea3324'},
            {min: 150, color: '8c1a4b'},
            {min: 250, color: '731425'}
          ],
          latest: (monitor) => Math.round(monitor.latest.pm25_avg_15)
        },
        pm25_avg_60: {
          label: "PM 2.5 (1h)",
          levels: [
            {min: 0, color: '68e143'},
            {min: 12, color: 'ffff55'},
            {min: 35, color: 'ef8533'},
            {min: 55, color: 'ea3324'},
            {min: 150, color: '8c1a4b'},
            {min: 250, color: '731425'}
          ],
          latest: (monitor) => Math.round(monitor.latest.pm25_avg_60)
        },
        pm10_env: {
          label: "PM 1.0",
          levels: [
            {min: 0, color: '68e143'},
            {min: 12, color: 'ffff55'},
            {min: 35, color: 'ef8533'},
            {min: 55, color: 'ea3324'},
            {min: 150, color: '8c1a4b'},
            {min: 250, color: '731425'}
          ],
          latest: (monitor) => Math.round(monitor.latest.pm10_env)
        },
        pm100_env: {
          label: "PM 10",
          levels: [
            {min: 0, color: '68e143'},
            {min: 12, color: 'ffff55'},
            {min: 35, color: 'ef8533'},
            {min: 55, color: 'ea3324'},
            {min: 150, color: '8c1a4b'},
            {min: 250, color: '731425'}
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
    showInactive: function(value) {
      _.mapValues(this.monitors, this.setMarkerMap);
    },

    showPrivate: function(value) {
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
    setMarkerMap(monitor){
      let checkActive = (this.showInactive && !monitor.is_active) || monitor.is_active;
      let checkSJVAir = (this.showPrivate && !monitor.is_sjvair) || monitor.is_sjvair;
      monitor._marker.setMap((checkActive && checkSJVAir) ? this.map : null);
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
        fill_color: '969696',
        border_color: '000',
        shape: monitor.is_sjvair ? 'circle' : 'square'
      }

      if(monitor.is_active && value != null){
        for(let level of this.fields[field].levels){
          if(value > level.min){
            params['fill_color'] = level.color;
          } else {
            break;
          }
        }
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
        .then(response => {
          _.map(response.data, (monitor) => {
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
                anchor: new window.google.maps.Point(16, 16)
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

            this.monitors[monitor.id]._marker.setPosition(
              new window.google.maps.LatLng(
                monitor.position.coordinates[1],
                monitor.position.coordinates[0]
              )
            );

            this.monitors[monitor.id]._marker.setLabel(
              this.getMonitorLabel(monitor)
            );

            this.setMarkerMap(this.monitors[monitor.id]);
          });
        })
    }
  }
}
</script>
