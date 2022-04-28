import { darken, toHex } from "color2k";
import { MonitorField } from "./MonitorField";
import { Colors, MonitorTypesMeta, MonitorFields } from "../utils";
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
    //const latest = parseFloat(this.data.latest[(Monitor.displayField as keyof IMonitorSensorData)]!);
    const latest = MonitorFields[Monitor.displayField].latest(this);
    const params: Partial<IMarkerParams> = {
      border_size: 0,
      fill_color: Colors.gray,
      size: this.data.is_active ? 24 : 16,
      shape: 'square'
    }

    switch (this.data.device) {
      case 'PurpleAir':
        params.shape = this.data.is_sjvair ? 'circle' : 'square';
        break;

      case 'AirNow':
      case 'BAM1022':
        params.shape = 'polygon';
        params.sides = 3;
        params.size = 32
        break;
    }

    if(this.data.location == 'inside'){
      params.border_color = Colors.black;
      params.border_size = 2;
    }

    if(this.data.is_active && latest){
      for(let level of MonitorFields[Monitor.displayField].levels){
        if(latest >= level.min){
          params.fill_color = level.color;
        } else {
          break;
        }
      }
    }

    if(params.border_color == undefined){
      params.border_color = toHex(darken(params.fill_color!, 6));
      params.border_size = 1;
    }

    return params;
  }
}
