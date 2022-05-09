import { mix } from "color2k";
import { MonitorField } from "../models";
import { dateUtil } from "./date";
import { http } from "./http";


export * from "./colors";
export * from "./constants";
export * from "./map";
export {
  dateUtil,
  http
}

export function pmValueToColor(value: number) {
  const lastLvl = MonitorField.levels[MonitorField.levels.length - 1];

  if (value >= lastLvl.min) {
    return `#${lastLvl.color}`;

  } else if (value <= 0) {
    return `#${MonitorField.levels[0].color}`;

  } else {
    for (let i = 0; i <= MonitorField.levels.length - 1; i++) {
      if (MonitorField.levels[i].min > value) {
        // Level for current value
        const min = MonitorField.levels[i-1];
        // Level threshold for current value
        const max = MonitorField.levels[i]
        // Difference between max and min values => total steps in level
        const lvlDiff = min.min === -Infinity ? max.min : max.min - min.min;
        // Difference between threshold and current values => steps remaining for current level
        const valDiff = max.min - value;
        // Difference between total steps and steps remaining
        const divisable = lvlDiff - valDiff;
        // Percent of steps used in level
        const diff = divisable / lvlDiff;

        // Color magic
        return mix(`#${min.color}`, `#${max.color}`, diff);
      }
    }

    // Gentle way to signify an error
    return "#FFFFFF";
  }
}
