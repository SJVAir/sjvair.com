import { Monitor } from "../models";
import type { IMonitorData, IMonitorManager, MonitorId, MonitorSerachParams, MonitorsRecord, NonFunctionPropertyNames } from "../types";

// Serach by address

export class MonitorManager implements IMonitorManager {
  private _airNow: MonitorsRecord = {};
  private _monitors: MonitorsRecord = {};
  private _purpleAir: MonitorsRecord = {};
  private _purpleAirInside: MonitorsRecord = {};
  private _sjvAirBAM: MonitorsRecord = {};
  private _sjvAirInactive: MonitorsRecord = {}
  private _sjvAirPurple: MonitorsRecord = {};

  constructor(monitors?: Array<IMonitorData>) {
    if (monitors && monitors.length > 0) {
      for (let i = 0; i <= monitors.length - 1; i++) {
        const monitor = new Monitor(monitors[i]);

        this._monitors[monitor.data.id] = monitor;

        if (!monitor.data.is_active) {
          this._sjvAirInactive[monitor.data.id] = monitor;
          continue;
        }

        switch (monitor.data.device) {
          case "PurpleAir":
            if (monitor.data.is_sjvair) {
              this._sjvAirPurple[monitor.data.id] = monitor;

            } else if (monitor.data.location === "inside") {
              this._purpleAirInside[monitor.data.id] = monitor;

            } else {
              this._purpleAir[monitor.data.id] = monitor;
            }
            break;

          case "AirNow":
            this._airNow[monitor.data.id] = monitor;
            break;

          case "BAM1022":
            this._sjvAirBAM[monitor.data.id] = monitor;
            break;
        }
      }
    } else {
      return this;
    }
  }

  get airNow(): Readonly<MonitorsRecord> {
    return this._airNow;
  };

  get monitors(): Readonly<MonitorsRecord> {
    return this._monitors;
  };

  get purpleAir(): Readonly<MonitorsRecord> {
    return this._purpleAir;
  };

  get purpleAirInside(): Readonly<MonitorsRecord> {
    return this._purpleAirInside;
  };

  get sjvAirBAM(): Readonly<MonitorsRecord> {
    return this._sjvAirBAM;
  };

  get sjvAirInactive(): Readonly<MonitorsRecord> {
    return this._sjvAirInactive;
  }

  get sjvAirPurple(): Readonly<MonitorsRecord> {
    return this._sjvAirPurple
  };

  private has(id: MonitorId): boolean {
    return id in this._monitors && !!this._monitors[id];
  }

  private findById(id: MonitorId): Monitor | void {
    if (this.has(id)) {
      return this._monitors[id];
    } else {
      console.warn(`Monitor ${ id } was requested but not found`);
    }
  }

  private findByName(name: string): Monitor | void {
    let monitor: Monitor | undefined = undefined;

    this._forEach(m => {
      if (m.data.name === name) {
        monitor = m;
      }
    })

    return monitor;
  }

  private findByCounty(county: string): Monitor | undefined {
    let monitor: Monitor | undefined = undefined;

    this._forEach(m => {
      if (m.data.county === county) {
        monitor = m;
      }
    })

    return monitor;
  }

  private _find(param: MonitorSerachParams): Monitor | MonitorsRecord | void {
    const [[key, value]] = Object.entries(param);

    switch (key) {
      case "id":
        return this.findById(value);
      case "name":
        return this.findByName(value);
      case "county":
        return this.findByCounty(value);
      default:
        throw new Error(`[MonitorManager] unable to index monitors by key ${ key }`);
    }
  }

  private _forEach(
    deviceTypeOrCallback: NonFunctionPropertyNames<IMonitorManager> | ((entry: Monitor) => any),
    callback?: ((entry: Monitor) => any)
  ): void {
    let cb = callback || function() {};
    let collection: NonFunctionPropertyNames<IMonitorManager> = (typeof deviceTypeOrCallback === "string")
      ? deviceTypeOrCallback
      : "monitors";

    for (let id in this[collection]) {
      cb(this[collection][id]);
    }
  }

  find(param: MonitorSerachParams): Readonly<Monitor> | Readonly<MonitorsRecord> | void {
    return this._find(param);
  }

  forEach(
    deviceTypeOrCallback: NonFunctionPropertyNames<IMonitorManager> | ((entry: Readonly<Monitor>) => any),
    callback?: ((entry: Readonly<Monitor>) => any)
  ): void {
    this._forEach(deviceTypeOrCallback, callback);
  }

  from(m: MonitorManager): MonitorManager {
    Object.assign(this, m);
    return this;
  }
}
