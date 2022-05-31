import { Colors } from "../utils/colors";
import type { MonitorDataField, IColorMap, IMonitorData} from "../types";

export class MonitorField {
  static genMulti(...fieldDefinitions: Array<ConstructorParameters<typeof MonitorField>>) {
    const fields = {} as Record<MonitorDataField, MonitorField>;

    for (let def of fieldDefinitions) {
      fields[def[0]] = new MonitorField(...def);
    }

    return fields;
  }

  static levels: Array<IColorMap> = [
    {min: -Infinity, color: Colors.green},
    {min: 12, color: Colors.yellow},
    {min: 35, color: Colors.orange},
    {min: 55, color: Colors.red},
    {min: 150, color: Colors.purple},
    {min: 250, color: Colors.maroon}
  ];

  label: string;
  latest?: number;
  levels = MonitorField.levels;
  name: MonitorDataField;
  updateDuration: string;

  constructor(fieldName: MonitorDataField, displayLabel: string, updateDuration: string, monitorData: IMonitorData) {

    this.label = displayLabel;
    this.name = fieldName;
    this.updateDuration = updateDuration;

    if (monitorData.latest && this.name in monitorData.latest) {
      this.latest = Math.round(parseFloat(monitorData.latest[this.name]));
    }
  }
}
