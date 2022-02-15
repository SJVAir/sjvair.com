import { MonitorField } from "../models/MonitorField";

export const MonitorFieldColors = {
  pm25: "#00ccff",
  pm25_avg_15: "#006699",
  pm25_avg_60: "#000033"
} as const;

export const MonitorTypesMeta = {
  AirNow: {
    monitorFields: MonitorField.genMulti(
      ["pm25", "PM 2.5", "60m"]
    )
  },
  BAM1022: {
    monitorFields: MonitorField.genMulti(
      ["pm25", "PM 2.5", "60m"]
    )
  },
  PurpleAir: {
    monitorFields: MonitorField.genMulti(
      ["pm10", "PM 1.0", ""],
      ["pm25", "PM 2.5", "2m"],
      ["pm25_avg_15", "PM 2.5", "15m"],
      ["pm25_avg_60", "PM 2.5", "60m"]
    )
  }
} as const;
