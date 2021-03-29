import dateUtil from "../utils/date";
import http from "../utils/http";
import Monitor from "../models/monitor";

export class DateRange {
  constructor(range={}) {
    this.lte = range.endDate;
    this.gte = range.startDate;
  }

  get lte() {
    return this._lte.toISOString();
  }

  set lte(value) {
    this._lte = value
      ? dateUtil(value).endOf('day')
      : dateUtil().endOf('day');
  }

  get gte() {
    return this._gte.toISOString();
  }

  set gte(value) {
    this._gte = value
      ? dateUtil(value).startOf('day')
      : dateUtil(this.lte).subtract(3, 'day').startOf('day');
  }
}

class ActiveMonitor {
  constructor(monitor, dateRange) {
    Object.assign(this, monitor);
    this.chartData = [];
    this.entries = [];
    this.dateRange = new DateRange(dateRange);
  }

  get dataFields() {
    return Object.keys(this.monitorFields);
  }

  get monitorFields() {
    return ActiveMonitor.monitorFields[this.device];
  }

  get sensors() {
    return ActiveMonitor.sensors[this.device];
  }

  async loadEntries() {
    this.entries = [];
    for (let sensorGroup of this.sensors) {
      await this.fetchEntriesPage(sensorGroup);
    }
  }

  async fetchEntriesPage(sensor, page=1) {
    await http.get(`monitors/${this.id}/entries/`, {
      params: {
        fields: this.dataFields.join(','),
        page: page,
        timestamp__gte: dateUtil.$defaultFormat(this.dateRange.gte),
        timestamp__lte: dateUtil.$defaultFormat(this.dateRange.lte),
        sensor: sensor
      }
    })
    .then(async res => {
      this.entries.push(...res.data.data);

      if(res.data.has_next_page){
        await this.fetchEntriesPage(sensor, page + 1);

      } else {
        this.processEntries();
      }
    })
    .catch(e => console.error(`Unable to fetch entries page ${page} for monitor ${this.id}`, e));
  }

  processEntries() {
    const chartData = Object.fromEntries(this.dataFields.map(f => {
      return [f, {
        color: ActiveMonitor.fieldColors[f],
        fieldName: f,
        data: []
      }];
    }));

    // Keep things performant, currently "reverse for" is fastest (2021/03)
    for(let i = this.entries.length - 1; i >= 0; i--) {
      // Convert timestamp to dayjs object
      this.entries[i].timestamp = dateUtil.utc(this.entries[i].timestamp).tz('America/Los_Angeles');
      // Derive chart data
      //const xData = this.entries[i].timestamp.toISOString();
      //const yData = Object.fromEntries(this.dataFields.map(f => {
      //  return [f, {
      //    color: ActiveMonitor.fieldColors[f],
      //    fieldName: f,
      //    value: parseFloat(this.entries[i][f], 10)
      //  }];
      //}));

      //chartData.push({ xData, yData });
      for (let protodata of Object.values(chartData)) {
        const metadata = {
          get color() { return protodata.color; },
          get fieldName() { return protodata.fieldName; },
        };
        const dataPoint = {
          xData: this.entries[i].timestamp.toISOString(),
          yData: parseFloat(this.entries[i][protodata.fieldName], 10)
        };
        Object.assign(dataPoint, metadata);
        protodata.data.push(dataPoint);
        Object.assign(protodata.data, metadata);
      }
    }
    this.chartData = Object.values(chartData).map(pd => pd.data);
  }
}

// Specify the fields we want for each monitor
ActiveMonitor.monitorFields = {
  PurpleAir: {
    pm25_env: '2m',
    pm25_avg_15: '15m',
    pm25_avg_60: '60m'
  },
  AirNow: {
    pm25_env: '60m'
  },
  BAM1022: {
    pm25_env: '60m'
  }
};

// Specify the sensors we want for each sensor (empty is default)
ActiveMonitor.sensors = {
  PurpleAir: ['a'],
  AirNow: [''],
  BAM1022: ['']
};

// Specify colors to represent each field
ActiveMonitor.fieldColors = {
    pm25_env: "#00ccff",
    pm25_avg_15: "#006699",
    pm25_avg_60: "#000033"
}

class MonitorsService {
  constructor() {
    this.activeMonitor = null;
    this.routeMonId = null;
    this.handleClick = null;
    this.monitors = {};
  }

  monitorExists(monitorId) {
    return monitorId in this.monitors;
  }

  clearActiveMonitor() {
    this.activeMonitor = null;
    this.routeMonId = null;
  }

  async loadMonitors(monitorCB) {
    await http.get("/monitors")
    .then(res => {
      for (let monitor of res.data.data) {
        if (monitor.id in this.monitors) {
          this.monitors[monitor.id].update(monitor);

        } else {
          this.monitors[monitor.id] = new Monitor(monitor);

          this.monitors[monitor.id]._marker.addListener('click', () => {
            this.setActiveMonitor(monitor.id);
            this.handleClick(this.activeMonitor);
          });
        }

        if (monitorCB) {
          monitorCB(this.monitors[monitor.id]);
        }
      }
    })
    .catch(e => console.error("Unable to fetch monitors\n", e))
    // Check to see if we are still waiting to set the active monitor
    .finally(() => {
      if (!this.activeMonitor && this.monitorExists(this.routeMonId)) {
        this.setActiveMonitor(this.routeMonId);
      }
    });
  }

  setActiveMonitor(monitorId, dateRange) {
    const noop = this.activeMonitor && (monitorId === this.activeMonitor.id);
    const wait = !(monitorId in this.monitors);

    if (noop) {
      return;
    } else if (wait) {
        this.routeMonId = monitorId;
    } else {
      this.activeMonitor = new ActiveMonitor(this.monitors[monitorId], dateRange);
    }
  }
}

export default new MonitorsService();
