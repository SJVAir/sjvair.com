import { dateUtil } from "../modules";
import type { ChartDataField, IParsedEntry, MonitorFieldColor } from "../types";

export class ChartDataPoint {
  color: MonitorFieldColor;
  fieldName: ChartDataField;
  xData: any;
  yData: number;

  constructor(c: ChartDataPoint["color"], n: ChartDataPoint["fieldName"], e: IParsedEntry) {
    // TODO-PERF: How to not convert every date
    this.color = c;
    this.fieldName = n;
    this.xData = dateUtil.dayjs.utc(e.timestamp).tz('America/Los_Angeles').toISOString();
    this.yData = parseFloat(e.data[n]);
  }
}
