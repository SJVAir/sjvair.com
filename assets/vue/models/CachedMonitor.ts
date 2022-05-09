import { DateRange } from ".";
import type { MonitorId } from "../types";

export class CachedMonitor {
  id: MonitorId;
  dateRange: DateRange;

  constructor(id: MonitorId, dateRange?: DateRange) {
    this.id = id;
    this.dateRange = dateRange || new DateRange();
  }
}
