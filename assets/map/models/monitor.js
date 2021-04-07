import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import relativeTime from 'dayjs/plugin/relativeTime';
import tinycolor from 'tinycolor2';

import AppController from "../controllers/App.controller";
import colors from "../utils/colors";

dayjs.extend(utc);
dayjs.extend(relativeTime);

class MonitorField {
  constructor(fieldName, label) {
    this.label = label;
    this.levels = [
      {min: 0, color: colors.green},
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

    //this.latest.timestamp = dayjs.utc(this.latest.timestamp).local();

    this._marker = new window.google.maps.Marker({
      size: new window.google.maps.Size(32, 32),
      origin: window.google.maps.Point(0, 0),
      anchor: new window.google.maps.Point(16, 16),
      label: {
        color: colors.black,
        text: ''
      },
      title: monitor.name
    });

    Monitor.setDynamicData(this);
  }

  static setDynamicData(instance, data) {
    // If new data, update the monitor instance
    if (data) {
      (instance.name !== data.name) && instance._marker.setTitle(data.name);
      Object.assign(instance, data);
    }

    instance.latest.timestamp = dayjs.utc(instance.latest.timestamp).local();
    instance.updateMapMarker();
  }

  get isVisible() {
    // showSJVAirPurple
    // showSJVAirInactive
    // showSJVAirBAM
    // showPurpleAir
    // showPurpleAirInside
    // showAirNow

    // All inactive non-SJVAir monitors are hidden.
    if(!this.is_active && !this.is_sjvair){
      return false;
    }

    if(this.device == 'PurpleAir' && this.is_sjvair) {
      return AppController.flags.SJVAirPurple && (AppController.flags.SJVAirInactive || this.is_active);

    } else if (this.device == 'BAM1022'){
      return AppController.flags.SJVAirBAM;

    } else if (this.device == 'PurpleAir') {
      return AppController.flags.PurpleAir && (AppController.flags.PurpleAirInside || this.location == 'outside');

    } else if (this.device == 'AirNow'){
      return AppController.flags.AirNow;
    }
    return false;
  }

  getMarkerParams(){
    let params = {
      border_size: 0,
      fill_color: colors.gray,
      shape: 'square'
    }

    switch (this.device) {
      case 'PurpleAir':
        params.shape = this.is_sjvair ? 'circle' : 'square';
        break;

      case 'AirNow':
        params.shape = 'polygon';
        params.sides = 6;
        break;

      case 'BAM1022':
        params.shape = 'polygon';
        params.sides = 3;
    }

    if(this.location == 'inside'){
      params.border_color = colors.black;
      params.border_size = 2;
    }

    if(this.is_active && this.latest[Monitor.displayField] != null){
      for(let level of Monitor.fields[Monitor.displayField].levels){
        if(this.latest[Monitor.displayField] >= level.min){
          params.fill_color = level.color;
        } else {
          break;
        }
      }
    }

    if(params.border_color == undefined){
      params.border_color = tinycolor(params.fill_color).darken(3).toHex();
      params.border_size = 1;
    }

    return params;
  }

  update(monitorData) {
    Monitor.setDynamicData(this, monitorData);
  }

  updateMapMarker() {
    const params = this.getMarkerParams();

    this._marker.setIcon(
      `/api/1.0/marker.png?${ new URLSearchParams(params).toString() }`
    );

    let label = this._marker.getLabel();
    label.color = `#${ Monitor.textColors.get(params.fill_color) || colors.black }`;
    label.text = (this.latest === null || !this.is_active)
      ? ' '
      : Math.round(this.latest[Monitor.displayField]).toString();

    this._marker.setLabel(label);

    this._marker.setPosition(
      new window.google.maps.LatLng(
        this.position.coordinates[1],
        this.position.coordinates[0]
      )
    );
  }

}

// Default field to display
Monitor.displayField = "pm25_avg_60";
// Assign display labels to fields
Monitor.fields = MonitorField.genMulti(
  ["pm25_env", "PM 2.5"],
  ["pm25_avg_15", "PM 2.5 (15m)"],
  ["pm25_avg_60", "PM 2.5 (1h)"],
  ["pm10_env", "PM 1.0"],
  ["pm100_env", "PM 10"]
);

// Specify alternate text colors based on the background color
Monitor.textColors = new Map()
  .set(colors.white, colors.black)
  .set(colors.gray, colors.black)
  .set(colors.black, colors.white)
  .set(colors.green, colors.black)
  .set(colors.yellow, colors.black)
  .set(colors.orange, colors.white)
  .set(colors.red, colors.white)
  .set(colors.purple, colors.white)
  .set(colors.maroon, colors.white);
