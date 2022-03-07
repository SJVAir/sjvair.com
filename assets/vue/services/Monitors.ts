import MonitorsBackgroundService from "./MonitorsBackground?worker";
import { CachedMonitor, DateRange, Monitor } from "../models";
import { BackgroundServiceClient } from "../webworkers/BackgroundServiceClient";
import { dateUtil, http } from "../utils";
import type { MonitorId, IMonitorsBackgroundService, Nullable, ChartDataArray, IMonitorSubscription, IMonitorData } from "../types";

export class MonitorsService extends BackgroundServiceClient<IMonitorsBackgroundService> {
  static instance: MonitorsService;


  activeMonitor: Nullable<Monitor> = null;
  cachedMonitor: Nullable<CachedMonitor> = null;
  dateRange: DateRange = new DateRange();
  loadingEntries: boolean = false;
  loadingMonitors: boolean = false;
  monitors: Record<MonitorId, Monitor> = {};

  constructor() {
    if (MonitorsService.instance) {
      return MonitorsService.instance;
    }

    super(new MonitorsBackgroundService());

    MonitorsService.instance = this;
  }

  clearActiveMonitor() {
    this.activeMonitor = null;
    this.cachedMonitor = null;
  }

  downloadCSV(): void {
    if (!this.activeMonitor) {
      return console.error("Unable to download CSV file, no active monitor");
    }

    const path = `${ window.location.origin }${ http.defaults.baseURL }monitors/${this.activeMonitor.data.id}/entries/csv`;
    const params = new URLSearchParams({
      fields: this.activeMonitor.dataFields.join(','),
      timestamp__gte: dateUtil.$defaultFormat(this.dateRange.start),
      timestamp__lte: dateUtil.$defaultFormat(this.dateRange.end),
    }).toString();

    window.open(`${ path }/?${ params }`);
  }

  async fetchChartData(id: IMonitorData["id"]): Promise<void | ChartDataArray> {
    if (!(id in this.monitors)) {
      return console.error(`Unable to fetch chart data, monitor with id "${ id }" not found.`);
    }

    this.loadingEntries = true;

    return await this.run("fetchChartData", this.monitors[id], this.dateRange)
      .then(chartData => {
        this.loadingEntries = false;
        return chartData;
      })
      .catch(error => console.error(`Error fetching chart data for ${ this.monitors[id].data.name }:\n`, error));
  }

  async loadMonitors(): Promise<void> {
    this.loadingMonitors = true;

    console.log("starting background task")
    await this.run("fetchMonitors")
      .then(monitors => {
        console.log("inside then")
        this.monitors = monitors;
        this.loadingMonitors = false;

        if (!this.activeMonitor && this.cachedMonitor && this.monitorExists(this.cachedMonitor.id)) {
          this.setActiveMonitor(this.cachedMonitor.id, this.cachedMonitor.dateRange);
        }
      })
      .catch(error => console.error("Error fetching monitors:\n", error));
  }
  
  async loadSubscriptions(): Promise<void | Array<IMonitorSubscription>> {
    return await this.run("loadSubscriptions")
      .catch(error => console.error("Error loading subscriptions:\n", error));
  }

  monitorExists(id: MonitorId): boolean {
    return id in this.monitors;
  }

  setActiveMonitor(id: MonitorId, dateRange?: DateRange) {
    if (this.activeMonitor && (id === this.activeMonitor.data.id)) {
      return;

    } else if (this.loadingMonitors) {
      this.cachedMonitor = new CachedMonitor(id, dateRange);

    } else {
      this.activeMonitor = this.monitors[id];
      /* if we remove this dateRange assignment, the date range is saved
       * between activeMonitor assignments. Feature? Option for user?
       */
      this.dateRange = new DateRange();
    }
  }
}
