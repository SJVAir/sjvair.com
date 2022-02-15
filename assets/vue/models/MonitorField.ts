import type { Monitor } from "./Monitor";
import { Colors } from "../utils";
import type { MonitorDataField, IPMLevel} from "../types";

export class MonitorField {
  static genMulti(...fieldDefinitions: Array<ConstructorParameters<typeof MonitorField>>) {
    const fields = {} as Record<MonitorDataField, MonitorField>;

    for (let def of fieldDefinitions) {
      fields[def[0]] = new MonitorField(...def);
    }

    return fields;
  }

  static levels: Array<IPMLevel> = [
    {min: -Infinity, color: Colors.green},
    {min: 12, color: Colors.yellow},
    {min: 35, color: Colors.orange},
    {min: 55, color: Colors.red},
    {min: 150, color: Colors.purple},
    {min: 250, color: Colors.maroon}
  ];

  label: string;
  levels = MonitorField.levels;
  name: MonitorDataField;
  updateDuration: string;

  constructor(fieldName: MonitorDataField, displayLabel: string, updateDuration: string) {

    this.label = displayLabel;
    this.name = fieldName;
    this.updateDuration = updateDuration;
  }

  latest(monitor: Monitor): number | void {
    if (this.name in monitor.data.latest) {
      return Math.round(parseFloat(monitor.data.latest[this.name]));
    }
  }
}
