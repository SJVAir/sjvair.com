import { darken, toHex } from "color2k";
import { MonitorField } from "./MonitorField";
import { Colors, dateUtil, valueToColor } from "../utils";
import type { ChartDataField, IMarkerParams, IMonitor, IMonitorData, MonitorDataField } from "../types";

export const Display_Field = "pm25_avg_15" as const;

function getMarkerParams(monitorData: IMonitorData): IMarkerParams {
  const fill_color = `#${Colors.gray}`;
  const params: IMarkerParams = {
    border_color: toHex(darken(fill_color, .1)),
    border_size: 1,
    fill_color,
    value_color: fill_color,
    size: 8, //monitorData.is_active ? 16 : 6,
    shape: 'square'
  }

  switch(monitorData.device) {
    case "AirNow": 
    case "BAM1022":
      params.shape = "triangle";
      break;
    case "PurpleAir":
      (monitorData.is_sjvair) && (params.shape = "circle");
      break;
    default:
      console.error(`Unknown device type for monitor ${ monitorData.id }`);
      params.shape = "diamond";
  }

  if (monitorData.latest) {
    const valueColor = valueToColor(+monitorData.latest[Monitor.displayField], MonitorField.levels);
    params.value_color = valueColor;

    if (monitorData.is_active) {
      params.fill_color = valueToColor(+monitorData.latest[Monitor.displayField], MonitorField.levels);
      params.border_color = toHex(darken(params.fill_color, .1));

      switch(monitorData.device) {
        case "AirNow": 
        case "BAM1022":
          params.size = 14;
          break;
        case "PurpleAir":
          if (monitorData.is_sjvair) {
            params.size = 16
          } else {
            params.size = 10;
          }
          break;
      }

      if (monitorData.location === "inside"){
        params.border_color = `#${ Colors.black }`;
        params.border_size = 2;
      }
    }
  }

  return params;
}

export class Monitor implements IMonitor {
  // Default field to display
  static displayField: ChartDataField = Display_Field;


  data: IMonitorData;
  dataFields: Array<ChartDataField>;
  displayField: string = Monitor.displayField;
  lastUpdated: string;
  markerParams: IMarkerParams;
  monitorFields!: Record<MonitorDataField, MonitorField>;

  constructor(monitorData: IMonitorData) {
    switch (monitorData.device) {
      case "AirNow":
        this.monitorFields = MonitorField.genMulti(
          ["pm25", "PM 2.5", "60m", monitorData],
          ["pm100", "PM 10", "60M", monitorData]
        );
        break;

      case "BAM1022":
        this.monitorFields = MonitorField.genMulti(
          ["pm25", "PM 2.5", "60m", monitorData]
        );
        break;

      case "PurpleAir":
        this.monitorFields = MonitorField.genMulti(
          ["pm10", "PM 1.0", "2m", monitorData],
          ["pm25", "PM 2.5", "2m", monitorData],
          ["pm25_avg_15", "PM 2.5", "15m", monitorData],
          ["pm25_avg_60", "PM 2.5", "60m", monitorData],
          ["pm100", "PM 10", "", monitorData]
        );
        break;
    }

    this.data = monitorData;
    this.dataFields = Object.keys(this.monitorFields) as Array<ChartDataField>;
    this.markerParams = getMarkerParams(monitorData);

    this.lastUpdated = (monitorData.latest && Object.keys(monitorData.latest).length > 1)
      ? dateUtil.dayjs(monitorData.latest.timestamp).fromNow()
      : "never";
  }

}
