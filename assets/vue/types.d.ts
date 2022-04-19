import type { AxiosResponse } from "axios";
import type { Dayjs } from "dayjs";
//import { Marker } from "leaflet";
import type { ChartDataPoint, Monitor, MonitorField } from "./models";
import type { MonitorsBackgroundService, D3BackgroundService } from "./services";
import type { Colors, MonitorFieldColors, MonitorTypesMeta } from "./utils";

// Utility types
export type Nullable<T> = T | null;
export type Override<T, U> = Omit<T, keyof U> & U;
export type ValueOf<T> = T[keyof T];
export type ReplaceReturnType<T extends (...a: any) => any, R> = (...a: Parameters<T>) => R;

// Value types
export type ChartDataArray = Array<Array<ChartDataPoint>>;
export type ChartDataField = keyof typeof MonitorFieldColors;
export type ChartDataRecord = Record<ChartDataField, Array<ChartDataPoint>>;
export type ID3Service = typeof D3BackgroundService;
export type Device = keyof typeof MonitorTypesMeta;
export type EntriesPageResponse = AxiosResponse<IEntriesPageResponse, any>;
export type MonitorDataField = "pm10" | "pm25" | "pm25_avg_15" | "pm25_avg_60" | "pm100";
export type MonitorFieldColor = ValueOf<typeof MonitorFieldColors>;
export type MonitorId = Monitor["data"]["id"];
export type IMonitorsBackgroundService = typeof MonitorsBackgroundService;
export type MonitorsRecord = Record<MonitorId, Monitor>;

// Interfaces
export interface IActiveMonitor {
  entries: Array<IMonitorEntry>;
  monitor: Monitor;
}

export interface IBackgroundService {
  [key: string]: (...input: Array<any>) => any;
}

export interface IChartDataPoint {
  xData: any;
  yData: number;
}

export interface IDateRange {
  startDate: string | typeof Dayjs;
  endDate: string | typeof Dayjs;
}

export interface IEntriesPageResponse {
  count: number;
  data: Array<any>;
  has_next_page: boolean;
  has_previous_page: boolean;
  page: number;
  pages: number;
}

export interface IMarkerParams {
  border_color: string;
  border_size: number;
  fill_color: ValueOf<typeof Colors>;
  sides?: number;
  size: number;
  shape: string;
}

export interface IMonitor {
  data: IMonitorData;
  dataFields: Array<ChartDataField>;
  monitorFields: Record<ChartDataField, MonitorField>;
}

export interface IMonitorData {
  id: string;
  name: string;
  device: Device;
  is_active: boolean;
  is_sjvair: boolean;
  position: IMonitorPosition;
  last_active_limit: number;
  location: string;
  latest: IMonitorSensorData;
  county: string;
  purple_id: number | null;
}

export interface IMonitorEntry {
  timestamp: string;
  sensor: string;
  [field: string]: string;
}

export interface IMonitorPosition {
  type: string;
  coordinates: Array<number>;
}

export interface IMonitorSensorData {
  fahrenheit: string;
  id: string;
  celcius: string;
  humidity: string;
  pm10: string;
  pm25: string;
  pm100: string;
  pm25_avg_15: string;
  pm25_avg_60: string;
  pm10_standard: string;
  pm25_standard: string;
  pm100_standard: string;
  particles_03um: string;
  particles_05um: string;
  particles_10um: string;
  particles_25um: string;
  particles_50um: string;
  particles_100um: string;
  pressure: string | null;
  sensor: string;
  timestamp: string;
}

export interface IMonitorSubscription {
  level: "unhealthy_sensitive" | "unhealthy" | "very_unhealthy" | "hazardous";
  monitor: IMonitorSensorData["id"];
}

export interface IMonitorVisibility {
  SJVAirPurple: boolean;
  SJVAirInactive: boolean
  SJVAirBAM: boolean;
  PurpleAir: boolean;
  PurpleAirInside: boolean;
  AirNow: boolean;
  displayInactive: boolean;
} 

export interface IParsedEntry {
  timestamp: string | null,
  data: {
    [key: string]: string;
  }
}

export interface IPMLevel {
  min: number;
  color: ValueOf<typeof Colors>;
}

