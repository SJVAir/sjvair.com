import { Monitor, ChartDataPoint } from "../models";
import { BackgroundService } from "../webworkers/BackgroundService";
import { http, dateUtil, MonitorFieldColors } from "../modules";

import type { DateRange } from "../models";
import type { ChartDataArray, ChartDataField, ChartDataRecord, MonitorsRecord, IMonitorData, IMonitorEntry, IMonitorSubscription, IEntriesPageResponse, IParsedEntry } from "../types";

export const MonitorsBackgroundService = {

  async fetchMonitors(): Promise<MonitorsRecord> {
    return http.get<{ data: Array<IMonitorData> }>("/monitors")
      .then(res => {
        const monitors: MonitorsRecord = {};

        for (let monitorData of res.data.data) {
          monitors[monitorData.id] = new Monitor(monitorData);
        }

        return monitors;
      });
  },

  async fetchEntries(m: Monitor, d: DateRange): Promise<Array<IMonitorEntry>> {
    const entries: Array<IMonitorEntry> = [];
    let hasNextPage: boolean = false;
    let pageNumber = 0;

    do {
      pageNumber++;
      const page: IEntriesPageResponse = await this.fetchEntriesPage(m, d, pageNumber)
      
      if (page.data.length) {
        entries.push(...page.data)
        hasNextPage = page.has_next_page;
      }

    } while (hasNextPage);

    return entries;
  },

  async fetchEntriesPage(m: Monitor, d: DateRange, page: number = 1): Promise<IEntriesPageResponse> {
    return http.get<IEntriesPageResponse>(`monitors/${m.data.id}/entries/`, {
      params: {
        fields: m.dataFields.join(','),
        page: page,
        timestamp__gte: dateUtil.$defaultFormat(d.start),
        timestamp__lte: dateUtil.$defaultFormat(d.end)
      }
    }).then(res => res.data)
    .catch(_ => {
      console.error(`Unable to fetch entries page ${page} for monitor ${m.data.id}`);
      return { count: 0, data: [], has_next_page: false, has_previous_page: false, page: 0, pages: 0 };
    });
  },

  async fetchChartData(m: Monitor, d: DateRange): Promise<ChartDataArray> {
    // TODO-PERF: How to do this in one loop?
    return this.fetchEntries(m, d)
      .then(entries => {
        let chartDataRecord: ChartDataRecord = {} as ChartDataRecord;
        const parsedEntries = entries.map(e => {
          const entry: IParsedEntry = {
            timestamp: null,
            data: {}
          };

          for (let key in e) {
            switch (key) {
              case "sensor":
                break;
              case "timestamp":
                entry.timestamp = e.timestamp;
                break;
              default:
                if (e[key])
                entry.data[key] = e[key];
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
  },

  async loadSubscriptions(): Promise<Array<IMonitorSubscription>> {
    return http.get("alerts/subscriptions")
      .then(res => res.data.data);
  }
};

export default new BackgroundService(MonitorsBackgroundService);
