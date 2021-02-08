import Monitor from "../models/monitor";
import GoogleMapsInit from '../utils/gmaps';
import http from "../utils/http";

class AppController {
  constructor() {
    this.activeMonitor = null;
    this.flags = AppController.flags;
    this.monitorFields = Monitor.fields;
    this.monitors = {};
    this.map = null;
  }

  async init() {
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
    await this.loadMonitors();
    this.setInitialViewport();
  }

  hideMonitorDetail() {
    this.activeMonitor = null;
  }

  updateVisibility() {
    for (let id in this.monitors) {
      this.setMarkerMap(this.monitors[id]);
    }
  }

  async loadMonitors() {
    const response = await http.get("/monitors")
      .catch(error => ({ error }));

    if ("error" in response) {
      return console.error("Unable to fetch monitors\n", response.error);
    }

    for (let monitor of response.data) {
      if (monitor.id in this.monitors) {
        this.monitors[monitor.id].update(monitor);

      } else {
        this.monitors[monitor.id] = new Monitor(monitor);
        this.monitors[monitor.id]._marker.addListener('click', () => {
          this.selectMonitor(monitor.id);
        });
      }

      this.setMarkerMap(this.monitors[monitor.id]);
    }

    // (maybe?) TODO: sort by device before returning
  }

  setMarkerMap(monitor){
    monitor._marker.setMap(
      monitor.isVisible ? this.map : null
    );
  }

  selectMonitor(monitorId) {
    this.hideMonitorDetail()
    this.activeMonitor = this.monitors[monitorId];
    this.map.panTo(this.activeMonitor._marker.getPosition());
  }

  setInitialViewport() {
    const bounds = new window.google.maps.LatLngBounds();
    for (let id in this.monitors) {
      bounds.extend(this.monitors[id]._marker.position);
    }
    this.map.fitBounds(bounds);
  }
}

AppController.flags = {
  SJVAirPurple: true,
  SJVAirInactive: false,
  SJVAirBAM: true,
  PurpleAir: true,
  PurpleAirInside: false,
  AirNow: true,
};

export default new AppController();
