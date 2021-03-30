import Monitor from "../models/monitor";
import GoogleMapsInit from '../utils/gmaps';
import monitorsService, {DateRange} from "../services/Monitors.service";

class AppController {
  constructor() {
    this.flags = AppController.flags;
    this.monitorFields = Monitor.fields;
    this.monitors = monitorsService.monitors;
    this.map = null;
    this.$router = null;
    this.$routes = null;
  }

  get activeMonitor() {
    return monitorsService.activeMonitor;
  }

  async init(router, routes) {
    this.$router = router;
    this.$routes = routes;
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

  updateVisibility() {
    for (let id in this.monitors) {
      this.setMarkerMap(this.monitors[id]);
    }
  }

  async loadMonitors() {
    if (!monitorsService.handleClick) {
      monitorsService.handleClick = m => this.selectMonitor(m);
    }
    await monitorsService.loadMonitors(m => this.setMarkerMap(m));
  }

  setMarkerMap(monitor){
    monitor._marker.setMap(
      monitor.isVisible ? this.map : null
    );
  }

  selectMonitor(activeMonitor) {
    const range = new DateRange();
    this.$router.push({
      name: "details",
      params: {
        id: activeMonitor.id
      },
      query: {
        timestamp__gte: range.gte,
        timestamp__lte: range.lte
      }
    });
    this.map.panTo(activeMonitor._marker.getPosition());
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
