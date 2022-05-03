import { darken, toHex } from "color2k";
import { MonitorField } from "./MonitorField";
import { Colors, pmValueToColor } from "../utils";
import type { ChartDataField, IMarkerParams, IMonitor, IMonitorData, MonitorDataField } from "../types";

export const Display_Field = "pm25_avg_15" as const;

function getMarkerParams(monitorData: IMonitorData): IMarkerParams {
  const fill_color = `#${Colors.gray}`;
  const params: IMarkerParams = {
    border_color: toHex(darken(fill_color, .1)),
    border_size: 1,
    fill_color,
    size: monitorData.is_active ? 12 : 8,
    shape: 'square'
  }

  switch(monitorData.device) {
    case "AirNow": 
    case "BAM1022":
      params.shape = "triangle";
      params.size = 16
      break;
    case "PurpleAir":
      params.shape = (monitorData.is_sjvair) ? "circle" : "square";
      break;
    default:
      console.error(`Unknown device type for monitor ${ monitorData.id }`);
      params.shape = "diamond";
  }

  if (monitorData.location === "inside"){
    params.border_color = `#${ Colors.black }`;
    params.border_size = 2;
  }

  if(monitorData.is_active && monitorData.latest){
    params.fill_color = pmValueToColor(+monitorData.latest[Monitor.displayField])
  }

  return params;
}

export class Monitor implements IMonitor {
  // Default field to display
  static displayField: ChartDataField = Display_Field;


  data: IMonitorData;
  dataFields: Array<ChartDataField>;
  displayField: string = Monitor.displayField;
  markerParams: IMarkerParams;
  monitorFields!: Record<MonitorDataField, MonitorField>;

  constructor(monitorData: IMonitorData) {
    switch (monitorData.device) {
      case "AirNow":
        this.monitorFields = MonitorField.genMulti(
          ["pm25", "PM 2.5", "60m", monitorData],
          ["pm100", "PM 10", "", monitorData]
        );
        break;

      case "BAM1022":
        this.monitorFields = MonitorField.genMulti(
          ["pm25", "PM 2.5", "60m", monitorData]
        );
        break;

      case "PurpleAir":
        this.monitorFields = MonitorField.genMulti(
          ["pm10", "PM 1.0", "", monitorData],
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
  }

}
