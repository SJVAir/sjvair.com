import { BackgroundService } from "../webworkers/BackgroundService";
import { Monitor, ChartDataPoint } from "../models";
import { http, dateUtil, MonitorFieldColors } from "../utils";

import type { DateRange } from "../models";
import type { ChartDataArray, ChartDataField, EntriesPageResponse, MonitorsRecord, IMonitorData, IMonitorEntry, IMonitorSubscription } from "../types";

export const MonitorsBackgroundService = {

  async fetchMonitors(): Promise<MonitorsRecord> {
    return http.get<Array<IMonitorData>>("/monitors")
      .then(res => {
        const monitors: MonitorsRecord = {};

        for (let monitorData of res.data) {
          monitors[monitorData.id] = new Monitor(monitorData);
        }

        return monitors;
      })
    //const monitors: MonitorsRecord = {};
    //const res = await http.get("/monitors").catch(error => error);

    //if (res instanceof Error) {
    //  return res;
    //}

    //if ("data" in res.data) {
    //  for (let monitorData of res.data.data) {
    //    monitors[monitorData.id] = new Monitor(monitorData);
    //  }
    //}

    //return monitors;

    //monitors = newMonitors;

    //if (!activeMonitor && cachedMonitor && monitorExists(cachedMonitor.id)) {
    //  setActiveMonitor(cachedMonitor.id, cachedMonitor.dateRange);
    //}
  },

  async fetchEntries(m: Monitor, d: DateRange): Promise<Array<IMonitorEntry>> {
    const entries: Array<IMonitorEntry> = [];
    let hasNextPage: boolean = false;
    let pageNumber = 1;

    do {
      const page: EntriesPageResponse = await this.fetchEntriesPage(m, d, pageNumber)
        .catch(error => console.error(`Error fetching entries page ${ page } for monitor ${ m.data.name }`, error));
      
      if (page && "data" in page.data) {
        entries.push(...page.data.data)

        if (page.data.has_next_page) {
          pageNumber++;
          hasNextPage = page.data.has_next_page;
        }
      }

    } while (hasNextPage);

    return entries;
  },

  async fetchEntriesPage(m: Monitor, d: DateRange, page: number = 1): Promise<EntriesPageResponse> {
    return http.get<EntriesPageResponse>(`monitors/${m.data.id}/entries/`, {
      params: {
        fields: m.dataFields.join(','),
        page: page,
        timestamp__gte: dateUtil.$defaultFormat(d.start),
        timestamp__lte: dateUtil.$defaultFormat(d.end)
      }
    }).then(res => res.data);
    //}).catch(error => console.error(`Unable to fetch entries page ${page} for monitor ${activeMonitor!.data.id}`, error));
  },

  async fetchChartData(m: Monitor, d: DateRange): Promise<ChartDataArray> {
    // TODO-PERF: How to do this in one loop?
    return this.fetchEntries(m, d)
      .then(entries => {
        const chartDataRecord: Record<ChartDataField, Array<ChartDataPoint>> = {} as Record<ChartDataField, Array<ChartDataPoint>>;
        const parsedEntries = entries.map(e => {
          const entry: any = {
            timestamp: null,
            data: {}
          };

          for (let key in e) {
            if (key === "sensor") {
              continue;

            } else if (key === "timestamp") {
              entry.timestamp = e.timestamp;

            } else {
              entry.data.key = e[key];
            }
          }

          return entry;
        });

        for (let i = parsedEntries.length - 1; i >= 0; i--) {
          const entry = parsedEntries[i];

          for (let field in entry.data) {
            if (field in MonitorFieldColors) {
              if (!(field in chartDataRecord)) {
                chartDataRecord[field as ChartDataField] = [];
              }
              const monitorField = m.monitorFields[field as ChartDataField];
              const dataPoint = new ChartDataPoint(MonitorFieldColors[field as ChartDataField], monitorField.name as ChartDataField, entry);

              chartDataRecord[field as ChartDataField].unshift(dataPoint);
            }
          }
        }

        return Object.values(chartDataRecord);
      });
    //const entries = await this.fetchEntries(m, d);

    //if (entries instanceof Error) {
    //  return entries;
    //}

    //const chartDataRecord: Record<DataField, Array<ChartDataPoint>> = {} as Record<DataField, Array<ChartDataPoint>>;

    //// TODO-PERF: How to do this in one loop?
    //for (let fieldName in m.monitorFields) {
    //  const field = m.monitorFields[fieldName as DataField];
    //  const chartData: Array<ChartDataPoint> = chartDataRecord[field.name] = [];
    //  
    //  for (let i = entries.length - 1; i >= 0; i--) {
    //    const entry = entries[i];

    //    chartData.push(new ChartDataPoint(field, entry));
    //  }
    //}
    //return Object.values(chartDataRecord);
  },

  async loadSubscriptions(): Promise<Array<IMonitorSubscription>> {
    return http.get("alerts/subscriptions")
      .then(res => res.data.data);
    //const res = await http.get("alerts/subscriptions").catch(error => error);

    //if (res instanceof Error) {
    //  console.error("Unable to fetch subscriptions", res);

    //} else {
    //  return res.data.data;
    //}
  }
};

export default new BackgroundService(MonitorsBackgroundService);
