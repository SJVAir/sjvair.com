import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import relativeTime from 'dayjs/plugin/relativeTime';
import tinycolor from 'tinycolor2';

import colors from "../utils/colors";

dayjs.extend(utc);
dayjs.extend(relativeTime);

class MonitorField {
  constructor(fieldName, label) {
    this.label = label;
    this.levels = [
      {min: -Infinity, color: colors.green},
      {min: 12, color: colors.yellow},
      {min: 35, color: colors.orange},
      {min: 55, color: colors.red},
      {min: 150, color: colors.purple},
      {min: 250, color: colors.maroon}
    ];
    this.latest = (monitor) => Math.round(monitor.latest[fieldName]);
  }
}

MonitorField.genMulti = function(...fieldData) {
  const fields = {};
  for (let data of fieldData) {
    fields[data[0]] = new MonitorField(data[0], data[1]);
  }
  return fields;
}

export default class Monitor {
  constructor(monitor) {
    Object.assign(this, monitor);
    if(this.latest) {
      this.latest.timestamp = dayjs.utc(this.latest.timestamp).local();
    }
  }

  get displayField() {
    return Monitor.displayField;
  }

  get isVisible() {
    // showSJVAirPurple
    // showSJVAirInactive
    // showSJVAirBAM
    // showPurpleAir
    // showPurpleAirInside
    // showAirNow

    if(!Monitor.visibility.displayInactive && !this.is_active){
      return false;
    }

    if(this.device == 'PurpleAir' && this.is_sjvair) {
      return Monitor.visibility.SJVAirPurple;

    } else if (this.device == 'BAM1022'){
      return Monitor.visibility.SJVAirBAM;

    } else if (this.device == 'PurpleAir') {
      return Monitor.visibility.PurpleAir && (Monitor.visibility.PurpleAirInside || this.location == 'outside');

    } else if (this.device == 'AirNow'){
      return Monitor.visibility.AirNow;
    }
    return false;
  }

  getMarkerParams(){
    let params = {
      border_size: 0,
      fill_color: colors.gray,
      size: this.is_active ? 24 : 16,
      shape: 'square'
    }

    switch (this.device) {
      case 'PurpleAir':
        params.shape = this.is_sjvair ? 'circle' : 'square';
        break;

      case 'AirNow':
      case 'BAM1022':
        params.shape = 'polygon';
        params.sides = 3;
        params.size = 32
        break;
    }

    if(this.location == 'inside'){
      params.border_color = colors.black;
      params.border_size = 2;
    }

    if(this.is_active && this.latest != null && this.latest[Monitor.displayField] != null){
      for(let level of Monitor.fields[Monitor.displayField].levels){
        if(this.latest[Monitor.displayField] >= level.min){
          params.fill_color = level.color;
        } else {
          break;
        }
      }
    }

    if(params.border_color == undefined){
      params.border_color = tinycolor(params.fill_color).darken(6).toHex();
      params.border_size = 1;
    }

    return params;
  }
}

// Default field to display
Monitor.displayField = "pm25_avg_15";
// Assign display labels to fields
Monitor.fields = MonitorField.genMulti(
  ["pm25", "PM 2.5"],
  ["pm25_avg_15", "PM 2.5 (15m)"],
  ["pm25_avg_60", "PM 2.5 (1h)"],
  ["pm10", "PM 1.0"],
  ["pm100", "PM 10"]
);

Monitor.visibility = {
  SJVAirPurple: true,
  SJVAirInactive: false,
  SJVAirBAM: true,
  PurpleAir: true,
  PurpleAirInside: false,
  AirNow: true,
};
