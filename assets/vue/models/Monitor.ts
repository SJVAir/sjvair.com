import { darken, toHex } from "color2k";
import { MonitorField } from "./MonitorField";
import { Colors, MonitorTypesMeta, pmValueToColor } from "../utils";
import type { ChartDataField, IMarkerParams, IMonitor, IMonitorData, MonitorDataField } from "../types";

export class Monitor implements IMonitor {
  // Default field to display
  static displayField: ChartDataField = "pm25_avg_15";


  data: IMonitorData;
  dataFields: Array<ChartDataField>;
  monitorFields: Record<MonitorDataField, MonitorField>;

  constructor(monitorData: IMonitorData) {
    const meta = MonitorTypesMeta[monitorData.device]

    this.data = monitorData;
    this.dataFields = Object.keys(meta.monitorFields) as Array<ChartDataField>;
    this.monitorFields = meta.monitorFields;
  }

  get displayField() {
    return Monitor.displayField;
  }


  get markerParams(){
    const params: Partial<IMarkerParams> = {
      border_size: 0,
      fill_color: `#${Colors.gray}`,
      size: this.data.is_active ? 12 : 8,
      shape: 'square'
    }

    switch(this.data.device) {
      case "AirNow": 
      case "BAM1022":
        params.shape = "triangle";
        params.size = 16
        break;
      case "PurpleAir":
        params.shape = (this.data.is_sjvair) ? "circle" : "square";
        break;
      default:
        console.error(`Unknown device type for monitor ${ this.data.id }`);
        params.shape = "diamond";
    }

    if (this.data.location === "inside"){
      params.border_color = `#${ Colors.black }`;
      params.border_size = 2;
    }

    if(this.data.is_active && this.data.latest){
      params.fill_color = pmValueToColor(+this.data.latest[this.displayField])
    }

    if(params.border_color == undefined){
      params.border_color = toHex(darken(params.fill_color!, .1));
      params.border_size = 1;
    }

    return params;
  }
}
